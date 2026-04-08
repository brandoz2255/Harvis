---
name: harvis-research
description: >
  Web research skill — searches the web via exec tool calls, fetches pages,
  synthesizes findings. Use when asked to research or look up anything.
metadata:
  openclaw:
    emoji: "🔍"
    always: false
    requires:
      bins: [curl, jq]
---

# Harvis Research Skill

You have web access. Use the `exec` tool to run curl commands.

**NEVER type curl commands as text. ALWAYS call the exec tool.**

---

## Step 1 — Search

Call `exec` with this command (replace YOUR_QUERY):

```
curl -s -X POST http://backend:8000/api/tools/search -H "Content-Type: application/json" -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" -H "X-Live-Web: true" -d '{"query":"YOUR_QUERY","max_results":10}'
```

Read the JSON result. Pick the best URLs from the results.

## Step 2 — Fetch pages

For each good URL, call `exec` with (replace THE_URL):

```
curl -s -X POST http://backend:8000/api/tools/web-fetch -H "Content-Type: application/json" -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" -H "X-Live-Web: true" -d '{"url":"THE_URL","purpose":"research"}'
```

Read the `text` field from the result.

## Step 3 — Summarize

After fetching sources, write a clear summary for the user:
- What you found
- Key facts
- Source URLs

Do not dump raw JSON. Summarize in plain language.
