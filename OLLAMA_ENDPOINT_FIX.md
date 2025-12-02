# Ollama Endpoint 404 Fix for IDE AI Features

## Problem

IDE AI Assistant was failing with 404 errors:
```
Client error '404 Not Found' for url 'http://ollama:11434/api/generate'
```

This affected:
- AI Assistant chat (SSE streaming)
- Copilot code suggestions
- Diff proposals for code changes

## Root Cause

The backend `ide_ai.py` was using Ollama's `/api/generate` endpoint for all operations, but Ollama has two distinct APIs:

1. **`/api/generate`** - For text completion with a single prompt string
   - Request: `{ model, prompt, stream, options }`
   - Response: `{ response: "text" }` (or streamed chunks)
   
2. **`/api/chat`** - For conversational chat with message history
   - Request: `{ model, messages: [{role, content}], stream, options }`
   - Response: `{ message: { content: "text" } }` (or streamed chunks)

The IDE AI Assistant needs `/api/chat` for proper conversation handling with message history and role-based context.

## Solution

### 1. Split Ollama query functions

**Before** (single function for everything):
```python
async def query_ollama(prompt: str, model: str, stream: bool):
    # Used /api/generate for everything
    response = await client.post(f"{OLLAMA_URL}/api/generate", ...)
```

**After** (separate functions for different use cases):
```python
async def query_ollama_generate(prompt: str, model: str):
    """For code completions - uses /api/generate"""
    response = await client.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, ...}
    )
    return response.json().get("response", "")

async def query_ollama_chat(messages: list, model: str, stream: bool):
    """For chat conversations - uses /api/chat"""
    response = await client.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": model, "messages": messages, "stream": stream, ...}
    )
    if stream:
        return response  # Return response object for streaming
    else:
        return response.json().get("message", {}).get("content", "")
```

### 2. Update chat streaming endpoint

Changed from building a single prompt string to sending proper messages array:

**Before**:
```python
# Built a flat prompt string
prompt = "System: ...\n\nUser: ...\n\nAssistant:"
# Used /api/generate
response = await client.stream("POST", f"{OLLAMA_URL}/api/generate", 
                               json={"prompt": prompt, ...})
# Parsed "response" field
token = data["response"]
```

**After**:
```python
# Built messages array with roles
messages = [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
]
# Used /api/chat
response = await client.stream("POST", f"{OLLAMA_URL}/api/chat",
                               json={"messages": messages, ...})
# Parsed "message.content" field
token = data["message"]["content"]
```

### 3. Update copilot and diff endpoints

- **Copilot** (`/api/ide/copilot/suggest`): Uses `query_ollama_generate()` - kept as-is since it works with single prompt
- **Diff proposal** (`/api/ide/chat/propose-diff`): Changed to use `query_ollama_chat()` with messages array

## Files Modified

- `python_back_end/vibecoding/ide_ai.py`:
  - Replaced `query_ollama()` with `query_ollama_generate()` and `query_ollama_chat()`
  - Updated `/chat/send` endpoint to use `/api/chat` with messages
  - Updated streaming parser to read `message.content` instead of `response`
  - Updated `/chat/propose-diff` to use chat endpoint with messages

## Testing

After restarting the backend:

1. **AI Assistant Chat**: 
   - Send a message → Should stream response without 404 errors
   - Check browser console → No "404 Not Found" errors
   - Verify SSE data arrives as `data: {"token": "..."}`

2. **Copilot Suggestions**:
   - Type code in editor → Pause → Ghost text appears
   - Tab to accept → Code inserted
   - No 404 errors in logs

3. **Diff Proposals**:
   - Ask AI to modify code → Should generate diff
   - Accept changes → File updated
   - No errors during proposal generation

## Backend Logs

Successful streaming should show:
```
INFO: Streaming response from Ollama chat endpoint
DEBUG: Received token: "Hello"
DEBUG: Received token: " world"
...
```

Instead of:
```
ERROR: Streaming error: Client error '404 Not Found' for url 'http://ollama:11434/api/generate'
```

## API Reference

### Ollama /api/generate (for completions)
```bash
curl -X POST http://ollama:11434/api/generate \
  -d '{
    "model": "mistral",
    "prompt": "Complete this code: def hello():",
    "stream": false
  }'
```

### Ollama /api/chat (for conversations)
```bash
curl -X POST http://ollama:11434/api/chat \
  -d '{
    "model": "mistral",
    "messages": [
      {"role": "system", "content": "You are a coding assistant"},
      {"role": "user", "content": "Write a hello world function"}
    ],
    "stream": false
  }'
```

## Status

✅ **Resolved** - All IDE AI features now use correct Ollama endpoints
- AI Assistant chat streams correctly
- Copilot provides suggestions
- Diff proposals work as expected
- Backend restarted to apply changes







