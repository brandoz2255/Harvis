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

## Latest Research Findings (Updated)
- **Client Code is Updated:** The user logs show "AI SDK Error details:", which confirms the changes to `page.tsx` have been applied.
- **Error Persistence:** The `TypeError: Error in input stream` persists, which means the API route is **still** returning a non-stream response (likely JSON) or closing the connection early.
- **Docker Production Mode:** The `Dockerfile` builds a production app (`npm run build`). API routes in production builds are **compiled** and do not hot-reload from volume mounts like client components potentially might (depending on setup). 
- **Conclusion:** The `api/ai-chat/route.ts` changes (specifically the fix to return stream errors instead of JSON) likely have **not** been applied because the container wasn't fully rebuilt after that specific change.

## Action Plan
1. **Force Rebuild:** You must force a rebuild of the frontend container to compile the new API route code.
   ```bash
   docker compose build --no-cache harvis-frontend
   docker compose up -d --force-recreate harvis-frontend
   ```
2. **Verify API Route:** After rebuild, if the backend is down, the API route should now return a valid stream with an error chunk (`3:"..."`) instead of a 500 JSON response.
3. **Check Logs:** Watch the `harvis-frontend` logs. You should see `[AI-Chat] Enqueuing ...` logs if the new API route code is active.

## Debugging Checklist
- [ ] Run `docker compose build harvis-frontend`
- [ ] Restart container
- [ ] Check logs for `[AI-Chat] Call to backend...` (indicates route is running)


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
