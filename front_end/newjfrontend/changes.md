

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

