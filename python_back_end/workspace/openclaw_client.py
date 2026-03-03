"""
OpenClaw WebSocket client for Harvis Workspaces.

Manages connections to the OpenClaw gateway (ws://harvis-ai-openclaw:18789)
and streams activity log events back to the calling code.

Protocol (OpenClaw gateway v3):
  1. Connect via WebSocket.
  2. Server immediately sends a connect.challenge event with a nonce:
       {"type":"event","event":"connect.challenge","payload":{"nonce":"...","ts":...}}
  3. Client sends a JSON-RPC "connect" request with device identity + auth token:
       {"type":"req","id":"1","method":"connect","params":{
           "minProtocol":3,"maxProtocol":3,
           "client":{"id":"gateway-client","version":"1.0.0",
                     "platform":"linux","mode":"backend"},
           "role":"operator",
           "scopes":["operator.admin"],
           "auth":{"token":"<OPENCLAW_GATEWAY_TOKEN>"},
           "device":{"id":"<sha256-hex>","publicKey":"<base64url>",
                     "signature":"<base64url>","signedAt":<ms>,"nonce":"<challenge-nonce>"}}}
  4. Server responds: {"type":"res","id":"1","ok":true,...}
     Device identity + shared token auth triggers skipPairingForOperatorSharedAuth,
     so scopes are granted without manual pairing approval.
  5. Send chat via:
       {"type":"req","id":"2","method":"chat.send","params":{
           "sessionKey":"agent:main:<session>",
           "message":"...","idempotencyKey":"<uuid>"}}
  6. Receive events: {"type":"event","event":"chat","payload":{
         "state":"final"|"error","message":{...},"runId":"...","sessionKey":"..."}}
     Agent progress events: {"type":"event","event":"agent","payload":{...}}

Device identity notes:
  - Ed25519 key pair is generated once per process.
  - Device ID = SHA-256(raw 32-byte public key), hex-encoded.
  - Public key sent as base64url of the raw 32-byte key (not PEM).
  - Signature payload: "v2|{deviceId}|{clientId}|{clientMode}|{role}|{scopes}|{ms}|{token}|{nonce}"
  - With shared token auth + device identity, OpenClaw sets skipPairingForOperatorSharedAuth=true
    and skips the pairing/approval flow, granting the requested scopes directly.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
import uuid
from typing import AsyncGenerator, Optional

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = logging.getLogger(__name__)

OPENCLAW_URL = os.getenv("OPENCLAW_URL", "ws://harvis-ai-openclaw:18789")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# GitHub credentials for Harvis's bot account (harvisai-dulc3-cmd).
# Injected into workspace directives so the agent can push branches and open PRs.
# Never hardcoded — must come from the environment / K8s secret.
HARVIS_GITHUB_TOKEN = os.getenv("HARVIS_GITHUB_TOKEN", "")
HARVIS_GITHUB_USER = os.getenv("HARVIS_GITHUB_USER", "harvisai-dulc3-cmd")
HARVIS_GITHUB_EMAIL = os.getenv("HARVIS_GITHUB_EMAIL", "harvisai@users.noreply.github.com")

# Must match the OpenClaw protocol version (frames.ts PROTOCOL_VERSION = 3)
PROTOCOL_VERSION = 3

# Ed25519 SPKI DER prefix (12 bytes) — strip this to get the raw 32-byte key
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")

# Client identity constants (must be valid OpenClaw client IDs/modes)
_CLIENT_ID = "gateway-client"
_CLIENT_MODE = "backend"

# operator.admin grants access to all gateway methods including chat.send
_CLIENT_SCOPES = ["operator.admin"]


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _generate_device_identity():
    """Generate a fresh Ed25519 key pair and derive the device ID."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Export DER-encoded SPKI public key, then strip the 12-byte prefix to get raw 32 bytes
    pub_der = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if pub_der[: len(_ED25519_SPKI_PREFIX)] == _ED25519_SPKI_PREFIX:
        raw_pub = pub_der[len(_ED25519_SPKI_PREFIX):]
    else:
        raw_pub = pub_der  # fallback (shouldn't happen for Ed25519)

    device_id = hashlib.sha256(raw_pub).hexdigest()
    pub_b64url = _base64url_encode(raw_pub)
    return private_key, device_id, pub_b64url


# Module-level device identity — generated once per process startup.
# OpenClaw's skipPairingForOperatorSharedAuth flag means token-authenticated operator
# clients with device identity are auto-approved without manual pairing.
_device_private_key, _device_id, _device_pub_b64url = _generate_device_identity()
logger.debug("OpenClaw device identity initialized: deviceId=%s...", _device_id[:16])


def _build_device_params(nonce: str) -> dict:
    """
    Build the signed device identity block for the OpenClaw connect handshake.

    Payload format (v2): "v2|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce"
    """
    signed_at_ms = int(time.time() * 1000)
    scopes_str = ",".join(_CLIENT_SCOPES)
    payload = "|".join([
        "v2",
        _device_id,
        _CLIENT_ID,
        _CLIENT_MODE,
        "operator",
        scopes_str,
        str(signed_at_ms),
        OPENCLAW_GATEWAY_TOKEN,
        nonce,
    ])
    sig_bytes = _device_private_key.sign(payload.encode("utf-8"))
    return {
        "id": _device_id,
        "publicKey": _device_pub_b64url,
        "signature": _base64url_encode(sig_bytes),
        "signedAt": signed_at_ms,
        "nonce": nonce,
    }


def _build_context_brief(chat_history: list[dict], current_task: str = "") -> str:
    """
    Build a compact context string from Harvis chat history.

    Instead of dumping raw messages (which can be thousands of tokens), this
    produces a short paragraph covering:
      - what the user has been working on (last 3 user turns, truncated)
      - the most recent assistant reply (first 200 chars)

    The current task itself is excluded — it's already in the directive.

    Returns an empty string when there's nothing useful to include.
    """
    if not chat_history:
        return ""

    # Collect the last few user messages, excluding the current task
    user_turns: list[str] = []
    for m in reversed(chat_history):
        if m.get("role") != "user":
            continue
        text = (m.get("content") or "").strip()
        if not text or text == current_task:
            continue
        # Truncate each prior turn to 120 chars so the whole brief stays small
        user_turns.append(text[:120] + ("…" if len(text) > 120 else ""))
        if len(user_turns) == 3:
            break
    user_turns.reverse()

    # Grab the last assistant reply for result context
    last_assistant = ""
    for m in reversed(chat_history):
        if m.get("role") == "assistant":
            text = (m.get("content") or "").strip()
            if text:
                last_assistant = text[:200] + ("…" if len(text) > 200 else "")
                break

    if not user_turns and not last_assistant:
        return ""

    parts: list[str] = []
    if user_turns:
        parts.append("Prior requests: " + " | ".join(user_turns))
    if last_assistant:
        parts.append("Last response: " + last_assistant)

    return "\n".join(parts)


class OpenClawEvent:
    """A single event streamed from the OpenClaw gateway."""

    def __init__(self, event_type: str, data: dict):
        self.type = event_type   # "token" | "tool_call" | "tool_result" | "log" | "done" | "error"
        self.data = data
        # Sub-agent tracking: populated by OpenClawClient._handle_agent_event.
        # run_id  — OpenClaw's internal runId for this agent invocation.
        # agent_label — human-readable label: "Agent" | "Sub-Agent 1" | "Sub-Agent 2" …
        self.run_id: Optional[str] = None
        self.agent_label: Optional[str] = None

    def to_sse(self) -> str:
        """Format as a Server-Sent Event string for streaming to the frontend."""
        payload: dict = {"type": self.type, **self.data}
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.agent_label:
            payload["agent_label"] = self.agent_label
        return f"data: {json.dumps(payload)}\n\n"


class OpenClawClient:
    """
    Async WebSocket client for a single OpenClaw workspace session.

    Each workspace launch creates one client instance. The client holds the
    WebSocket connection open, streaming events until the task is done or
    the caller cancels.
    """

    # Keywords that indicate the parent agent delegated work to a sub-agent and will
    # "auto-announce" the result when the sub-agent finishes.  When we see these in a
    # "final" chat event we must NOT break — we keep the connection open and wait for
    # the sub-agent's result to arrive as a second "final" event on the same session.
    _DELEGATION_SIGNALS = (
        "sub-agent spawned",
        "auto-announce",
        "spawned agent",
        "spawning agent",
        "sub-agent is",
    )

    def __init__(
        self,
        workspace_id: str,
        session_id: Optional[str] = None,
        agent_id: str = "main",
    ):
        self.workspace_id = workspace_id
        # session_id becomes part of the OpenClaw session key.
        # Re-using the same session_id across launches gives OpenClaw memory
        # of previous tasks for the same user.
        self.session_id = session_id or f"harvis-ws-{workspace_id}"
        # agent_id selects which OpenClaw agent handles this session.
        # "main" uses the default local Ollama model configured in openclaw.json.
        self.agent_id = agent_id
        self._ws = None
        self._cancelled = asyncio.Event()
        self._request_id = 0
        # Tracks the full accumulated text from the most recent "partial" chat event
        # sequence so we can emit only the incremental delta, not the whole cumulative
        # text each time (OpenClaw partial events contain full text-so-far, not a delta).
        self._last_partial_text: str = ""
        # Sub-agent run tracking.
        # Maps runId → friendly label so frontend can attribute each event to an agent.
        # First runId seen = "Agent" (parent); subsequent ones = "Sub-Agent 1", "Sub-Agent 2" …
        self._run_labels: dict[str, str] = {}
        self._sub_agent_counter: int = 0

    def _next_id(self) -> str:
        self._request_id += 1
        return str(self._request_id)

    @property
    def _session_key(self) -> str:
        """
        OpenClaw session key format: agent:<agentId>:<mainKey>
        Normalized to lowercase alphanumeric + hyphens.
        agent_id selects the configured OpenClaw agent (e.g. "main" or "kimi").
        """
        safe_session = self.session_id.lower().replace("_", "-")
        safe_agent = self.agent_id.lower().replace("_", "-")
        return f"agent:{safe_agent}:{safe_session}"

    async def _connect(self):
        """Open the WebSocket and authenticate via the connect handshake."""
        ws = await websockets.connect(
            OPENCLAW_URL,
            ping_interval=20,
            ping_timeout=10,
            open_timeout=10,
        )

        # Step 1: Receive the connect.challenge event the server sends immediately on open.
        # {"type":"event","event":"connect.challenge","payload":{"nonce":"...","ts":...}}
        raw_challenge = await asyncio.wait_for(ws.recv(), timeout=10)
        challenge = json.loads(raw_challenge)
        if not (challenge.get("type") == "event" and challenge.get("event") == "connect.challenge"):
            await ws.close()
            raise ConnectionError(
                f"OpenClaw expected connect.challenge event, got: {challenge}"
            )
        nonce = challenge.get("payload", {}).get("nonce", "")
        if not nonce:
            await ws.close()
            raise ConnectionError("OpenClaw connect.challenge missing nonce")

        # Step 2: Send the connect handshake with device identity + scopes.
        # Device identity + shared token auth triggers skipPairingForOperatorSharedAuth,
        # bypassing the pairing/approval flow and granting our requested scopes directly.
        req_id = self._next_id()
        await ws.send(json.dumps({
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": {
                "minProtocol": PROTOCOL_VERSION,
                "maxProtocol": PROTOCOL_VERSION,
                "client": {
                    "id": _CLIENT_ID,
                    "version": "1.0.0",
                    "platform": "linux",
                    "mode": _CLIENT_MODE,
                },
                "role": "operator",
                "scopes": _CLIENT_SCOPES,
                "auth": {
                    "token": OPENCLAW_GATEWAY_TOKEN,
                },
                "device": _build_device_params(nonce),
            },
        }))

        # Step 3: Wait for the handshake response.
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        ack = json.loads(raw)

        if ack.get("type") != "res" or not ack.get("ok"):
            await ws.close()
            error_detail = ack.get("error", {}).get("message", str(ack))
            raise ConnectionError(f"OpenClaw connect handshake failed: {error_detail}")

        logger.info("[workspace:%s] Connected and authenticated to OpenClaw", self.workspace_id)
        return ws

    async def stream(
        self,
        task_message: str,
        chat_history: list[dict],
    ) -> AsyncGenerator[OpenClawEvent, None]:
        """
        Launch a task on OpenClaw and stream back all events until done.

        Args:
            task_message: The task description / user message to send.
            chat_history: Full Harvis chat history (list of {role, content} dicts).

        Yields:
            OpenClawEvent objects.
        """
        # Reset per-stream state
        self._last_partial_text = ""
        self._run_labels = {}
        self._sub_agent_counter = 0

        try:
            self._ws = await self._connect()
        except Exception as e:
            logger.error("[workspace:%s] Failed to connect to OpenClaw: %s", self.workspace_id, e)
            yield OpenClawEvent("error", {"message": f"Could not connect to workspace backend: {e}"})
            return

        # ── Post-connect handshake log ────────────────────────────────────────
        yield OpenClawEvent("log", {
            "message": f"Connected to OpenClaw gateway (agent: {self.agent_id})",
        })

        try:
            # Build an imperative message that forces the agent to execute immediately.
            # Lead with the task directive; context is only appended as reference.

            # Extract the last user message — it's the most specific, actionable request.
            last_user_msg = next(
                (m["content"] for m in reversed(chat_history)
                 if m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].strip()),
                task_message,
            )

            # Build a compact context brief instead of dumping raw history.
            # This keeps per-request token cost low regardless of conversation length.
            context_block = _build_context_brief(chat_history, current_task=last_user_msg)

            # Session-scoped workspace directory — isolates file ops per run.
            safe_session = self.session_id.replace("/", "-").replace(" ", "-")
            workdir = f"/home/node/workspaces/{safe_session}"

            # GitHub availability hint — injected only when the token is configured.
            # The actual token is in $GH_TOKEN env var inside the OpenClaw container.
            # The harvis-github skill handles the full PR workflow procedure.
            # Do NOT inject the raw token here — it would appear in session history.
            github_hint = ""
            # Derive backend hostname from BACKEND_URL env so the same image
            # works in both k8s (harvis-ai-merged-backend) and Docker Compose (backend).
            _backend_host = os.getenv("BACKEND_URL", "http://backend:8000").rstrip("/")
            if HARVIS_GITHUB_TOKEN:
                github_hint = (
                    "\nGITHUB: Pre-configured. $GH_TOKEN / $GH_USER / $GH_EMAIL are set in env.\n"
                    f"For PR creation use the harvis-github skill procedure "
                    f"(POST to {_backend_host}/github/pulls).\n"
                    "Never print $GH_TOKEN. Never push to main.\n"
                )

            # RAG search hint — always injected so the agent uses local knowledge
            # before writing code or answering questions about the codebase.
            rag_hint = (
                "\nRAG SEARCH (REQUIRED before writing code):\n"
                "Search the Harvis knowledge base FIRST using:\n"
                f"  curl -s -X POST {_backend_host}/rag/search \\\n"
                "    -H 'Content-Type: application/json' \\\n"
                "    -H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\" \\\n"
                "    -d '{\"query\": \"<your search terms>\", \"context_type\": \"code\", \"top_k\": 5}'\n"
                "Use context_type 'docs' for architecture/design questions.\n"
                "Do NOT search the public web. Use this endpoint as your only search tool.\n"
            )

            # Imperative directive — task first, context last, no asking back.
            directive = (
                f"WORKSPACE DIRECTORY: {workdir}\n"
                f"Before doing anything, run: mkdir -p {workdir} && cd {workdir}\n"
                f"All file operations (read, write, exec) MUST happen inside {workdir}.\n"
                f"{github_hint}"
                f"{rag_hint}"
                f"\nEXECUTE THIS TASK NOW: {last_user_msg}\n\n"
                "RULES:\n"
                "- Do NOT ask for clarification or say \"what task\".\n"
                "- Do NOT describe what you will do — just do it.\n"
                "- Call your tools (exec, write, read) immediately to complete the task.\n"
                "- Start with a tool call, not a text response.\n"
            )

            if context_block:
                full_message = (
                    f"{directive}\n"
                    f"CONTEXT (brief summary of prior conversation — do not reply to this):\n{context_block}"
                )
            else:
                full_message = directive

            # Send the chat message via chat.send.
            req_id = self._next_id()
            idempotency_key = str(uuid.uuid4())
            await self._ws.send(json.dumps({
                "type": "req",
                "id": req_id,
                "method": "chat.send",
                "params": {
                    "sessionKey": self._session_key,
                    "message": full_message,
                    "idempotencyKey": idempotency_key,
                },
            }))

            logger.info(
                "[workspace:%s] Task sent to OpenClaw (sessionKey=%s), streaming response...",
                self.workspace_id, self._session_key,
            )

            # ── Post-send status log ──────────────────────────────────────────
            yield OpenClawEvent("log", {
                "message": f"Task dispatched to agent — model loading, may take a moment…",
            })

            # Track whether we've emitted the "reasoning" hint yet.
            # Injected once right before the first token so the timeline
            # shows activity during the model warm-up gap.
            _reasoning_logged = False

            # Consume events until the chat reaches a terminal state.
            # OpenClaw pushes:
            #   {"type":"res","id":"<req_id>","ok":true}          — send ack (ignore)
            #   {"type":"event","event":"agent","payload":{...}}  — tool/progress events
            #   {"type":"event","event":"chat","payload":{"state":"final"/"error",...}}
            async for raw in self._ws:
                if self._cancelled.is_set():
                    yield OpenClawEvent("cancelled", {"message": "Workspace cancelled by user."})
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                # Ignore acks and other non-event frames
                if msg_type == "res":
                    if not msg.get("ok"):
                        err = msg.get("error", {}).get("message", "Unknown error")
                        logger.error("[workspace:%s] RPC error: %s", self.workspace_id, err)
                        yield OpenClawEvent("error", {"message": err})
                        break
                    continue

                if msg_type != "event":
                    continue

                event_name = msg.get("event", "")
                payload = msg.get("payload", {})

                # Agent events — tool calls and progress log lines
                if event_name == "agent":
                    for event in self._handle_agent_event(payload):
                        # Inject a one-time "Agent generating response…" log just
                        # before the first token so the timeline shows activity
                        # during the model warm-up gap instead of a blank spinner.
                        if event.type == "token" and not _reasoning_logged:
                            _reasoning_logged = True
                            yield OpenClawEvent("log", {
                                "message": "Agent generating response…",
                            })
                        yield event

                # Chat events — partial streaming or final response
                elif event_name == "chat":
                    state = payload.get("state")

                    if state == "final":
                        # Extract text from the message content blocks
                        message = payload.get("message") or {}
                        content = message.get("content", [])
                        text = self._extract_text(content)

                        # Detect sub-agent delegation: the parent agent has handed off
                        # work to a sub-agent and will "auto-announce" the result when
                        # the sub-agent completes.  Don't treat this as task completion —
                        # keep the WebSocket open so the sub-agent's result comes through
                        # as a second "final" event on the same session.
                        text_lower = text.lower()
                        if any(sig in text_lower for sig in self._DELEGATION_SIGNALS):
                            logger.info(
                                "[workspace:%s] Sub-agent delegation detected — keeping connection open",
                                self.workspace_id,
                            )
                            yield OpenClawEvent("log", {"message": "Sub-agent working — waiting for result…"})
                            # Reset partial tracker for the sub-agent's upcoming stream
                            self._last_partial_text = ""
                            continue  # keep the async-for loop running

                        yield OpenClawEvent("done", {"summary": text})
                        break

                    elif state == "error":
                        err = payload.get("errorMessage", "OpenClaw agent error")
                        yield OpenClawEvent("error", {"message": err})
                        break

                    # "partial" state — OpenClaw sends the FULL accumulated text each
                    # time, not a delta.  Compute the new portion ourselves and emit
                    # only that, so the frontend gets clean incremental tokens instead
                    # of 30+ events each containing the entire growing response.
                    elif state == "partial":
                        message = payload.get("message") or {}
                        content = message.get("content", [])
                        text = self._extract_text(content)
                        if text:
                            delta = text[len(self._last_partial_text):]
                            self._last_partial_text = text
                            if delta:
                                yield OpenClawEvent("token", {"content": delta})

        except ConnectionClosed as e:
            logger.warning("[workspace:%s] OpenClaw connection closed: %s", self.workspace_id, e)
            yield OpenClawEvent("done", {"summary": ""})

        except WebSocketException as e:
            logger.error("[workspace:%s] WebSocket error: %s", self.workspace_id, e)
            yield OpenClawEvent("error", {"message": f"Workspace connection error: {e}"})

        finally:
            await self.close()

    def _extract_text(self, content: list) -> str:
        """Extract plain text from an OpenClaw content block array."""
        parts = []
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif "text" in block:
                    parts.append(str(block["text"]))
        return "".join(parts)

    def _resolve_agent_label(self, run_id: Optional[str]) -> str:
        """
        Return a human-readable label for a given runId.

        The first runId seen in a session is the parent agent ("Agent").
        Each new runId after that is a sub-agent ("Sub-Agent 1", "Sub-Agent 2", …).
        This lets the frontend clearly show which agent performed each action.
        """
        if not run_id:
            return "Agent"
        if run_id not in self._run_labels:
            if not self._run_labels:
                self._run_labels[run_id] = "Agent"
                logger.info(
                    "[workspace:%s] Parent agent run started: runId=%s",
                    self.workspace_id, run_id[:12],
                )
            else:
                self._sub_agent_counter += 1
                label = f"Sub-Agent {self._sub_agent_counter}"
                self._run_labels[run_id] = label
                logger.info(
                    "[workspace:%s] Sub-agent spawned: runId=%s → %s (total sub-agents: %d)",
                    self.workspace_id, run_id[:12], label, self._sub_agent_counter,
                )
        return self._run_labels[run_id]

    def _tag(self, event: OpenClawEvent, run_id: Optional[str]) -> OpenClawEvent:
        """Attach run_id and agent_label to an event in-place and return it."""
        event.run_id = run_id
        event.agent_label = self._resolve_agent_label(run_id)
        return event

    def _handle_agent_event(self, payload: dict):
        """
        Yield OpenClawEvent(s) from an agent event payload.

        OpenClaw agent event format (from pi-embedded-subscribe.handlers.tools.ts):
          {
            "runId": "...",
            "stream": "tool" | "assistant" | "lifecycle" | ...,
            "data": { "phase": "start"|"update"|"result", "name": "exec", ... },
            "seq": 0,
            "ts": 1234567890
          }

        Tool stream phases:
          start  → {name, toolCallId, args}
          update → {name, toolCallId, partialResult}
          result → {name, toolCallId, isError, result, meta}

        Assistant stream:
          {text: "..."}

        Lifecycle stream:
          {phase: "start"|"end"|"error", ...}
        """
        stream = payload.get("stream", "")
        data = payload.get("data") or {}
        run_id: Optional[str] = payload.get("runId") or None

        # Register this runId (creates label if first time seen).
        # This must happen before we emit any events so lifecycle "start" events
        # are already attributed to the correct agent.
        if run_id:
            self._resolve_agent_label(run_id)

        if stream == "tool":
            phase = data.get("phase", "")
            tool_name = data.get("name", "unknown")

            if phase == "start":
                # Tool is being called — emit as tool_call
                tool_args = data.get("args") or {}
                logger.info(
                    "[openclaw] tool_call  session=%.12s tool=%s args=%.80s",
                    self._session_key, tool_name, str(tool_args),
                )
                yield self._tag(OpenClawEvent("tool_call", {
                    "tool": tool_name,
                    "args": tool_args,
                }), run_id)
            elif phase == "result":
                # Tool finished — emit as tool_result
                result_data = data.get("result")
                output = ""
                if isinstance(result_data, str):
                    output = result_data
                elif isinstance(result_data, dict):
                    # Extract text from result dict (OpenClaw often wraps output)
                    output = (
                        result_data.get("output")
                        or result_data.get("text")
                        or result_data.get("stdout")
                        or str(result_data)
                    )
                elif result_data is not None:
                    output = str(result_data)

                success = not data.get("isError", False)
                logger.info(
                    "[openclaw] tool_result session=%.12s tool=%s success=%s output=%.80s",
                    self._session_key, tool_name, success, output,
                )
                yield self._tag(OpenClawEvent("tool_result", {
                    "tool": tool_name,
                    "output": output[:2000],  # cap output length
                    "success": success,
                }), run_id)
            elif phase == "update":
                # Partial tool output — emit as log so it shows in the UI
                partial = data.get("partialResult")
                if partial:
                    yield self._tag(OpenClawEvent("log", {
                        "message": f"[{tool_name}] {str(partial)[:500]}",
                    }), run_id)

        elif stream == "assistant":
            text = data.get("text", "")
            if text:
                yield self._tag(OpenClawEvent("token", {"content": text}), run_id)

        elif stream == "lifecycle":
            phase = data.get("phase", "")
            label = self._resolve_agent_label(run_id)
            if phase == "error":
                err_detail = data.get("error") or data.get("message") or "unknown error"
                yield self._tag(OpenClawEvent("log", {
                    "message": f"{label} error: {err_detail}",
                }), run_id)
            elif phase == "start":
                model_hint = data.get("model") or data.get("modelId") or ""
                model_str = f" ({model_hint})" if model_hint else ""
                yield self._tag(OpenClawEvent("log", {
                    "message": f"{label} started{model_str} — waiting for first token…",
                }), run_id)
            elif phase == "end":
                yield self._tag(OpenClawEvent("log", {
                    "message": f"{label} finished",
                }), run_id)

        else:
            # Catch-all: emit any other event as a log so nothing is silently dropped
            kind = payload.get("kind") or payload.get("type", "")
            if kind in ("tool_call", "tool.call", "toolCall"):
                yield self._tag(OpenClawEvent("tool_call", {
                    "tool": payload.get("toolName") or payload.get("name", "unknown"),
                    "args": payload.get("args") or payload.get("input", {}),
                }), run_id)
            elif kind in ("tool_result", "tool.result", "toolResult"):
                yield self._tag(OpenClawEvent("tool_result", {
                    "tool": payload.get("toolName") or payload.get("name", "unknown"),
                    "output": payload.get("output", ""),
                    "success": payload.get("success", True),
                }), run_id)
            elif kind in ("log", "info", "debug"):
                msg = payload.get("message") or str(payload)
                yield self._tag(OpenClawEvent("log", {"message": msg}), run_id)
            else:
                # Unknown event — emit as log with raw data
                msg = payload.get("message") or payload.get("text") or ""
                if msg:
                    yield self._tag(OpenClawEvent("log", {"message": str(msg)[:500]}), run_id)

    def cancel(self):
        """Signal the stream loop to stop after the current event."""
        self._cancelled.set()
        logger.info("[workspace:%s] Cancel requested", self.workspace_id)

    async def close(self):
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
                logger.info("[workspace:%s] WebSocket closed", self.workspace_id)
            except Exception:
                pass
