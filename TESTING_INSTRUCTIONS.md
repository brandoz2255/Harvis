# Testing Instructions for Ghost Suggestions & Propose Fixes

## ✅ Changes Applied

### 1. **Fixed Ghost Suggestions** (MonacoCopilot.tsx)
- **Problem**: Monaco wasn't automatically triggering the provider
- **Fix**: Added manual `onDidChangeContent` listener that triggers inline suggestions after 600ms idle
- **Fix**: Changed to respond to BOTH Automatic AND Explicit triggers (was only Automatic)

### 2. **Enhanced Error Logging**
- Added comprehensive console logging throughout the flow:
  - `handleProposeDiff` in page.tsx
  - `proposeDiff` in ide-api.ts  
  - MonacoCopilot provider calls
- All logs use emoji prefixes for easy filtering:
  - 🚀 = Function entry
  - ✅ = Success
  - ❌ = Error
  - 📁 = Path/file info
  - 📝 = Selection info
  - 🌐 = API call
  - 🔍 = Detection/checking

---

## 🧪 Testing Steps

### Test 1: Ghost Suggestions Now Working

1. **Open the IDE** at http://localhost:9000/ide
2. **Create/Open a Python file** (e.g., `test.py`)
3. **Open browser DevTools** (F12) → Console tab
4. **Type this code**:
   ```python
   def calculate_sum(a, b):
   ```
5. **Pause for 1 second** (don't type anything)

**Expected Console Logs**:
```
✅ Editor mounted, MonacoCopilot should register now
MonacoCopilot: Registering provider for language: python
MonacoCopilot: Provider registered successfully
MonacoCopilot: Setting up content change listener for automatic suggestions
MonacoCopilot: Setup complete - suggestions will appear as you type and pause
MonacoCopilot: Content changed, triggering inline suggestion after idle
MonacoCopilot: provideInlineCompletions called {triggerKind: 1, position: "1:28", enabled: true}
MonacoCopilot: Trigger received {kind: "Explicit"}
MonacoCopilot: Calling API for suggestion...
MonacoCopilot: API response {hasSuggestion: true, suggestionLength: XX, suggestionPreview: "return a + b"}
```

**Expected Behavior**:
- Ghost text should appear: `return a + b` (faded/gray)
- Press **Tab** → Accepts suggestion
- Press **Esc** → Dismisses suggestion

**If NO ghost text appears**:
- Check console for errors
- Check Network tab → Filter "suggest" → Should see POST to `/api/ide/copilot/suggest`
- Check backend logs: `docker logs backend --tail 50`

---

### Test 2: Manual Trigger Works

1. **Type some code**
2. **Press Alt+]** (or Opt+] on Mac)

**Expected Console Logs**:
```
MonacoCopilot: Manual trigger via Alt+]
MonacoCopilot: provideInlineCompletions called
```

**Expected Behavior**:
- Suggestion appears immediately
- No need to wait for idle timeout

---

### Test 3: Propose Diff With Full Logging

1. **Open a file** in the IDE
2. **Press Ctrl+Shift+I** (or Cmd+Shift+I on Mac) - Quick Propose shortcut
3. **OR** Right-click → "AI → Propose changes..."
4. **Enter instructions**: "Add docstring and type hints"
5. **Watch the console**

**Expected Console Logs (Step-by-step)**:
```
🚀 handleProposeDiff called {filepath: "test.py", instructions: "Add docstring...", hasSession: true}
📁 Normalized path: test.py
✅ Found active tab: test.py
🌐 Calling IDEChatAPI.proposeDiff... {sessionId: "...", filepath: "test.py", ...}
[IDEChatAPI] proposeDiff called {...}
[IDEChatAPI] Request body: {"session_id":"...","filepath":"test.py",...}
[IDEChatAPI] Request headers: {Content-Type: "application/json", Authorization: "Bearer ..."}
[IDEChatAPI] Response status: 200 OK
[IDEChatAPI] Response received: {hasDraft: true, hasDiff: false, stats: {...}}
✅ Propose diff response received: {hasDraft: true, hasDiff: false, stats: {...}}
✅ Diff view shown
```

**Expected Behavior**:
- Diff viewer opens showing side-by-side comparison
- Left = original code, Right = AI-modified code
- Toolbar shows "Accept" / "Reject" / "Merge" buttons
- Stats pill shows `+X −Y` lines changed

**If propose does NOTHING**:
- Check where the console logs STOP
- Most likely issues:
  1. **❌ No current session** → Need to create/open a session first
  2. **❌ Active tab not found** → File might not be open in editor
  3. **[IDEChatAPI] Request failed:** → Check error message
  4. **401 Unauthorized** → Auth token missing/expired
  5. **404 Not Found** → Backend endpoint not registered
  6. **500 Internal Server Error** → Check backend logs

---

### Test 4: Check Backend Logs

```bash
# Watch backend logs in real-time
docker logs -f backend

# Or check last 100 lines
docker logs backend --tail 100
```

**Expected Backend Logs for Suggest**:
```
INFO: POST /api/ide/copilot/suggest
DEBUG: Received copilot suggestion request for test.py
DEBUG: Calling Ollama with prompt...
DEBUG: Ollama response: "return a + b"
INFO: Returning suggestion (length: 15)
```

**Expected Backend Logs for Propose**:
```
INFO: POST /api/ide/diff/propose
DEBUG: Proposing changes for test.py
DEBUG: Base content: 50 lines
DEBUG: Instructions: Add docstring and type hints
DEBUG: Calling Ollama chat API...
DEBUG: Generated draft content: 65 lines
INFO: Returning diff proposal with stats: {lines_added: 20, lines_removed: 5}
```

**If backend shows NO logs**:
- Requests aren't reaching the backend
- Check nginx logs: `docker logs nginx --tail 50`
- Check if `/api/ide/*` routes are proxied correctly

---

### Test 5: Network Tab Verification

1. **Open DevTools** (F12) → Network tab
2. **Filter by "ide"** or "copilot" or "suggest"
3. **Type code and pause**

**Expected Requests**:

#### For Ghost Suggestions:
```
POST /api/ide/copilot/suggest
Status: 200
Request Payload:
{
  "session_id": "abc123",
  "filepath": "test.py",
  "language": "python",
  "content": "def calculate_sum(a, b):\n",
  "cursor_offset": 27,
  "model": "gpt-oss"
}

Response:
{
  "suggestion": "return a + b",
  "range": {"start": 27, "end": 27}
}
```

#### For Propose:
```
POST /api/ide/diff/propose
Status: 200
Request Payload:
{
  "session_id": "abc123",
  "filepath": "test.py",
  "base_content": "...",
  "instructions": "Add docstring",
  "mode": "draft"
}

Response:
{
  "draft_content": "...",
  "diff": null,
  "stats": {"lines_added": 10, "lines_removed": 2, "hunks": 1},
  "base_etag": "abc123..."
}
```

---

## 🐛 Common Issues & Solutions

### Issue 1: "❌ No current session"
**Solution**: Create a session first:
1. Click "New Session" in top-left
2. Wait for container to start (status: running)
3. Then try again

### Issue 2: "❌ Active tab not found"
**Solution**: Make sure file is actually open:
1. File must be visible in the editor
2. Should appear in editor tabs at top
3. Path must match exactly

### Issue 3: "401 Unauthorized" in Network tab
**Solution**: Auth token issue:
1. Check if logged in (top-right should show username)
2. Check localStorage: `localStorage.getItem('access_token')`
3. Re-login if token expired

### Issue 4: No ghost text appears but API works
**Solution**: Monaco rendering issue:
1. Check "Suggestions ON" toggle in AI Assistant panel
2. Try pressing Alt+] to manually trigger
3. Check Monaco version: `window.monaco?.editor.VERSION`
4. Should be >= 0.31.0 for InlineCompletionsProvider support

### Issue 5: Backend returns 503 "AI service unavailable"
**Solution**: Ollama issue:
1. Check if Ollama is running: `docker ps | grep ollama`
2. Check if model exists: `docker exec ollama ollama list`
3. Should see `gpt-oss` in the list
4. If not: `docker exec ollama ollama pull gpt-oss`

### Issue 6: Suggestions are slow (> 5 seconds)
**Solution**: Model is too large:
1. Check current model in AI Assistant panel
2. Switch to faster model: `deepseek-coder:6.7b` or `codellama:7b`
3. Or reduce `num_predict` in backend `COMPLETION_PARAMS`

---

## 📊 Success Criteria

✅ **Ghost Suggestions Working**:
- [ ] Console shows "MonacoCopilot: Provider registered successfully"
- [ ] Console shows "MonacoCopilot: Content changed, triggering inline suggestion after idle"
- [ ] Console shows "MonacoCopilot: API response"
- [ ] Network tab shows POST to `/api/ide/copilot/suggest`
- [ ] Ghost text appears in editor (faded/gray)
- [ ] Tab accepts suggestion
- [ ] Esc dismisses suggestion

✅ **Propose Working**:
- [ ] Console shows "🚀 handleProposeDiff called"
- [ ] Console shows "[IDEChatAPI] proposeDiff called"
- [ ] Console shows "✅ Diff view shown"
- [ ] Network tab shows POST to `/api/ide/diff/propose`
- [ ] Diff viewer opens with side-by-side comparison
- [ ] Can accept/reject changes

---

## 🔍 Debugging Checklist

If things still don't work, go through this checklist:

1. **Services running**:
   - [ ] `docker ps` shows backend, nginx, ollama all running
   - [ ] No container restarts/crashes

2. **Frontend loaded**:
   - [ ] Browser shows IDE page (not 404 or error)
   - [ ] No console errors on page load
   - [ ] Monaco editor visible and functional

3. **Session active**:
   - [ ] Session created and status = "running"
   - [ ] File open in editor
   - [ ] Editor tabs visible

4. **MonacoCopilot mounted**:
   - [ ] Console shows "MonacoCopilot: Provider registered"
   - [ ] Console shows "MonacoCopilot: Setup complete"

5. **Auth working**:
   - [ ] Logged in (username visible)
   - [ ] `localStorage.getItem('access_token')` returns token
   - [ ] Network requests include Authorization header

6. **Backend reachable**:
   - [ ] Can access http://localhost:9000/api/ide/providers
   - [ ] Returns list of available models
   - [ ] No CORS or network errors

7. **Ollama working**:
   - [ ] `docker exec ollama ollama list` shows models
   - [ ] `gpt-oss` or similar model available
   - [ ] Backend can reach ollama:11434

---

## 📝 What Changed

### Files Modified:
1. **`app/ide/components/MonacoCopilot.tsx`**:
   - Added `onDidChangeContent` listener to manually trigger suggestions
   - Changed to respond to both Automatic AND Explicit triggers
   - Added proper cleanup for content change listener

2. **`app/ide/page.tsx`**:
   - Added comprehensive logging to `handleProposeDiff`
   - Added error alerts for visibility

3. **`app/ide/lib/ide-api.ts`**:
   - Added detailed logging to `proposeDiff` API call
   - Logs request body, headers, response status

### How It Works Now:
1. **User types** → `onDidChangeContent` fires
2. **Debounce 600ms** → Wait for idle
3. **Call `editor.action.inlineSuggest.trigger()`** → Monaco triggers provider with `Explicit`
4. **Provider responds** → Fetches from `/api/ide/copilot/suggest`
5. **Ghost text appears** → Monaco renders as inline suggestion
6. **Tab/Esc** → Accept or dismiss

---

## 🎯 Next Steps

Once you verify:
1. Ghost suggestions appear automatically as you type
2. Propose diff opens the comparison viewer
3. Can accept/reject changes

Then we're good! If either still doesn't work, check the console logs and let me know exactly where it stops.

The extensive logging will tell us exactly what's happening (or not happening).




