# MCP RAG Server Connection Issues

**Date:** 2026-03-31  
**Status:** ✅ RESOLVED

---

## Solution

**Root Cause**: The MCP HTTP+SSE transport spec requires that all JSON-RPC responses travel back over the SSE stream as `event: message` events, not as HTTP response bodies. opencode's MCP client was:

1. Opening GET /sse ✓
2. Reading the endpoint announcement ✓
3. POSTing initialize to /message — getting 200 + JSON body back
4. Ignoring the HTTP body and waiting for the response on the SSE stream
5. Never seeing it → 30s timeout → connection closed

**Fix Applied**:

1. **Added per-connection SSE queues**: Each SSE connection gets a unique `connectionId` and an `asyncio.Queue` for responses
2. **Updated `/sse` endpoint**: Now announces endpoint as `/message?connectionId=<uuid>` and streams responses from the queue
3. **Updated `/message` endpoint**: Pushes responses to the SSE queue and returns 202 Accepted
4. **Fixed RpcRequest model**: Made `id` and `params` optional to handle MCP notifications

**Correct opencode Configuration**:

```json
{
  "harvis-rag": {
    "type": "remote",
    "url": "http://192.168.10.246:8000/sse",
    "enabled": true
  }
}
```

**IMPORTANT**: The URL must include `/sse` suffix - opencode's MCP client expects this path.

---

## Current Status

### ✅ Working Components

1. **MCP RAG Server** deployed at `http://192.168.10.246:8000`
2. **All endpoints respond correctly**:
   - `GET /sse` - Returns 200, sends SSE stream with connectionId
   - `POST /message?connectionId=<uuid>` - Handles JSON-RPC, returns 202
   - Responses stream back via SSE as `event: message`

3. **MCP Protocol Implementation**:
   - `initialize` - Returns server info via SSE
   - `tools/list` - Returns 5 RAG tools via SSE
   - `tools/call` - Executes tools via SSE
   - `ping` - Keepalive support
   - `notifications/initialized` - Handled correctly

4. **opencode Connection**: ✅ Connected and working!

---

## Server Logs (Successful Flow)

```
INFO: SSE connection opened: 2ba74d9d-c3c7-450e-98be-20b4d3e5699f
INFO: Sent endpoint announcement for 2ba74d9d-c3c7-450e-98be-20b4d3e5699f
INFO: MCP request: method=initialize, id=0
INFO: Sending initialize response via SSE
INFO: POST /message?connectionId=2ba74d9d-c3c7-450e-98be-20b4d3e5699f HTTP/1.1" 202 Accepted
INFO: Received notification: notifications/initialized
INFO: MCP request: method=tools/list, id=1
INFO: tools/list: 5 tools
```

---

## Testing Commands

### Manual Test (Works)
```bash
# Test SSE endpoint
curl -s http://192.168.10.246:8000/sse | head -5

# Test tools/list (direct, no SSE)
curl -s -X POST http://192.168.10.246:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}' | jq .
```

### opencode Test
```bash
opencode mcp list
# Expected: harvis-rag connected
```

---

**Resolved:** 2026-03-31 23:25

