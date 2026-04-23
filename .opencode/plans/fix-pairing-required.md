# Fix: OpenClaw pairing required

## Root Cause

OpenClaw's connect validation in `message-handler.ts` has this logic:

```typescript
skipPairingForOperatorSharedAuth = role === "operator" && sharedAuthOk && !isControlUi && !isWebchat
```

Our client sends `mode: "webchat"`, so `isWebchat = true`, making `skipPairingForOperatorSharedAuth = false`. This means pairing is always required for our connection.

## Fix

**File:** `python_back_end/openclaw/gateway_proxy.py`

Change `_CLIENT_MODE` from `"webchat"` to `"backend"`:

```python
_CLIENT_MODE = "backend"  # was "webchat"
```

This makes `isWebchat = false`, so `skipPairingForOperatorSharedAuth = true` (since role is "operator" and shared auth is OK), which skips the pairing requirement.

## Build & Deploy

1. Verify: `python3 -m py_compile python_back_end/openclaw/gateway_proxy.py`
2. Build & deploy: `./ci_pipeline.sh -y -p -f v2.34.79s -b v2.34.79s -m "fix: use backend mode to skip device pairing for operator auth"`
3. Test: send a message through the chat UI
