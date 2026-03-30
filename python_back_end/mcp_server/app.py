import os
import logging
import json
import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

from .registry import registry, invoke_tool
from .vectordb_client import VectorDBClient
from .embedding_client import EmbeddingClient
from .tools import register_all_tools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global clients
_vectordb_client: VectorDBClient | None = None
_embedding_client: EmbeddingClient | None = None

# Set global clients for tools
import sys
from importlib import import_module

_tools_module_path = "mcp_server.tools"
for submodule in [
    "search_code",
    "search_cyber",
    "search_linux",
    "search_all",
    "get_sources",
]:
    try:
        module = import_module(f"{_tools_module_path}.{submodule}")
        if hasattr(module, "_vectordb_client"):
            module._vectordb_client = _vectordb_client
        if hasattr(module, "_embedding_client"):
            module._embedding_client = _embedding_client
    except ImportError:
        pass


# Per-connection SSE queues: connectionId -> asyncio.Queue
_sse_queues: Dict[str, asyncio.Queue] = {}


class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[str | int] = None
    method: str
    params: Optional[dict] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup on startup/shutdown."""
    global _vectordb_client, _embedding_client

    # Get config from environment
    db_url = os.getenv("DATABASE_URL")
    qwen3_url = os.getenv("EMBED_QW3_URL", "http://localhost:8080")
    nomic_url = os.getenv("EMBED_NOMIC_URL", "http://localhost:8081")

    if not db_url:
        logger.warning("DATABASE_URL not set, vector search will fail")
    else:
        _vectordb_client = VectorDBClient(db_url)
        await _vectordb_client.initialize()
        logger.info(f"VectorDB client initialized")

    _embedding_client = EmbeddingClient(qwen3_url, nomic_url)
    logger.info(
        f"Embedding client initialized (qwen3: {qwen3_url}, nomic: {nomic_url})"
    )

    # Update tool modules with clients
    for submodule in [
        "search_code",
        "search_cyber",
        "search_linux",
        "search_all",
        "get_sources",
    ]:
        try:
            module = import_module(f"{_tools_module_path}.{submodule}")
            if hasattr(module, "_vectordb_client"):
                module._vectordb_client = _vectordb_client
            if hasattr(module, "_embedding_client"):
                module._embedding_client = _embedding_client
            logger.info(f"Updated {submodule} with clients")
        except ImportError as e:
            logger.warning(f"Could not update {submodule}: {e}")

    logger.info("MCP RAG Server started")
    yield

    # Cleanup
    if _vectordb_client:
        await _vectordb_client.close()
    if _embedding_client:
        await _embedding_client.close()
    logger.info("MCP RAG Server stopped")


# Create FastAPI app
app = FastAPI(
    title="Harvis RAG MCP Server",
    description="MCP server for querying Harvis RAG vector database",
    version="1.0.0",
    lifespan=lifespan,
)

# Register all tools on startup
register_all_tools()
logger.info(f"Registered {len(registry)} tools: {list(registry.keys())}")


@app.post("/")
async def streamable_http_handler(request: Request) -> Response:
    """
    MCP Streamable HTTP transport (2025-03-26 spec).
    opencode POSTs JSON-RPC directly to the base URL.
    Returns JSON for single responses, or SSE if client sends Accept: text/event-stream.
    """
    try:
        body = await request.json()
        req = RpcRequest(**body)
    except Exception as e:
        logger.error(f"Invalid JSON-RPC request: {e}")
        return Response(status_code=400, content=str(e))

    # Notifications expect no response
    if req.id is None or req.method.startswith("notifications/"):
        logger.info(f"Received notification: {req.method}")
        return Response(status_code=202)

    response = await handle_mcp_request(req)

    if "text/event-stream" in request.headers.get("Accept", ""):
        async def _stream() -> AsyncGenerator[str, None]:
            yield f"event: message\ndata: {json.dumps(response)}\n\n"
        return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return JSONResponse(content=response)


@app.get("/sse")
async def sse_endpoint(request: Request) -> StreamingResponse:
    """
    SSE endpoint for MCP HTTP+SSE transport.
    Announces the message endpoint and streams JSON-RPC responses back to the client.
    """
    connection_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues[connection_id] = queue
    logger.info(f"SSE connection opened: {connection_id}")

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            # Announce the POST endpoint including this connection's ID
            yield f"event: endpoint\ndata: /message?connectionId={connection_id}\n\n"
            logger.info(f"Sent endpoint announcement for {connection_id}")

            while True:
                try:
                    # Wait for a response to push, with keepalive timeout
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: message\ndata: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            logger.info(f"SSE connection cancelled: {connection_id}")
            raise
        except GeneratorExit:
            logger.info(f"SSE generator exited: {connection_id}")
            raise
        except Exception as e:
            logger.error(f"SSE stream error [{connection_id}]: {e}")
            raise
        finally:
            _sse_queues.pop(connection_id, None)
            logger.info(f"SSE connection closed: {connection_id}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "tools": list(registry.keys()),
        "vectordb_connected": _vectordb_client is not None,
        "embedding_client_ready": _embedding_client is not None,
    }


@app.post("/message")
async def message_handler(request: Request) -> Response:
    """
    MCP message handler for SSE transport.
    Processes JSON-RPC requests and pushes responses back onto the SSE stream.
    Returns 202 Accepted — the actual response travels via SSE.
    """
    connection_id = request.query_params.get("connectionId")
    try:
        body = await request.json()
        req = RpcRequest(**body)
    except Exception as e:
        logger.error(f"Invalid JSON-RPC request: {e}")
        return Response(status_code=400, content=str(e))

    # Notifications have no id and expect no response
    is_notification = req.id is None or req.method.startswith("notifications/")
    if is_notification:
        logger.info(f"Received notification: {req.method}")
        return Response(status_code=202)

    response = await handle_mcp_request(req)

    queue = _sse_queues.get(connection_id) if connection_id else None
    if queue is not None:
        await queue.put(response)
        return Response(status_code=202)
    else:
        # No SSE connection found — fall back to returning in HTTP body
        logger.warning(
            f"No SSE queue for connectionId={connection_id}, returning inline"
        )
        return JSONResponse(content=response)


@app.post("/sse/message")
async def sse_message_handler(request: Request) -> Response:
    """Alternate path for when base URL includes /sse."""
    return await message_handler(request)


@app.post("/mcp")
async def mcp_handler(req: RpcRequest) -> Dict[str, Any]:
    """Direct MCP handler (returns response in HTTP body, not SSE)."""
    return await handle_mcp_request(req)


async def handle_mcp_request(req: RpcRequest) -> Dict[str, Any]:
    """Handle MCP JSON-RPC requests. Always returns a response dict."""
    params = req.params or {}
    logger.info(f"MCP request: method={req.method}, id={req.id}")

    if req.method == "ping":
        return {"jsonrpc": "2.0", "id": req.id, "result": {}}

    if req.method == "initialize":
        result = {
            "jsonrpc": "2.0",
            "id": req.id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "harvis-rag", "version": "1.0.0"},
            },
        }
        logger.info("Sending initialize response via SSE")
        return result

    if req.method == "tools/list":
        result = {
            "jsonrpc": "2.0",
            "id": req.id,
            "result": {
                "tools": [
                    {
                        "name": name,
                        "description": "RAG search tool",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "top_k": {"type": "integer", "default": 5},
                            },
                            "required": ["query"],
                        },
                    }
                    for name in registry.keys()
                ]
            },
        }
        logger.info(f"tools/list: {len(result['result']['tools'])} tools")
        return result

    if req.method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        tool = registry.get(tool_name)
        if not tool:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
            }

        try:
            result = await invoke_tool(tool, args)
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {
                    "content": [{"type": "text", "text": str(result.model_dump())}]
                },
            }
        except ValueError as e:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {"code": -32000, "message": f"Invalid arguments: {str(e)}"},
            }
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {"code": -32000, "message": str(e)},
            }

    return {
        "jsonrpc": "2.0",
        "id": req.id,
        "error": {"code": -32601, "message": f"Method not found: {req.method}"},
    }


@app.get("/tools")
async def list_tools() -> Dict[str, Any]:
    """List all available tools."""
    return {
        "tools": [
            {
                "name": name,
                "scope": tool.scope,
                "timeout_s": tool.timeout_s,
            }
            for name, tool in registry.items()
        ]
    }
