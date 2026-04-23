---
name: harvis-web-search
description: >
  Web search via the Harvis backend proxy. Uses DuckDuckGo (DDGS) with
  Tavily fallback. NEVER call external URLs directly — always use this
  endpoint. Security: API keys stay in the backend, never exposed to OpenClaw.
metadata:
  openclaw:
    emoji: "🌐"
    always: false
    requires:
      bins: [curl, jq]
---

# Harvis Web Search Skill

Use this skill when you need to search the web or fetch content from URLs.

**Security rule**: You must NEVER call external URLs directly with curl or
any other tool. ALL web searches and fetches MUST go through the Harvis
backend proxy.

---

## Search Endpoint

```bash
curl -s -X POST http://backend:8000/api/web-search \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "YOUR SEARCH QUERY HERE",
    "max_results": 5
  }' | jq '.'
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search query |
| `max_results` | int | 5 | Number of results (1-20) |

## Response Format

```json
{
  "query": "original query",
  "results": [
    {
      "title": "Page Title",
      "url": "https://example.com/page",
      "snippet": "Relevant excerpt from the page...",
      "content": "Full extracted content (if available)",
      "score": 0.85
    }
  ],
  "total": 5
}
```

## Content Extraction

To extract full content from a specific URL:

```bash
curl -s -X POST http://backend:8000/api/web-search \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "URL: https://example.com/article",
    "max_results": 1
  }' | jq '.results[0].content'
```

Prefix the query with `URL:` to force content extraction instead of search.

## When to Use Web Search

| Use web search when... | Use RAG (harvis-rag) when... |
|-----------------------|------------------------------|
| User asks about current events | User asks about the codebase |
| Need latest info on a topic | Need internal API docs |
| Fact-checking external claims | Looking up existing code |
| Researching new technologies | Understanding project architecture |
| User explicitly asks to "search" | User asks about internal knowledge |

## Rules

1. **Always use the backend proxy** — never curl external URLs directly
2. **Use RAG for internal knowledge** — only search the web when RAG can't help
3. **Search before saying "I don't know"** — check RAG first, then web search
4. **Cite sources** — always include title and URL in your response
5. **Max 5 results** — don't overload with too many sources
