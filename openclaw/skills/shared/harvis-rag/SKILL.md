---
name: harvis-rag
description: >
  Search the Harvis local vector database for relevant code and documentation.
  Always loaded. Use this BEFORE saying "I don't know" — the answer may already
  be in the knowledge base.
metadata: {"openclaw": {"emoji": "\ud83d\udcda", "always": true}}
---

# Harvis RAG — Vector Search Skill

## When to use (mandatory)

**Search the RAG before:**
- Saying "I don't know", "I'm not sure", or "I don't have that information"
- Writing a new function, class, or module — it may already exist
- Answering questions about how something works in the codebase
- Answering questions about the project architecture or design decisions
- Looking up any internal API, endpoint, config, or schema

If the RAG returns no results (total: 0) or all scores are below 0.4, then you can say you don't know.

---

## Corpus types

| `context_type` | Use for |
|---------------|---------|
| `"code"` | Functions, classes, file content, implementation patterns, endpoints |
| `"docs"` | Architecture docs, README content, design decisions, how-tos |

When unsure, run **both** — one code search and one docs search.

---

## Search — code corpus

```bash
bash --noprofile --norc +H -lc "curl -s -X POST http://backend:8000/rag/search \
  -H \"Content-Type: application/json\" \
  -H \"Authorization: Bearer \$OPENCLAW_GATEWAY_TOKEN\" \
  -d '{\"query\": \"YOUR QUERY HERE\", \"context_type\": \"code\", \"top_k\": 5, \"score_threshold\": 0.3}' | jq '.results[] | {score, source, text: .text[:400]}'"
```

## Search — docs corpus

```bash
bash --noprofile --norc +H -lc "curl -s -X POST http://backend:8000/rag/search \
  -H \"Content-Type: application/json\" \
  -H \"Authorization: Bearer \$OPENCLAW_GATEWAY_TOKEN\" \
  -d '{\"query\": \"YOUR QUERY HERE\", \"context_type\": \"docs\", \"top_k\": 5, \"score_threshold\": 0.3}' | jq '.results[] | {score, source, text: .text[:400]}'"
```

---

## Score interpretation

| Score | Meaning |
|-------|---------|
| >= 0.7 | Strong match — use this |
| 0.5-0.7 | Good match — likely relevant |
| 0.3-0.5 | Weak match — use with judgment |
| < 0.3 | Not returned (filtered by threshold) |

---

## Rules

1. **Search before saying "I don't know"** — this is not optional.
2. Run both `"code"` and `"docs"` searches if the question could span either corpus.
3. Never make web requests for internal knowledge — this endpoint is the only path.
4. If `total: 0` after both searches, you may admit uncertainty.
5. Cite the `source` file path when using a result in your answer.
