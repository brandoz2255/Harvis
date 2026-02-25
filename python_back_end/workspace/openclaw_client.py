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


class OpenClawEvent:
    """A single event streamed from the OpenClaw gateway."""

    def __init__(self, event_type: str, data: dict):
        self.type = event_type   # "token" | "tool_call" | "tool_result" | "log" | "done" | "error"
        self.data = data

    def to_sse(self) -> str:
        """Format as a Server-Sent Event string for streaming to the frontend."""
        return f"data: {json.dumps({'type': self.type, **self.data})}\n\n"


class OpenClawClient:
    """
    Async WebSocket client for a single OpenClaw workspace session.

    Each workspace launch creates one client instance. The client holds the
    WebSocket connection open, streaming events until the task is done or
    the caller cancels.
    """

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
        try:
            self._ws = await self._connect()
        except Exception as e:
            logger.error("[workspace:%s] Failed to connect to OpenClaw: %s", self.workspace_id, e)
            yield OpenClawEvent("error", {"message": f"Could not connect to workspace backend: {e}"})
            return

        try:
            # Build the full message with conversation context and a clear directive.
            # Limit context to recent messages to avoid overwhelming the model.
            context_lines = [
                f"{m['role'].upper()}: {m['content']}"
                for m in chat_history[-20:]
                if isinstance(m.get("content"), str) and m["content"].strip()
            ]
            context_block = "\n".join(context_lines)

            if context_lines:
                full_message = (
                    f"[CONVERSATION CONTEXT]\n{context_block}\n\n"
                    f"[TASK]\n{task_message}\n\n"
                    "Use your tools to complete this task. "
                    "Call exec, write, or read as needed — do not describe actions, perform them."
                )
            else:
                full_message = (
                    f"[TASK]\n{task_message}\n\n"
                    "Use your tools to complete this task. "
                    "Call exec, write, or read as needed — do not describe actions, perform them."
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
                        yield event

                # Chat events — partial streaming or final response
                elif event_name == "chat":
                    state = payload.get("state")

                    if state == "final":
                        # Extract text from the message content blocks
                        message = payload.get("message") or {}
                        content = message.get("content", [])
                        text = self._extract_text(content)
                        yield OpenClawEvent("done", {"summary": text})
                        break

                    elif state == "error":
                        err = payload.get("errorMessage", "OpenClaw agent error")
                        yield OpenClawEvent("error", {"message": err})
                        break

                    # "partial" state — streaming delta; yield as token
                    elif state == "partial":
                        message = payload.get("message") or {}
                        content = message.get("content", [])
                        text = self._extract_text(content)
                        if text:
                            yield OpenClawEvent("token", {"content": text})

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

    def _handle_agent_event(self, payload: dict):
        """
        Yield OpenClawEvent(s) from an agent event payload.
        Agent events carry tool calls, tool results, and log lines.
        """
        kind = payload.get("kind") or payload.get("type", "")

        if kind in ("tool_call", "tool.call", "toolCall"):
            yield OpenClawEvent("tool_call", {
                "tool": payload.get("toolName") or payload.get("name", "unknown"),
                "args": payload.get("args") or payload.get("input", {}),
            })
        elif kind in ("tool_result", "tool.result", "toolResult"):
            yield OpenClawEvent("tool_result", {
                "tool": payload.get("toolName") or payload.get("name", "unknown"),
                "output": payload.get("output", ""),
                "success": payload.get("success", True),
            })
        elif kind in ("log", "info", "debug"):
            msg = payload.get("message") or str(payload)
            yield OpenClawEvent("log", {"message": msg})

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
