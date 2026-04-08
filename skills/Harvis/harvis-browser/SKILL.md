---
name: harvis-browser
description: >
  Interactive browser automation skill — opens real browser sessions, navigates
  websites, clicks elements, fills forms, takes screenshots. Use when asked to
  interact with a website or when you need to visually inspect a web page.
metadata:
  openclaw:
    emoji: "\U0001F310"
    always: false
    requires:
      bins: [curl, jq]
---

# Harvis Browser Skill

You have access to a real Firefox browser via the browser-runner sidecar.
All commands go through the Harvis backend proxy at `http://backend:8000/api/tools/browser/*`.

**NEVER type curl commands as text. ALWAYS call the `exec` tool.**

Every request MUST include `workspace_id` and `capability_token` in the JSON body.
These are provided in your directive as `$BROWSER_WORKSPACE_ID` and `$BROWSER_CAP_TOKEN`.

Auth headers required on every call:
- `Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN`
- `X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}`

---

## Step 1 -- Open a browser session

Call `exec` with:

```
curl -s -X POST http://backend:8000/api/tools/browser/session \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","headless":true}'
```

Save the `sessionId` from the response. You need it for all subsequent calls.

## Step 2 -- Navigate to a URL

URLs MUST use `https://`. Allowed domains include: github.com, claude.ai, anthropic.com,
stackoverflow.com, developer.mozilla.org, docs.python.org, npmjs.com, pypi.org,
react.dev, nextjs.org, and others in the allowlist.

Call `exec` with (replace SESSION_ID and TARGET_URL):

```
curl -s -X POST http://backend:8000/api/tools/browser/navigate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID","url":"TARGET_URL"}'
```

Returns: `{"url": "...", "title": "..."}` with the final page URL and title.

## Step 3 -- Take a screenshot (to see the page)

Call `exec` with:

```
curl -s -X POST http://backend:8000/api/tools/browser/screenshot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID"}'
```

Returns: `{"artifact_path": "browser/xxx.png"}` -- the screenshot is saved as an artifact.

## Step 4 -- Interact with elements

### Click an element

```
curl -s -X POST http://backend:8000/api/tools/browser/act \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID","action":"click","selector":"CSS_SELECTOR"}'
```

### Type into an input field

```
curl -s -X POST http://backend:8000/api/tools/browser/act \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID","action":"type","selector":"CSS_SELECTOR","text":"TEXT_TO_TYPE"}'
```

### Press a key (enter, tab, escape)

```
curl -s -X POST http://backend:8000/api/tools/browser/act \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID","action":"press","key":"enter"}'
```

### Wait for an element to appear

```
curl -s -X POST http://backend:8000/api/tools/browser/act \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID","action":"waitForSelector","selector":"CSS_SELECTOR","timeoutMs":10000}'
```

## Step 5 -- Close the session when done

Always close the browser session when finished:

```
curl -s -X POST http://backend:8000/api/tools/browser/close \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "X-OpenClaw-SessionKey: ${OPENCLAW_SESSION_KEY:-main}" \
  -d '{"workspace_id":"'"$BROWSER_WORKSPACE_ID"'","capability_token":"'"$BROWSER_CAP_TOKEN"'","sessionId":"SESSION_ID"}'
```

---

## Workflow pattern

1. Open session -> get sessionId
2. Navigate to URL
3. Screenshot to see what's on the page
4. Act (click/type/press) on elements
5. Screenshot again to verify
6. Repeat 3-5 as needed
7. Close session

## Tips

- Always take a screenshot after navigating to see the page state.
- Use CSS selectors for elements. Common patterns: `button`, `a[href*="login"]`, `input[name="q"]`, `#id`, `.class`.
- If a click navigates to a new page, take a screenshot to see the result.
- If an element is not found, take a screenshot first to understand the page layout.
- The `timeoutMs` parameter on act defaults to 10000 (10 seconds).
- Sessions are isolated -- each session is its own browser window.
