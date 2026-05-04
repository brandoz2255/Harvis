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
import re
import time
import uuid
from typing import AsyncGenerator, Optional

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = logging.getLogger(__name__)

OPENCLAW_URL = os.getenv("OPENCLAW_URL", "ws://harvis-ai-openclaw:18789")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# Optional failover: if connecting to the primary OpenClaw fails, try this URL.
# Used to keep a remote primary (e.g. desktop GPU box) with the local bundled
# container as the safety net. Empty string disables fallback.
OPENCLAW_FALLBACK_URL = os.getenv("OPENCLAW_FALLBACK_URL", "")
OPENCLAW_FALLBACK_TOKEN = os.getenv("OPENCLAW_FALLBACK_TOKEN", "") or OPENCLAW_GATEWAY_TOKEN

# HOME directory used by the OpenClaw gateway we're talking to. The dockerized
# container runs as `node` with HOME=/home/node; a host-installed OpenClaw on
# host.docker.internal:18790 typically runs as the user (e.g. /home/<you>).
# Wrong value → mkdir/cd in the model's task brief targets a directory the
# gateway user cannot create, and the very first tool call fails. Override via
# OPENCLAW_HOME env var when pointing at a non-default gateway.
OPENCLAW_HOME = os.getenv("OPENCLAW_HOME", "/home/node").rstrip("/")

# Identity files (mounted into backend container).
# docker-compose mounts ./openclaw/config -> /app/openclaw_config:ro
_IDENTITY_DIR = os.getenv("HARVIS_OPENCLAW_IDENTITY_DIR", "/app/openclaw_config")
_IDENTITY_FILES = (
    ("IDENTITY", "IDENTITY.md"),
    ("SOUL", "SOUL.md"),
    ("USER", "USER.md"),
    ("AGENT", "AGENT.md"),
)
_IDENTITY_CACHE: Optional[str] = None


def _load_identity_bundle() -> str:
    """
    Load Harvis identity + behavior documents and return a single markdown block.

    Injected into every OpenClaw run so the agent is persistent even if OpenClaw
    session memory resets (or a different sessionKey is used, e.g. Discord).
    """
    global _IDENTITY_CACHE
    # If we previously failed to load (cached empty), try again on subsequent calls.
    # This matters in Docker when volumes/env are added after the process first started.
    if _IDENTITY_CACHE:
        return _IDENTITY_CACHE

    parts: list[str] = []
    for label, fname in _IDENTITY_FILES:
        path = os.path.join(_IDENTITY_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                parts.append(f"## {label}\n\n{content}\n")
        except Exception as exc:
            logger.warning("OpenClaw identity file missing/unreadable: %s (%s)", path, exc)

    if not parts:
        _IDENTITY_CACHE = ""
        return ""

    _IDENTITY_CACHE = (
        "SYSTEM IDENTITY (always follow; do not argue; do not restate):\n\n"
        + "\n".join(parts)
        + "\n"
    )
    return _IDENTITY_CACHE

# GitHub credentials — either GitHub App (preferred) or legacy PAT.
# The actual token is never injected into the directive; the skill mints it at runtime.
# We only check whether GitHub is configured so we know to inject the hint.
HARVIS_GITHUB_TOKEN = os.getenv("HARVIS_GITHUB_TOKEN", "")       # legacy PAT fallback
HARVIS_GITHUB_APP_ID = os.getenv("HARVIS_GITHUB_APP_ID", "")     # GitHub App (preferred)
HARVIS_GITHUB_USER = os.getenv("HARVIS_GITHUB_USER", "HarvisAI[bot]")
HARVIS_GITHUB_EMAIL = os.getenv("HARVIS_GITHUB_EMAIL", "2995570+HarvisAI[bot]@users.noreply.github.com")

# True when any GitHub auth method is configured
_GITHUB_CONFIGURED = bool(HARVIS_GITHUB_APP_ID or HARVIS_GITHUB_TOKEN)


def _exec_via_bash(shell_one_liner: str) -> str:
    """
    Wrap a shell one-liner for OpenClaw `exec` so `$OPENCLAW_GATEWAY_TOKEN` expands.

    Many exec paths invoke argv directly (no shell). A bare
    `curl ... -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN"` then sends the
    literal dollar-name string and Harvis returns 401 Invalid proxy token.
    """
    escaped = shell_one_liner.replace("\\", "\\\\").replace('"', '\\"')
    return f'bash --noprofile --norc +H -lc "{escaped}"'


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


def _derive_identity_from_private_key(private_key: Ed25519PrivateKey):
    public_key = private_key.public_key()
    # Export DER-encoded SPKI public key, then strip the 12-byte prefix to get raw 32 bytes
    pub_der = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if pub_der[: len(_ED25519_SPKI_PREFIX)] == _ED25519_SPKI_PREFIX:
        raw_pub = pub_der[len(_ED25519_SPKI_PREFIX):]
    else:
        raw_pub = pub_der  # fallback (shouldn't happen for Ed25519)
    device_id = hashlib.sha256(raw_pub).hexdigest()
    pub_b64url = _base64url_encode(raw_pub)
    return device_id, pub_b64url


# Persistent device identity path.
# OpenClaw pairs devices by deviceId; a fresh keypair on every backend restart
# invalidates any prior pairing, forcing the user to re-approve the device via
# `openclaw devices approve …` after every restart. Persisting the key keeps
# the pairing valid across restarts.
_DEVICE_KEY_PATH = os.getenv(
    "HARVIS_OPENCLAW_DEVICE_KEY",
    "/data/artifacts/openclaw-device-key.pem",
)


def _load_or_create_device_identity():
    """Load the persisted Ed25519 private key, or generate + save a new one."""
    try:
        if os.path.exists(_DEVICE_KEY_PATH):
            with open(_DEVICE_KEY_PATH, "rb") as f:
                pem = f.read()
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            private_key = load_pem_private_key(pem, password=None)
            if not isinstance(private_key, Ed25519PrivateKey):
                raise ValueError("Persisted key is not Ed25519")
            device_id, pub_b64url = _derive_identity_from_private_key(private_key)
            logger.info(
                "OpenClaw device identity loaded from %s (deviceId=%s…)",
                _DEVICE_KEY_PATH, device_id[:16],
            )
            return private_key, device_id, pub_b64url
    except Exception as exc:
        logger.warning(
            "Failed to load persisted device key (%s): %s — regenerating",
            _DEVICE_KEY_PATH, exc,
        )

    private_key = Ed25519PrivateKey.generate()
    device_id, pub_b64url = _derive_identity_from_private_key(private_key)
    try:
        os.makedirs(os.path.dirname(_DEVICE_KEY_PATH), exist_ok=True)
        pem_bytes = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
        with open(_DEVICE_KEY_PATH, "wb") as f:
            f.write(pem_bytes)
        os.chmod(_DEVICE_KEY_PATH, 0o600)
        logger.info(
            "OpenClaw device identity generated + saved to %s (deviceId=%s…). "
            "Approve once via `openclaw devices approve <request-id>` on the host.",
            _DEVICE_KEY_PATH, device_id[:16],
        )
    except Exception as exc:
        logger.warning("Failed to persist device key to %s: %s", _DEVICE_KEY_PATH, exc)
    return private_key, device_id, pub_b64url


# Module-level device identity — loaded or generated once per process startup.
_device_private_key, _device_id, _device_pub_b64url = _load_or_create_device_identity()


def _build_device_params(nonce: str, token: str = "") -> dict:
    """
    Build the signed device identity block for the OpenClaw connect handshake.

    Payload format (v2): "v2|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce"

    Args:
        nonce: Challenge nonce from the server.
        token: Gateway token to sign with. Falls back to module-level constant.
    """
    effective_token = token or OPENCLAW_GATEWAY_TOKEN
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
        effective_token,
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
    Render recent chat history as an in-order transcript so the agent has real
    conversational memory (names, prior asks, references like "that image",
    "the file you just looked at").

    Budget: up to ~4000 chars total (~1000 tokens). Comfortably fits inside
    the 8K num_ctx local models default to while leaving room for tools +
    system prompt + new task.

    The current task itself is excluded — it's already in the directive.
    Returns an empty string when there's nothing useful to include.
    """
    if not chat_history:
        return ""

    MAX_TURNS = 10              # keep the last N turns (user+assistant combined)
    MAX_CHARS_USER = 500
    MAX_CHARS_ASSISTANT = 600
    TOTAL_BUDGET_CHARS = 4000

    # Walk newest → oldest, drop the current task if it's the most recent user turn
    recent: list[tuple[str, str]] = []  # (role, text) newest-first
    skipped_current = False
    for m in reversed(chat_history):
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        text = (m.get("content") or "").strip()
        if not text:
            continue
        if not skipped_current and role == "user" and text == current_task:
            skipped_current = True
            continue

        if role == "user":
            if len(text) > MAX_CHARS_USER:
                text = text[:MAX_CHARS_USER] + "…"
        else:  # assistant
            if len(text) > MAX_CHARS_ASSISTANT:
                text = text[:MAX_CHARS_ASSISTANT] + "…"

        recent.append((role, text))
        if len(recent) >= MAX_TURNS:
            break

    if not recent:
        return ""

    # Put oldest first so the transcript reads chronologically
    recent.reverse()

    lines: list[str] = ["Recent conversation (most recent last):"]
    used = len(lines[0])
    for role, text in recent:
        prefix = "User:" if role == "user" else "You (Harvis):"
        line = f"{prefix} {text}"
        if used + len(line) > TOTAL_BUDGET_CHARS:
            # Budget hit — stop rather than spilling into the tool/system prompt.
            lines.append("…(earlier turns trimmed to stay within context budget)…")
            break
        lines.append(line)
        used += len(line)

    return "\n".join(lines)


_BROWSER_REFUSAL_SIGNALS = (
    "as a text-based ai",
    "as a language model",
    "i do not have direct access to a web browser",
    "cannot execute the request literally",
    "cannot take real-time screenshots",
    "i cannot browse",
    "simulated screenshot",
)


def _extract_browser_target_url(task_text: str) -> str:
    """
    Best-effort URL extraction for browser tasks.
    Returns an https URL, defaulting to Google when no explicit URL is present.
    """
    text = task_text or ""
    explicit = re.search(r'https?://[^\s)]+', text, re.IGNORECASE)
    if explicit:
        return explicit.group(0)

    bare = re.search(r'\b([a-z0-9-]+\.[a-z]{2,}(?:/[^\s)]*)?)\b', text, re.IGNORECASE)
    if bare:
        return f"https://{bare.group(1)}"

    return "https://google.com"


def _looks_like_browser_or_screenshot_task(task_text: str) -> bool:
    low = (task_text or "").lower()
    return (
        "http://" in low
        or "https://" in low
        or ".com" in low
        or "screenshot" in low
        or "screen shot" in low
        or "navigate" in low
        or "open " in low
        or "website" in low
        or "webpage" in low
    )


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
        gateway_url: Optional[str] = None,
        gateway_token: Optional[str] = None,
        workspace_prefix: str = "",
    ):
        self.workspace_id = workspace_id
        # session_id becomes part of the OpenClaw session key.
        # Re-using the same session_id across launches gives OpenClaw memory
        # of previous tasks for the same user.
        self.session_id = session_id or f"harvis-ws-{workspace_id}"
        # agent_id selects which OpenClaw agent handles this session.
        # "main" uses the default local Ollama model configured in openclaw.json.
        self.agent_id = agent_id
        # Per-instance gateway overrides — enables BYO mode routing.
        # Falls back to module-level constants when not provided.
        self.gateway_url = gateway_url or OPENCLAW_URL
        self.gateway_token = gateway_token or OPENCLAW_GATEWAY_TOKEN
        # Workspace prefix for filesystem isolation (bundled: "bundled/<uid>/", BYO: "")
        self.workspace_prefix = workspace_prefix
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
        """
        Open the WebSocket and authenticate via the connect handshake.

        Tries `self.gateway_url` first. If that fails with a connection-level
        error and `OPENCLAW_FALLBACK_URL` is set (and different), retries against
        the fallback. On fallback success, mutates `self.gateway_url`/token so any
        later reconnects in the same stream stay on the working endpoint.
        """
        try:
            return await self._connect_to(self.gateway_url, self.gateway_token)
        except (OSError, asyncio.TimeoutError, ConnectionError, WebSocketException) as primary_exc:
            fallback_url = OPENCLAW_FALLBACK_URL
            if not fallback_url or fallback_url == self.gateway_url:
                raise
            logger.warning(
                "[workspace:%s] Primary OpenClaw %s failed (%s) — falling back to %s",
                self.workspace_id, self.gateway_url, primary_exc, fallback_url,
            )
            ws = await self._connect_to(fallback_url, OPENCLAW_FALLBACK_TOKEN or self.gateway_token)
            self.gateway_url = fallback_url
            self.gateway_token = OPENCLAW_FALLBACK_TOKEN or self.gateway_token
            return ws

    async def _connect_to(self, url: str, token: str):
        """Single-target connect + handshake. Raises on any failure."""
        ws = await websockets.connect(
            url,
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
                "caps": ["tool-events"],
                "role": "operator",
                "scopes": _CLIENT_SCOPES,
                "auth": {
                    "token": token,
                },
                "device": _build_device_params(nonce, token),
            },
        }))

        # Step 3: Wait for the handshake response.
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        ack = json.loads(raw)

        if ack.get("type") != "res" or not ack.get("ok"):
            await ws.close()
            error_detail = ack.get("error", {}).get("message", str(ack))
            raise ConnectionError(f"OpenClaw connect handshake failed: {error_detail}")

        logger.info("[workspace:%s] Connected and authenticated to OpenClaw at %s", self.workspace_id, url)
        return ws

    async def stream(
        self,
        task_message: str,
        chat_history: list[dict],
        interactive_context: Optional[dict] = None,
        live_web: bool = False,
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
        # _narrative_cut: index into _last_partial_text marking where the
        # last "narrative" (text the model emitted before a tool call) was
        # already surfaced as a log event. Anything past this index is fresh
        # narrative awaiting the next tool_call to flush as a "💬 ..." line.
        self._narrative_cut = 0
        self._run_labels = {}
        self._sub_agent_counter = 0

        try:
            self._ws = await self._connect()
        except Exception as e:
            logger.error("[workspace:%s] Failed to connect to OpenClaw: %s", self.workspace_id, e)
            yield OpenClawEvent("error", {
                "message": f"Could not connect to workspace backend: {e}",
                "fix_hint": "The OpenClaw container may not be running. Check `docker compose ps` or `kubectl get pods -n ai-agents`.",
            })
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

            # Session-scoped workspace directory.
            #
            # The OpenClaw gateway's `exec` and `write` tools run with CWD
            # /home/node/.openclaw/workspace — that is what `write` treats as
            # its root. Previously we handed the model an absolute path under
            # /home/node/workspaces/bundled/<uid>/<session>/, but the `write`
            # tool does not cooperate with that path: files written relative
            # to the tool land in /home/node/.openclaw/workspace/, while the
            # model tried to `cd` into the scoped dir it was told, read its
            # own file back, and failed (empty dir, file actually elsewhere).
            #
            # Fix: place the workdir inside the real exec CWD, so `mkdir`,
            # `cd`, `write` (which treats relative paths as rooted in
            # /home/node/.openclaw/workspace) and subsequent `python3 file.py`
            # all agree on one location.
            safe_session = self.session_id.replace("/", "-").replace(" ", "-")
            _scope_tag = self.workspace_prefix.replace("/", "-").strip("-")
            _scope_slug = f"{_scope_tag}-" if _scope_tag else ""
            workdir = f"{OPENCLAW_HOME}/.openclaw/workspace/session-{_scope_slug}{safe_session}"
            workdir_rel = f"session-{_scope_slug}{safe_session}"

            # GitHub availability hint — injected only when the token is configured.
            # The actual token is in $GH_TOKEN env var inside the OpenClaw container.
            # The harvis-github skill handles the full PR workflow procedure.
            # Do NOT inject the raw token here — it would appear in session history.
            github_hint = ""
            # Derive backend hostname from BACKEND_URL env so the same image
            # works in both k8s (harvis-ai-merged-backend) and Docker Compose (backend).
            _backend_host = os.getenv("BACKEND_URL", "http://backend:8000").rstrip("/")
            if _GITHUB_CONFIGURED:
                github_hint = (
                    "\nGITHUB: Pre-configured via GitHub App. "
                    "$GH_APP_ID / $GH_INSTALLATION_ID / $GH_PRIVATE_KEY are set in env.\n"
                    f"For PR creation use the harvis-github skill procedure "
                    f"(POST to {_backend_host}/github/pulls).\n"
                    "Never print any credential values. Never push to main.\n"
                )

            repo_hint = (
                "\nREPO MOUNTING (workspace-first routing):\n"
                "If a GitHub repo is mounted for this user, prefer editing inside "
                f"{OPENCLAW_HOME}/projects/<owner>/<repo> instead of creating detached files.\n"
                "When repository paths are provided in task context/events, set your "
                "workdir to that mounted repo and run git operations there.\n"
            )

            # RAG search hint — always injected so the agent uses local knowledge
            # before writing code or answering questions about the codebase.
            _rag_curl = (
                f"curl -s -X POST {_backend_host}/rag/search "
                f"-H \"Content-Type: application/json\" "
                f"-H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\" "
                f"-H \"X-OpenClaw-SessionKey: {self._session_key}\" "
                "-d '{\"query\": \"<your search terms>\", \"context_type\": \"code\", \"top_k\": 5}'"
            )
            rag_hint = (
                "\nRAG SEARCH (REQUIRED before writing code):\n"
                "Search the Harvis knowledge base FIRST using one `exec` with:\n"
                f"  {_exec_via_bash(_rag_curl)}\n"
                "Use context_type 'docs' for architecture/design questions.\n"
                "IMPORTANT: Use the bash-wrapped command above so `$OPENCLAW_GATEWAY_TOKEN` expands.\n"
            )

            # Web access hint — tell the agent to CALL exec, not print commands.
            # Qwen 3.5 copies raw bash as text if we show it as code blocks.
            _live_hdr = ' -H "X-Live-Web: true"' if live_web else ""
            _max_r = "10" if live_web else "8"
            _search_inner = (
                f"curl -s -X POST {_backend_host}/api/tools/search"
                f" -H \"Content-Type: application/json\""
                f" -H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\""
                f" -H \"X-OpenClaw-SessionKey: {self._session_key}\""
                f"{_live_hdr}"
                f" -d '{{\"query\":\"REPLACE_WITH_QUERY\",\"max_results\":{_max_r}}}'"
            )
            _fetch_inner = (
                f"curl -s -X POST {_backend_host}/api/tools/web-fetch"
                f" -H \"Content-Type: application/json\""
                f" -H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\""
                f" -H \"X-OpenClaw-SessionKey: {self._session_key}\""
                f"{_live_hdr}"
                f" -d '{{\"url\":\"REPLACE_WITH_URL\",\"purpose\":\"research\"}}'"
            )
            _search_cmd = _exec_via_bash(_search_inner)
            _fetch_cmd = _exec_via_bash(_fetch_inner)
            web_hint = (
                "\nWEB ACCESS:\n"
                "You can search the internet and fetch web pages.\n"
                "IMPORTANT: Call the `exec` tool with these bash-wrapped commands. Do NOT type them as text.\n\n"
                f"To search: call exec with command: {_search_cmd}\n"
                f"To fetch a URL: call exec with command: {_fetch_cmd}\n\n"
                "After exec returns the JSON result, read it and summarize for the user.\n"
                "The bash wrapper is required so `$OPENCLAW_GATEWAY_TOKEN` expands (otherwise you get Invalid proxy token).\n"
                "Never output the command as text. Always call exec.\n"
            )

            # Browser automation hint — injected when interactive_context is provided
            # with workspace_id and capability_token (from workspace_web_caps table).
            browser_hint = ""
            if interactive_context:
                _bws_id = interactive_context.get("workspace_id", "")
                _bcap = interactive_context.get("capability_token", "")
                if _bws_id and _bcap:
                    _b_base = f"{_backend_host}/api/tools/browser"
                    _b_auth = (
                        f"-H \"Content-Type: application/json\" "
                        f"-H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\" "
                        f"-H \"X-OpenClaw-SessionKey: {self._session_key}\""
                        f"{_live_hdr}"
                    )
                    _b_creds = f'"workspace_id":"{_bws_id}","capability_token":"{_bcap}"'
                    _b_open = (
                        f"curl -s -X POST {_b_base}/session {_b_auth} "
                        f"-d '{{{_b_creds},\"headless\":true}}'"
                    )
                    _b_nav = (
                        f"curl -s -X POST {_b_base}/navigate {_b_auth} "
                        f"-d '{{{_b_creds},\"sessionId\":\"SESSION_ID\",\"url\":\"https://TARGET_URL\"}}'"
                    )
                    _b_shot = (
                        f"curl -s -X POST {_b_base}/screenshot {_b_auth} "
                        f"-d '{{{_b_creds},\"sessionId\":\"SESSION_ID\"}}'"
                    )
                    _b_click = (
                        f"curl -s -X POST {_b_base}/act {_b_auth} "
                        f"-d '{{{_b_creds},\"sessionId\":\"SESSION_ID\",\"action\":\"click\",\"selector\":\"CSS_SEL\"}}'"
                    )
                    _b_type = (
                        f"curl -s -X POST {_b_base}/act {_b_auth} "
                        f"-d '{{{_b_creds},\"sessionId\":\"SESSION_ID\",\"action\":\"type\",\"selector\":\"CSS_SEL\",\"text\":\"VALUE\"}}'"
                    )
                    _b_press = (
                        f"curl -s -X POST {_b_base}/act {_b_auth} "
                        f"-d '{{{_b_creds},\"sessionId\":\"SESSION_ID\",\"action\":\"press\",\"key\":\"enter\"}}'"
                    )
                    _b_close = (
                        f"curl -s -X POST {_b_base}/close {_b_auth} "
                        f"-d '{{{_b_creds},\"sessionId\":\"SESSION_ID\"}}'"
                    )
                    browser_hint = (
                        "\nBROWSER AUTOMATION (interactive website access):\n"
                        "You have a real Firefox browser. Use exec tool with these bash-wrapped curl commands.\n"
                        "Never claim you cannot browse or screenshot websites; you can and must use these tools.\n"
                        "IMPORTANT: Call exec tool. Do NOT type these as text.\n\n"
                        "CREDENTIALS: Copy the EXACT `workspace_id` and `capability_token` strings from the "
                        "JSON in this task message into every browser `-d` body. "
                        "If you alter them, Harvis returns 403 Invalid capability token.\n"
                        "401 Invalid proxy token means the bash-wrapped Authorization header did not expand "
                        "`$OPENCLAW_GATEWAY_TOKEN` — use only the provided bash -lc commands.\n\n"
                        "Each line MUST be run via the bash wrapper so `$OPENCLAW_GATEWAY_TOKEN` expands "
                        "(otherwise Harvis returns Invalid proxy token).\n"
                        "DO NOT use the internal `browser` tool for this workflow. "
                        "Only use `exec` with the /api/tools/browser/* proxy commands below.\n"
                        "Also keep the X-OpenClaw-SessionKey exactly as provided.\n\n"
                        f"  Open session:  {_exec_via_bash(_b_open)}\n"
                        "  -> Returns JSON: {\"sessionId\":\"...\"}\n"
                        "     Mandatory next step: read that returned `sessionId` value and paste the exact string\n"
                        "     into subsequent commands in place of SESSION_ID.\n\n"
                        f"  Navigate:      {_exec_via_bash(_b_nav)}\n"
                        "  -> URLs MUST be https. Returns page title and final URL.\n\n"
                        f"  Screenshot:    {_exec_via_bash(_b_shot)}\n"
                        "  -> Returns artifact_path of the saved screenshot.\n"
                        "  Then call the `image` tool with `file_path` set to that artifact_path.\n"
                        "  IMPORTANT: Do NOT call `read` on the artifact_path for screenshot analysis.\n\n"
                        f"  Click:         {_exec_via_bash(_b_click)}\n\n"
                        f"  Type text:     {_exec_via_bash(_b_type)}\n\n"
                        f"  Press key:     {_exec_via_bash(_b_press)}\n\n"
                        f"  Close session: {_exec_via_bash(_b_close)}\n\n"
                        "MANDATORY WORKFLOW for this workspace:\n"
                        "- open session\n"
                        "- navigate\n"
                        "- screenshot\n"
                        "- close session\n\n"
                        "If you need to interact (click/type/press), do it *after* navigate and then screenshot again if needed.\n"
                        "Always screenshot after navigating to see the page. Close session when done.\n"
                    )
                    logger.info(
                        "[workspace:%s] Browser hints injected (workspace_id=%s)",
                        self.workspace_id, _bws_id,
                    )

            # Imperative directive — task first, context last, no asking back.
            _workdir_init = _exec_via_bash(f"mkdir -p {workdir} && cd {workdir} && pwd")
            directive = (
                f"WORKSPACE DIRECTORY: {workdir}\n"
                "FILESYSTEM LAYOUT (IMPORTANT — READ BEFORE USING TOOLS):\n"
                f"- The `exec` tool runs commands with CWD {OPENCLAW_HOME}/.openclaw/workspace\n"
                "- The `write` tool treats relative paths as rooted at the SAME directory\n"
                f"- Your session sub-directory is `{workdir_rel}/` under that root\n"
                f"- Use the RELATIVE form `{workdir_rel}/<filename>` for `write`\n"
                f"- Use the ABSOLUTE form `{workdir}/<filename>` for `exec`/`python3`\n"
                f"- DO NOT assume any {OPENCLAW_HOME}/workspaces/... path exists — that tree is unrelated to the exec CWD.\n"
                "\n"
                "MANDATORY WORKDIR INIT:\n"
                f"Your VERY FIRST action MUST be an `exec` tool call that runs exactly:\n"
                f"  {_workdir_init}\n"
                "Do not run `cd` alone; do not run other tools before this.\n"
                f"All file operations (read, write, exec) MUST happen inside {workdir}.\n"
                f"{github_hint}"
                f"{repo_hint}"
                f"{rag_hint}"
                f"{web_hint}"
                f"{browser_hint}"
                f"\nEXECUTE THIS TASK NOW: {last_user_msg}\n\n"
                "RULES:\n"
                "- ALWAYS use tool calls (exec, write, read). NEVER type commands as text.\n"
                "- NARRATE BETWEEN TOOLS. Every tool call AND every tool result "
                "must be wrapped in one short sentence (under 25 words):\n"
                "    (a) BEFORE a tool call: state what you are about to do and "
                "why, then immediately call the tool.\n"
                "        Example: \"Writing the helper script first.\" → write "
                "tool call.\n"
                "    (b) AFTER a tool result: state what you observed and what "
                "you'll do next, then call the next tool (or end if done).\n"
                "        Example: \"Got a 200 with the JSON I expected — now "
                "parsing it for the price field.\" → exec tool call.\n"
                "  The user sees these as 💬 progress notes between tool calls. "
                "Keep them concrete (mention the actual file/url/error/value "
                "you saw) and free of filler like \"Let me\", \"I'll now\", "
                "\"Great\", or \"Okay\".\n"
                "- Do NOT ask for clarification. Just narrate one line, then act.\n"
                "- Do NOT pre-plan in long paragraphs. One sentence, then a tool.\n"
                "- Do NOT chain tools silently. Even if you already know the next "
                "tool, write the one-sentence narration first so the user can "
                "follow along.\n"
                "- You CAN access the internet. Call exec with the bash-wrapped curl commands above.\n"
                "- Never claim browser/screenshot limitations. You have real browser tooling in this workspace.\n"
                "- If the user asks for a screenshot or website check, execute the browser workflow and provide the artifact.\n"
                "- After exec returns a result, summarize it clearly; markdown formatting is allowed (bold, bullets, code).\n"
                "- For tasks with independent parallel parts (e.g. research + code check, multiple URLs), "
                "use `sessions_spawn` to delegate sub-agents when available; merge results in your final answer.\n"
                "- SUB-AGENTS: Spawned workers are internal only. Do NOT repeat Harvis identity, "
                "Discord/channel setup, or integration boilerplate in sub-agent replies. "
                "Do NOT describe multiple 'Discord instances' or duplicate the assistant persona — "
                "one Harvis, one user-facing voice; sub-agents return facts only for the parent to merge.\n"
                "\n"
                "PYTHON EXECUTION RULES (read before running python3):\n"
                "- NEVER call `python3 -c '...'` when the code contains any of: `decode`, "
                "`base64`, `b64decode`, `exec`, `system`, or `eval`. The sandbox will flag "
                "the command as obfuscated and BLOCK it; you will see `Approval required` "
                "or `Obfuscated command detected` in the exec output. That means the command "
                "DID NOT RUN.\n"
                "- Always: (1) use the `write` tool to save a `.py` file under your "
                f"session workdir (path form: `{workdir_rel}/<name>.py`), then "
                f"(2) run it with `exec`: `python3 {workdir}/<name>.py`.\n"
                "- For binary/decoded output, print using `sys.stdout.buffer.write(...)` or "
                "`.hex()` — do NOT call `.decode('utf-8')` on bytes you don't know are UTF-8.\n"
                "- If an exec result mentions `Approval required`, `Obfuscated command detected`, "
                "or `approval-pending`, treat the command as FAILED and rewrite it as a "
                "write-then-run script. Do not proceed as if the command succeeded.\n"
                "\n"
                "ANSWER CONTRACT:\n"
                "- Every task MUST end with a human-readable final answer that reports either "
                "the observed result OR a clear statement of uncertainty.\n"
                "- NEVER end with `Copy that.`, `Standing by.`, `On it.`, an empty reply, or a "
                "restatement of the task.\n"
                "- If you cannot determine the answer after using tools, say: "
                "\"I could not determine the answer. Blocker: <one-sentence reason>.\" — then stop.\n"
                "- If you fabricate or guess a flag/answer without tool evidence, that is a "
                "failure. Prefer honest uncertainty to a hallucinated result.\n"
            )

            identity_bundle = _load_identity_bundle()
            if context_block:
                full_message = (
                    f"{identity_bundle}\n{directive}\n"
                    f"CONTEXT (brief summary of prior conversation — do not reply to this):\n{context_block}"
                )
            else:
                full_message = f"{identity_bundle}\n{directive}"

            # Extra guardrail: if the agent asks identity/setup questions, it's not following instructions.
            # Keep this short and at the top of the task message.
            full_message = (
                "DO NOT ask identity/setup questions. You already have your identity and mission. "
                "You are Harvis.\n\n"
                + full_message
            )

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
            saw_tool_call = False
            corrective_retry_count = 0
            looks_visual_task = _looks_like_browser_or_screenshot_task(last_user_msg)
            target_url = _extract_browser_target_url(last_user_msg)

            # Consume events until the chat reaches a terminal state.
            # OpenClaw pushes:
            #   {"type":"res","id":"<req_id>","ok":true}          — send ack (ignore)
            #   {"type":"event","event":"agent","payload":{...}}  — tool/progress events
            #   {"type":"event","event":"chat","payload":{"state":"final"/"error",...}}
            _oc_frame_count = 0
            async for raw in self._ws:
                if self._cancelled.is_set():
                    yield OpenClawEvent("cancelled", {"message": "Workspace cancelled by user."})
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                # region agent log — trace the first ~20 inbound frames and any chat terminal state
                _oc_frame_count += 1
                try:
                    _ev = msg.get("event", "")
                    _state = (msg.get("payload") or {}).get("state") if isinstance(msg.get("payload"), dict) else None
                    if _oc_frame_count <= 20 or _ev == "chat":
                        import json as _json5, time as _time5, uuid as _uuid5
                        _log_path = "/tmp/debug-d007eb.log"
                        with open(_log_path, "a", encoding="utf-8") as _f:
                            _f.write(_json5.dumps({
                                "sessionId": "d007eb",
                                "id": f"log_{int(_time5.time()*1000)}_{_uuid5.uuid4().hex[:8]}",
                                "timestamp": int(_time5.time()*1000),
                                "location": "openclaw_client.py:stream:frame",
                                "message": "oc_inbound_frame",
                                "data": {
                                    "workspace_id": self.workspace_id,
                                    "frame_no": _oc_frame_count,
                                    "msg_type": msg_type,
                                    "event": _ev,
                                    "state": _state,
                                },
                                "runId": "run_oc_stream",
                                "hypothesisId": "H_stall",
                            }, separators=(",", ":")) + "\n")
                except Exception:
                    pass
                # endregion

                # ── Handle incoming RPC requests from OpenClaw ──────────────
                if msg_type == "req":
                    method = msg.get("method", "")
                    req_id = msg.get("id")
                    if "approval" in method or "exec" in method:
                        logger.info(
                            "[workspace:%s] Auto-approving RPC request: method=%s id=%s",
                            self.workspace_id, method, req_id,
                        )
                        await self._ws.send(json.dumps({
                            "type": "res",
                            "id": req_id,
                            "ok": True,
                            "result": {"decision": "allow", "approved": True},
                        }))
                    else:
                        logger.warning(
                            "[workspace:%s] Ignoring unknown RPC request: method=%s",
                            self.workspace_id, method,
                        )
                    continue

                # Ignore acks and other non-event frames
                if msg_type == "res":
                    if not msg.get("ok"):
                        err = msg.get("error", {}).get("message", "Unknown error")
                        logger.error("[workspace:%s] RPC error: %s", self.workspace_id, err)
                        # Detect specific error patterns for better hints
                        if "model" in err.lower() and ("not found" in err.lower() or "404" in err):
                            hint = (
                                "The requested model is not available in Ollama. "
                                "Run: docker exec harvis-ollama ollama list  to see installed models, "
                                "then pull one yourself: docker exec harvis-ollama ollama pull <model>"
                            )
                        elif "unknown method" in err.lower():
                            hint = "OpenClaw protocol mismatch. Check that the OpenClaw image version matches the client."
                        else:
                            hint = "An RPC error occurred in the OpenClaw gateway. Check: docker compose logs openclaw --tail 30"
                        yield OpenClawEvent("error", {
                            "message": err,
                            "fix_hint": hint,
                        })
                        break
                    continue

                if msg_type != "event":
                    continue

                event_name = msg.get("event", "")
                payload = msg.get("payload", {})

                # ── Auto-approve exec tool requests ──────────────────────────
                # OpenClaw sends an "exec.approval.requested" event when an
                # agent wants to run a shell command.  We immediately approve
                # by calling exec.approval.decide so the agent doesn't block
                # for the 120s timeout.  The Harvis orchestrator controls what
                # agents can reach at the network layer.
                if event_name == "exec.approval.requested":
                    approval_id = payload.get("id")
                    cmd = payload.get("request", {}).get("command", "?")
                    logger.info(
                        "[workspace:%s] Auto-approving exec: id=%s cmd=%s",
                        self.workspace_id, approval_id, cmd[:120],
                    )
                    approve_req_id = self._next_id()
                    await self._ws.send(json.dumps({
                        "type": "req",
                        "id": approve_req_id,
                        "method": "exec.approval.resolve",
                        "params": {
                            "id": approval_id,
                            "decision": "allow-always",
                        },
                    }))
                    continue

                # Agent events — tool calls and progress log lines
                if event_name == "agent":
                    for event in self._handle_agent_event(payload):
                        if event.type == "tool_call":
                            saw_tool_call = True
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
                        if not text.strip() and self._last_partial_text.strip():
                            # Some gateways close after partial token stream and send an
                            # empty final payload. Reuse the last partial text so the
                            # workspace can still emit a usable completion summary.
                            text = self._last_partial_text
                        text_lower = text.lower()

                        # If the model responded with a simulated/refusal answer for a
                        # browser/screenshot task, nudge it once to execute tools for real.
                        if (
                            interactive_context
                            and looks_visual_task
                            and not saw_tool_call
                            and corrective_retry_count < 1
                            and any(sig in text_lower for sig in _BROWSER_REFUSAL_SIGNALS)
                        ):
                            corrective_retry_count += 1
                            self._last_partial_text = ""
                            self._narrative_cut = 0
                            yield OpenClawEvent("log", {
                                "message": "Agent returned a simulated response; forcing real browser execution...",
                            })
                            req_id = self._next_id()
                            correction = (
                                "CORRECTION: Do NOT simulate. You have a real browser.\n"
                                "Execute this NOW with tool calls:\n"
                                "1) open browser session\n"
                                f"2) navigate to {target_url}\n"
                                "3) take screenshot\n"
                                "4) call image tool on artifact_path\n"
                                "5) close session\n"
                                "Return the screenshot result and concise findings using markdown."
                            )
                            await self._ws.send(json.dumps({
                                "type": "req",
                                "id": req_id,
                                "method": "chat.send",
                                "params": {
                                    "sessionKey": self._session_key,
                                    "message": correction,
                                    "idempotencyKey": str(uuid.uuid4()),
                                },
                            }))
                            continue

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
                            self._narrative_cut = 0
                            continue  # keep the async-for loop running

                        # Empty final + the agent never even tried to call a
                        # tool — the most pathological case (model returned a
                        # totally silent turn). Retry once with a corrective
                        # prompt before falling through to the user-facing
                        # "rephrase it" message.
                        if (
                            not text.strip()
                            and not saw_tool_call
                            and corrective_retry_count < 1
                        ):
                            corrective_retry_count += 1
                            self._last_partial_text = ""
                            self._narrative_cut = 0
                            logger.warning(
                                "[workspace:%s] Empty final + no tool call — retrying with corrective prompt",
                                self.workspace_id,
                            )
                            yield OpenClawEvent("log", {
                                "message": "Agent returned an empty response; retrying with a clearer instruction…",
                            })
                            req_id = self._next_id()
                            correction = (
                                "CORRECTION: Your previous response was empty.\n"
                                "Do NOT return an empty message. Either:\n"
                                "  • Call the appropriate tool to attempt the task, or\n"
                                "  • Answer the user directly using markdown.\n\n"
                                f"USER REQUEST: {last_user_msg}\n\n"
                                "Respond now."
                            )
                            await self._ws.send(json.dumps({
                                "type": "req",
                                "id": req_id,
                                "method": "chat.send",
                                "params": {
                                    "sessionKey": self._session_key,
                                    "message": correction,
                                    "idempotencyKey": str(uuid.uuid4()),
                                },
                            }))
                            continue

                        # If the final summary is empty (e.g. the model ran a bunch
                        # of tools and then just replied with nothing, or the sub-agent
                        # returned an empty message), synthesize a clear fallback so
                        # the user never sees a blank "Workspace complete".
                        if not text.strip():
                            if saw_tool_call:
                                text = (
                                    "The agent ran tools for this task but did not "
                                    "return a written answer. This usually means the "
                                    "model got stuck in a retry loop or the sandbox "
                                    "blocked a critical command.\n\n"
                                    "Next step: re-run the task, or review the tool "
                                    "output above. If you see `Approval required` or "
                                    "`Obfuscated command detected`, the command was "
                                    "blocked — try rephrasing the task to use a file "
                                    "(`write` then `python3 file.py`) instead of "
                                    "`python3 -c '...'`."
                                )
                            else:
                                text = (
                                    "The agent produced no answer and did not call any "
                                    "tools. If the task requires file or web access, "
                                    "rephrase it more explicitly (e.g. \"open https://… "
                                    "and screenshot\", \"read the attached file and "
                                    "report its contents\")."
                                )
                            logger.warning(
                                "[workspace:%s] Empty final summary — synthesized fallback (saw_tool_call=%s)",
                                self.workspace_id, saw_tool_call,
                            )

                        yield OpenClawEvent("done", {"summary": text})
                        break

                    elif state == "error":
                        err = payload.get("errorMessage", "OpenClaw agent error")
                        err_lower = err.lower()
                        if "connection error" in err_lower or "fetch failed" in err_lower:
                            hint = (
                                "The agent could not reach the model backend. "
                                "Verify Ollama is running: docker compose ps ollama  "
                                "and the model exists: docker exec harvis-ollama ollama list"
                            )
                        elif "timeout" in err_lower:
                            hint = "The agent timed out. The model may be overloaded or the task too complex for a single turn."
                        elif "model" in err_lower:
                            hint = "Model error — check that qwen3.5-32k:latest exists in Ollama."
                        else:
                            hint = "The OpenClaw agent encountered an error. Check: docker compose logs openclaw --tail 30"
                        yield OpenClawEvent("error", {
                            "message": err,
                            "fix_hint": hint,
                        })
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
                            # OpenClaw should send monotonic cumulative text; if not, reset
                            # to avoid corrupt deltas (restarts / alternate stream shape).
                            if self._last_partial_text and not text.startswith(
                                self._last_partial_text
                            ):
                                self._last_partial_text = ""
                                self._narrative_cut = 0
                            delta = text[len(self._last_partial_text) :]
                            self._last_partial_text = text
                            if delta:
                                yield OpenClawEvent("token", {"content": delta})

        except ConnectionClosed as e:
            logger.warning("[workspace:%s] OpenClaw connection closed: %s", self.workspace_id, e)
            # If we received partial tokens before close, surface them as final summary.
            yield OpenClawEvent("done", {"summary": self._last_partial_text or ""})

        except WebSocketException as e:
            logger.error("[workspace:%s] WebSocket error: %s", self.workspace_id, e)
            yield OpenClawEvent("error", {
                "message": f"Workspace connection error: {e}",
                "fix_hint": "WebSocket connection to OpenClaw failed. The container may have restarted. Try again.",
            })

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
                # Flush any narrative the model emitted between the last tool
                # call and this one as a 💬 log event. The directive in the
                # task brief asks the model to prefix every tool call with a
                # short "what I'm about to do" sentence; this surfaces it as
                # a progress line to Discord/UI without bloating the chat
                # bubble. Skip near-empty narratives so we don't spam logs
                # when the model goes straight to the next tool.
                narrative = self._last_partial_text[self._narrative_cut:].strip()
                if narrative and len(narrative) > 5:
                    snippet = narrative if len(narrative) <= 280 else narrative[:277] + "…"
                    yield self._tag(OpenClawEvent("log", {
                        "message": f"💬 {snippet}",
                    }), run_id)
                self._narrative_cut = len(self._last_partial_text)
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

                # Re-classify sandbox "approval pending" / obfuscation warnings as
                # FAILED tool results. OpenClaw returns these with success=true even
                # though the command never actually ran, and the model then treats
                # them as if the command had succeeded. Surfacing them as failures
                # (plus an explicit log line) makes the model try a different
                # approach instead of proceeding on a phantom success.
                _low = output.lower()
                if (
                    "approval required" in _low
                    or "obfuscated command detected" in _low
                    or "approval-pending" in _low
                ):
                    success = False
                    yield self._tag(OpenClawEvent("log", {
                        "message": (
                            "⚠ OpenClaw sandbox blocked the last command "
                            "(approval-pending / obfuscation). The command DID NOT run. "
                            "Rewrite it as a `write` → `python3 file.py` sequence."
                        ),
                    }), run_id)

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
                # Partial tool output — emit as log so it shows in the UI.
                # OpenClaw wraps streamed output in a content-block dict
                # ({'content': [{'type': 'text', 'text': '...'}]}); using
                # str(...) on that includes ~36 chars of dict wrapper before
                # the actual text, which combined with Discord's 120-char log
                # truncation chops the meaty content. Extract text properly
                # and strip leading divider/whitespace noise so the FIRST
                # visible character is informative.
                partial = data.get("partialResult")
                if partial:
                    text = ""
                    if isinstance(partial, dict):
                        content = partial.get("content")
                        if isinstance(content, list):
                            text = self._extract_text(content)
                        elif "text" in partial:
                            text = str(partial.get("text") or "")
                        elif "output" in partial:
                            text = str(partial.get("output") or "")
                    elif isinstance(partial, str):
                        text = partial
                    if not text:
                        text = str(partial)
                    # Strip leading whitespace and lines that are pure
                    # ASCII separators (=, -, _, *, #) so previews skip
                    # banner-divider lines and start at real content.
                    lines = text.lstrip().splitlines()
                    while lines and not lines[0].strip(" =-_*#\t"):
                        lines.pop(0)
                    cleaned = "\n".join(lines).strip()
                    if cleaned:
                        yield self._tag(OpenClawEvent("log", {
                            "message": f"[{tool_name}] {cleaned[:500]}",
                        }), run_id)

        elif stream == "assistant":
            # Assistant text is streamed via chat `partial` state; emitting here duplicates output.
            pass

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
                # Determine parent run_id — first registered run is the parent.
                parent_run_id: Optional[str] = None
                if self._run_labels:
                    first_run = next(iter(self._run_labels))
                    if first_run != run_id:
                        parent_run_id = first_run
                yield self._tag(OpenClawEvent("agent_start", {
                    "agent_label": label,
                    "model": model_hint or None,
                    "parent_run_id": parent_run_id,
                    "message": f"{label} started" + (f" ({model_hint})" if model_hint else "") + " — waiting for first token…",
                }), run_id)
            elif phase == "end":
                yield self._tag(OpenClawEvent("agent_end", {
                    "agent_label": label,
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
        """Signal the stream loop to stop and force-close the websocket so
        the consumer (``async for raw in self._ws``) unblocks immediately
        instead of only on the next inbound frame. A long-running LLM turn
        can otherwise silently hold the loop for minutes."""
        self._cancelled.set()
        logger.info("[workspace:%s] Cancel requested", self.workspace_id)
        ws = self._ws
        if ws is not None:
            try:
                # websockets.close() is awaitable — schedule it so the cancel
                # call stays synchronous (matches existing callers). Use
                # get_running_loop so we don't accidentally create a new loop.
                loop = asyncio.get_running_loop()
                loop.create_task(ws.close(code=1000, reason="cancelled"))
            except RuntimeError:
                # Called from outside an event loop — nothing we can do, the
                # _cancelled flag check on the next iteration will still exit.
                pass
            except Exception as exc:
                logger.debug(
                    "[workspace:%s] ws.close scheduling failed: %s",
                    self.workspace_id, exc,
                )

    async def close(self):
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
                logger.info("[workspace:%s] WebSocket closed", self.workspace_id)
            except Exception:
                pass
