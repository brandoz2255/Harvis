from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from .registry import registry, invoke_tool
from .auth import require_scopes
from .tools.os_ops import register_os_ops  # registers tools at import

app = FastAPI(title="MCP OS-OPS Server")
register_os_ops()

class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    method: str
    params: dict

@app.post("/mcp/invoke")
async def mcp_invoke(req: RpcRequest, authorization: str = Header(None)):
    if req.method != "tool.invoke":
        raise HTTPException(400, "Unsupported method")
    tool_name = req.params.get("name")
    args = req.params.get("args", {})
    tool = registry.get(tool_name)
    if not tool:
        raise HTTPException(404, f"Unknown tool {tool_name}")
    require_scopes(authorization, tool.scope)
    try:
        result = await invoke_tool(tool, args)
        return {"jsonrpc": "2.0", "id": req.id, "result": result}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": req.id,
                "error": {"code": -32000, "message": str(e)}}
