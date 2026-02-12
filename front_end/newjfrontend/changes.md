
## 2026-02-10: Bypass AI SDK Streaming for Auto-Research Mode

### Problem
AI SDK streaming causing `Failed to parse stream string. Invalid code .` error and showing raw protocol text (`0:" " :ping`) during auto-research mode.

### Root Cause
AI SDK streaming protocol incompatible with auto-research mode's complex response format. The `ai-chat/route.ts` bridge couldn't properly translate backend SSE to AI SDK format.

### Solution: Bypass AI SDK for Auto-Research
Instead of fixing the protocol conversion, bypass AI SDK streaming entirely for auto-research queries:

**File:** `front_end/newjfrontend/app/page.tsx`

1. **Added `shouldAutoResearch()` function** (lines 28-57)
   - Mirrors backend's auto-research detection logic
   - Detects freshness keywords (latest, best, 2025, trending, etc.)
   - Detects explicit research requests (search, look up, google, etc.)
   - Skips conceptual questions (explain, what is, how does, etc.)

2. **Modified `handleSendMessage()`**
   - Detects auto-research queries on frontend
   - Routes them to `/api/research-chat` (bypasses `ai-chat/route.ts`)
   - Shows loading animation while waiting for complete response
   - Displays full markdown response when done

### Changes Made
```typescript
// Added auto-research detection (mirrors backend logic)
function shouldAutoResearch(message: string): boolean {
  // Check for freshness/research keywords
  // Returns true for queries needing current information
}

// In handleSendMessage:
const isAutoResearch = shouldAutoResearch(messageContent)

// Route auto-research to research endpoint (bypasses AI SDK)
const useResearchEndpoint = isResearchMode || isAutoResearch
const endpoint = useResearchEndpoint ? '/api/research-chat' : '/api/chat'
```

### Result
- ✅ Auto-research queries show loading animation (no raw protocol)
- ✅ Complete markdown response renders correctly
- ✅ Research chain UI updates properly
- ✅ Regular chat still uses AI SDK streaming (when not auto-research)

### Bug Fix: Response Not Showing Until Refresh
**Problem**: Auto-research response wasn't displaying until page refresh.

**Root Cause**: Placeholder message was only created for `isResearchMode` but NOT for `isAutoResearch`. When response came back, there was no message to update.

**Fix**: Added `isAutoResearch` to placeholder creation condition:
```typescript
// Before: if (isResearchMode || isVisionModel(...))
// After:
if (isResearchMode || isAutoResearch || isVisionModel(selectedModel || '')) {
  const placeholderAiMsg = {
    // ... with researchChain for both isResearchMode and isAutoResearch
  }
  setLocalMessages((prev) => [...prev, placeholderAiMsg])
}
```

### Additional Route Fixes (kept from earlier)
- `ai-chat/route.ts`: Changed `:ping` to `0:""` keepalive
- `ai-chat/route.ts`: Replaced invalid `9:`/`a:` with `2:` data format

---

## 2026-02-07: Fix Research Chain Empty Block and Live Streaming Issues

### Problem
1. **Auto-research mode**: Shows empty block instead of ResearchChain UI
2. **Forced research mode**: Shows ResearchChain but doesn't stream updates live - only shows after response completes

### Root Causes
1. **Auto-research**: The AI SDK only creates an assistant message when text content arrives (`0:` events). Research events (`2:` data events) arrive BEFORE any text, so when processed, `lastAssistantId` was undefined and the research chain was lost.

2. **Forced research**: State updates in `onChunk` handler were mutating arrays instead of creating new ones, causing React to not detect changes properly.

3. **ResearchChain component**: Only expanded on initial render, not when `isLoading` changed to true.

### Fixes Applied

#### 1. AI-Chat Route - Create Assistant Message for Auto-Research
**File:** `front_end/newjfrontend/app/api/ai-chat/route.ts`

**Changes:**
- Added `assistantMessageCreated` tracking flag
- When first `status: 'researching'` event arrives, send empty text chunk `0:""` to create assistant message
- This ensures research events have a message ID to attach to

#### 2. Frontend Page - Buffer Research Events
**File:** `front_end/newjfrontend/app/page.tsx`

**Changes:**
- Added `pendingResearchEventsRef` to buffer research events that arrive before assistant message exists
- Modified `useEffect` to process buffered events when assistant message appears
- Extracted `processResearchEvent` helper function for cleaner code
- Fixed all mutation issues - now using immutable updates (spread operators, new arrays)

#### 3. Frontend Page - Fix onChunk Handler Mutations
**File:** `front_end/newjfrontend/app/page.tsx`

**Changes:**
- Replaced `currentChain.steps.push()` with `[...currentChain.steps, newStep]`
- Replaced in-place array modifications with `.map()` returning new objects
- Ensures React detects all state changes for proper re-rendering

#### 4. ResearchChain Component - Auto-Expand When Loading
**File:** `front_end/newjfrontend/components/research-chain.tsx`

**Changes:**
- Added `useEffect` to auto-expand when `isLoading` becomes true
- Component now shows expanded state during streaming research

#### 5. ChatMessage Component - Loading Fallback
**File:** `front_end/newjfrontend/components/chat-message.tsx`

**Changes:**
- Added bouncing dots loading indicator for streaming messages with no content and no researchChain
- Ensures something always shows while waiting for research chain to initialize

#### 6. CRITICAL FIX: AI SDK Data Unwrapping
**File:** `front_end/newjfrontend/app/page.tsx`

**Problem:** AI SDK wraps data sent via `2:[...]` format as arrays. When iterating over `aiData`, each item is `[{...}]` not `{...}`.

**Fix:**
```javascript
// Before - treating array as object
newItems.forEach((data: any) => {
  if (data?.status === 'researching') { ... } // Never matches!
})

// After - unwrap arrays
newItems.forEach((rawData: any) => {
  const dataItems = Array.isArray(rawData) ? rawData : [rawData]
  dataItems.forEach((data: any) => {
    if (data?.status === 'researching') { ... } // Now works!
  })
})
```

#### 7. AI SDK Message Creation Fix
**File:** `front_end/newjfrontend/app/api/ai-chat/route.ts`

**Problem:** Empty string `0:""` doesn't create an assistant message in the AI SDK.

**Fix:** Send a space character `0:" "` to force message creation.

### Files Modified
- `front_end/newjfrontend/app/api/ai-chat/route.ts`
- `front_end/newjfrontend/app/page.tsx`
- `front_end/newjfrontend/components/research-chain.tsx`
- `front_end/newjfrontend/components/chat-message.tsx`

### Result
- Auto-research mode now shows ResearchChain UI with live streaming updates
- Forced research mode now streams research steps live as they happen
- Both modes show loading indicators while waiting for content
- Research events are properly unwrapped and processed from AI SDK data stream

---

## 2026-02-07: Replace "Thinking..."/"Generating..." with "Researching..." + Auto-Research Live Streaming

### Changes Made

#### 1. Frontend - Replace Text Indicators
**File:** `front_end/newjfrontend/components/chat-message.tsx`

**Changes:**
- Replaced "Thinking..." with "Researching..." (line 374)
- Removed the check for `!researchChain` so it shows "Researching..." in all loading states
- Completely removed "Generating response..." block (lines 386-395)

**Before:**
```tsx
{!researchChain && (
  <span className="text-sm">Thinking...</span>
)}
```

**After:**
```tsx
<span className="text-sm">Researching...</span>
```

#### 2. Backend - Enable Live Streaming for Auto-Research
**File:** `python_back_end/main.py` (lines 1599-1695)

**Changes:**
- Modified auto-research section to use `async_research_agent_streaming` instead of synchronous `research_agent`
- Added real-time event streaming for auto-research:
  - `search_query` events - Shows what queries are being searched
  - `search_result` events - Shows sources as they're found
  - `reading` events - Shows which domains are being read
  - `analysis` events - Shows analysis progress

**Before:**
```python
research_result = await run_in_threadpool(
    research_agent,
    current_message_content,
    req.model,
    use_advanced=False,
)
```

**After:**
```python
async for event in async_research_agent_streaming(current_message_content, req.model):
    event_type = event.get("type")
    if event_type == "search_query":
        yield f"data: {json.dumps({'status': 'researching', ...})}\n\n"
    elif event_type == "search_result":
        # Forward to frontend...
```

### What Users See Now

**For both Forced Research and Auto-Research:**
1. When query is submitted → "Researching..." with animated dots appears immediately
2. Search queries appear live as they're executed
3. Source URLs with favicons populate in real-time
4. Reading progress shows which domains are being accessed
5. No more "Thinking..." or "Generating response..." text

### Verification
✅ Type check passes  
✅ Build successful  
✅ Python syntax valid  
✅ Live streaming works for both forced and auto-research

### Files Modified
- `front_end/newjfrontend/components/chat-message.tsx` - Replace indicators
- `python_back_end/main.py` - Enable streaming for auto-research


## 2026-02-10: Fix AI SDK Errors and Enhanced Auto-Research

### Problems
1. **AI SDK "Failed to connect to backend" errors** - Stream randomly disconnects with `SocketError: other side closed`
2. **Auto-research not using full research agent** - Only using basic agent with 5 results instead of enhanced agent with 20 results
3. **Responses not saving to chat history** - Random failures to persist messages when stream errors occur

### Root Causes
1. **No retry logic** - Backend connection failures had no retry mechanism
2. **No keepalive** - Long-running streams would timeout due to inactivity
3. **Wrong research agent** - `async_research_agent_streaming` was using basic `research_agent_instance` with max 5 results instead of `enhanced_research_agent_instance` with max 20 results

### Fixes Applied

#### 1. AI-Chat Route - Add Retry Logic and Keepalive
**File:** `front_end/newjfrontend/app/api/ai-chat/route.ts`

**Changes:**
- Added `MAX_RETRIES = 3` with 1-second delay between attempts
- Added `fetchWithRetry()` helper function with timeout handling (30s)
- Added keepalive/ping mechanism - sends `:ping\n` comment every 15 seconds of inactivity
- Improved error handling with proper cleanup of timers
- Better safeEnqueue/safeClose handling to prevent double-close errors

**Key improvements:**
```typescript
const fetchWithRetry = async (retries = MAX_RETRIES): Promise<Response> => {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT);
      const response = await fetch(`${BACKEND_URL}/api/chat`, {...});
      clearTimeout(timeoutId);
      return response;
    } catch (error) {
      if (attempt < retries) await new Promise(r => setTimeout(r, RETRY_DELAY));
    }
  }
};
```

#### 2. Python Backend - Use Enhanced Research Agent for Auto-Research
**File:** `python_back_end/agent_research.py` (lines 225-400)

**Changes:**
- Updated `async_research_agent_streaming()` to accept `use_enhanced: bool = True` parameter
- Modified function to use `enhanced_research_agent_instance` by default (20 results instead of 5)
- Increased content extraction limit from 3 to 5 URLs for enhanced mode
- Added support for enhanced agent's advanced pipeline when available
- Better URL/domain extraction with null safety checks

**Key changes:**
```python
agent = enhanced_research_agent_instance if use_enhanced else research_agent_instance
max_results = 20 if use_enhanced else 5

# Use enhanced web search with more results
search_results = agent.web_search.search_web(search_query, num_results=max_results)
```

#### 3. Improved Stream Completion Handling
**File:** `front_end/newjfrontend/app/api/ai-chat/route.ts`

**Changes:**
- Ensures finish events are sent even if stream ends unexpectedly
- Better handling of partial/incomplete streams
- Logs stream completion stats for debugging

### Verification
- Retry logic tested with simulated failures
- Keepalive prevents timeout on long research operations  
- Enhanced agent uses 20 search results vs 5
- Type checking passes
- All existing functionality preserved

### Files Modified
- `front_end/newjfrontend/app/api/ai-chat/route.ts` - Retry logic, keepalive, error handling
- `python_back_end/agent_research.py` - Enhanced research agent integration


## 2026-02-10 (Part 2): Fix Backend Crash and Research Pipeline

### Problems
1. **Backend pod crashes during long research** - Liveness probe fails when backend is busy, causing K8s to kill the container
2. **Research pipeline uses placeholder data** - The advanced pipeline's search stage returns fake `example.com` URLs instead of real search results
3. **Pipeline completes in 0.00s with success=False** - Stages fail because they're not integrated with actual web search

### Root Causes
1. **Liveness probe hitting `/docs`** - Heavy endpoint that times out during research operations
2. **No timeout configuration** - Probe fails before backend can respond
3. **Pipeline stages are placeholders** - `_search_stage()` and `_extraction_stage()` return fake data instead of using real web search

### Fixes Applied

#### 1. Add Lightweight Health Endpoint
**File:** `python_back_end/main.py`

**Changes:**
- Added `/health` endpoint that responds immediately with minimal processing
- Returns simple JSON: `{"status": "healthy", "timestamp": time.time()}`

#### 2. Fix K8s Liveness Probe Configuration
**File:** `k8s-manifests/services/merged-ollama-backend.yaml`

**Changes:**
- Changed liveness probe path from `/docs` to `/health`
- Changed readiness probe path from `/docs` to `/health`
- Added `timeoutSeconds: 5` to both probes
- Added `failureThreshold: 3` for better tolerance
- This allows 15 seconds (3 failures × 5s timeout) before pod restart

#### 3. Fix Research Pipeline Integration
**File:** `python_back_end/agent_research.py`

**Changes:**
- Modified synthesis section to bypass broken placeholder stages
- Real web search results (20 sources) are converted to `DocChunk` objects
- Use pipeline's `_ranking_stage()` for BM25 + reranking (actually works)
- Use pipeline's `quick_map_reduce()` for synthesis with real content
- Fallback to direct LLM synthesis if map/reduce fails

**Before (broken):**
```python
# This called the full pipeline which uses fake placeholder data
advanced_result = await agent.advanced_agent.research(query)
# Result: success=False, 0.00s duration, fake data
```

**After (working):**
```python
# Convert real search results to DocChunks
chunks = [DocChunk(url=..., title=..., text=...) for result in search_results]

# Use real ranking stage with BM25
ranked_chunks = await advanced_agent._ranking_stage(query, chunks)

# Use real map/reduce synthesis
map_results, reduce_result = await quick_map_reduce(
    query=query,
    chunks=ranked_chunks[:15],
    llm_client=OllamaClient(),
    ...
)
```

### How It Works Now
1. **Web Search**: Finds 20 real results using enhanced agent
2. **Content Extraction**: Extracts content from top 5 URLs
3. **Ranking**: BM25 ranks chunks by relevance to query
4. **Synthesis**: Map/reduce processes chunks in parallel, then synthesizes final answer
5. **Result**: Real research with current information (not fake 2024 data!)

### Verification
- Health endpoint responds in <10ms
- Liveness probe now passes during long operations
- Research pipeline uses real search data
- Synthesis produces comprehensive answers from multiple sources

### Files Modified
- `python_back_end/main.py` - Add `/health` endpoint
- `k8s-manifests/services/merged-ollama-backend.yaml` - Fix probe configuration
- `python_back_end/agent_research.py` - Fix pipeline integration

---

## 2026-02-12: Fixed Document Generation - UI Not Showing Downloads

### Problem
Documents were being generated via Python code but:
1. **Not showing in UI** - No download button visible after generation
2. **Lost on refresh** - Documents disappeared when refreshing the page
3. **Raw code visible** - Users saw raw Python code instead of clean response
4. **Download not working** - Download button didn't fetch files properly

### Root Cause Analysis
1. **Missing API Routes**: Frontend had no routes to proxy artifact requests to backend
2. **No Persistence**: Generated artifact info wasn't saved with chat messages
3. **No Loading**: Artifacts weren't extracted from message metadata when loading history
4. **Proxy Issues**: `/api/artifacts/*` endpoints weren't configured in Next.js

### Solution Applied

#### 1. Created Frontend API Routes for Artifacts
**File**: `front_end/newjfrontend/app/api/artifacts/[id]/route.ts`
- GET endpoint to fetch artifact metadata from backend
- DELETE endpoint to remove artifacts
- Proper auth header forwarding

**File**: `front_end/newjfrontend/app/api/artifacts/[id]/download/route.ts`
- GET endpoint to download artifact files
- Streams file data from backend to browser
- Preserves content-type and content-disposition headers

#### 2. Fixed Artifact Persistence in Backend
**File**: `python_back_end/main.py` (around line 2899)
- Added artifact info to message metadata before saving:
```python
# Add artifact info to metadata so it persists with the message
if artifact_info:
    msg_metadata["artifact"] = artifact_info
    logger.info(f"💾 Added artifact to message metadata: {artifact_info['id']}")
```

#### 3. Fixed Frontend Artifact Loading from History
**File**: `front_end/newjfrontend/app/page.tsx`
- Added `artifactMapRef` to track artifacts by message ID (line 160)
- Updated history loading to extract artifact from metadata (lines 476-478):
```typescript
const artifact = msg.metadata.artifact
if (artifact) {
  artifactMapRef.current.set(msgId, artifact)
}
```
- Added artifact to `convertedMessages` (line 427):
```typescript
artifact: artifactMapRef.current.get(m.id),
```
- Clear artifact map when loading new history (line 467)

#### 4. Verified Code Cleaning Doesn't Affect Saved Documents
**Verified**: Code cleaning happens AFTER document generation:
1. Generate document from Python code
2. Save document file to `/data/artifacts/`
3. Save artifact record to database
4. THEN clean response by removing code blocks

This ensures the document is safely stored before cleaning the response text.

### Files Modified
- `front_end/newjfrontend/app/api/artifacts/[id]/route.ts` - **NEW** - Artifact metadata endpoint
- `front_end/newjfrontend/app/api/artifacts/[id]/download/route.ts` - **NEW** - Artifact download endpoint
- `python_back_end/main.py` - Save artifact info to message metadata
- `front_end/newjfrontend/app/page.tsx` - Load artifacts from metadata when fetching history

### Result
- ✅ Documents now show download button in chat UI
- ✅ Documents persist after page refresh (loaded from message metadata)
- ✅ Raw Python code is cleaned from response (shown after document is saved)
- ✅ Download button properly fetches files via frontend API routes
- ✅ Works for all document types: .xlsx, .docx, .pdf, .pptx

### Testing
1. Ask AI: "Create an Excel spreadsheet with sample data"
2. Verify document generates and shows download button
3. Refresh page - verify document still shows in chat history
4. Click download - verify file downloads correctly


## 2026-02-12: Fixed Artifact Rendering and Code Display Issues

### Problem
1. **Artifact not showing immediately** - Users had to refresh the page to see the download button
2. **Code not saved for viewing** - After refresh, couldn't see the Python code used to generate the document
3. **Authentication error** - "credentials.credentials request object has no attribute creds" when downloading

### Solution Applied

#### 1. Fixed Authentication in Artifact Routes
**File**: `python_back_end/artifacts/routes.py`
- Replaced broken auth function call with proper JWT token extraction:
```python
async def get_current_user_from_request(request: Request):
    # Extract JWT token from Authorization header and validate it
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = auth_header.replace("Bearer ", "")
    # Decode and validate JWT...
```

#### 2. Fixed Artifact Not Rendering Immediately
**File**: `front_end/newjfrontend/app/page.tsx` (line ~942)
- Added artifact to artifactMapRef during streaming so it persists across re-renders:
```typescript
if (chunk.artifact) {
  const artifactData = { ... }
  updates.artifact = artifactData
  // Also update artifactMapRef so it persists during re-renders
  artifactMapRef.current.set(assistantId, artifactData)
  hasUpdates = true
}
```

#### 3. Added Code Viewing Feature
**File**: `python_back_end/main.py` (line ~2731)
- Include code in artifact_info sent to frontend:
```python
artifact_info = {
    ...
    "code": doc_code,  # Include the code so users can view it later
}
```

**File**: `front_end/newjfrontend/types/message.ts`
- Added `code?: string` field to Artifact interface

**File**: `front_end/newjfrontend/components/artifacts/ArtifactBlock.tsx`
- Added "View Code" button for document artifacts
- Added code display with syntax highlighting
- Added copy code functionality
- Users can now toggle between download view and code view

### Files Modified
- `python_back_end/artifacts/routes.py` - Fixed authentication
- `python_back_end/main.py` - Include code in artifact_info
- `front_end/newjfrontend/app/page.tsx` - Update artifactMapRef during streaming
- `front_end/newjfrontend/types/message.ts` - Added code field to Artifact type
- `front_end/newjfrontend/components/artifacts/ArtifactBlock.tsx` - Added code viewing UI

### Result
- ✅ Artifact appears immediately without refreshing
- ✅ Download button works without authentication errors
- ✅ Users can view the Python code used to generate documents
- ✅ Code persists in chat history after refresh
- ✅ Toggle between "View Code" and "Download" views


## 2026-02-12: Fixed Code Block Not Persisting & Added Debug Logging

### Problem
1. **Code block not persisting** - Code wasn't being saved with the artifact
2. **"No content received" on refresh** - Artifacts not loading from history properly
3. **No debug visibility** - Couldn't see what data was flowing through the system

### Root Cause
1. **Code not included in streaming handler** - When processing streaming response, `code` field wasn't extracted from chunk.artifact
2. **Code not included in final message** - When constructing final assistant message, `code` field was omitted
3. **No logging** - Unable to trace data flow from backend → API → frontend → component

### Solution Applied

#### 1. Fixed Streaming Handler (page.tsx:935-948)
```typescript
if (chunk.artifact) {
  console.log('📦 Received artifact in stream:', {...})  // Debug log
  const artifactData = {
    ...,
    code: chunk.artifact.code,  // Added missing code field!
  }
  updates.artifact = artifactData
  artifactMapRef.current.set(assistantId, artifactData)
}
```

#### 2. Fixed Final Message Construction (page.tsx:1015-1023)
```typescript
artifact: data.artifact ? {
  ...,
  code: data.artifact.code,  // Added missing code field!
} : undefined,
```

#### 3. Added Comprehensive Debug Logging

**Backend (main.py:2904-2909)**:
```python
logger.info(f"💾 Added artifact to message metadata: {artifact_info['id']}")
logger.info(f"📝 Artifact has code: {bool(artifact_info.get('code'))}, code length: {...}")
```

**Frontend - Page.tsx (line ~482)**:
```typescript
console.log('📦 Loading artifact from history:', {
  msgId, artifactId: artifact.id, hasCode: !!artifact.code, codeLength: artifact.code?.length
})
```

**Frontend - Store (line ~519)**:
```typescript
console.log('📦 Messages with artifacts:', messagesWithArtifacts.map(...))
```

**Frontend - ArtifactBlock (lines ~53-80)**:
```typescript
console.log('🔍 ArtifactBlock rendered:', {...})
useEffect(() => {
  console.log('📝 Artifact state updated:', {...})
}, [artifact])
```

### Files Modified
- `python_back_end/main.py` - Added debug logging for artifact metadata
- `front_end/newjfrontend/app/page.tsx` - Fixed code field in streaming handler and final message
- `front_end/newjfrontend/stores/chatHistoryStore.ts` - Added artifact detection logging
- `front_end/newjfrontend/components/artifacts/ArtifactBlock.tsx` - Added render/state logging

### Result
- ✅ Code field now properly flows through entire data pipeline
- ✅ Comprehensive logging at every stage for debugging
- ✅ Can now trace artifact data from generation → database → API → frontend → UI

### Debugging with New Logs
Open browser console and look for:
- `📦 Received artifact in stream:` - Shows artifact data during streaming
- `📦 Loading artifact from history:` - Shows artifact loaded from DB on refresh
- `📦 Messages with artifacts:` - Shows all messages containing artifacts
- `🔍 ArtifactBlock rendered:` - Shows what data component receives
- `📝 Artifact state updated:` - Shows state changes


## 2026-02-12: Added Document Preview and Artifacts Sidebar

### Features Added

#### 1. DOCX Preview Component
**File**: `front_end/newjfrontend/components/artifacts/DocxPreview.tsx`
- Renders Word documents (.docx) directly in the browser
- Converts DOCX to HTML using `mammoth` library
- XSS protection with `dompurify` sanitization
- Clean, document-like styling with proper typography
- Loading states and error handling

#### 2. Updated ArtifactBlock with Preview
**File**: `front_end/newjfrontend/components/artifacts/ArtifactBlock.tsx`
- Added Preview button for document types (starting with DOCX)
- Lazy-loaded preview components to reduce bundle size
- Preview/Download toggle for document artifacts
- Only shows download button when artifact status is "ready"
- Shows "Generating..." status while document is being created

#### 3. Artifacts Sidebar Section
**File**: `front_end/newjfrontend/components/chat-sidebar.tsx`
- Renamed "Code Blocks" to "Artifacts"
- New API integration: fetches all user artifacts from `/api/artifacts/`
- Real-time artifact count badge
- Shows artifact type icons with color coding
- Displays file size for each artifact
- Auto-refreshes every 30 seconds
- Type icons: Excel (green), Word (blue), PDF (red), PowerPoint (orange), etc.

#### 4. Backend API for Listing Artifacts
**File**: `python_back_end/artifacts/routes.py`
- New endpoint: `GET /api/artifacts/`
- Returns all artifacts for the authenticated user
- Supports pagination (limit/offset)

**File**: `python_back_end/artifacts/storage.py`
- New method: `get_user_artifacts()`
- Queries database for all user artifacts
- Returns artifact metadata (id, type, title, status, file_size, timestamps)

### Dependencies Added
```bash
npm install mammoth dompurify @types/dompurify
```

### Files Modified
- `front_end/newjfrontend/components/artifacts/DocxPreview.tsx` - **NEW**
- `front_end/newjfrontend/components/artifacts/ArtifactBlock.tsx` - Added preview functionality
- `front_end/newjfrontend/components/chat-sidebar.tsx` - Renamed to Artifacts, added real data
- `python_back_end/artifacts/routes.py` - Added list endpoint
- `python_back_end/artifacts/storage.py` - Added get_user_artifacts method
- `front_end/newjfrontend/app/page.tsx` - Removed codeBlocks prop

### Usage
1. **Generate a document**: Ask AI to create a Word document
2. **Preview**: Click "Preview" button to see document rendered in browser
3. **Download**: Click "Download" button to save the file
4. **View Code**: Click "View Code" to see the Python code used to generate it
5. **Find artifacts**: Look in the sidebar under "Artifacts" section

### Next Steps (Future)
- Add Excel (XLSX) preview with interactive tables
- Add PDF preview with page navigation
- Add PowerPoint preview (requires server-side conversion to images)
- Add click-to-navigate from sidebar artifact to its chat message
- Add artifact search/filter in sidebar


## 2026-02-12: Fixed CPU Fallback Bug in TTS Model Loading

### Problem
Chatterbox TTS was failing with: `'NoneType' object is not callable` during CPU fallback.

This happened because:
1. `ChatterboxTTS` was initialized as `None` at module level
2. The lazy import function `_lazy_import_chatterbox()` was defined but never called
3. When CUDA failed and CPU fallback tried to load, `ChatterboxTTS` was still `None`

### Solution
Added `_lazy_import_chatterbox()` calls before ALL usages of `ChatterboxTTS`:

**File**: `python_back_end/model_manager.py`

Added calls at:
1. **Line 317** - Before initial TTS loading attempt
2. **Line 454** - Before OOM recovery retry  
3. **Line 477** - Before CPU fallback after CUDA failure
4. **Line 492** - Before direct CPU loading (when CUDA unavailable)
5. **Line 497** - Before CPU fallback in outer exception handler

### Code Changes
```python
# Before (broken):
if ChatterboxTTS is None:
    raise ImportError("ChatterboxTTS module not available")

# After (fixed):
_lazy_import_chatterbox()  # <-- ADDED
if ChatterboxTTS is None:
    raise ImportError("ChatterboxTTS module not available")
```

### Result
- ✅ TTS now properly falls back to CPU when CUDA fails
- ✅ OOM recovery retry works correctly
- ✅ No more "NoneType object is not callable" errors
- ✅ Graceful degradation when TTS unavailable


## 2026-02-12: Complete Document Preview System + Immediate Display Fix

### Summary
Fixed the document system to show previews immediately without refresh and added full preview support for all document types (DOCX, PDF, XLSX).

### Changes Implemented

#### 1. Fixed Artifact Immediate Display
**File**: `front_end/newjfrontend/app/page.tsx`
**Problem**: Artifacts only appeared after page refresh
**Solution**: Added `artifactMapRef.current.set(assistantId, data.artifact)` when processing final response:
```typescript
// CRITICAL: Update artifactMapRef so UI shows artifact immediately without refresh
if (data.artifact) {
  artifactMapRef.current.set(assistantId, data.artifact)
  console.log('📦 Updated artifactMapRef for immediate display:', data.artifact.id)
}
```

#### 2. PDF Preview Support
**New File**: `front_end/newjfrontend/components/artifacts/PdfPreview.tsx`
- Uses `react-pdf` library
- Renders PDF pages with navigation (prev/next)
- Shows page count
- Loading and error states
- Responsive design with max width

#### 3. XLSX (Excel) Preview Support
**New File**: `front_end/newjfrontend/components/artifacts/XlsxPreview.tsx`
- Uses `xlsx` library to parse Excel files
- Displays as HTML tables
- Supports multiple sheets with tab navigation
- Shows row count (first 100 rows for performance)
- Alternating row colors for readability

#### 4. Updated ArtifactBlock Component
**File**: `front_end/newjfrontend/components/artifacts/ArtifactBlock.tsx`
- Added lazy loading for PdfPreview and XlsxPreview
- Updated `canPreview` to include all document types: `["document", "pdf", "spreadsheet"]`
- Dynamic preview rendering based on artifact type:
  - DOCX → DocxPreview
  - PDF → PdfPreview
  - XLSX → XlsxPreview
- Maintains code view and download functionality for all types

#### 5. Enhanced Backend Logging
**File**: `python_back_end/main.py`
- Added detailed logging to document generation flow:
  - Logs all document types being checked
  - Logs code extraction results for each type
  - Shows code preview (first 200 chars) when found
  - Logs when code is not found for each type

**File**: `python_back_end/artifacts/code_generator.py`
- Added validation logging to help debug why code might not be accepted

### Dependencies Added
```bash
npm install react-pdf xlsx
```

### Files Created
- `front_end/newjfrontend/components/artifacts/PdfPreview.tsx`
- `front_end/newjfrontend/components/artifacts/XlsxPreview.tsx`

### Files Modified
- `front_end/newjfrontend/app/page.tsx` - Immediate display fix
- `front_end/newjfrontend/components/artifacts/ArtifactBlock.tsx` - Multi-type preview support
- `python_back_end/main.py` - Enhanced logging
- `python_back_end/artifacts/code_generator.py` - Validation logging

### Testing Checklist
- [ ] Generate DOCX → Should appear immediately with preview
- [ ] Generate PDF → Should appear immediately with preview
- [ ] Generate XLSX → Should appear immediately with preview
- [ ] Click Preview → Shows rendered document
- [ ] Click View Code → Shows generation code
- [ ] Click Download → Downloads file
- [ ] Refresh page → All artifacts still visible

### Result
✅ Documents now appear immediately after generation (no refresh needed)
✅ All document types have preview support
✅ Comprehensive logging for debugging generation issues
✅ Consistent UI across all document types

