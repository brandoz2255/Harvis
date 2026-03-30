import os
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

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


class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    method: str
    params: dict


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


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "tools": list(registry.keys()),
        "vectordb_connected": _vectordb_client is not None,
        "embedding_client_ready": _embedding_client is not None,
    }


@app.post("/mcp/invoke")
async def mcp_invoke(req: RpcRequest) -> Dict[str, Any]:
    """
    Invoke an MCP tool.

    Expects JSON-RPC 2.0 format request with:
    - method: "tool.invoke"
    - params.name: tool name
    - params.args: tool arguments
    """
    if req.method != "tool.invoke":
        raise HTTPException(status_code=400, detail="Unsupported method")

    tool_name = req.params.get("name")
    args = req.params.get("args", {})

    tool = registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

    try:
        result = await invoke_tool(tool, args)
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "result": result.model_dump(),
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
