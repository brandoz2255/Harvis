"""
OpenClaw Gateway Proxy — WebSocket relay between newjfrontend and OpenClaw gateway.

Accepts WebSocket connections from the frontend at /ws/openclaw, performs the
OpenClaw connect handshake using Ed25519 device identity, then relays JSON-RPC
frames bidirectionally.

Each frontend connection gets its own OpenClaw connection with a unique session
key. The proxy is transparent — it relays raw JSON-RPC frames without parsing
or modifying them, so all 80+ OpenClaw RPC methods work automatically.

Protocol (OpenClaw gateway v3):
  1. Frontend connects to ws://backend:8000/ws/openclaw
  2. Backend connects to ws://openclaw:18789
  3. Backend performs connect.challenge → connect handshake
  4. Frames relayed bidirectionally:
       frontend ↔ backend ↔ OpenClaw gateway
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Optional

import websockets.client
from websockets.client import WebSocketClientProtocol
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse

from auth_optimized import get_current_user_optimized
from jwt import decode as jwt_decode
from jose import JWTError, jwt as jwt_encode
import os

logger = logging.getLogger(__name__)

# ─── OpenClaw connection constants ────────────────────────────────────────────

OPENCLAW_URL = os.getenv("OPENCLAW_URL", "ws://openclaw:18789")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

PROTOCOL_VERSION = 3

_CLIENT_ID = "gateway-client"
_CLIENT_MODE = "webchat"
_CLIENT_SCOPES = ["operator.admin", "operator.approvals", "operator.pairing"]

# Ed25519 SPKI DER prefix — strip to get raw 32-byte key
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")

# ─── Device identity (generated once per process) ─────────────────────────────

def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _generate_device_identity():
    """Generate Ed25519 key pair and derive device ID."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    pub_der = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if pub_der[: len(_ED25519_SPKI_PREFIX)] == _ED25519_SPKI_PREFIX:
        raw_pub = pub_der[len(_ED25519_SPKI_PREFIX):]
    else:
        raw_pub = pub_der

    device_id = hashlib.sha256(raw_pub).hexdigest()
    pub_b64url = _base64url_encode(raw_pub)
    return private_key, device_id, pub_b64url


_device_private_key, _device_id, _device_pub_b64url = _generate_device_identity()
logger.info("[gateway-proxy] Device identity initialized: deviceId=%s...", _device_id[:16])


def _build_device_params(nonce: str) -> dict:
    """Build signed device identity block for the OpenClaw connect handshake."""
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


# ─── Router ───────────────────────────────────────────────────────────────────

router = APIRouter()


async def _connect_to_openclaw(
    ws: WebSocket,
    user_id: int,
) -> WebSocketClientProtocol:
    """
    Connect to OpenClaw gateway and perform the auth handshake.

    Returns an open websockets connection to the OpenClaw gateway.
    """
    while True:
        try:
            oc_ws = await websockets.client.connect(
                OPENCLAW_URL,
                ping_interval=20,
                ping_timeout=10,
                open_timeout=10,
                extra_headers={
                    "Origin": os.getenv("HARVIS_ORIGIN", "https://harvis.dulc3.tech"),
                },
            )

            # Step 1: Receive connect.challenge
            try:
                raw_challenge = await asyncio.wait_for(oc_ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                await oc_ws.close()
                raise ConnectionError("OpenClaw connect.challenge timeout")

            challenge = json.loads(raw_challenge)
            if not (challenge.get("type") == "event" and challenge.get("event") == "connect.challenge"):
                await oc_ws.close()
                raise ConnectionError(
                    f"Expected connect.challenge, got: {json.dumps(challenge)[:200]}"
                )
            nonce = challenge.get("payload", {}).get("nonce", "")
            if not nonce:
                await oc_ws.close()
                raise ConnectionError("OpenClaw connect.challenge missing nonce")

            # Step 2: Send connect handshake
            req_id = "1"
            await oc_ws.send(json.dumps({
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

            # Step 3: Wait for handshake response
            try:
                raw = await asyncio.wait_for(oc_ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                await oc_ws.close()
                raise ConnectionError("OpenClaw connect response timeout")

            ack = json.loads(raw)
            if ack.get("type") != "res" or not ack.get("ok"):
                await oc_ws.close()
                error_detail = ack.get("error", {}).get("message", str(ack))
                raise ConnectionError(f"OpenClaw connect failed: {error_detail}")

            logger.info("[gateway-proxy] Connected and authenticated to OpenClaw")
            return oc_ws

        except (ConnectionError, Exception) as e:
            logger.warning("[gateway-proxy] Failed to connect to OpenClaw: %s", e)
            await asyncio.sleep(2)
            # Retry connection


async def _relay(src: WebSocket, dst: WebSocketClientProtocol, label: str = ""):
    """Relay messages from src to dst."""
    try:
        async for message in src:
            if isinstance(message, str):
                await dst.send(message)
            elif isinstance(message, bytes):
                await dst.send(message)
    except websockets.exceptions.ConnectionClosed:
        pass


async def _handle_openclaw_ws(
    ws: WebSocket,
    user_id: int,
):
    """Handle a single frontend WebSocket connection."""
    await ws.accept()
    logger.info("[gateway-proxy] Frontend connected (user=%d)", user_id)

    session_key = f"agent:main:harvis-ui-{uuid.uuid4().hex[:12]}"
    message_history: list = []

    oc_ws = await _connect_to_openclaw(ws, user_id)
    logger.info("[gateway-proxy] OpenClaw connected, starting relays")

    async def frontend_to_openclaw():
        try:
            while True:
                data = await ws.receive_text()
                msg = json.loads(data)
                if msg.get("method") == "chat.send" and "params" in msg:
                    if "sessionKey" not in msg["params"]:
                        msg["params"]["sessionKey"] = session_key
                        msg["params"]["idempotencyKey"] = msg.get("id", uuid.uuid4().hex)
                elif msg.get("method") == "chat.history":
                    await ws.send_json({
                        "type": "res",
                        "id": msg["id"],
                        "ok": True,
                        "payload": {"messages": message_history}
                    })
                    continue
                logger.debug("[gateway-proxy] FE→OC: %s", msg.get("method", msg.get("type", "?")))
                await oc_ws.send(json.dumps(msg))
        except WebSocketDisconnect:
            logger.info("[gateway-proxy] Frontend disconnected normally")
        except Exception as e:
            logger.error("[gateway-proxy] frontend→openclaw error: %s", e, exc_info=True)

    async def openclaw_to_frontend():
        try:
            while True:
                raw = await oc_ws.recv()
                msg = json.loads(raw)
                if msg.get("type") == "event":
                    if "sessionKey" not in msg.get("payload", {}):
                        if msg.get("event") in ("chat", "agent"):
                            msg["payload"]["sessionKey"] = session_key
                    if msg.get("event") == "chat":
                        payload = msg.get("payload", {})
                        if payload.get("type") == "final":
                            message_history.append({
                                "role": "assistant",
                                "content": payload.get("content", []),
                                "timestamp": payload.get("timestamp", int(time.time() * 1000))
                            })
                logger.debug("[gateway-proxy] OC→FE: %s", msg.get("event", msg.get("method", "?")))
                await ws.send_json(msg)
        except websockets.exceptions.ConnectionClosed:
            logger.info("[gateway-proxy] OpenClaw connection closed")
        except Exception as e:
            logger.error("[gateway-proxy] openclaw→frontend error: %s", e, exc_info=True)

    done, pending = await asyncio.wait(
        [asyncio.create_task(frontend_to_openclaw()), asyncio.create_task(openclaw_to_frontend())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        await oc_ws.close()
    except Exception:
        pass
    logger.info("[gateway-proxy] Connection closed (user=%d, session=%s)", user_id, session_key[:20])


def _extract_token_from_ws(ws) -> Optional[str]:
    """Extract JWT token from headers, cookies, or query params."""
    auth = ws.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    
    cookie_header = ws.headers.get("cookie", "")
    for cookie in cookie_header.split(";"):
        cookie = cookie.strip()
        if cookie.startswith("auth_token="):
            return cookie.split("=", 1)[1]
    
    query_token = ws.query_params.get("token", "")
    if query_token:
        return query_token
    
    return None


async def _authenticate_ws(ws) -> Optional[dict]:
    """Authenticate WebSocket connection using token from headers/cookies/query params."""
    token = _extract_token_from_ws(ws)
    if not token:
        return None
    
    # Use same default as auth_optimized.py for consistency
    secret = os.getenv("JWT_SECRET", "key")
    try:
        payload = jwt_decode(token, secret, algorithms=["HS256"])
        user_id = int(payload.get("sub", 0))
        if user_id == 0:
            return None
        
        from auth_optimized import auth_optimizer
        user_data = await auth_optimizer.get_user_from_cache_or_db(user_id)
        if user_data:
            return user_data
    except JWTError:
        pass
    except Exception as e:
        logger.warning("[gateway-proxy] Auth error: %s", e)
    
    return None


@router.websocket("/ws/openclaw")
async def openclaw_gateway_proxy(ws: WebSocket):
    """
    WebSocket proxy endpoint for OpenClaw gateway.

    Authenticates the user, connects to OpenClaw gateway, and relays
    JSON-RPC frames bidirectionally.
    """
    # Authenticate user
    user = await _authenticate_ws(ws)
    if user is None:
        # Auth failed — send error and close
        try:
            await ws.accept()
            await ws.send_json({"type": "error", "message": "Authentication required"})
            await ws.close(code=4001, reason="Authentication required")
        except Exception:
            pass
        return

    await _handle_openclaw_ws(ws, user['id'])
