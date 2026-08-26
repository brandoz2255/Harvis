# Agent Reach placement (Harvis)

Date: 2026-08-01 · Status: Phase 0–1 scaffold

Upstream: https://github.com/Panniantong/agent-reach (MIT)

## Locked placement

| Layer | Role |
|-------|------|
| Flag `HARVIS_AGENT_REACH_ENABLED` | Default OFF; lane-5 gate in `authz.py` |
| Module `python_back_end/agent_reach/` | Zero-config tools (Jina, YT, GH, RSS) |
| Build tools `agent_reach.*` | Advertised only when flag on. **Build/workspace only — the Chat lane is NOT wired** |
| Compose profile `agent-reach` | Optional sidecar placeholder — not required for Phase 1 |
| OpenClaw pod | **No install, no egress widen** |

## Phase 1 tools

- `agent_reach.web_read`
- `agent_reach.yt_transcript`
- `agent_reach.gh_view`
- `agent_reach.rss_read`

Cookie platforms: later or never in default distro.

## Egress containment (implemented 2026-08-01)

Every tool goes through `agent_reach.tools._safe_get`, which:

1. rejects any scheme other than http(s);
2. resolves DNS itself and refuses the request if **any** A/AAAA record is
   private, loopback, link-local, reserved, multicast, unspecified, or an
   IPv4-mapped form of one — a name that answers with both a public and an
   internal address is treated as an attack, not a multi-homed host;
3. **pins the TCP connection to a validated address**, carrying the real
   hostname in the `Host` header and in the TLS SNI so certificate verification
   is unaffected. This is what closes the DNS-rebinding window between our
   lookup and the HTTP client's own lookup;
4. follows redirects **manually**, re-running steps 1–3 on every hop (capped at
   5). httpx's built-in `follow_redirects=True` was the original hole: hop 1 was
   validated and hops 2..n were not;
5. verifies after connect that the peer address really is public, and caps the
   response body at 8 MB.

`gh_view` additionally carries its host allowlist across redirects, so a GitHub
URL cannot be bounced off-platform.

Verified live: `127.0.0.1`, `localhost`, `[::1]`, `10.0.0.5`, `169.254.169.254`,
the internal service names `pgsql` and `browser-runner`, and the rebinding name
`127.0.0.1.nip.io` are all refused, while `example.com` and an
`http://github.com` → HTTPS redirect chain both succeed.

## Failure honesty

`rss_read` used to return `{"ok": true}` unconditionally — a non-feed page came
back as a successful read with zero items. It now distinguishes a well-formed
but empty feed (`ok: true`, `count: 0`) from an unreadable payload (`ok: false`
plus the content-type it actually received). `dispatch_agent_reach` converts any
`ok: false` result into an `ERROR: …` string, because the caller in
`workspace/orchestration/tools.py` decides success by testing for that prefix
and was otherwise reading failure JSON as a successful tool call.

`yt_transcript` reports `ok: false` when no captions exist, and now runs the
synchronous extractor via `asyncio.to_thread` instead of blocking the event
loop for up to 25 seconds.

## Privacy

`web_read` proxies through the third-party reader at `r.jina.ai`, so every URL
read this way is disclosed to that operator. The result carries `"via": "jina"`
so the disclosure is visible in the tool output and in any audit of it.

## Closest cousins

Web Research toggle, `openclaw_proxy` web-fetch/search, `python_back_end/research/`.
