---
name: harvis-browser
description: >
  Interactive browser automation skill — opens real browser sessions, navigates
  websites, clicks elements, fills forms, takes screenshots. Use when asked to
  interact with a website or when you need to visually inspect a web page.
  Only available in BYO mode or when explicitly enabled.
metadata:
  openclaw:
    emoji: "\ud83c\udf10"
    always: false
    requires:
      bins: [curl, jq]
---

# Harvis Browser Skill

You have access to a real browser via the browser-runner sidecar.
All commands go through the Harvis backend proxy at `http://backend:8000/api/tools/browser/*`.

**NEVER type curl commands as text. ALWAYS call the `exec` tool.**

Every request MUST include `workspace_id` and `capability_token` in the JSON body.
These are provided in your directive as `$BROWSER_WORKSPACE_ID` and `$BROWSER_CAP_TOKEN`.

Auth headers required on every call:
- `Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN`
- `X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}`

---

## Step 1 — Open a browser session

```bash
curl -s -X POST http://backend:8000/api/tools/browser/session \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","headless":true}'
```

Save the `sessionId` from the response.

## Step 2 — Navigate to a URL

URLs MUST use `https://`.

```bash
curl -s -X POST http://backend:8000/api/tools/browser/navigate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID","url":"TARGET_URL"}'
```

## Step 3 — Take a screenshot

```bash
curl -s -X POST http://backend:8000/api/tools/browser/screenshot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID"}'
```

Returns: `{"artifact_path": "browser/xxx.png"}`

## Step 4 — Interact with elements (click, type, press, waitForSelector)

```bash
# Click
curl -s -X POST http://backend:8000/api/tools/browser/act \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID","action":"click","selector":"CSS_SELECTOR"}'

# Type
# Same but: "action":"type","selector":"CSS_SELECTOR","text":"TEXT_TO_TYPE"

# Press key
# Same but: "action":"press","key":"enter"

# Wait for element
# Same but: "action":"waitForSelector","selector":"CSS_SELECTOR","timeoutMs":10000
```

## Step 5 — Close the session when done

Always close when finished:

```bash
curl -s -X POST http://backend:8000/api/tools/browser/close \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID"}'
```

## Workflow pattern

1. Open session -> get sessionId
2. Navigate to URL
3. Screenshot to see the page
4. Act (click/type/press) on elements
5. Screenshot again to verify
6. Repeat 3-5 as needed
7. Close session
