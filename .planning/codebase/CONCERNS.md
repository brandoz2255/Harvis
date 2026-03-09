# Codebase Concerns

**Analysis Date:** 2025-02-06

## Research Sources Display Issues

### Issue 1: ResearchBlock Not Showing in AI Chat Mode

**Problem:** The `ResearchBlock` component (`front_end/newjfrontend/components/ResearchBlock.tsx`) only appears when `discoveredSources` is passed to the `ChatMessage` component. However, `discoveredSources` is only populated during real-time streaming in research mode.

**Root Cause:**
- In `page.tsx`, the `discoveredSources` property is only set when processing streaming chunks with `status === 'sources_discovered'` (line 508-510)
- When loading messages from chat history, the sources are stored in `metadata.sources` but are mapped to `searchResults`, NOT `discoveredSources`

**Code Flow:**
```typescript
// page.tsx lines 276-280 - Loading from history
if (msg.metadata) {
  const sources = msg.metadata.sources || msg.metadata.searchResults
  if (sources && sources.length > 0) {
    searchResultsMapRef.current.set(msgId, sources)  // ← Goes to searchResults
  }
}
```

**Impact:**
- ResearchBlock (the Perplexity-style expandable panel) never shows when viewing past research chats
- Users only see the basic source cards in the footer, not the rich research UI

**Fix Approach:**
When loading from history, also populate `discoveredSourcesMapRef` so the ResearchBlock appears:
```typescript
if (sources && sources.length > 0) {
  searchResultsMapRef.current.set(msgId, sources)
  // Also populate discoveredSources for ResearchBlock display
  discoveredSourcesMapRef.current.set(msgId, sources.map(s => ({
    title: s.title,
    url: s.url,
    domain: s.domain || new URL(s.url).hostname.replace('www.', '')
  })))
}
```

---

### Issue 2: Footer Sources Section Shows Only 1 Source Instead of 5

**Problem:** The sources section at the bottom of assistant messages only displays 1 source when there should be 5.

**Root Cause Analysis:**

**Backend (`python_back_end/main.py`):**
1. In the `/api/research-chat` endpoint (line 3757-3768), the final response includes:
   ```python
   "sources": sources[:5] if sources else []
   ```
   This correctly limits to 5 sources.

2. However, in the auto-research section of `/api/chat` (lines 1665-1686), sources are also returned:
   ```python
   "sources": sources[:5],
   ```

3. The issue is in the `agent_research.py` `research_agent` function which returns sources from the research agent. Looking at the code, the research agent returns formatted sources.

**Frontend (`page.tsx`):**
The issue is in how sources are processed during the streaming response. Looking at line 542:
```typescript
if (chunk.sources || chunk.search_results) {
  updates.searchResults = chunk.sources || chunk.search_results
  hasUpdates = true
}
```

But earlier in lines 508-514, discovered sources are being handled:
```typescript
if (chunk.status === 'sources_discovered' && chunk.sources) {
  discoveredSourcesMapRef.current.set(assistantId, chunk.sources)
  updates.discoveredSources = chunk.sources
  updates.sourcesCount = chunk.current_count
  updates.currentQuery = chunk.query
  hasUpdates = true
}
```

**The Real Problem:**

In the research-chat endpoint (`main.py` lines 3517-3561), sources are discovered and streamed in real-time via `sources_discovered` events. However, the final formatted sources list is sent in the `complete` event.

Looking at `main.py` line 3762:
```python
"sources": sources[:5] if sources else []
```

The `sources` variable is built from `quality_sources` which are filtered and ranked (lines 3633-3661). The number of `quality_sources` depends on the filtering in `_filter_and_rank_sources`.

**Root Cause in research_agent.py:**

In `research_agent.py` lines 237-258, the `_filter_and_rank_sources` method:
```python
def _filter_and_rank_sources(self, sources: list, min_sources: int = 3, max_sources: int = 8) -> list:
    # Score each source
    scored = [(self._score_source(s), s) for s in sources]
    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    # Filter out negative-scored sources
    filtered = [s for score, s in scored if score >= 0]
    # Ensure we have at least min_sources (even if low quality)
    if len(filtered) < min_sources:
        remaining = [s for score, s in scored if score < 0][:min_sources - len(filtered)]
        filtered.extend(remaining)
    # Cap at max_sources
    return filtered[:max_sources]
```

**The Issue:** If many sources receive negative scores during filtering (due to SEO spam detection or irrelevant domains), the final list may have fewer than 5 sources.

**Verification:**
Check the scoring logic in `research_agent.py` lines 183-235:
- High-quality domains (+5): github.com, docs.*, etc.
- Reputable publishers (+3): medium.com, engineering.*, etc.
- SEO spam indicators (-3): "complete guide", "ultimate guide", etc.
- Irrelevant domains (-5): goodreads.com, pinterest.com, etc.

**Impact:**
- Users see fewer sources than expected
- The "Sources (N)" header may show a different number than actual displayed sources

**Fix Approach:**
1. Review the scoring algorithm to ensure it's not too aggressive
2. Increase `max_results` in the search phase to ensure enough sources survive filtering
3. Add logging to track how many sources are filtered out and why

---

### Issue 3: Data Format Mismatch Between Discovered Sources and Search Results

**Problem:** Two different data structures are used for the same concept:

1. **DiscoveredSource** (real-time streaming):
   ```typescript
   interface DiscoveredSource {
     title: string
     url: string
     domain: string
     query?: string
   }
   ```

2. **SearchResult** (final display):
   ```typescript
   interface SearchResult {
     title: string
     url: string
     snippet: string
     source?: string
   }
   ```

**Impact:**
- Code complexity: need to handle both formats
- Missing fields: `SearchResult` has `snippet` but `DiscoveredSource` doesn't
- Inconsistent display: ResearchBlock shows domain, footer sources show snippet

**Fix Approach:**
Standardize on a single format or ensure proper mapping between them. The `ChatMessage` component expects `searchResults` to have a `snippet` property (line 509 in chat-message.tsx), but discovered sources don't have this field.

---

### Issue 4: Sources Not Persisted Correctly in Auto-Research Mode

**Problem:** In `/api/chat` auto-research mode (lines 1600-1762), sources are discovered and returned in the response, but the metadata saving may not work correctly.

**Code Analysis:**
In `main.py` lines 1723-1738:
```python
research_metadata = {
    "sources": sources[:5] if sources else [],
    "videos": videos[:6] if videos else [],
    "auto_researched": True,
}

asst_msg = await chat_history_manager.add_message(
    user_id=current_user.id,
    session_id=saved_session_id,
    role="assistant",
    content=analysis,
    model_used=req.model,
    input_type="text",
    metadata=research_metadata,
)
```

**Potential Issue:** The sources are correctly saved to metadata, but when loading from history (page.tsx lines 276-280), they are retrieved from `msg.metadata.sources`.

**Verification Needed:**
Check if `ChatHistoryManager.add_message` properly handles the metadata field and if `get_session_messages` returns it correctly.

---

### Issue 5: No Sources Display in Standard (Non-Research) AI Chat

**Problem:** When the auto-research triggers in `/api/chat`, sources are discovered and streamed, but the UI doesn't handle them the same way as explicit research mode.

**Code Analysis:**
In `main.py` lines 1638-1655, auto-research discovers sources and emits them:
```python
yield f"data: {json.dumps({'status': 'sources_discovered', 'sources': discovered_sources, 'current_count': len(discovered_sources), 'query': query})}\n\n"
```

But in `page.tsx`, this is handled in the research-mode-specific code path (lines 508-514). The AI SDK chat path doesn't handle discovered sources.

**Impact:**
- Auto-research shows sources in real-time but may not display them correctly in the final message
- Inconsistent UX between manual research mode and auto-research

**Fix Approach:**
Ensure both code paths (research mode fetch and AI SDK streaming) handle sources consistently.

---

## Summary of Data Flow Issues

```
Backend Research Agent
  ↓ (returns)
Result: {analysis, sources[], videos[], ...}

Backend API Endpoint (/api/research-chat)
  ↓ (streams via SSE)
1. {status: 'sources_discovered', sources: [...]}  ← DiscoveredSource format
2. {status: 'complete', sources: [...], videos: [...]}  ← SearchResult format

Frontend page.tsx
  ↓ (processes streaming)
discoveredSourcesMapRef ← sources_discovered events (DiscoveredSource[])
searchResultsMapRef ← complete event sources (SearchResult[])

Frontend chat-message.tsx
  ↓ (renders)
ResearchBlock ← discoveredSources (DiscoveredSource[])
Footer Sources ← searchResults (SearchResult[])
```

**Key Mismatches:**
1. Two different source formats (DiscoveredSource vs SearchResult)
2. Sources not mapped correctly when loading from history
3. Filtering may reduce source count below expected 5
4. Auto-research and manual research have different code paths

---

*Concerns audit: 2025-02-06*
