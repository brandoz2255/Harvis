# Streaming & Timeout Fixes

**Date**: January 25, 2026  
**Author**: AI Assistant  

## Overview

This document describes fixes implemented to resolve Nginx 499 timeouts and SSE streaming errors affecting voice chat, research mode, and text-to-speech generation.

---

## Problems Fixed

### 1. Nginx 499 Timeouts

**Symptom**: Random `NetworkError` and HTTP status 499 during voice/text chat, especially when TTS generation took 10-15+ seconds.

**Root Cause**: Global Nginx timeouts were set to 60 seconds, but TTS + Ollama inference could exceed this.

**Solution**: Updated `nginx.conf` with extended timeouts:

```nginx
# Global proxy timeout settings - increased for TTS/Whisper processing
proxy_connect_timeout 3600s;  # 1 hour
proxy_send_timeout 3600s;
proxy_read_timeout 3600s;
send_timeout 3600s;
client_body_timeout 3600s;

# Keep-alive settings to prevent connection drops
keepalive_timeout 3600s;
keepalive_requests 1000;
```

---

### 2. Research Mode Streaming Error

**Symptom**: `TypeError: Error in input stream` when using research mode toggle.

**Root Cause**: Backend `/api/research-chat` was converted to return SSE (Server-Sent Events) to keep the connection alive during web searches, but the frontend hook tried to parse as regular JSON.

**Solution**:

**Backend** (`python_back_end/main.py`):
- Converted `/api/research-chat` to return `StreamingResponse` with SSE events
- Added header `X-Accel-Buffering: no` for Nginx compatibility
- Events: `starting` → `searching` → `researching` → `processing` → `complete`

**Frontend** (`hooks/useApiWithRetry.ts`):
- Auto-detects `text/event-stream` content-type
- Parses SSE events and extracts final `complete` payload
- Logs stream status to console for debugging

---

### 3. Duplicate SSE Handling & Client Timeout

**Symptom**: Connection drops and conflicts even with Nginx timeouts increased.

**Root Cause**:
1. **Duplicate Parsers**: `app/page.tsx` had manual SSE parsing logic that conflicted with the built-in parser in `useApiWithRetry.ts`.
2. **Client Timeout Mismatch**: Frontend default timeout was 5 minutes (300s), while Nginx was set to 1 hour (3600s). Combined operations (Research + TTS) could exceed 5 minutes.

**Solution**:
- **Unified Logic**: Removed manual parsing from `app/page.tsx`. Now `useApiWithRetry` handles ALL requests (JSON & SSE) uniformly.
- **Synced Timeouts**: Increased frontend default timeout to **3600s (1 hour)** to match Nginx settings.

---

### 4. Voice Chat (mic-chat) Timeouts

**Symptom**: Browser killed connection during TTS audio sampling (~3-6 seconds).

**Solution**: Converted `/api/mic-chat` to streaming SSE with progress events:

| Event Status | Description |
|--------------|-------------|
| `transcribing` | Whisper speech-to-text in progress |
| `chat` | LLM inference in progress |
| `generating_speech` | TTS model generating audio |
| `speaking` | Audio file being written |
| `complete` | Final result with audio path |

---

## Files Changed

| File | Change |
|------|--------|
| `python_back_end/main.py` | Streaming SSE for `/api/mic-chat` and `/api/research-chat` |
| `front_end/.../hooks/useApiWithRetry.ts` | Auto-detect SSE and parse stream transparently |
| `front_end/.../components/chat-input.tsx` | SSE handling for voice input |
| `front_end/.../app/page.tsx` | Research mode SSE handling |
| `nginx.conf` | 1-hour timeouts, keepalive settings |

---

## Deployment Notes

After making these changes, restart Nginx to apply timeout settings:

```bash
docker restart nginx-proxy
```

---

## Testing Checklist

- [x] **Research mode**: Toggle search and ask complex questions with web search
- [x] **Voice input**: Speak and wait for TTS response  
- [x] **Text chat**: Send messages and wait for audio responses
- [x] **Long responses**: Request detailed explanations (tests timeout fixes)
- [x] **Console logs**: Verify `Stream status: ...` messages appear

---

## Related Issues

- Prevents Nginx 499 "client closed request" errors
- Prevents `NetworkError when attempting to fetch resource`
- Prevents `TypeError: Error in input stream` in research mode
