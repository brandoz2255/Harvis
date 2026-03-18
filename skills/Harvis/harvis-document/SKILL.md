---
name: harvis-document
description: >
  Structured document generator — writes DOCX files from user requests.
  Use for reports, changelogs, summaries, proposals, READMEs, meeting notes,
  and any formatted long-form content the user wants to download.
  Also handles "mimic this document" requests when the user uploads a file.
metadata:
  openclaw:
    emoji: "📝"
    always: false
    requires:
      bins: [curl, jq]
---

# Harvis Document Skill

Use this skill when asked to write, create, or generate a document, report,
or formatted file that the user will want to download — OR when asked to
recreate/mimic an uploaded file (image, PDF, or DOCX).

---

## Workflow A: Write a new document from scratch

Follow Steps 1-4 below.

## Workflow B: Mimic an uploaded document

If the task includes a `file_id`, use this workflow instead.

### Step B1 — Analyze the uploaded file

```bash
ANALYSIS=$(curl -s -X POST http://harvis-ai-merged-backend:8000/api/tools/file-analyze \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"<file_id from task>\", \"user_id\": ${HARVIS_USER_ID:-0}, \"hint\": \"<any user hint>\"}")
echo "$ANALYSIS"

# Extract the structure
STRUCTURE=$(echo "$ANALYSIS" | jq '.structure')
TITLE=$(echo "$ANALYSIS" | jq -r '.structure.title // "Recreated Document"')
echo "Title: $TITLE"
echo "Pages analyzed: $(echo "$ANALYSIS" | jq '.pages_analyzed')"
```

If the request fails, report the error and stop.

### Step B2 — Write the recreated document

Use the `write` tool to create `/tmp/document-draft.md` based on the structure
returned by file-analyze. Follow the exact sections, headings, and content
order from the original. Preserve all text, tables, and lists.

### Step B3 — Save and return (same as Steps 3-4 below)

---

## Workflow A Steps

### Step 1 — Understand the structure

Before writing anything, plan the document:
- What is the title?
- What sections does it need?
- What content goes in each section?

Think through the full structure first. A good document has a clear hierarchy.

### Step 2 — Write the content

Use the `write` tool to create a markdown draft at `/tmp/document-draft.md`:

```markdown
# Document Title

## Section 1

Content for section 1.

## Section 2

Content for section 2.

### Subsection 2.1

Detailed content.

## Conclusion

Summary and next steps.
```

Use proper markdown:
- `#` for the document title
- `##` for top-level sections
- `###` for subsections
- `-` for bullet lists
- `1.` `2.` for numbered lists
- `` ``` `` for code blocks
- `>` for important callouts

Write the complete document. Do not use placeholder text like "add content here."

### Step 3 — Save as artifact

```bash
CONTENT=$(cat /tmp/document-draft.md)

PAYLOAD=$(jq -n \
  --arg title "<document title>" \
  --arg content "$CONTENT" \
  --argjson user_id "${HARVIS_USER_ID:-0}" \
  '{title: $title, content: $content, format: "docx", sources: [], user_id: $user_id}')

SAVE_RESULT=$(curl -s -X POST http://harvis-ai-merged-backend:8000/api/tools/document-save \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

echo "$SAVE_RESULT"
ARTIFACT_ID=$(echo "$SAVE_RESULT" | jq -r '.artifact_id')
echo "Artifact ID: $ARTIFACT_ID"
```

If `artifact_id` is null or empty, report the error and stop.

### Step 4 — Return structured result

Output the following JSON block so Harvis renders a DOCX download card:

```json
{
  "type": "document_result",
  "title": "<document title>",
  "artifact_id": "<artifact_id from step 3>"
}
```

Then tell the user what you wrote and that they can download it from the document card:
"📄 Your document is ready — download it using the card below."
