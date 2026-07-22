---
name: harvis-research
description: >
  Web research via Harvis Tier 2 (search + web-fetch) and optional Tier 3
  (interactive browser). Use for lookups, docs, GitHub, Claude/Anthropic pages,
  and light assignment research. Never refuse for "no internet".
metadata:
  openclaw:
    emoji: "\ud83d\udd0d"
    always: false
---

# Harvis Research (Tier 2 + optional Tier 3)

## Rules

1. **Never** tell the user you cannot access the web or Claude sites. Use the
   Harvis backend APIs below.
2. **Never** `curl` a public URL directly. Use `/api/tools/search` and
   `/api/tools/web-fetch`, or Tier 3 browser APIs.
3. Optional: `POST http://backend:8000/api/research-chat` for heavier research
   if available (same `Authorization` bearer token).

## Headers (every request)

Use the **exact** `X-OpenClaw-SessionKey` string from the Harvis workspace task message (do not guess `main`).

```text
Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN
Content-Type: application/json
X-OpenClaw-SessionKey: <from Harvis task>
```

## Tier 2 — search

OpenClaw `exec` often runs without a shell — wrap in `bash` so the token expands (otherwise Harvis returns **Invalid proxy token**).

```bash
bash --noprofile --norc +H -lc "curl -s -X POST http://backend:8000/api/tools/search -H \"Content-Type: application/json\" -H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\" -H \"X-OpenClaw-SessionKey: YOUR_SESSION_KEY\" -d '{\"query\":\"YOUR QUERY\",\"max_results\":8}'"
```

## Tier 2 — fetch a specific https URL

```bash
bash --noprofile --norc +H -lc "curl -s -X POST http://backend:8000/api/tools/web-fetch -H \"Content-Type: application/json\" -H \"Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN\" -H \"X-OpenClaw-SessionKey: YOUR_SESSION_KEY\" -d '{\"url\":\"https://claude.ai/docs\",\"purpose\":\"research\"}'"
```

Use `jq` to trim `.text` if the response is large. Prefer official docs and
GitHub; if the backend returns 400/415, try another allowlisted URL.

## Tier 3 — interactive browser (Firefox)

**Only if** you have been given `workspace_id` and `capability_token` (e.g. from
a Harvis workspace run with interactive mode enabled) AND the browser skill
is available at `/skills/harvis-browser/SKILL.md`.

Read that skill for the full workflow. If you lack `workspace_id` /
`capability_token`, skip Tier 3 and complete the task with Tier 2 only.

## After research

Summarize with citations (titles + URLs). Offer a DOCX report via
`/api/tools/document-save` when the user wants a formal deliverable.
