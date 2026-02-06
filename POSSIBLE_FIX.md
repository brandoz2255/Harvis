# AI SDK Input Stream Error Analysis & Fix Guide

## Issue Description
User is encountering `AI SDK Error: TypeError: Error in input stream` when using the chat interface.

**Error Details:**
```
AI SDK Error: TypeError: Error in input stream 64279432e0f87088.js:10:45042
AI SDK Error details: 
Object { message: "Error in input stream", cause: undefined, name: "TypeError", stack: "" }
```

## Root Cause Analysis
This error typically means the AI‑SDK’s client‑side stream handler is receiving something that isn’t a valid readable stream (or the stream is being closed/errored early), often from a malformed or failed server response.

### Likely Causes
1. **API Route Returning Non-Stream:** The API route (e.g., `POST /api/chat`) might be returning a plain JSON error object (e.g., 500 or 401) instead of a ReadableStream. The client tries to pipe `response.body` into `AI.createStreamableValue` or `streamText`, but fails if the body is not a stream.
2. **Stream Interruption:** The server might be closing the connection early or sending invalid chunks.
3. **Invalid Response Format:** The server is sending non‑stream data (like a plain JSON object) instead of the expected NDJSON or AI‑SDK‑compatible chunks.
4. **Network/Proxy Issues:** Nginx or Docker networking might be buffering the response or returning a 502/504 error page (HTML) instead of the expected stream.

## Debugging Steps

### 1. Check the API Route Response
In the browser’s **Network tab**, inspect the `/api/chat` request:
- **Status Code:** Should be 200. If 4xx/5xx, that's the issue.
- **Content-Type:** Should be `text/plain` or `application/json` (depending on streaming mode), NOT `text/html`.
- **Response Body:** Check if it contains the stream data (lines starting with `0:`, `d:`, etc.) or if it's a JSON error message.

### 2. Log Response Before Streaming (Client-Side)
Modify `fetchWithRetry` or the place where `fetch` is called to log the response before it's passed to the AI SDK:

```typescript
const res = await fetch("...");
console.log("status:", res.status);
// WARNING: Reading the body here will consume the stream! Only do this for debugging non-200 responses.
if (!res.ok) {
  console.log("error body:", await res.text());
}
```

### 3. Verify Server-Side Stream Construction
Ensure the API route returns a proper `ReadableStream` and not `null`/`undefined`.
- If manually creating a stream: ensure `getReader()` is valid and `controller.enqueue` is getting `Uint8Array` data.
- If using `streamText`: ensure `toDataStreamResponse()` is called.

### 4. Check Client-Side Usage
Ensure `response.body` is being passed correctly to `AI.createStreamableValue` or similar. If `response.body` is null, you’ll get `TypeError: Error in input stream`.

## Proposed Fixes

### A. Handle Non-200 Responses in API Route
Modify `/api/ai-chat/route.ts` to ensuring it always returns *something* compatible, or better yet, verify that the frontend handles HTTP errors *before* starting the stream processing.

**Action:**
In `app/page.tsx` (or where `useChat` is used), ensure the `onError` handler is robust. 

### B. Add Try/Catch in Fetch
Add a try/catch block around the fetch and stream creation to catch setup errors early:

```typescript
try {
  const response = await fetch("/api/chat", { ... });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  // ... handle stream
} catch (err) {
  console.error("stream setup error:", err);
}
```

### C. Verify Nginx Configuration
If Nginx is in front (Docker Compose), ensure proxy buffering is disabled for the API route to preventing it from waiting for the full response before sending chunks.

```nginx
location /api/ {
    proxy_buffering off;
    proxy_cache off;
    # ...
}
```

## Implementation Plan
1. **Enhanced Logging (Completed):** We added detailed error logging to `useChat` `onError` in `page.tsx`.
2. **API Route Debugging (Completed):** We added logging to `safeEnqueue` in `/api/ai-chat` to see exactly what's being sent.
3. **Verify Deployment:** Rebuild and restart the container to see the new logs.
4. **Fix API Route:** If the logs show we are sending JSON errors instead of stream data, update the route to return a proper stream even for errors, or fix the client to handle JSON errors.
