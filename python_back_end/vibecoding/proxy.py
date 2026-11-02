"""HTTP reverse proxy to route requests to per-session code-server containers.

This proxy keeps code-server unexposed to the public network and enforces authZ.
"""

import logging
from typing import Dict, Optional
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from starlette.websockets import WebSocketDisconnect
import asyncio
import websockets
from fastapi.responses import StreamingResponse

from auth_utils import get_current_user
from .containers import get_container_manager
from .terminal import authenticate_websocket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibecode", tags=["vibecode-proxy"])


def _filter_response_headers(headers: httpx.Headers) -> Dict[str, str]:
    """Remove hop-by-hop headers that should not be forwarded back to the client."""
    hop_by_hop = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
    return {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}


async def _resolve_target_base_url(session_id: str, current_user: Dict) -> str:
    """Resolve target base URL for the session's code-server.

    Requires that the container was created with a published host port label
    (vibecode_host_port). Verifies ownership via user_id label; a container with
    no user_id label is refused, since code-server itself runs with --auth none.
    """
    container_manager = get_container_manager()
    container = await container_manager.get_container(session_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    user_id_label = container.labels.get("user_id")
    if not user_id_label or str(current_user["id"]) != user_id_label:
        raise HTTPException(status_code=403, detail="Unauthorized")

    host_port = container.labels.get("vibecode_host_port")
    internal_port = container.labels.get("vibecode_internal_port", "8080")

    # Prefer host-published port if available; fallback to container port via host network
    if host_port:
        return f"http://127.0.0.1:{host_port}"

    # Last-resort fallback to container-exposed port through Docker engine publish (unlikely here)
    try:
        container.reload()
        ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
        host_bindings = ports.get(f"{internal_port}/tcp")
        if host_bindings and len(host_bindings) > 0:
            return f"http://127.0.0.1:{host_bindings[0].get('HostPort')}"
    except Exception as e:
        logger.warning(f"Could not resolve published port: {e}")

    raise HTTPException(status_code=503, detail="Session proxy is not available")


@router.api_route("/sessions/{session_id}/proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_http(
    session_id: str,
    path: str,
    request: Request,
    current_user: Dict = Depends(get_current_user),
) -> Response:
    """Generic HTTP proxy to the session's code-server.

    WebSockets are not handled by this handler and can be added separately if needed.
    """
    base_url = await _resolve_target_base_url(session_id, current_user)

    # Build full target URL
    query = request.url.query
    target_url = f"{base_url}/{path}" + (f"?{query}" if query else "")

    # Prepare request content and headers
    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)
    # Do not forward client Authorization to code-server (we run with --auth none)
    headers.pop("authorization", None)

    timeout = httpx.Timeout(60.0, connect=10.0)

    async def stream_response(client: httpx.AsyncClient, method: str) -> StreamingResponse:
        async with client.stream(method, target_url, content=body, headers=headers) as resp:
            filtered = _filter_response_headers(resp.headers)
            return StreamingResponse(resp.aiter_bytes(), status_code=resp.status_code, headers=filtered)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        return await stream_response(client, request.method)


@router.websocket("/sessions/{session_id}/proxy/ws/{path:path}")
async def proxy_websocket(
    websocket: WebSocket,
    session_id: str,
    path: str,
):
    """WebSocket proxy for code-server. The caller must present the same JWT the terminal
    websocket takes (``token`` query parameter, or the ``token`` cookie) and own the
    session's container; code-server runs with --auth none, so this is the only gate.
    """
    try:
        user = await authenticate_websocket(
            token=websocket.query_params.get("token"), cookies=dict(websocket.cookies)
        )
    except HTTPException:
        await websocket.close(code=1008)
        return

    try:
        container_manager = get_container_manager()
        container = await container_manager.get_container(session_id)
        if not container:
            await websocket.close(code=4404)
            return
        user_id_label = container.labels.get("user_id")
        if not user_id_label or str(user["id"]) != user_id_label:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        host_port = container.labels.get("vibecode_host_port")
        internal_port = container.labels.get("vibecode_internal_port", "8080")
        if host_port:
            base_ws = f"ws://127.0.0.1:{host_port}"
        else:
            # Fallback to published port, if any
            container.reload()
            ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            host_bindings = ports.get(f"{internal_port}/tcp")
            if host_bindings and len(host_bindings) > 0:
                base_ws = f"ws://127.0.0.1:{host_bindings[0].get('HostPort')}"
            else:
                await websocket.close(code=1011)
                return

        # Preserve the original query string, minus our own JWT: code-server must not see it.
        query = urlencode(
            [(k, v) for k, v in parse_qsl(websocket.scope.get("query_string", b"").decode(),
                                          keep_blank_values=True) if k != "token"]
        )
        target_url = f"{base_ws}/{path}" + (f"?{query}" if query else "")

        async with websockets.connect(target_url, ping_interval=None) as target_ws:
            async def client_to_server():
                try:
                    while True:
                        msg = await websocket.receive_text()
                        await target_ws.send(msg)
                except WebSocketDisconnect:
                    await target_ws.close()
                except Exception:
                    await target_ws.close()

            async def server_to_client():
                try:
                    while True:
                        msg = await target_ws.recv()
                        # websockets lib may return bytes or str
                        if isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                except Exception:
                    await websocket.close()

            await asyncio.gather(client_to_server(), server_to_client())

    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


