# Ollama Compatibility Layer - Smoke Tests

## Overview

The IDE AI Assistant now includes an automatic compatibility layer that detects Ollama version at runtime and uses the appropriate API endpoint:
- **Newer Ollama (v0.1.0+)**: Uses `/api/chat` with messages array
- **Older Ollama (pre-v0.1.0)**: Uses `/api/generate` with prompt string

## Prerequisites

### 1. Check Ollama is Running

```bash
docker ps | grep ollama
```

Expected output: Container named `ollama` should be running.

### 2. Check Ollama Version

```bash
docker exec ollama ollama --version
```

Or check via API:

```bash
curl http://localhost:11434/api/version
```

## Smoke Tests

### Test 1: Check Ollama Connectivity

```bash
curl -s http://localhost:11434/api/tags
```

**Expected Result**: JSON response with list of available models

**Sample Output**:
```json
{
  "models": [
    {
      "name": "mistral:latest",
      "modified_at": "2024-01-15T10:30:00Z",
      "size": 4109865159
    }
  ]
}
```

**If this fails**: Ollama container is not running or not accessible.

---

### Test 2: Check if /api/chat Endpoint Exists

```bash
curl -X POST http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "messages": [{"role": "user", "content": "Hi"}],
    "stream": false
  }'
```

**Expected Results**:

**If Newer Ollama** (v0.1.0+):
```json
{
  "model": "mistral",
  "message": {
    "role": "assistant",
    "content": "Hello! How can I help you today?"
  },
  "done": true
}
```

**If Older Ollama** (pre-v0.1.0):
```json
{"error": "Not Found"}
```
Or HTTP 404 status code.

---

### Test 3: Check /api/generate Endpoint (Fallback)

```bash
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "prompt": "User: Hi\n\nAssistant:",
    "stream": false
  }'
```

**Expected Result**: Works on both old and new Ollama versions
```json
{
  "model": "mistral",
  "response": "Hello! How can I help you today?",
  "done": true
}
```

---

### Test 4: Check Model Availability

```bash
curl -X POST http://localhost:11434/api/show \
  -H "Content-Type: application/json" \
  -d '{"name": "mistral"}'
```

**Expected Result**: Model details
```json
{
  "modelfile": "...",
  "parameters": "...",
  "template": "..."
}
```

**If this fails**: Model not pulled. Run:
```bash
docker exec ollama ollama pull mistral
```

---

### Test 5: Test IDE AI Assistant Backend (Direct)

**Login first** to get auth cookie:
```bash
curl -X POST http://localhost:9000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "yourpassword"}' \
  -c cookies.txt
```

**Test streaming chat**:
```bash
curl -X POST http://localhost:9000/api/ide/chat/send \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "session_id": "test-session-id",
    "message": "Write a hello world function in Python",
    "history": [],
    "model": "mistral"
  }'
```

**Expected Result**: SSE stream of tokens
```
data: {"token": "def"}

data: {"token": " hello"}

data: {"token": "_world"}

data: {"token": "():"}

...

data: {"done": true}
```

**If this fails**: Check backend logs:
```bash
docker logs backend | grep -i "ollama\|ide"
```

---

### Test 6: Test Copilot Suggestions

```bash
curl -X POST http://localhost:9000/api/ide/copilot/suggest \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "session_id": "test-session-id",
    "filepath": "test.py",
    "language": "python",
    "content": "def hello():\n    ",
    "cursor_offset": 17
  }'
```

**Expected Result**: Code suggestion
```json
{
  "suggestion": "print(\"Hello, World!\")",
  "range": {"start": 17, "end": 17}
}
```

---

## Troubleshooting

### Issue: "Model not found"

**Solution**: Pull the model
```bash
docker exec ollama ollama pull mistral
```

**Verify**:
```bash
docker exec ollama ollama list
```

---

### Issue: "Ollama connection refused"

**Check Ollama is running**:
```bash
docker ps | grep ollama
docker logs ollama | tail -20
```

**Restart Ollama if needed**:
```bash
docker restart ollama
```

**Check from backend container**:
```bash
docker exec backend curl http://ollama:11434/api/tags
```

---

### Issue: "404 Not Found" on both /api/chat and /api/generate

**This means Ollama is not running or the URL is wrong.**

1. Check `OLLAMA_URL` environment variable in backend:
```bash
docker exec backend env | grep OLLAMA
```

Should be: `OLLAMA_URL=http://ollama:11434`

2. Test connectivity from backend:
```bash
docker exec backend curl -v http://ollama:11434/api/tags
```

---

### Issue: Backend logs show "Ollama /api/chat detection: False"

**This is expected for older Ollama versions.** The compatibility layer will automatically use `/api/generate` instead.

Check backend logs:
```bash
docker logs backend | grep "Ollama /api/chat detection"
```

You should see:
- `Ollama /api/chat detection: True` (newer Ollama)
- `Ollama /api/chat detection: False` (older Ollama, will use /api/generate)

---

### Issue: SSE stream returns "error" event

**Check the error message**:
```bash
docker logs backend | grep "Streaming error"
```

Common causes:
- Model not available → Pull the model
- Ollama overloaded → Restart Ollama container
- Network issues → Check Docker network

---

## Expected Behavior Summary

| Ollama Version | /api/chat Works? | Endpoint Used | Conversion Required? |
|----------------|------------------|---------------|---------------------|
| v0.1.0+        | ✅ Yes           | `/api/chat`   | No (native)         |
| Pre-v0.1.0     | ❌ No (404)      | `/api/generate` | Yes (messages→prompt) |

**The compatibility layer handles this automatically!**

---

## Testing Frontend

### Browser Console Test

1. Open http://localhost:9000/ide
2. Open Developer Tools → Console
3. Paste:

```javascript
// Test chat streaming
fetch('/api/ide/chat/send', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  credentials: 'include',
  body: JSON.stringify({
    session_id: 'test',
    message: 'Say hello in Python',
    history: [],
    model: 'mistral'
  })
}).then(async res => {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    console.log(decoder.decode(value));
  }
});
```

**Expected**: Console logs SSE chunks: `data: {"token": "..."}`

---

### UI Test

1. Navigate to http://localhost:9000/ide
2. Click **AI Assistant** tab (right panel)
3. Type: "Write a hello world function in Python"
4. Press Send

**Expected**: 
- Message appears in chat
- Response streams token-by-token
- No 404 errors in browser console
- No "Authorization missing" errors

---

## Health Check Endpoint (Future Enhancement)

Consider adding:

```bash
curl http://localhost:9000/api/ide/health
```

Should return:
```json
{
  "ollama": {
    "url": "http://ollama:11434",
    "available": true,
    "api_version": "chat" | "generate",
    "models": ["mistral", ...]
  }
}
```

---

## Success Criteria

✅ All tests pass  
✅ Chat streams without 404 errors  
✅ Copilot suggestions work  
✅ Backend logs show Ollama detection  
✅ Frontend receives SSE tokens  
✅ No authorization errors (cookies working)  

---

## Quick Reference: Common Commands

```bash
# Check Ollama models
docker exec ollama ollama list

# Pull a model
docker exec ollama ollama pull mistral

# Check backend logs
docker logs backend -f | grep -i ollama

# Restart backend
docker restart backend

# Restart Ollama
docker restart ollama

# Test from backend container
docker exec backend curl http://ollama:11434/api/tags
```







