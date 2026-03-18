---
name: harvis-research
description: >
  Web research skill — fetches public sources via the Harvis safe proxy,
  synthesizes findings, and saves a structured DOCX report as an artifact.
  Use when asked to research, look up, investigate, or report on a topic.
metadata:
  openclaw:
    emoji: "🔍"
    always: false
    requires:
      bins: [curl, jq]
---

# Harvis Research Skill

Use this skill when asked to research a topic, write a research report, or
investigate something that requires gathering information from the web.

**Security rule**: You must NEVER call external URLs directly with curl or any
other tool. ALL web searches and fetches MUST go through the Harvis backend.
There are two approved endpoints:
- **Preferred**: `http://backend:8000/api/research-chat` — full DuckDuckGo search + content extraction
- **Fallback**: `http://backend:8000/api/tools/web-fetch` — fetch a specific URL

The browser tool is **disabled**. Do not attempt to use it.

---

## Research Workflow

Always follow all five steps in order.

### Step 1 — Plan (3-5 search queries)

Think through what sub-questions need to be answered to fully cover the topic.
List 3-5 specific search queries or URLs you will fetch. Plan before you act.

Good sources: Wikipedia, official docs, reputable news sites, academic pages.
Avoid: paywalled sites, social media, forums.

### Step 2 — Search and fetch sources

Use the research-chat endpoint to search for each query. Collect 3-5 quality sources.

```bash
# Search via Harvis research agent (DuckDuckGo + content extraction)
RESULT=$(curl -s -X POST http://backend:8000/api/research-chat \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "YOUR SEARCH QUERY HERE", "use_advanced": true}')
echo "$RESULT"
```

For a specific URL, use the web-fetch fallback:

```bash
SOURCE=$(curl -s -X POST http://backend:8000/api/tools/web-fetch \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article", "purpose": "research"}' \
  | jq '{title, url, text: .text[:2000], word_count}')
echo "$SOURCE"
```

Note the `title` and `url` of each source you fetch. If a request fails (non-200),
skip that source and try the next one on your list.

### Step 3 — Synthesize

Write a structured markdown research document. Use this template:

```markdown
# Research: <Topic>

## Summary

2-3 paragraph overview of the key findings.

## Key Findings

- **Finding 1**: explanation (Source: Title)
- **Finding 2**: explanation (Source: Title)
- **Finding 3**: explanation (Source: Title)

## Analysis

Deeper discussion of the findings, patterns, and implications.

## Conclusion

Brief conclusion and any open questions.

## References

- [Source Title 1](https://url1)
- [Source Title 2](https://url2)
```

Write the full document content. Do not skip sections.

### Step 4 — Save as DOCX artifact

```bash
# Write draft to file first so escaping is clean
cat > /tmp/research-draft.md << 'DRAFT_EOF'
<paste your full markdown here>
DRAFT_EOF

CONTENT=$(cat /tmp/research-draft.md)

# Build sources JSON array
SOURCES='[
  {"title": "Source Title 1", "url": "https://url1"},
  {"title": "Source Title 2", "url": "https://url2"}
]'

PAYLOAD=$(jq -n \
  --arg title "Research: <topic>" \
  --arg content "$CONTENT" \
  --argjson sources "$SOURCES" \
  --argjson user_id "${HARVIS_USER_ID:-0}" \
  '{title: $title, content: $content, format: "docx", sources: $sources, user_id: $user_id}')

SAVE_RESULT=$(curl -s -X POST http://backend:8000/api/tools/document-save \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

echo "$SAVE_RESULT"
ARTIFACT_ID=$(echo "$SAVE_RESULT" | jq -r '.artifact_id')
echo "Artifact ID: $ARTIFACT_ID"
```

If `artifact_id` is null or the request fails, report the error and skip Step 5.

### Step 5 — Return structured result

After saving the artifact, output the following JSON block so Harvis can render
source cards and a DOCX download card in the chat UI:

```json
{
  "type": "research_result",
  "summary": "2-3 sentence summary of the key findings for the user.",
  "sources": [
    {"title": "Source Title 1", "url": "https://url1", "snippet": "Brief excerpt..."},
    {"title": "Source Title 2", "url": "https://url2", "snippet": "Brief excerpt..."}
  ],
  "artifact_id": "<artifact_id from step 4>"
}
```

Then write a friendly summary of what you found for the user, followed by:
"📄 I've saved a full research report — you can download it from the document card."
