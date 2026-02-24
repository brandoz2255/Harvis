"""
OpenClaw WebSocket client for Harvis Workspaces.

Manages connections to the OpenClaw gateway (ws://harvis-ai-openclaw:18789)
and streams activity log events back to the calling code.

Protocol note: OpenClaw uses method-based JSON-RPC over WebSocket.
The gateway authenticates via a token sent as the first message.
See: openclaw/openclaw/src/gateway/server-methods/ for all RPC methods.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator, Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = logging.getLogger(__name__)

OPENCLAW_URL = os.getenv("OPENCLAW_URL", "ws://harvis-ai-openclaw:18789")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")


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

    def __init__(self, workspace_id: str, session_id: Optional[str] = None):
        self.workspace_id = workspace_id
        # session_id scopes the conversation history inside OpenClaw.
        # Re-using the same session_id across launches gives OpenClaw memory
        # of previous tasks for the same user — "one-shot but resumable".
        self.session_id = session_id or f"harvis-ws-{workspace_id}"
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._cancelled = asyncio.Event()
        self._request_id = 0

    def _next_id(self) -> str:
        self._request_id += 1
        return str(self._request_id)

    async def _connect(self) -> websockets.WebSocketClientProtocol:
        """Open the WebSocket and authenticate with the gateway token."""
        ws = await websockets.connect(
            OPENCLAW_URL,
            ping_interval=20,
            ping_timeout=10,
            open_timeout=10,
        )

        # Authenticate — OpenClaw expects a token message first.
        await ws.send(json.dumps({
            "type": "auth",
            "token": OPENCLAW_GATEWAY_TOKEN,
        }))

        # Read the auth ack. If auth fails the gateway closes the connection.
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        ack = json.loads(raw)

        if ack.get("type") == "error" or ack.get("error"):
            await ws.close()
            raise ConnectionError(f"OpenClaw auth failed: {ack}")

        logger.info(f"[workspace:{self.workspace_id}] Connected and authenticated to OpenClaw")
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
            chat_history:  Full Harvis chat history (list of {role, content} dicts).
                          This is prepended to the OpenClaw session as context.

        Yields:
            OpenClawEvent objects — one per log line, token, tool call, or completion.
        """
        try:
            self._ws = await self._connect()
        except Exception as e:
            logger.error(f"[workspace:{self.workspace_id}] Failed to connect to OpenClaw: {e}")
            yield OpenClawEvent("error", {"message": f"Could not connect to workspace backend: {e}"})
            return

        try:
            # Build the system context from Harvis chat history.
            # OpenClaw receives this as a synthetic "context" message so it
            # understands what the user has been discussing.
            context_lines = [
                f"{m['role'].upper()}: {m['content']}"
                for m in chat_history[-30:]  # cap at last 30 messages
                if isinstance(m.get("content"), str) and m["content"].strip()
            ]
            context_block = "\n".join(context_lines)

            full_message = (
                f"[HARVIS CONVERSATION CONTEXT]\n{context_block}\n\n"
                f"[TASK]\n{task_message}"
            ) if context_lines else task_message

            # Send the chat message via the gateway's chat.stream RPC method.
            # See: openclaw/openclaw/src/gateway/server-methods/chat.*
            req_id = self._next_id()
            await self._ws.send(json.dumps({
                "type": "call",
                "id": req_id,
                "method": "chat.stream",
                "params": {
                    "sessionId": self.session_id,
                    "message": full_message,
                    "agentId": "default",
                },
            }))

            logger.info(f"[workspace:{self.workspace_id}] Task sent to OpenClaw, streaming response...")

            # Stream events from the gateway until done or cancelled.
            async for raw in self._ws:
                if self._cancelled.is_set():
                    yield OpenClawEvent("cancelled", {"message": "Workspace cancelled by user."})
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                event_type = msg.get("event") or msg.get("type", "log")
                data = msg.get("data", {})

                # Normalize the event shape for the frontend.
                if event_type in ("token", "content"):
                    yield OpenClawEvent("token", {"content": data.get("content", "")})

                elif event_type in ("tool_call", "tool.call"):
                    yield OpenClawEvent("tool_call", {
                        "tool": data.get("name", "unknown"),
                        "args": data.get("args", {}),
                    })

                elif event_type in ("tool_result", "tool.result"):
                    yield OpenClawEvent("tool_result", {
                        "tool": data.get("name", "unknown"),
                        "output": data.get("output", ""),
                        "success": data.get("success", True),
                    })

                elif event_type in ("log", "info"):
                    yield OpenClawEvent("log", {"message": data.get("message", str(data))})

                elif event_type in ("done", "complete", "end"):
                    yield OpenClawEvent("done", {
                        "summary": data.get("content", data.get("summary", "")),
                    })
                    break

                elif event_type == "error":
                    yield OpenClawEvent("error", {
                        "message": data.get("message", str(data)),
                    })
                    break

        except ConnectionClosed as e:
            logger.warning(f"[workspace:{self.workspace_id}] OpenClaw connection closed: {e}")
            yield OpenClawEvent("done", {"summary": ""})

        except WebSocketException as e:
            logger.error(f"[workspace:{self.workspace_id}] WebSocket error: {e}")
            yield OpenClawEvent("error", {"message": f"Workspace connection error: {e}"})

        finally:
            await self.close()

    def cancel(self):
        """Signal the stream loop to stop after the current event."""
        self._cancelled.set()
        logger.info(f"[workspace:{self.workspace_id}] Cancel requested")

    async def close(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info(f"[workspace:{self.workspace_id}] WebSocket closed")
        self._ws = None
