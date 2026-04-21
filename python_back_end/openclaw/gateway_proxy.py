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

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse

from auth_optimized import get_current_user_optimized

logger = logging.getLogger(__name__)

# ─── OpenClaw connection constants ────────────────────────────────────────────

OPENCLAW_URL = os.getenv("OPENCLAW_URL", "ws://openclaw:18789")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

PROTOCOL_VERSION = 3

_CLIENT_ID = "gateway-proxy"
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
    ws: websockets.WebSocketServerProtocol,
    user_id: int,
) -> websockets.WebSocketClientProtocol:
    """
    Connect to OpenClaw gateway and perform the auth handshake.

    Returns an open websockets connection to the OpenClaw gateway.
    """
    while True:
        try:
            oc_ws = await websockets.connect(
                OPENCLAW_URL,
                ping_interval=20,
                ping_timeout=10,
                open_timeout=10,
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


async def _relay(src: websockets.WebSocket, dst: websockets.WebSocket, label: str = ""):
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
    # Accept the frontend connection
    await ws.accept()
    logger.info("[gateway-proxy] Frontend connected (user=%d)", user_id)

    # Generate a unique session key for this connection
    session_key = f"agent:main:harvis-ui-{uuid.uuid4().hex[:12]}"

    # Connect to OpenClaw gateway
    oc_ws = await _connect_to_openclaw(ws, user_id)

    try:
        # Relay: frontend → OpenClaw
        async def frontend_to_openclaw():
            try:
                async for message in ws:
                    if isinstance(message, str):
                        msg = json.loads(message)
                        # Inject session key into chat.send if needed
                        if msg.get("method") == "chat.send" and "params" in msg:
                            if "sessionKey" not in msg["params"]:
                                msg["params"]["sessionKey"] = session_key
                                msg["params"]["idempotencyKey"] = msg.get("id", uuid.uuid4().hex)
                        await oc_ws.send(json.dumps(msg))
                    elif isinstance(message, bytes):
                        await oc_ws.send(message)
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.error("[gateway-proxy] frontend→openclaw error: %s", e)

        # Relay: OpenClaw → frontend
        async def openclaw_to_frontend():
            try:
                async for message in oc_ws:
                    msg = json.loads(message)

                    # Inject session key into events if missing
                    if msg.get("type") == "event" and "sessionKey" not in msg.get("payload", {}):
                        if msg.get("event") in ("chat", "agent"):
                            msg["payload"]["sessionKey"] = session_key

                    await ws.send_json(msg)
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                logger.error("[gateway-proxy] openclaw→frontend error: %s", e)

        # Run both relays concurrently
        await asyncio.gather(
            frontend_to_openclaw(),
            openclaw_to_frontend(),
        )

    except WebSocketDisconnect:
        logger.info("[gateway-proxy] Frontend disconnected")
    except Exception as e:
        logger.error("[gateway-proxy] Connection error: %s", e)
    finally:
        # Close OpenClaw connection
        try:
            await oc_ws.close()
        except Exception:
            pass
        logger.info("[gateway-proxy] Connection closed (user=%d, session=%s)", user_id, session_key[:20])


@router.websocket("/ws/openclaw")
async def openclaw_gateway_proxy(ws: WebSocket):
    """
    WebSocket proxy endpoint for OpenClaw gateway.

    Authenticates the user, connects to OpenClaw gateway, and relays
    JSON-RPC frames bidirectionally.
    """
    # Authenticate user
    user = await get_current_user_optimized(ws)
    if user is None:
        # Auth failed — send error and close
        try:
            await ws.accept()
            await ws.send_json({"type": "error", "message": "Authentication required"})
            await ws.close(code=4001, reason="Authentication required")
        except Exception:
            pass
        return

    await _handle_openclaw_ws(ws, user.id)
