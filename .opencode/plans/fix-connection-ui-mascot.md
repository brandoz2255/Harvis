# Fix: Connection Drops, UI Polish, Mascot Integration

## Problem Summary

1. **WebSocket connection drops immediately** — Backend logs show `accepted → open → closed` repeatedly. Messages sent to OpenClaw go to "void" (never received). Chat history times out at 60s because `chat.history` hangs.
2. **UI is ugly** — `Sparkles` icon used instead of mascot, input box centered and oversized, empty state shows artifacts through.
3. **Mascot missing** — `HarvisMascot` exists and works in original chat but not wired into OpenClaw chat.

---

## Root Cause Analysis: Connection Drops

### `gateway_proxy.py` relay bug (PRIMARY)
The relay functions use `async for message in ws` which **does not work correctly with FastAPI WebSockets**. FastAPI's `WebSocket` class doesn't properly support async iteration. This causes the relay coroutines to exit immediately, which cancels both tasks in `asyncio.gather`, which closes the OpenClaw connection, which triggers `onclose` on the frontend client, which triggers reconnection → loop of death.

### Secondary issues
- No keepalive pings on the OpenClaw WebSocket → connection times out from inactivity
- `chat.history` JSON-RPC method not implemented in backend proxy → 60s timeout
- Each frontend disconnect creates a new OpenClaw connection → no session persistence

---

## Plan

### Phase 1: Fix WebSocket Relay (gateway_proxy.py)

**File:** `python_back_end/openclaw/gateway_proxy.py`

**1.1 Replace broken relay with explicit receive loops**

Replace `frontend_to_openclaw()` and `openclaw_to_frontend()` functions that use `async for message in ws`. Use explicit `while True: msg = await ws.receive()` loops instead.

```python
# frontend_to_openclaw:
async def frontend_to_openclaw():
    try:
        while True:
            message = await ws.receive()
            if isinstance(message, str):
                msg = json.loads(message)
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

# openclaw_to_frontend:
async def openclaw_to_frontend():
    try:
        while True:
            message = await oc_ws.recv()
            msg = json.loads(message)
            if msg.get("type") == "event" and "sessionKey" not in msg.get("payload", {}):
                if msg.get("event") in ("chat", "agent"):
                    msg["payload"]["sessionKey"] = session_key
            await ws.send_json(msg)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error("[gateway-proxy] openclaw→frontend error: %s", e)
```

**1.2 Use `asyncio.gather(..., return_exceptions=True)`**

So when one relay fails, the other keeps running until the connection is fully torn down.

**1.3 Add keepalive ping to OpenClaw connection**

In `openclaw_to_frontend()`, add periodic ping:
```python
ping_task = asyncio.create_task(_ping_keepalive(oc_ws))
try:
    await asyncio.gather(openclaw_task, ping_task, return_exceptions=True)
finally:
    ping_task.cancel()
```

**1.4 Implement `chat.history` in backend proxy**

Add a JSON-RPC handler in the relay that translates `chat.history` to the appropriate OpenClaw call. If OpenClaw doesn't support `chat.history`, the proxy needs to track messages in-memory and return them on request.

Actually, looking at the code more carefully — the proxy is **transparent** (relays raw JSON-RPC). If OpenClaw supports `chat.history`, it'll work once the relay is fixed. If not, we need to implement message tracking in the proxy. Let me check if OpenClaw has a `chat.history` method...

The client calls `client.loadChatHistory()` which sends `chat.history` JSON-RPC. If OpenClaw gateway supports this, it'll work. If not, we need to add message tracking to the proxy.

**Decision:** For now, add basic message tracking to the proxy so `chat.history` works even if OpenClaw doesn't natively support it. Track all messages in a dict keyed by session_key.

```python
# Add to _handle_openclaw_ws:
message_store = {}  # session_key → [messages]

# In openclaw_to_frontend relay:
if msg.get("type") == "res" and msg.get("method") == "chat.send":
    # Store the response as chat history
    ...

# Handle chat.history requests in frontend_to_openclaw:
if msg.get("method") == "chat.history":
    history = message_store.get(session_key, [])
    await ws.send_json({
        "type": "res",
        "id": msg["id"],
        "ok": True,
        "payload": {"messages": history}
    })
    continue  # Don't forward to OpenClaw
```

### Phase 2: Fix Frontend — UI Polish

**2.1 Replace Sparkles icon with HarvisMascot in messages**

**File:** `front_end/newjfrontend/components/openclaw/ChatMessageList.tsx`

In `SingleMessage`, replace:
```tsx
<div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-1">
  <Sparkles className="h-4 w-4 text-primary" />
</div>
```
With:
```tsx
<div className="w-7 h-7 shrink-0 mt-1">
  <HarvisMascot state={isAssistant ? "idle" : "idle"} size={28} />
</div>
```

Also replace `Sparkles` in `StreamingMessage` avatar:
```tsx
<div className="w-7 h-7 shrink-0 mt-1">
  <HarvisMascot state="talking" size={28} />
</div>
```

**2.2 Replace empty state Sparkles with clickable HarvisMascot**

In the empty state (line ~273), replace the Sparkles icon with a large, clickable HarvisMascot:
```tsx
<div className="flex flex-col items-center justify-center h-full text-center py-20">
  <HarvisMascot size={100} interactive state="idle" />
  <h3 className="text-lg font-medium mt-4 mb-1">Start a conversation</h3>
  <p className="text-sm text-muted-foreground">
    Send a message to begin chatting with OpenClaw
  </p>
</div>
```

**2.3 Reposition input box to right, make smaller**

**File:** `front_end/newjfrontend/components/openclaw/OpenClawChatInput.tsx`

Change the layout from:
```tsx
<div className="flex items-end gap-2">
  <div className="flex-1 relative">
    <Textarea ... />
  </div>
  <Button ... />
</div>
```
To:
```tsx
<div className="flex justify-end">
  <div className="w-full max-w-lg">
    <div className="flex items-end gap-2">
      <Textarea ... placeholder="Ask Harvis..." />
      <Button ... />
    </div>
  </div>
</div>
```

Also make the textarea smaller:
- `min-h-[32px]` (was `min-h-[40px]`)
- Remove `max-h-[200px]` (or reduce to `max-h-[120px]`)
- Reduce padding inside textarea
- Make send button `h-8 w-8` (was `h-10 w-10`)

**2.4 Fix empty state showing through sidebar artifacts**

**File:** `front_end/newjfrontend/components/openclaw/ChatMessageList.tsx`

In the empty state, add a solid background so artifacts don't show through:
```tsx
<div className="flex flex-col items-center justify-center h-full text-center py-20 bg-background/80 backdrop-blur-sm">
```

### Phase 3: Fix Frontend — Connection Issues

**3.1 Increase client timeout for `chat.history`**

**File:** `front_end/newjfrontend/lib/openclaw/client.ts`

The client has a 60s timeout on all requests. For `chat.history`, this is fine if the relay works. But we should also handle the timeout gracefully in the UI:
- Show "No history available" instead of spinning forever
- Add error handling in `useOpenClawChat.loadHistory()`

```typescript
const loadHistory = useCallback(async () => {
  if (!client || !client.connected) return
  try {
    const result = await client.loadChatHistory()
    if (result.type === "res" && result.ok) {
      const messages = (result.payload as any)?.messages ?? []
      for (const msg of messages) {
        appendMessage(msg)
      }
    } else {
      console.warn("[OpenClawChat] History load returned error:", result)
    }
  } catch (e) {
    console.error("[OpenClawChat] Failed to load history:", e)
    // Don't spam console - just log once
  }
}, [client, appendMessage])
```

**3.2 Handle connection status in UI**

**File:** `front_end/newjfrontend/components/openclaw/ChatView.tsx`

The "Disconnected" badge shows when `isConnected` is false. The connection should auto-reconnect via the client's built-in reconnection logic. But we should:
- Add a reconnect button when disconnected
- Show connection retry progress

### Phase 4: Testing

**4.1 Verify connection stays open**
- Open the chat page
- Check backend logs — should see `Frontend connected` and `Connection closed` (on tab close), not rapid open/close cycles
- Send a message — should see it relayed to OpenClaw and response flowing back

**4.2 Verify mascot appears**
- Empty state should show large clickable HarvisMascot
- Assistant messages should show small HarvisMascot instead of Sparkles icon
- Click mascot → should trigger startle animation
- Click 4 times → should turn angry (red)

**4.3 Verify input box**
- Input should be right-aligned, smaller
- Placeholder text should say "Ask Harvis..."
- Send button should be visible and functional

**4.4 Verify chat history loads**
- After sending a message, history should load on reconnection
- No more 60s timeout errors

---

## Files to Modify

| File | Changes |
|------|---------|
| `python_back_end/openclaw/gateway_proxy.py` | Fix relay loops, add message tracking, add keepalive pings, handle chat.history |
| `front_end/newjfrontend/components/openclaw/ChatMessageList.tsx` | Replace Sparkles with HarvisMascot, fix empty state styling |
| `front_end/newjfrontend/components/openclaw/OpenClawChatInput.tsx` | Reposition input right, smaller size |
| `front_end/newjfrontend/lib/openclaw/client.ts` | Better timeout/error handling for history |
| `front_end/newjfrontend/components/openclaw/ChatView.tsx` | (optional) Add reconnect button |

## Build & Deploy

1. Verify Python compiles: `python3 -c "import py_compile; [py_compile.compile(f, doraise=True) for f in __import__('glob').glob('python_back_end/**/*.py')]"`
2. Build & deploy: `./ci_pipeline.sh -v`
3. Verify in browser
