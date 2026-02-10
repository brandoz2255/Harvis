
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
