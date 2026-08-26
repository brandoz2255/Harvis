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
from collections import deque
from typing import AsyncGenerator, Deque, Optional, Tuple

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


def _debug400831(location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
    return  # debug logging removed


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


# Must match the OpenClaw protocol version (frames.ts PROTOCOL_VERSION).
# v3 → OpenClaw v2026.2.23 and earlier
# v4 → OpenClaw v2026.5.17+ (bumped during B7 upgrade work, 2026-05-24).
# OpenClaw rejects mismatched protocols at WS handshake — see openclaw logs
# for "protocol mismatch ... expected=N probeMin=N" to confirm the version.
PROTOCOL_VERSION = 4

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


def _synthesize_narrative(tool_name: str, tool_args: dict) -> str:
    """Generate a basic 💬 line from a tool call's args when the model
    didn't emit its own reasoning text.

    Smaller / more terse models (granite4.1, qwen-coder, llama3.1) often
    chain tool calls without any commentary in between, leaving the user
    with a wall of "Running command" lines and no visibility into WHY
    each call is happening. This synthesizes a one-line reason from the
    most informative part of the tool args.
    """
    if not isinstance(tool_args, dict):
        tool_args = {}

    if tool_name in ("exec", "harvis-terminal", "shell", "bash"):
        cmd = (tool_args.get("preview") or tool_args.get("command") or "").strip()
        if not cmd:
            return f"Running {tool_name}"
        low = cmd.lower()
        if "cracker.py" in low:
            parts = cmd.split()
            try:
                idx = next(i for i, p in enumerate(parts) if p.endswith("cracker.py"))
                for p in parts[idx + 1:]:
                    if not p.startswith("-"):
                        h = p.strip(",;\"'")
                        return f"Cracking hash {h[:14]}…" if len(h) > 14 else f"Cracking hash {h}"
            except (StopIteration, IndexError):
                pass
            return "Running cracker.py"
        if low.startswith(("mkdir ", "mkdir\t")):
            return "Setting up workspace dir"
        if low.startswith(("ls ", "ls\t", "ls\n")) or low == "ls":
            return "Listing files"
        if low.startswith(("cat ", "head ", "tail ", "less ", "more ")):
            return f"Reading {cmd.split(maxsplit=1)[1][:50]}" if " " in cmd else "Reading file"
        if low.startswith(("grep ", "rg ", "ripgrep ")):
            return f"Searching: {cmd[:60]}"
        if low.startswith(("python3 ", "python ")):
            tail = cmd.split(maxsplit=1)[1] if " " in cmd else cmd
            return f"Running python: {tail[:60]}{'…' if len(tail) > 60 else ''}"
        if low.startswith(("curl ", "wget ", "http")):
            return f"HTTP: {cmd[:60]}{'…' if len(cmd) > 60 else ''}"
        if low.startswith("git "):
            return f"Git: {cmd[:60]}{'…' if len(cmd) > 60 else ''}"
        cmd_short = cmd if len(cmd) <= 80 else cmd[:77] + "…"
        return f"Running: {cmd_short}"

    if tool_name == "write":
        path = tool_args.get("path") or tool_args.get("file_path") or ""
        if path:
            short = path if len(path) <= 50 else "…" + path[-47:]
            return f"Writing {short}"
        return "Writing file"

    if tool_name == "read":
        path = tool_args.get("path") or tool_args.get("file_path") or ""
        if path:
            short = path if len(path) <= 50 else "…" + path[-47:]
            return f"Reading {short}"
        return "Reading file"

    if tool_name == "edit":
        path = tool_args.get("path") or tool_args.get("file_path") or ""
        if path:
            short = path if len(path) <= 50 else "…" + path[-47:]
            return f"Editing {short}"
        return "Editing file"

    if tool_name == "image":
        return "Analyzing image"

    if tool_name in ("memory_search", "memory_search_unified"):
        q = tool_args.get("query") or tool_args.get("q") or ""
        return f"Memory search: {q[:60]}" if q else "Searching memory"

    if tool_name == "memory_store":
        return "Saving to memory"

    if tool_name in ("local_rag", "rag_search"):
        q = tool_args.get("query") or tool_args.get("q") or ""
        return f"RAG: {q[:60]}" if q else "Searching local knowledge"

    if tool_name == "web_search":
        q = (tool_args.get("query") or tool_args.get("q") or "").strip()
        if q:
            short = q if len(q) <= 80 else q[:77] + "…"
            return f"Web search: \"{short}\""
        return "Searching the web"

    if tool_name == "web_fetch":
        url = (tool_args.get("url") or tool_args.get("href") or "").strip()
        if url:
            short = url if len(url) <= 80 else url[:77] + "…"
            return f"Fetching {short}"
        return "Fetching URL"

    return f"Using {tool_name}"


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


def _looks_like_terminal_execution_task(task_text: str) -> bool:
    low = (task_text or "").lower()
    if (
        "terminal" in low
        or "run " in low
        or "execute" in low
        or "stdout" in low
        or "python3" in low
        or ".py" in low
        or "decode" in low
        or "encoded" in low
        or "decrypt" in low
        or "encrypted" in low
        or "crack" in low
        or "hash" in low
        or "rockyou" in low
        or "wordlist" in low
        or "base64" in low
        or "number bases" in low
        or "password dump" in low
        or "password dumps" in low
    ):
        return True
    if re.search(r"\b0x[0-9a-f]{6,}\b", low) is not None:
        return True
    if re.search(r"\b[01]{8}(?:\s+[01]{8}){2,}\b", low) is not None:
        return True
    # Two or more lines that look like md5 / sha1 / sha256 hashes -> CTF crack task.
    hash_lines = re.findall(r"(?m)^[a-f0-9]{32,64}$", low)
    if len(hash_lines) >= 2:
        return True
    return False


def _looks_like_pasted_code_or_command(text: str) -> bool:
    low = (text or "").lower()
    return (
        "```python" in low
        or "```sh" in low
        or "```bash" in low
        or "python3 " in low
        or "import base64" in low
        or "import binascii" in low
        or "def decode_" in low
        or "/home/node/.openclaw/workspace/" in low
    )


_HASH_HEX_TASK_RE = re.compile(
    # MD5 (32) / SHA1 (40) / SHA224 (56) / SHA256 (64) hex strings, ≥2 = a
    # hash-cracking brief. Conservative: require word boundaries so we
    # don't false-fire on long random-looking strings inside chat history.
    r"\b[a-f0-9]{32,64}\b",
    re.IGNORECASE,
)


def _looks_like_hash_task(text: str) -> bool:
    """True if the user message contains ≥2 hash-shaped hex strings."""
    if not text:
        return False
    return len(_HASH_HEX_TASK_RE.findall(text)) >= 2


# C1: when hermes4 enters narration mode for a hash task, the final chat
# message often contains regurgitated system-prompt fragments OR fake
# `{"name":"write",...}` JSON pasted as text instead of emitted via the
# tool_call channel. These signals tell us the model didn't actually run
# the cracker even though it talked like it did.
_HASH_NARRATION_REGURGITATION_RE = re.compile(
    r"\bHASH-CRACKING TASK\b"
    r"|\bRESPONSE FORMAT — READ THIS FIRST\b"
    r"|\bREQUIRED SEQUENCE\b"
    r"|\bMUST be write \(saving crack\.py\)\b"
    r"|\bCALL 1 \(write\)\b"
    r"|```(?:json)?\s*\{\s*\"name\"\s*:\s*\"(?:write|exec)\""
    r"|`write`\s+(?:tool[_ ]?call|the\s+script)"
    r"|I[' ]ll\s+(?:write|create|save)\s+(?:the\s+)?(?:python\s+)?script",
    re.IGNORECASE,
)


def _looks_like_hash_narration_regurgitation(text: str) -> bool:
    """True if `text` contains hash-CodeAct hint regurgitation or fake tool JSON."""
    if not text:
        return False
    return _HASH_NARRATION_REGURGITATION_RE.search(text) is not None


def _looks_like_memory_echo(text: str) -> bool:
    """Detect the model returning a stale memory line instead of doing the task.

    Symptoms: very short final answer that looks like a previous chat reply
    (`you're a firefighter`, `yo what's next`, `got it`, `standing by`).
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if len(stripped) > 200:
        return False
    low = stripped.lower()
    return (
        "you're a firefighter" in low
        or "you are a firefighter" in low
        or "yo, what's next" in low
        or "yo what's next" in low
        or "what's next" == low
        or "got it" == low
        or "standing by" in low
        or "copy that" in low
        or "on it" == low
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
        # req ids whose `res` frame must be treated as non-fatal in the stream
        # loop (e.g. best-effort sessions.reset — a failed reset must never
        # abort the workspace; it just leaves the prior behavior).
        self._suppress_res_ids: set[str] = set()

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

    async def _reset_session_turns(self, reason: str = "reset") -> None:
        """Clear OpenClaw's server-side replayed turn history for THIS session
        key while keeping the key alive (OpenClaw rotates to a fresh sessionId
        with systemSent=False, totalTokens=0 — verified via probe 2026-05-29).

        Used before a SELF-CONTAINED corrective re-ask so the model doesn't see
        a stale completed-task turn ("...cracked successfully" + a prior tool
        result), which drives tool-call emission to 0% on both qwen3:14b and
        qwen3.5:9b (harness-measured). After reset, OpenClaw re-sends only its
        bundled system prompt — Harvis's per-task skill hints from the original
        message are NOT replayed, so ONLY call this before a corrective that
        re-embeds its own task guidance (the hash corrective does; others do
        not). Best-effort: a failure just leaves the prior behavior.
        """
        if self._ws is None:
            return
        try:
            _rid = self._next_id()
            self._suppress_res_ids.add(_rid)  # its res must not abort the stream
            await self._ws.send(json.dumps({
                "type": "req",
                "id": _rid,
                "method": "sessions.reset",
                "params": {"key": self._session_key, "reason": reason},
            }))
            logger.info(
                "[workspace:%s] sessions.reset sent (key=%s reason=%s) before corrective",
                self.workspace_id, self._session_key[:48], reason,
            )
        except Exception as exc:
            logger.warning(
                "[workspace:%s] sessions.reset failed (continuing without it): %s",
                self.workspace_id, exc,
            )

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

        # ── Pick HOME + SKILLS_BASE for THIS connected gateway ───────────────
        # Two different things resolve based on which gateway we landed on:
        #   - OPENCLAW_HOME: the writable workspace root the agent can mkdir/cd
        #     into. host BYO → user home (e.g. /home/<user>); dockerized
        #     openclaw → /home/node (container HOME).
        #   - SKILLS_BASE: where the harvis CTF skills actually live. host BYO
        #     loads from ~/.openclaw/skills (per openclaw.json extraDirs);
        #     dockerized container mounts them at /skills-shared (per the
        #     docker-compose volume mount). The hash-crack/decode/etc hints
        #     below construct cracker.py paths using SKILLS_BASE so the model
        #     gets a path that ACTUALLY exists on its side.
        # Heuristic: localhost / host.docker.internal / 127.0.0.1 → host BYO.
        try:
            from urllib.parse import urlparse
            _host = (urlparse(self.gateway_url).hostname or "").lower()
            _is_host_byo = _host in ("localhost", "host.docker.internal", "127.0.0.1", "::1")
        except Exception:
            _is_host_byo = False

        if _is_host_byo:
            OPENCLAW_HOME = os.getenv("OPENCLAW_HOME", "/home/node").rstrip("/")
            SKILLS_BASE = f"{OPENCLAW_HOME}/.openclaw/skills"
        else:
            OPENCLAW_HOME = "/home/node"
            SKILLS_BASE = "/skills-shared"
        logger.info(
            "[workspace:%s] Resolved OPENCLAW_HOME=%s SKILLS_BASE=%s for gateway %s",
            self.workspace_id, OPENCLAW_HOME, SKILLS_BASE, self.gateway_url,
        )

        try:
            # Build an imperative message that forces the agent to execute immediately.
            # Lead with the task directive; context is only appended as reference.

            # Extract the last user message — it's the most specific, actionable request.
            # Always prefer the explicit `task_message` (the new task brief) over the
            # final entry of chat_history. Earlier we walked chat_history first, but
            # that meant a stale prior user line (e.g. "what is my job") was treated
            # as the current request when the new task came in via task_brief.
            last_user_msg = (task_message or "").strip()
            if not last_user_msg:
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
                "You can search the internet and fetch web pages via the "
                "`exec` tool. Use this FREELY whenever you are not 100% "
                "certain of your answer. The cost of searching is small. "
                "The cost of being confidently wrong is large.\n"
                "\nBEFORE answering ANY factual, technical, or "
                "'which-of-the-following' question, run this self-check:\n"
                "  1. Is this a topic I've seen exact training data on, "
                "or am I PATTERN-MATCHING from a similar-looking question?\n"
                "  2. If the question has multiple plausible-sounding "
                "options, am I sure my pick is correct — or does it just "
                "FEEL right?\n"
                "  3. Could a 30-second web search produce evidence that "
                "would change my answer?\n"
                "If the answer to ANY of these is uncertain (or you "
                "honestly don't know), web-search FIRST. Treat the first "
                "instinct as a hypothesis to verify, not the answer.\n"
                "\nThe only exceptions: pure-arithmetic questions, "
                "code-writing tasks, and the specialized skill workflows "
                "(hash / decode / crypto / forensics) which have their "
                "own tools.\n"
                "\nIMPORTANT: Call the `exec` tool with these bash-wrapped commands. Do NOT type them as text.\n\n"
                f"To search: call exec with command: {_search_cmd}\n"
                f"To fetch a URL: call exec with command: {_fetch_cmd}\n\n"
                "After exec returns the JSON result, read it CAREFULLY. "
                "If the snippets disagree with your initial instinct, the "
                "evidence wins — change your answer. Then summarize for "
                "the user, citing what you found.\n"
                "The bash wrapper is required so `$OPENCLAW_GATEWAY_TOKEN` expands (otherwise you get Invalid proxy token).\n"
                "Never output the command as text. Always call exec.\n"
            )

            # Browser automation hint — only injected when (1) interactive_context
            # is provided AND (2) the task actually looks browser/visual. Without
            # the visual-task gate, every task brief got 35 lines of curl-based
            # browser-session examples. Small models then echoed those examples
            # as text instead of running them, and even llama3.1:8b would
            # hallucinate browser calls for unrelated tasks (hash-cracking,
            # file edits, etc.). Visual-task heuristic is below at
            # _looks_like_browser_or_screenshot_task.
            browser_hint = ""
            looks_visual_task_for_hint = _looks_like_browser_or_screenshot_task(last_user_msg)
            if interactive_context and looks_visual_task_for_hint:
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

            # ── Harvis dedicated terminal hint ─────────────────────────────────
            # Small models (Hermes-3-8B etc.) bail on dense bootstrap sections.
            # Keep this tiny: one sentence + ONE concrete `exec` template the
            # model can mimic verbatim. The bare `exec` tool stays available
            # and is fine for one-shot work — this hint is only for cases
            # where /workspace persistence helps.
            #
            # Backend URL reachable from the agent's exec context depends on
            # WHERE openclaw is running:
            #   • host-BYO  (gateway = ws://host.docker.internal:…) → host
            #     bash; needs http://localhost:8000 (backend's published port).
            #   • dockerized openclaw fallback → container on openclaw-internal;
            #     needs http://backend:8000 (docker DNS).
            # Explicit override always wins: HARVIS_TERMINAL_AGENT_URL.
            _explicit = (os.getenv("HARVIS_TERMINAL_AGENT_URL") or "").strip()
            if _explicit:
                _term_agent_base = _explicit.rstrip("/")
            elif "host.docker.internal" in (self.gateway_url or ""):
                _term_agent_base = "http://localhost:8000"
            else:
                _term_agent_base = "http://backend:8000"
            _term_exec_url = (
                f"{_term_agent_base}/api/tools/terminal/{self.workspace_id}/exec"
            )
            _term_first_call = _exec_via_bash(
                f"curl -sS -X POST {_term_exec_url} "
                "-H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\" "
                "-H \"Content-Type: application/json\" "
                "-d '{\"cmd\":\"echo hi > /workspace/hi.txt && cat /workspace/hi.txt\"}'"
            )
            terminal_hint = (
                "\nHARVIS PERSISTENT SHELL (optional): an ubuntu container with "
                "a persistent /workspace lives at "
                f"{_term_exec_url}. To use it, call `exec` with: {_term_first_call}\n"
                "Files in /workspace survive across calls. Skip this for one-shot work.\n"
            )

            memory_hint = (
                "\nWORKSPACE MEMORY + CALLBACKS:\n"
                f"- Current OpenClaw callback/session key: `{self._session_key}`\n"
                f"- Legacy workspace/session slug: `{workdir_rel}`\n"
                "- Use the callback/session key above for `sessions_history`. "
                "Do NOT use the legacy slug as a session key.\n"
                "- `WORKSPACE MEMORY` below is BACKGROUND CONTEXT ONLY. Do NOT "
                "answer with it unless the current user request is explicitly a "
                "memory/identity follow-up (e.g. `what is my job`, `what am I`, "
                "`what did I just say`, `do you understand what you just "
                "outputted`).\n"
                "- The CURRENT user request below `EXECUTE THIS TASK NOW:` is "
                "ALWAYS more important than `WORKSPACE MEMORY`. If the new task "
                "is solve / decode / decrypt / crack / search / fetch / write / "
                "screenshot / browse, you MUST do that task using tools, even if "
                "the memory contains a prior chat answer.\n"
                "- Never reuse a prior assistant answer (e.g. `You're a "
                "firefighter.`, `Yo, what's next?`) as the response to a new task. "
                "Treat the memory as read-only background.\n"
                "- For memory-only follow-ups, answer from `WORKSPACE MEMORY` "
                "first; do NOT read `AGENTS.md`, `AGENT.md`, `USER.md`, or files "
                "inside the workspace directory to answer those.\n"
                "- If you need persistent memory beyond the provided context, you may "
                "try `memory_search` / `memory_get`; if unavailable or empty, fall "
                "back to `WORKSPACE MEMORY` and say what context was missing.\n"
            )

            _workdir_init = _exec_via_bash(f"mkdir -p {workdir} && cd {workdir} && pwd")

            # Hash detection — small/medium local models (gemma4:e4b, even
            # llama3.1:8b) don't auto-discover skills via TOOLS.md, so they
            # default to memory_search or hand-rolled python on hash-crack
            # tasks. Inline the cracker.py invocation in the prompt so the
            # tool is unmissable regardless of model.
            _HASH_HEX_RE = re.compile(
                r"\b[a-f0-9]{32}\b|\b[a-f0-9]{40}\b|\b[a-f0-9]{56}\b"
                r"|\b[a-f0-9]{64}\b|\b[a-f0-9]{96}\b|\b[a-f0-9]{128}\b",
                re.IGNORECASE,
            )
            _HASH_SALTED_RE = re.compile(r"\$(?:1|2[abxy]?|5|6|argon2)\$", re.IGNORECASE)
            _detected_hashes = (
                _HASH_HEX_RE.findall(last_user_msg or "")
                + _HASH_SALTED_RE.findall(last_user_msg or "")
            )
            hash_hint = ""
            if _detected_hashes:
                # ── Lever 1 (2026-05-28) — skill-dispatch shape ──
                # The model no longer authors the multi-tier orchestration
                # inside an exec heredoc. crack_all.py on disk does it all
                # (multi-hash batching, bundled wordlists, online lookup,
                # themed fetch). Same architecture as decode/crypto/forensics
                # — model emits ONE short command, the script handles the
                # complexity. Eliminates the gemma4/hermes4 indent-collapse
                # failure class entirely (workspaces 8e60e5cd, 31da2e56).
                _hcdir = f"{SKILLS_BASE}/hash-cracking"
                _n_hashes = len(_detected_hashes)
                _hash_list_str = "\n".join(f"  {h}" for h in _detected_hashes)
                _hashes_argv = " ".join(_detected_hashes)

                # Theme detection — maps user-visible keyword to crack_all.py's
                # --theme=NAME flag. crack_all.py currently ships only
                # `pokemon` as a supported theme; other detected themes
                # (cities, movies, anime, etc.) fall through to the bundled
                # tier only. Extending the skill is the right path for new
                # themes — add an entry to crack_all.py THEMES dict.
                _HASH_THEME_RE = re.compile(
                    r"\b(pok[eé]mon|cities|movies?|star\s*wars|anime|"
                    r"animals?|countries|names|colors?|fruits?|"
                    r"presidents|elements?|planets?|sports?)\b",
                    re.IGNORECASE,
                )
                _theme_match = _HASH_THEME_RE.search(last_user_msg or "")
                _has_theme_hint = bool(_theme_match)
                _theme_word = (
                    _theme_match.group(0).lower() if _theme_match else ""
                )
                _is_pokemon_theme = _theme_word in {"pokemon", "pokémon"}
                _theme_arg = " --theme=pokemon" if _is_pokemon_theme else ""

                hash_hint = (
                    "\nHASH-CRACKING TASK DETECTED.\n"
                    f"Hashes to crack ({_n_hashes}):\n{_hash_list_str}\n"
                    "\nDO NOT author Python in your reply. The skill on "
                    "disk does ALL the orchestration — multi-tier wordlists "
                    "(bundled top1k/top10k/top100k), online lookup, themed "
                    "fetch.\n"
                    "DO NOT call memory_search or web_search to crack "
                    "hashes — they don't crack.\n"
                    "DO NOT skip the tool call for any reason. Hints, "
                    "context, or prior runs do NOT replace execution.\n"
                    "Run via the `exec` tool — ONE short command:\n"
                    f"  python3 {_hcdir}/crack_all.py"
                    f"{_theme_arg} {_hashes_argv}\n"
                    "Returns one JSON dict: {hash: {verified, plaintext, "
                    "method, algo, tiers_tried}}.\n"
                    "\nAfter crack_all.py returns, summarize only the hashes "
                    "the cracker actually verified.\n"
                    "- Report `hash → plaintext` for every entry where "
                    "verified=true.\n"
                    "- For verified=false entries, say \"unverified\" — "
                    "full stop. Forbidden hedges: \"might be X\", \"could "
                    "be X\", \"intended answer might be Y\", \"likely X\", "
                    "\"probably X\", \"my guess is Z\". Either the cracker "
                    "verified it (state the verified plaintext) or it "
                    "didn't (say \"unverified\" with no guess).\n"
                    "- Do NOT call any other tools between this exec and "
                    "your final summary unless the user explicitly asks "
                    "for chained behavior.\n"
                )
                _debug400831(
                    "openclaw_client.py:stream:hash_hint",
                    "dispatch_hash_hint_built",
                    {
                        "workspace_id": self.workspace_id,
                        "detected_hashes": _detected_hashes[:3],
                        "n_hashes": _n_hashes,
                        "has_theme": _has_theme_hint,
                        "theme_arg": _theme_arg.strip() or None,
                        "lever": 1,
                    },
                    "run_hash_issue",
                    "H1",
                )
                logger.warning(
                    "[DBG400831][H1] dispatch_hash_hint workspace=%s "
                    "hashes=%d theme=%s",
                    self.workspace_id,
                    _n_hashes,
                    _theme_arg.strip() or "none",
                )

            # ---- decode skill detection ----
            _DECODE_VERB_RE = re.compile(
                r"\b(decode|decrypt this|what does this say|encoded|base64|"
                r"base32|hex(?:adecimal)? to|binary to|morse|cipher(?: ?text)?)\b",
                re.IGNORECASE,
            )
            _BASE64_BLOB_RE = re.compile(r"\b[A-Za-z0-9+/]{20,}={0,2}\b")
            _BINARY_BLOB_RE = re.compile(r"(?:[01]{8}\s*){4,}")
            _MORSE_BLOB_RE = re.compile(r"(?:[\.\-]{1,6}[\s/]+){4,}[\.\-]{1,6}")
            _decode_signal = (
                bool(_DECODE_VERB_RE.search(last_user_msg or ""))
                or bool(_BASE64_BLOB_RE.search(last_user_msg or ""))
                or bool(_BINARY_BLOB_RE.search(last_user_msg or ""))
                or bool(_MORSE_BLOB_RE.search(last_user_msg or ""))
            )
            decode_hint = ""
            if _decode_signal and not _detected_hashes:
                _decdir = f"{SKILLS_BASE}/decode"
                decode_hint = (
                    "\nDECODE TASK DETECTED. The user pasted an encoded blob "
                    "or asked to decode/decrypt without supplying a key.\n"
                    "DO NOT decode by sight. Even ROT13 trips small models.\n"
                    "DO NOT call memory_search.\n"
                    "DO NOT skip the tool call for any reason — hints, context, "
                    "or prior runs do NOT replace execution. You MUST call exec.\n"
                    "Run via the `exec` tool:\n"
                    f"  python3 {_decdir}/decoder.py \"<encoded blob>\"\n"
                    "Returns JSON with ranked candidates (lower score = more "
                    "English-like). Tries base64/base32/hex/binary/url/rot/atbash/"
                    "morse/ascii-decimal — pick the candidate whose plaintext "
                    "linguistically matches what the user is looking for.\n"
                    "If no candidates have a reasonable score, try `--all` to "
                    "see every method. Consider double-encoding (base64 of hex).\n"
                    "\nAfter decoder.py returns, report the result. "
                    "Prefer decoder.py over web_search for this task — it's "
                    "faster and verifies plaintexts. Web_search is fine if "
                    "you need to look up an encoding scheme you don't "
                    "recognize.\n"
                )

            # ---- classical-crypto skill detection ----
            _CRYPTO_VERB_RE = re.compile(
                r"\b(caesar|vigen[eè]re|atbash|shift cipher|rotation cipher|"
                r"classical cipher|substitution cipher)\b",
                re.IGNORECASE,
            )
            _crypto_signal = bool(_CRYPTO_VERB_RE.search(last_user_msg or ""))
            crypto_hint = ""
            if _crypto_signal:
                _ccdir = f"{SKILLS_BASE}/classical-crypto"
                crypto_hint = (
                    "\nCLASSICAL-CIPHER TASK DETECTED. The user mentioned a "
                    "classical cipher (Caesar / Vigenere / Atbash / shift / "
                    "rotation).\n"
                    "DO NOT solve by inspection. Even simple Caesar shifts "
                    "trip small models on novel text.\n"
                    "DO NOT skip the tool call for any reason — hints, known "
                    "shifts, or prior runs do NOT replace execution.\n"
                    "Run via the `exec` tool:\n"
                    f"  python3 {_ccdir}/cipher.py \"<ciphertext>\"\n"
                    "Auto-solves Caesar (brute 26 shifts), Atbash, and "
                    "Vigenere (auto key-length 2..12 via index of coincidence). "
                    "Returns JSON with candidates ranked by chi-squared score; "
                    "pick the most-English-likely. For known-key Vigenere add "
                    "`--cipher vigenere --key <KEY>`.\n"
                    "\nAfter cipher.py returns, report the result. "
                    "Prefer cipher.py over web_search for this task — it "
                    "brute-forces and scores. Web_search is fine if you "
                    "need to look up a cipher name you don't recognize.\n"
                )

            # ---- forensics-basics skill detection ----
            _FORENSICS_VERB_RE = re.compile(
                r"\b(strings|exiftool|binwalk|hexdump|metadata|"
                r"what'?s in (?:this|the) file|find the flag|hidden data|"
                r"forensics?|analyze (?:this )?(?:file|image|binary|archive))\b",
                re.IGNORECASE,
            )
            _FILE_PATH_RE = re.compile(
                r"(?:/[\w./-]+|\b[\w./-]+)\.(?:png|jpg|jpeg|gif|bmp|tiff|webp|"
                r"zip|tar|tar\.gz|tgz|7z|rar|bin|exe|dll|so|elf|pcap|pcapng|"
                r"docx?|pdf|xlsx?|pptx?|wav|mp3|mp4|mov|avi)\b",
                re.IGNORECASE,
            )
            _forensics_signal = (
                bool(_FORENSICS_VERB_RE.search(last_user_msg or ""))
                or bool(_FILE_PATH_RE.search(last_user_msg or ""))
            )
            forensics_hint = ""
            if _forensics_signal:
                _fbdir = f"{SKILLS_BASE}/forensics-basics"
                forensics_hint = (
                    "\nFILE-FORENSICS TASK DETECTED. The user wants to inspect "
                    "a file (find a flag, pull metadata, look for embedded "
                    "data).\n"
                    "DO NOT speculate about file contents. Every claim must "
                    "come from the analyzer's JSON output.\n"
                    "DO NOT skip the tool call for any reason.\n"
                    "Run via the `exec` tool:\n"
                    f"  python3 {_fbdir}/analyze.py /path/to/file\n"
                    "Wraps file/strings/exiftool/binwalk/xxd. Hunts for "
                    "flag{}, CTF{}, HTB{}, picoCTF{}, NCAE{} patterns plus "
                    "URLs/emails/base64/hashes inside `findings`. Drill into "
                    "`tools.*` for raw output if needed. If a finding is a "
                    "base64 blob, pipe to the decode skill; if a hash, pipe to "
                    "hash-cracking.\n"
                    "\nAfter analyze.py returns, report findings. "
                    "If the user asked you to chain (decode a finding, crack "
                    "a hash from findings), do those follow-up calls, then STOP. "
                    "Prefer analyze.py over web_search for inspecting files. "
                    "Web_search is fine if you need to look up a file format "
                    "or signature you don't recognize.\n"
                )

            # ---- creator skill detection ----
            _CREATOR_VERB_RE = re.compile(
                r"\b("
                r"(?:create|write|make|generate|scaffold)\s+(?:me\s+)?(?:a\s+|an\s+)?"
                r"(?:python\s+)?(?:script|cli|file|dockerfile|flask\s+app|fastapi"
                r"|github\s+action|gitignore|tool|helper|program|workflow)"
                r"|set up (?:a|the)?\s*gitignore"
                r"|write\s+a\s+\w+\s+(?:that|to)\s+\w+"
                r")\b",
                re.IGNORECASE,
            )
            _creator_signal = bool(_CREATOR_VERB_RE.search(last_user_msg or ""))
            creator_hint = ""
            if _creator_signal:
                _crdir = f"{SKILLS_BASE}/creator"
                creator_hint = (
                    "\nFILE-CREATION TASK DETECTED. The user wants you to "
                    "create a script / file / scaffold.\n"
                    "Use the `creator` skill so the output gets auto-verified "
                    "(py_compile / json.load / bash -n / yaml.safe_load) "
                    "before you tell the user it's done.\n\n"
                    "Two paths:\n"
                    "  (a) For common shapes — use a template:\n"
                    f"      python3 {_crdir}/creator.py scaffold "
                    f"<template> --out {workdir}/<filename> "
                    "--vars name=<short> description=\"<what it does>\"\n"
                    f"      Templates available: python-cli, python-script, "
                    "bash-script, dockerfile, flask-app, fastapi-app, "
                    "github-action, gitignore-python\n"
                    "  (b) For arbitrary content — write + auto-verify:\n"
                    f"      cat <<'EOF' | python3 {_crdir}/creator.py "
                    f"write {workdir}/<filename> --stdin\n"
                    "      <your code here>\n"
                    "      EOF\n\n"
                    "BOTH paths return JSON with `syntax_ok: true|false`. "
                    "DO NOT tell the user 'I created the script' unless "
                    "`syntax_ok: true`. If false, copy the `errors` verbatim "
                    "and either fix-and-rewrite or report the parser complaint.\n"
                )

            # ---- rejection / "try again" detection ----
            # ---- rejection / "try again" detection ----
            # Two classes of pattern:
            #   (a) explicit-keyword forms ("that's wrong", "try again", ...)
            #   (b) declarative-correction forms ("X is not directly affected
            #       by Y", "reconsider", "consider X instead", ...) — added
            #       2026-05-23 after scenario-MCQ correction (user's "API
            #       Gateway is not directly affected by prompt manipulation"
            #       did not match (a) — model doubled down).
            # CAUTION: the `actually|in fact` + .{0,40} + negation pattern is
            # the most false-positive-prone (e.g. "actually, I'm not sure
            # what you meant?"). Watch for it; if it false-positives in
            # practice, add `(?!.*\?\s*$)` lookahead or drop entirely.
            _REJECTION_RE = re.compile(
                r"\b("
                # ── (a) existing keyword forms ──
                r"(?:that'?s|that is)\s+(?:wrong|incorrect|not (?:right|correct))"
                r"|(?:wrong|incorrect)\s+answer"
                r"|try again"
                r"|do (?:it|this) (?:again|over|differently)"
                r"|(?:previous|last)\s+(?:answer|response)\s+(?:was\s+)?"
                r"(?:wrong|incorrect|bad|off|mistaken)"
                r"|(?:not (?:right|correct)|wrong|incorrect)\s*[\.\!\?]?\s*$"
                r"|fix (?:this|it|that)"
                r"|are you sure"
                r"|that('?s|\s+is)?\s+still\s+(?:wrong|incorrect)"
                # ── (b) declarative-correction forms (basculin/MCQ 2026-05-23) ──
                r"|is\s+not\s+(?:directly\s+)?(?:affected|related|exposed|targeted|impacted|involved)"
                r"|does\s+not\s+(?:directly\s+)?(?:affect|target|expose|apply|handle)"
                r"|(?:actually|in\s+fact)\b.{0,40}\b(?:not|isn'?t|is\s+not)\b"
                r"|(?:consider|try|use)\s+\w+\s+instead"
                r"|reconsider"
                r"|rethink"
                r")\b",
                re.IGNORECASE,
            )
            _retry_signal = bool(_REJECTION_RE.search(last_user_msg or ""))
            # Telemetry: if a NEW declarative pattern was the trip, log it
            # separately from keyword retries so we can measure prevalence.
            if _retry_signal:
                _RETRY_DECLARATIVE_RE = re.compile(
                    r"\b(?:is\s+not\s+(?:directly\s+)?(?:affected|related|"
                    r"exposed|targeted|impacted|involved)|does\s+not\s+"
                    r"(?:directly\s+)?(?:affect|target|expose|apply|handle)"
                    r"|reconsider|rethink|consider\s+\w+\s+instead)\b",
                    re.IGNORECASE,
                )
                if _RETRY_DECLARATIVE_RE.search(last_user_msg or ""):
                    logger.warning(
                        "[DBG] retry_hint fired via declarative pattern "
                        "(not keyword) workspace=%s msg_head=%r",
                        self.workspace_id,
                        (last_user_msg or "")[:80],
                    )
            retry_hint = ""
            if _retry_signal:
                retry_hint = (
                    "\nPRIOR-ANSWER-REJECTED. The user is telling you your "
                    "previous response was wrong. Do not paraphrase, defend, "
                    "or re-explain that earlier answer.\n"
                    # Explicit split by task class — prevents the model from
                    # web-searching for plaintexts when a tool-task gets
                    # corrected (would regress hash/decode/crypto workflows).
                    "For scenario/knowledge corrections: use `web_search` "
                    "for the user's specific claim BEFORE responding. Treat "
                    "their correction as authoritative new information, not "
                    "an opinion to argue with.\n"
                    "For tool-task corrections (hash / decode / crypto / "
                    "forensics): re-run the relevant tool from scratch — do "
                    "NOT web_search for a hash/decode/cipher result.\n"
                    "Required behavior:\n"
                    "1. Discard the prior tool output that's in your context. "
                    "Treat it as untrusted — it produced a wrong answer.\n"
                    "2. RE-RUN every relevant tool from scratch with the "
                    "current user message as the only source of truth. Do "
                    "NOT skip the tool call because you 'already know' the "
                    "answer — you don't.\n"
                    "3. Try alternate strategies the previous attempt missed:\n"
                    "   - For hash-cracking: try `--algo ntlm` (32-hex could "
                    "be NTLM, not MD5); try without the algo hint to let "
                    "identify_hash pick; ensure cracker.py auto-loads BOTH "
                    "top1k.txt AND rockyou.txt (it does by default — "
                    "`tiers_tried` in the JSON proves it).\n"
                    "   - For decode: try `--all` to see every candidate, "
                    "not just the top 5; consider that the input might be a "
                    "double encoding (base64 of hex of …).\n"
                    "   - For classical-crypto: try `--cipher vigenere` "
                    "explicitly if Caesar brute didn't surface a clean "
                    "result; if the user supplied a key, use it.\n"
                    "   - For forensics: try `--no-binwalk` if it stalled; "
                    "consider that the flag might be in a different format "
                    "(CTF{}/HTB{}/picoCTF{}/NCAE{}).\n"
                    "4. If after a fresh tool run the result is genuinely "
                    "the same, say so EXPLICITLY: \"Re-ran from scratch; "
                    "tool reports verified=false across tiers X, Y, Z. The "
                    "underlying answer hasn't changed.\" Then ask the user "
                    "for new context (different algorithm? different hash "
                    "list? expected plaintext shape?). Do NOT just retype "
                    "the previous response.\n"
                )

            # Imperative directive — task first, context last, no asking back.
            # NOTE: The previous "MANDATORY WORKDIR INIT" step ate small models'
            # only useful turn — they ran the mkdir, saw success=true, and
            # stopped without doing the actual task. We now bundle the workdir
            # bootstrap into the same first command as the task by recommending
            # the agent prefix its python3/curl with `mkdir -p {workdir} && `.
            directive = (
                f"WORKSPACE DIRECTORY: {workdir}\n"
                "FILESYSTEM LAYOUT (IMPORTANT — READ BEFORE USING TOOLS):\n"
                f"- The `exec` tool runs commands with CWD {OPENCLAW_HOME}/.openclaw/workspace\n"
                "- The `write` tool treats relative paths as rooted at the SAME directory\n"
                f"- Your session sub-directory is `{workdir_rel}/` under that root\n"
                f"- Use the RELATIVE form `{workdir_rel}/<filename>` for `write`\n"
                f"- Use the ABSOLUTE form `{workdir}/<filename>` for `exec`/`python3`\n"
                f"- DO NOT assume any {OPENCLAW_HOME}/workspaces/... path exists — that tree is unrelated to the exec CWD.\n"
                f"- The directory `{workdir}` may not exist yet. Prefix your first "
                f"`exec` shell command with `mkdir -p {workdir} && cd {workdir} && ` "
                "so the workdir is created in the SAME turn that does real work. "
                "Do NOT spend a separate tool call just to mkdir — that wastes your "
                "first turn and small models tend to stop after it.\n"
                f"{github_hint}"
                f"{repo_hint}"
                f"{rag_hint}"
                # NOTE: web_hint moved to fire IMMEDIATELY before
                # `EXECUTE THIS TASK NOW` below — maximum recency weight,
                # last thing the model reads before generating. Position
                # matters: at 42% of prompt the search-first directive
                # was drowned out by 4K chars of RULES/FAITHFUL REPORTING
                # before the task; qwen3:14b ignored it.
                f"{browser_hint}"
                f"{terminal_hint}"
                f"{memory_hint}"
                # NOTE: web_hint above (always-on) carries the permissive
                # "use FREELY / FIRST step for scenarios" framing. Previously
                # a duplicate WEB ACCESS paragraph lived here; that caused a
                # naming collision with web_hint and the model got conflicting
                # guidance. The directive is now consolidated into web_hint.
                f"{hash_hint}"
                f"{decode_hint}"
                f"{crypto_hint}"
                f"{forensics_hint}"
                f"{creator_hint}"
                f"{retry_hint}"
                f"{web_hint}"
                f"\nEXECUTE THIS TASK NOW: {last_user_msg}\n\n"
                "RULES:\n"
                "- ALWAYS use tool calls (exec, write, read). NEVER type commands as text.\n"
                "- NARRATE BETWEEN TOOLS. The user sees ONLY your prose between "
                "tool calls — they do NOT see your tool arguments. Every tool "
                "call must be preceded by one sentence (under 25 words) that "
                "names BOTH the action AND its purpose for the current task:\n"
                "    (a) BEFORE a tool call: name the action + WHY it serves "
                "the user's task, then immediately call the tool.\n"
                "        GOOD: \"Writing a Python script to brute-force "
                "SKY-HQNT-NNNN against the 5 MD5 hashes.\" → write tool call.\n"
                "        GOOD: \"Running the cracker now to check all 10,000 "
                "candidates.\" → exec tool call.\n"
                "        BAD:  \"Writing the helper script first.\" (says WHAT, "
                "not WHY — user has no idea what helper or what task).\n"
                "        BAD:  \"Running python.\" (mechanical; user already "
                "knows from the tool args).\n"
                "    (b) AFTER a tool result: state what you observed (concrete "
                "value, error, count) and what you'll do next.\n"
                "        GOOD: \"Got a 200 with the JSON I expected — now "
                "parsing it for the price field.\" → exec tool call.\n"
                "        GOOD: \"Cracker found 3 of 5 hashes; rerunning with "
                "wider digit range for the remaining 2.\" → exec tool call.\n"
                "  Keep narrations concrete (mention the actual file / hash / "
                "URL / count / error you saw) and free of filler like \"Let me\", "
                "\"I'll now\", \"Great\", or \"Okay\". The user is reading these "
                "as live status updates — they need to know WHY each step is "
                "happening, not just that python is being run.\n"
                "- DO NOT stop after a single setup/probe tool call. A `mkdir`, `pwd`, "
                "`uname`, or other workdir-init step is NOT the task. After it returns, "
                "make another tool call to do the actual work. The task is only complete "
                "when you have produced a final user-facing answer.\n"
                "- If you include a code block or terminal command in the final answer without first running it, "
                "the task is incomplete. Commands in text do not execute.\n"
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
                "- DO NOT decline a task because the input 'looks wrong' or 'needs verification' "
                "without first running the decode/parse yourself. Encoded strings (hex, base64, "
                "binary) are NORMAL inputs — try to decode them, then report what you got.\n"
                "- When you have tool output containing the answer, restate the relevant lines "
                "in your reply. Re-deriving from memory introduces errors; quoting the tool is safer.\n"
                "- After decoding, scan each result for a second layer (a base64-looking trailing "
                "chunk like `XYZ=`, a `0x...` prefix, a long 0/1 run). If you see one, decode it "
                "too — nested encodings are common in CTFs.\n"
                "\n"
                "TONE & STYLE:\n"
                "- Your responses should be short and concise. The user reads diffs and tool "
                "output, not your prose recap. End-of-turn summary: one or two sentences.\n"
                "- Do NOT use a colon before tool calls. Your tool calls may not be shown "
                "directly in the output, so text like \"Let me read the file:\" followed by "
                "a read tool call should just be \"Let me read the file.\" with a period.\n"
                "- When referencing specific functions or files, include the pattern "
                "`file_path:line_number` so the user can navigate.\n"
                "- Only use emojis if the user explicitly requests it. Default = no emojis "
                "in code or commits. (The 💬 narrative line is the surfacer's, not yours.)\n"
                "- Match response length to task: a yes/no question gets a yes/no answer, "
                "not headers and sections. A code change gets a one-sentence diff summary.\n"
                "\n"
                "EXECUTING ACTIONS WITH CARE:\n"
                "- Carefully consider the reversibility and blast radius of any action. "
                "Local, reversible actions (read a file, run a test, edit code in your "
                "session workdir) — do them freely. Hard-to-reverse / shared-state actions "
                "(git push, force-push, drop database table, rm -rf, send a message, "
                "post to an external service, modify CI/CD) — confirm with the user first "
                "unless the user has authorized the specific action in advance.\n"
                "- A user approving an action once does NOT mean they approve it in all "
                "contexts. Authorization stands for the scope specified, not beyond. "
                "Match the scope of your actions to what was actually requested.\n"
                "- Do NOT use destructive actions as a shortcut to make an obstacle go "
                "away. If you discover unexpected state (unfamiliar files, branches, lock "
                "files, uncommitted changes), investigate before deleting or overwriting "
                "— it may be the user's in-progress work. Resolve merge conflicts rather "
                "than discarding changes. Investigate what process holds a lock file "
                "rather than deleting it.\n"
                "\n"
                "FAITHFUL REPORTING:\n"
                "- Report outcomes faithfully. If a tool failed, say so with the relevant "
                "output. If you didn't run a verification step, say that rather than "
                "implying it succeeded. Never claim \"all tests pass\" when output shows "
                "failures. Never characterize incomplete or broken work as done.\n"
                "- When a check did pass or a task is complete, state it plainly. Don't "
                "hedge confirmed results with unnecessary disclaimers, don't downgrade "
                "finished work to \"partial\", don't re-verify things you already checked. "
                "The goal is an accurate report, not a defensive one.\n"
            )

            identity_bundle = _load_identity_bundle()
            if context_block:
                full_message = (
                    f"{identity_bundle}\n{directive}\n"
                    "WORKSPACE MEMORY (background context — DO NOT use to answer "
                    "the current task unless that task is itself a memory or "
                    "identity follow-up):\n"
                    f"{context_block}"
                )
            else:
                full_message = (
                    f"{identity_bundle}\n{directive}\n"
                    "WORKSPACE MEMORY: No recent conversation was provided with this launch."
                )

            # Extra guardrail: if the agent asks identity/setup questions, it's not following instructions.
            # Keep this short and at the top of the task message.
            # Append a sentinel-bracketed copy of the actual user task at the
            # END so model_proxy can scope CTF-detection to just the user's
            # query (not the 20K-char directive bundle full of skill-hint
            # keywords like "crack" / "decrypt" / "decode" that false-positive
            # the regex). Markers added 2026-05-25 after MCQ #1 retest
            # showed CTF-detect still firing post-user-role scope fix.
            full_message = (
                "DO NOT ask identity/setup questions. You already have your identity and mission. "
                "You are Harvis.\n\n"
                + full_message
                + "\n\n<!-- HARVIS_USER_TASK_BEGIN -->\n"
                + (last_user_msg or "")
                + "\n<!-- HARVIS_USER_TASK_END -->\n"
            )
            _is_hash_task = bool(_detected_hashes)
            if _is_hash_task:
                _debug400831(
                    "openclaw_client.py:stream:full_message",
                    "hash_prompt_dispatched",
                    {
                        "workspace_id": self.workspace_id,
                        "session_key": self._session_key[:48],
                        "has_hash_hint": "HASH-CRACKING TASK." in full_message,
                        "has_codeact": "First call MUST be write" in full_message,
                        "has_fewshot": "crack.py" in full_message,
                        "has_stop_asking_back": "Don't ask the user for confirmation" in full_message,
                        "mentions_web_search": "web_search" in full_message.lower(),
                    },
                    "run_hash_issue",
                    "H2",
                )
                logger.warning(
                    "[DBG400831][H2] hash_prompt_dispatched workspace=%s skey=%s has_hint=%s codeact=%s fewshot=%s stop_asking=%s has_web_search=%s",
                    self.workspace_id,
                    self._session_key[:48],
                    "HASH-CRACKING TASK." in full_message,
                    "First call MUST be write" in full_message,
                    "crack.py" in full_message,
                    "Don't ask the user for confirmation" in full_message,
                    "web_search" in full_message.lower(),
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
            saw_executing_tool_call = False
            corrective_retry_count = 0
            # C1.3: Retry-in-flight tracking. When a corrective retry is
            # sent, the model may take several seconds to produce its
            # response and OpenClaw may emit intermediate "empty final"
            # events before tool_calls actually flow. Without this guard,
            # Harvis prematurely synthesizes the "no answer" fallback and
            # closes the WS, leaving in-flight retry tool_calls with
            # nowhere to land (verified 2026-05-25 workspace 59fcc99c:
            # 18 tool_calls fired AFTER WebSocket closed).
            #
            # Flag is set by either retry branch (hash-narration or
            # generic empty+no-tools). On subsequent empty finals we
            # check `monotonic() - retry_started_at` against the
            # timeout; if under, we `continue` the loop and keep
            # listening. Sliding window: any agent tool_call event
            # arriving extends the timer by resetting it.
            retry_in_flight = False
            retry_started_at: Optional[float] = None
            _RETRY_TIMEOUT_S = 45.0
            # Loop guard: small ring of (tool, args_signature) for the most
            # recent tool calls. If the most recent N entries are identical,
            # we abort the run instead of letting the model spin forever on
            # an empty-output command (e.g. `bash -lc 'cd <bad-dir> && bash'`
            # returning "" and the model retrying the same call).
            _LOOP_GUARD_N = 3
            _recent_tool_calls: Deque[Tuple[str, str]] = deque(maxlen=_LOOP_GUARD_N)
            looks_visual_task = _looks_like_browser_or_screenshot_task(last_user_msg)
            looks_terminal_task = _looks_like_terminal_execution_task(last_user_msg)
            # Gate the hash corrective on the SAME signal that built the hint
            # (`_detected_hashes`), not the stricter ≥2-hash `_looks_like_hash_task`.
            # Bug (2026-06-09): a single-hash task ("crack this MD5 hash: <one>")
            # fires the hint (≥1 hash) but the corrective required ≥2, so when
            # qwen3.5:9b narrated without calling exec, no retry fired and the run
            # closed `done` with the narration as the summary ("just relays").
            # Coupling corrective→hint: if we told the model to crack a hash and it
            # didn't call the tool, retry — regardless of hash count.
            looks_hash_task = _looks_like_hash_task(last_user_msg) or bool(_detected_hashes)
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
                    # Best-effort RPCs (sessions.reset) — their res must never
                    # abort the workspace, even on ok=false. Swallow + continue.
                    _res_id = msg.get("id")
                    if _res_id in self._suppress_res_ids:
                        self._suppress_res_ids.discard(_res_id)
                        if not msg.get("ok"):
                            logger.warning(
                                "[workspace:%s] suppressed best-effort RPC res "
                                "(id=%s) error: %s",
                                self.workspace_id, _res_id,
                                msg.get("error", {}).get("message", "?"),
                            )
                        continue
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
                            # Sliding-window: a tool_call from the retry's
                            # stream proves the model is still working —
                            # extend the retry-in-flight timer.
                            if retry_in_flight:
                                retry_started_at = (
                                    asyncio.get_event_loop().time()
                                )
                            tool_name = (event.data or {}).get("tool", "")
                            # C1 diagnostic: log runId on every tool start so
                            # we can correlate retry-stream tool events with
                            # the parent workspace if they ever diverge.
                            logger.info(
                                "[workspace:%s] [DBG runId] agent tool_call "
                                "runId=%s tool=%s",
                                self.workspace_id,
                                getattr(event, "run_id", None) or "?",
                                tool_name,
                            )
                            # Loop guard — record (tool, args) and abort if
                            # the last N tool calls are identical.
                            _args_sig = json.dumps(
                                (event.data or {}).get("args", {}),
                                sort_keys=True, default=str,
                            )[:512]
                            _recent_tool_calls.append((tool_name, _args_sig))
                            if (
                                len(_recent_tool_calls) >= _LOOP_GUARD_N
                                and all(
                                    item == _recent_tool_calls[0]
                                    for item in _recent_tool_calls
                                )
                            ):
                                logger.warning(
                                    "[workspace:%s] Tool-call loop detected — "
                                    "same call repeated %d times: tool=%s args=%.120s",
                                    self.workspace_id, _LOOP_GUARD_N,
                                    tool_name, _args_sig,
                                )
                                yield event  # surface this last call to the UI
                                yield OpenClawEvent("error", {
                                    "message": (
                                        f"Aborting: agent repeated the same `{tool_name}` "
                                        f"call {_LOOP_GUARD_N} times with no progress. "
                                        "Refine your request — try giving an explicit "
                                        "command or filename so the model has somewhere "
                                        "to go."
                                    ),
                                })
                                self._cancelled.set()
                                break
                            # Retrieval-only tools (memory/session lookups) don't
                            # count as "actually doing the task" — they're pure
                            # context fetches. Tracking executing tool calls
                            # separately lets the corrective retry still fire
                            # when the model's only tool use was a memory probe
                            # followed by a stale chat-style answer.
                            retrieval_only = tool_name in {
                                "memory_search",
                                "memory_get",
                                "sessions_history",
                                "sessions_list",
                                "sessions_send",
                                "session_status",
                                "agents_list",
                            }
                            if not retrieval_only:
                                saw_executing_tool_call = True
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

                        # C1 fix: when the chat final carries `message.tool_calls`
                        # we must treat the turn as having called tools, even
                        # if no agent-stream `tool_call` event was emitted for
                        # them. This happens after the corrective retry —
                        # OpenClaw assigns retry tool events to a different
                        # runId (or doesn't mirror them on the agent stream),
                        # so the original loop's `saw_tool_call` never flips.
                        # Without this, a retry can produce N tool_calls and
                        # still close as "no tools called" → user sees fallback.
                        _final_tool_calls = message.get("tool_calls") or []
                        _final_run_id = (
                            payload.get("runId")
                            or message.get("runId")
                            or "?"
                        )
                        logger.info(
                            "[workspace:%s] [DBG runId] chat final runId=%s "
                            "final_tool_calls=%d text_chars=%d retry=%d",
                            self.workspace_id,
                            _final_run_id,
                            len(_final_tool_calls),
                            len(text),
                            corrective_retry_count,
                        )
                        if _final_tool_calls:
                            saw_tool_call = True
                            # Mirror the retrieval-only filter used on the
                            # agent stream so the "executing" flag stays a
                            # meaningful signal.
                            _RETRIEVAL_ONLY = {
                                "memory_search", "memory_get",
                                "sessions_history", "sessions_list",
                                "sessions_send", "session_status",
                                "agents_list",
                            }
                            for _tc in _final_tool_calls:
                                _tc_name = (
                                    (_tc.get("function") or {}).get("name")
                                    or _tc.get("name")
                                    or ""
                                )
                                if _tc_name and _tc_name not in _RETRIEVAL_ONLY:
                                    saw_executing_tool_call = True
                                    break
                            logger.info(
                                "[workspace:%s] [DBG runId] chat-final "
                                "tool_calls recovered: saw_tool_call=True "
                                "saw_executing=%s names=%s",
                                self.workspace_id,
                                saw_executing_tool_call,
                                [
                                    (tc.get("function") or {}).get("name")
                                    or tc.get("name")
                                    or "?"
                                    for tc in _final_tool_calls
                                ][:6],
                            )

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
                            # C1.3: arm the retry-in-flight guard so the next
                            # empty final doesn't trigger premature fallback
                            # synthesis. See state-vars block ~line 1905.
                            retry_in_flight = True
                            retry_started_at = asyncio.get_event_loop().time()
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

                        # Some models "solve" terminal tasks by pasting a Python
                        # file and a shell command into the final response, or by
                        # echoing a stale memory line, instead of invoking the
                        # write/exec tools. Either way: the file never exists and
                        # the command never ran. Retry once with an explicit
                        # tool-only correction.
                        pasted_code = _looks_like_pasted_code_or_command(text)
                        memory_echo = _looks_like_memory_echo(text)
                        if (
                            looks_terminal_task
                            and not saw_executing_tool_call
                            and corrective_retry_count < 1
                            and (pasted_code or memory_echo)
                        ):
                            corrective_retry_count += 1
                            # C1.3: arm the retry-in-flight guard so the next
                            # empty final doesn't trigger premature fallback
                            # synthesis. See state-vars block ~line 1905.
                            retry_in_flight = True
                            retry_started_at = asyncio.get_event_loop().time()
                            self._last_partial_text = ""
                            self._narrative_cut = 0
                            failure_kind = "pasted code/command" if pasted_code else "stale memory echo"
                            logger.warning(
                                "[workspace:%s] Terminal task returned %s with no tool calls — retrying",
                                self.workspace_id, failure_kind,
                            )
                            yield OpenClawEvent("log", {
                                "message": (
                                    "Agent did not run the task ("
                                    + failure_kind
                                    + "); forcing real terminal execution…"
                                ),
                            })
                            req_id = self._next_id()
                            correction = (
                                "CORRECTION: Your previous response did not actually run the task. "
                                + ("It pasted code or a shell command as text. "
                                   if pasted_code else
                                   "It reused a previous chat answer instead of doing the new task. ")
                                + "That did NOT create a file and did NOT execute anything.\n\n"
                                "You must now use tool calls only:\n"
                                f"1) Call `exec` exactly: {_workdir_init}\n"
                                f"2) If Python is needed, call `write` to create `{workdir_rel}/solve.py`\n"
                                f"3) Call `exec` to run: python3 {workdir}/solve.py\n"
                                "4) Report the exact observed stdout or the exact blocker.\n\n"
                                "Do not include a code block or shell command as plain text until after the "
                                "tool call has executed and returned output. Ignore prior chat memory "
                                "for this task — the user request below is the only goal.\n\n"
                                f"USER REQUEST: {last_user_msg}\n"
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

                        # C1: hash-task no-tool-call retry. Broad trigger for
                        # ANY hash-task final response that didn't emit an
                        # executing tool_call — covers all three observed
                        # failure modes:
                        #   - empty content + zero tool_calls (silent stop)
                        #   - narrative content + zero tool_calls ("I'll run
                        #     the cracker..." without ever calling it —
                        #     qwen3.5:9b coin-flip ~33% of the time at
                        #     production prompt complexity, verified
                        #     2026-05-28 via three direct-to-Ollama
                        #     replays of the same body)
                        #   - regurgitated system-prompt fragments / fake
                        #     {"name":"write",...} JSON in text (hermes4)
                        # All three share a common signature: hash task +
                        # no executing tool_call. Independent of WHAT the
                        # model wrote in content.
                        #
                        # Cap is 2 retries (was 1). At qwen3.5:9b's ~67% per-
                        # attempt rate, two retries push reliability to ~96%
                        # without unbounded looping. Retry budget is shared
                        # across all corrective branches (each ++ corrective_
                        # retry_count) so total cost is bounded.
                        hash_narration = _looks_like_hash_narration_regurgitation(text)
                        if (
                            looks_hash_task
                            and not saw_executing_tool_call
                            and corrective_retry_count < 2
                        ):
                            corrective_retry_count += 1
                            # C1.3: arm the retry-in-flight guard so the next
                            # empty final doesn't trigger premature fallback
                            # synthesis. See state-vars block ~line 1905.
                            retry_in_flight = True
                            retry_started_at = asyncio.get_event_loop().time()
                            self._last_partial_text = ""
                            self._narrative_cut = 0
                            if hash_narration:
                                failure_kind = "narration regurgitation"
                            elif text.strip():
                                # Narrative without tool_call — the qwen3.5:9b
                                # coin-flip miss. Model said what it WOULD do
                                # without doing it.
                                failure_kind = "intent without action"
                            else:
                                failure_kind = "empty final"
                            logger.warning(
                                "[workspace:%s] Hash task returned %s with no "
                                "executing tool call (attempt %d/2) — retrying "
                                "with tool-only directive",
                                self.workspace_id, failure_kind,
                                corrective_retry_count,
                            )
                            yield OpenClawEvent("log", {
                                "message": (
                                    f"Agent did not call the cracker ({failure_kind}) "
                                    f"— retry {corrective_retry_count}/2…"
                                ),
                            })
                            req_id = self._next_id()
                            # Corrective message matches the Lever 1 dispatch
                            # shape (one `exec` of crack_all.py, no separate
                            # write step). Pre-Lever-1 corrections referenced
                            # the write+exec pattern; those would now
                            # contradict the system prompt and confuse the
                            # model further.
                            # Concrete command — the EXACT detected hashes + theme
                            # (not "<every hash from the user request>" placeholders
                            # a 9B model fumbles). Mirrors the original dispatch
                            # command (line ~1279) so the corrective reinforces it.
                            # `_hcdir`/`_theme_arg`/`_hashes_argv` are defined inside
                            # the `if _detected_hashes:` block, which ran (the gate
                            # now requires _detected_hashes truthy → all defined).
                            _corr_cmd = (
                                f"python3 {_hcdir}/crack_all.py{_theme_arg} {_hashes_argv}"
                                if _detected_hashes
                                else "python3 /skills-shared/hash-cracking/crack_all.py "
                                "<every hash from the user request>"
                            )
                            correction = (
                                "CORRECTION: Your previous response did NOT "
                                "call the tool. Talking about what the "
                                "cracker will do, or describing the plan, "
                                "does not run it — you must emit an `exec` "
                                "tool_call through the tool channel.\n\n"
                                "Emit ONE `exec` tool_call NOW. Do not "
                                "narrate. Do not summarize the plan. The "
                                "command:\n"
                                f"  {_corr_cmd}\n\n"
                                "After exec returns JSON, summarize only the "
                                "hashes with verified=true. Say \"unverified\" "
                                "for the rest — do NOT guess plaintexts.\n\n"
                                f"USER REQUEST: {last_user_msg}\n"
                            )
                            # Context-hygiene (2026-05-29): clear OpenClaw's
                            # replayed turn history before this corrective so a
                            # stale completed-task turn ("...cracked successfully"
                            # + tool result) bled in from a prior run can't drive
                            # emission to 0%. Safe here because this corrective is
                            # self-contained (re-embeds the crack_all.py command +
                            # USER REQUEST), so it stands alone after the reset.
                            await self._reset_session_turns("reset")
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
                            # C1.3: arm the retry-in-flight guard so the next
                            # empty final doesn't trigger premature fallback
                            # synthesis. See state-vars block ~line 1905.
                            retry_in_flight = True
                            retry_started_at = asyncio.get_event_loop().time()
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

                        # C1.3: if a corrective retry was just sent, the
                        # model may still be generating. OpenClaw can emit
                        # an "empty final" as an intermediate event before
                        # tool_calls actually flow. Don't synthesize the
                        # fallback prematurely — keep listening for events
                        # until either a non-empty final/tool_call arrives
                        # OR the bounded timeout elapses. Sliding window:
                        # the agent-event handler resets `retry_started_at`
                        # on every fresh tool_call so we don't time out
                        # while the model is actively making progress.
                        if (
                            retry_in_flight
                            and not text.strip()
                            and not saw_tool_call
                        ):
                            _now = asyncio.get_event_loop().time()
                            _elapsed = (
                                _now - retry_started_at
                                if retry_started_at is not None
                                else 0.0
                            )
                            if _elapsed < _RETRY_TIMEOUT_S:
                                logger.info(
                                    "[workspace:%s] [DBG retry-in-flight] "
                                    "empty final after corrective, "
                                    "elapsed=%.1fs < %.0fs — keep listening",
                                    self.workspace_id,
                                    _elapsed, _RETRY_TIMEOUT_S,
                                )
                                continue
                            # Timeout exceeded — fall through to fallback
                            # synthesis with the existing logic.
                            logger.warning(
                                "[workspace:%s] [DBG retry-in-flight] "
                                "timeout reached (%.1fs ≥ %.0fs) — "
                                "synthesizing fallback",
                                self.workspace_id,
                                _elapsed, _RETRY_TIMEOUT_S,
                            )
                            retry_in_flight = False

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
                # call and this one as a 💬 log event. The directive asks the
                # model to prefix every tool call with a short reason; this
                # surfaces it as a progress line.
                #
                # Some models (granite4.1, qwen-coder, smaller llamas) chain
                # tool calls back-to-back without commentary text — Discord
                # then sees only "Running command" lines. When narrative is
                # empty, fall back to _synthesize_narrative on the tool args
                # so the user always gets one-sentence reasoning per step.
                narrative = self._last_partial_text[self._narrative_cut:].strip()
                if narrative and len(narrative) > 5:
                    snippet = narrative if len(narrative) <= 280 else narrative[:277] + "…"
                else:
                    snippet = _synthesize_narrative(tool_name, tool_args)
                if snippet:
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
                if tool_name == "exec" and (
                    "\"verified\": false" in output.lower()
                    or "verified=false" in output.lower()
                    or "tiers_tried" in output.lower()
                ):
                    _debug400831(
                        "openclaw_client.py:_handle_agent_event:tool_result",
                        "hash_exec_result_seen",
                        {
                            "workspace_id": self.workspace_id,
                            "success": success,
                            "snippet": output[:280],
                        },
                        "run_hash_issue",
                        "H3",
                    )
                    logger.warning(
                        "[DBG400831][H3] hash_exec_result_seen workspace=%s success=%s output=%.280s",
                        self.workspace_id,
                        success,
                        output,
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

    async def _send_abort(self, ws):
        """Tell the gateway to abort this session's running agent turn — stops
        generation + tool execution SERVER-SIDE (which is what actually kills a
        long run; closing the socket alone just detaches Harvis). Best-effort:
        fire the known abort RPCs; failures fall through to the socket close.
        Takes a captured `ws` ref because the stream's cleanup may null self._ws."""
        if ws is None:
            return
        for method, params in (
            ("sessions.abort", {"key": self._session_key}),
            ("chat.abort", {"sessionKey": self._session_key}),
        ):
            try:
                rid = self._next_id()
                self._suppress_res_ids.add(rid)  # its res must not abort the stream loop
                await ws.send(
                    json.dumps({"type": "req", "id": rid, "method": method, "params": params})
                )
                logger.warning(
                    "[workspace:%s] sent %s (key=%s) on cancel",
                    self.workspace_id, method, self._session_key[:48],
                )
            except Exception as exc:  # noqa: BLE001 — best-effort abort
                logger.warning(
                    "[workspace:%s] %s failed on cancel: %s", self.workspace_id, method, exc
                )

    async def _abort_then_close(self, ws):
        """Abort the server-side agent first, then close the (captured) socket."""
        try:
            await self._send_abort(ws)
        except Exception:  # noqa: BLE001
            pass
        if ws is not None:
            try:
                await ws.close(code=1000, reason="cancelled")
            except Exception:  # noqa: BLE001
                pass

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
                # Tell the GATEWAY to abort the running agent (stops generation +
                # tool execution server-side), THEN close the socket. Closing alone
                # only detaches Harvis; OpenClaw would keep running the agent. Pass
                # the captured `ws` — the stream's cleanup may null self._ws first.
                loop.create_task(self._abort_then_close(ws))
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
