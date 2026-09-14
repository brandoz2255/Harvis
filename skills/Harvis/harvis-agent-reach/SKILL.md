---
name: harvis-agent-reach
description: >
  Lane-5 Web Research helpers via Harvis backend tools (agent_reach.*).
  Zero-config: web_search, web_read, yt_transcript, gh_view, rss_read. Never call raw
  Agent Reach CLIs inside OpenClaw (egress-denied).
metadata:
  openclaw:
    emoji: "📡"
  harvis:
    requires_flag: HARVIS_AGENT_REACH_ENABLED
    risk_lane: 5
---

# Harvis Agent Reach (research / lane 5)

Use **Harvis tool names** only. Egress lives in the Harvis backend proxy — not
in the OpenClaw pod.

## Tools

| Tool | Purpose |
|------|---------|
| `agent_reach_web_search` | Find pages for a query — numbered results, no page bodies. Start here whenever you do not already have the URL |
| `agent_reach_web_read` | Readable text for a public URL (Jina) |
| `agent_reach_yt_transcript` | YouTube captions |
| `agent_reach_gh_view` | Public GitHub file — a `https://…` GitHub URL, or the shorthand `owner/repo/path[@ref]` (ref defaults to `main`) |
| `agent_reach_rss_read` | Public RSS/Atom feed items |

Requires `HARVIS_AGENT_REACH_ENABLED=1`. If denied, say so and fall back to
existing `/api/tools/search` + `web-fetch` when Web Research / live_web is on.

## Reading the results

- Only public internet addresses are reachable. Anything that resolves to a
  private, loopback, or link-local address is refused with `DENIED:` — that is
  the SSRF guard working, not a transient error. Do not retry it, and do not
  try to reach an internal host by IP, by redirect, or by a name that resolves
  to one.
- A reply starting with `ERROR:` or `DENIED:` is a **failure**. Never summarise
  it as though you read the page.
- `rss_read` with `"ok": true, "count": 0` means a real feed with nothing
  published. A feed you could not read comes back as `ERROR:` instead — the two
  are not the same, so say which one happened.
- Never assemble a URL from memory and hand it to `web_read` — a guessed path is
  usually a 404, and a model that guesses is exactly the model being asked a
  question its weights cannot answer. Search first, read what came back.
- `web_search` with `"ok": false, "error": "no results"` found nothing. Say that;
  do not answer from memory as if the search had succeeded.
- `web_read` routes the URL through the third-party reader `r.jina.ai`
  (`"via": "jina"` in the result). Do not send it URLs containing tokens,
  session ids, or anything private.

## Do not

- Do not install `agent-reach` inside OpenClaw.
- Do not use cookie/session CLIs for Twitter, Reddit, etc. in default product.
- Do not widen OpenClaw NetworkPolicy egress.
