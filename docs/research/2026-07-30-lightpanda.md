# Lightpanda — research and integration plan (2026-07-30)

Candidate: https://lightpanda.io · https://github.com/lightpanda-io/browser
Researched from primary sources only: the repo README, LICENSE file, the project's own
issue tracker, GitHub/Docker Hub APIs, and a local pull of the official image. Every
load-bearing number below was either read from the primary source or measured on this
machine; where something could not be verified it is marked as such.

---

## 1. What it actually is

**License: AGPL-3.0.** Verified directly from the LICENSE file — title line reads
"GNU AFFERO GENERAL PUBLIC LICENSE Version 3, 19 November 2007"
(https://raw.githubusercontent.com/lightpanda-io/browser/main/LICENSE; GitHub API
`license.spdx_id` = `AGPL-3.0`). Harvis has a zero-AGPL precedent (PyMuPDF was removed
purely for being AGPL). The legal posture here is different — see §7 — but this is a
decision gate before anything else in this document happens.

**Maturity: Beta, stated by the project itself.** README: *"Lightpanda is in Beta and
currently a work in progress. Stability and coverage are improving and many websites now
work. You may still encounter errors or crashes."* Versioned releases exist (0.3.4 →
0.3.6 between 2026-07-01 and 2026-07-25, so roughly biweekly), plus a `nightly` Docker
tag. Not production-ready by its own admission — its "Missing features" issue (#1799) is
titled *"Current limitations (v0.x — not yet production-ready)"*.

**Activity/adoption** (GitHub API, 2026-07-31): 33,128 stars, ~1.5k forks, repo created
2023-02-07, last push 2026-07-31 (i.e. active daily), 75 open issues+PRs.

**What it is:** a headless browser engine written from scratch in Zig — *"Not a Chromium
fork. Not a WebKit patch."* It embeds **V8** for JavaScript, uses libcurl for HTTP and
html5ever for HTML parsing, and builds a real DOM with DOM APIs, XHR/Fetch, cookies,
custom headers, proxy support, and network interception. **It has no graphical rendering
engine at all — by design.** The tagline is "JavaScript execution, no graphical
rendering." It can dump the post-JS DOM as HTML or Markdown. It runs a WebSocket **CDP
server** (`lightpanda serve`) so Chrome-protocol clients can drive it.

**The speed comes from not doing the work.** There is no layout in the browser-rendering
sense (issue #1799 admits "Partial CSS layout — incomplete Flexbox/Grid"), no paint, no
compositor, no GPU path. That is exactly why it is small and fast, and exactly why it
cannot do the visual half of what Harvis's `browser-runner` does.

## 2. Capability matrix

| Capability | Status | Source |
|---|---|---|
| HTML parse + DOM + DOM APIs | Yes | README |
| JavaScript execution (V8) | Yes | README |
| XHR / Fetch | Yes | README |
| **CORS** | **No — not implemented** (open #2015) | issue tracker |
| Cookies, custom headers, proxy | Yes | README |
| Network interception, robots.txt | Yes | README |
| Click + form input | Yes | README |
| DOM dump to HTML/Markdown | Yes | README |
| CSS layout | **Partial** — "incomplete Flexbox/Grid" | #1799 (project's own words) |
| **Screenshots** | **NO. Worse than no: `Page.captureScreenshot` returns a FAKE static placeholder PNG** so client tooling doesn't error (#2228 closed as fake-impl; #1766 resizes the fake to 1920×1080 "to be consistent w/ layout size returned") | #2228, #2197, #1766, #2204 |
| PDF (`Page.printToPDF`) | **Fake** — "returning a fake result instead of an error" | #2197 |
| Canvas / WebGL | No — "no visual rendering" | #1799 |
| WebSockets (in-page) | "Limited" | #1799 |
| Service Workers / Web Workers / WebRTC | Missing | #1799 |
| **CDP server** | Yes, WebSocket (`lightpanda serve`) | README |
| **Puppeteer** | Works via `puppeteer.connect({browserWSEndpoint})` — the documented, first-class client | README |
| **Playwright** | Partial. `chromium.connectOverCDP()` connects, but the project's own open issue #3076 says standard Playwright suites "may encounter unsupported commands, incomplete isolation, timeouts, or **silently degraded behavior**"; assertion-error crashes tracked in #1838/#1839; Python Playwright historically problematic (#552, #2754) | issue tracker |
| Docker image | `lightpanda/browser:nightly`, linux/amd64 + linux/arm64 | Docker Hub |
| Platforms | Linux x86_64/aarch64 (glibc), macOS x86_64/aarch64; **Windows: WSL2 only, no native binary** | README |

**The screenshot finding deserves emphasis:** a Puppeteer script calling
`page.screenshot()` against Lightpanda gets back a *valid PNG that is not the page*.
Any pipeline that consumes that image (a smoke-test verdict, a Discord preview, a
vision-model call) would silently operate on garbage. This is not a gap you can degrade
around; it is a gap that actively lies if you forget about it.

### Performance claims and whether they hold

Site + README claim, for 100 pages out of a 933-real-page corpus fetched over the network
on an AWS EC2 m5.large: **123 MB peak RAM vs headless Chrome's 2 GB (~16×), 5 s vs 46 s
execution (~9×)**, driven via chromedp. Assessment: the methodology is disclosed and the
direction is obviously credible — an engine that skips layout, paint, compositing, GPU,
and most Web APIs must beat full Chrome on both axes. The exact multipliers are
self-published and not independently verified here, and the comparison is structurally
favorable (Chrome is doing work Lightpanda has not implemented; Chrome also successfully
loads pages Lightpanda crashes on — beta caveat is theirs). Treat "much smaller and much
faster on the pages it can handle" as true; treat the 9×/16× as marketing-grade.

### Measured sizes (this machine, 2026-07-31)

- `lightpanda/browser:nightly` Docker image: **320 MB on disk** (75.7 MB compressed pull; arm64 variant ~same).
- Standalone 0.3.6 binary: 153.5 MB (x86_64-linux), 158.7 MB (aarch64-linux); 30.7 MB .deb.
- Harvis `harvis-browser-runner` (firefox-esr): **864 MB** (measured, and stated in its Dockerfile).
- Chromium alternative: already measured and rejected in `browser_runner/Dockerfile` —
  on Debian trixie chromium is 724.5 MB vs firefox-esr's 405.3 MB, i.e. **319 MB worse**.
  A headless-chromium runner image would land around ~1.2 GB.

## 3. Verdict per use case

### 3a. Repo Runner Phase 2 (load app, screenshot, interact, smoke-report) — **SKIP**

Killed by the screenshot gap alone: Lightpanda cannot render, and its CDP screenshot
endpoint returns a fake placeholder — a Phase 2 smoke test built on it would attach a
fake "screenshot" and could pass while the app is visually broken. Beyond that, Repo
Runner targets modern dev servers (Vite/Next): partial flexbox/grid layout, no canvas,
limited in-page WebSockets (Vite HMR runs over WebSocket), and missing CORS make even
DOM-level assertions unrepresentative of a real browser. Keep the firefox-esr
`browser-runner` for Phase 2. (A community fork adding "a minimal rendering path" exists
— issue #2343 — but it is an experiment, not upstream.)

### 3b. Web research / JS-rendered fetch — **WRAP** (adopt behind a flag, with fallback)

This is what Lightpanda is actually for, and the fit is genuine. The research pipeline's
extractor (`python_back_end/research/extract/html_trafilatura.py` behind
`extract/router.py`) does static HTTP fetch; JS-rendered SPAs come back empty. Lightpanda
executes JS and dumps the resulting DOM as HTML/Markdown at ~1/6 the RAM of a full
browser and a 320 MB image. Conditions: (1) the AGPL decision in §7 goes your way;
(2) it is a *fallback tier*, not the primary fetcher — beta crashes and missing CORS mean
some pages will render wrong or not at all, so on failure/empty output the pipeline falls
back to the plain fetch result; (3) lane-5 flag-gated, default OFF, same as every other
external-fetch surface.

### 3c. Replacing the 864 MB `browser-runner` — **SKIP** (complement, never replace)

`browser-runner`'s two consumers exist precisely to rasterize pages:
`tools/openclaw_proxy.py` (session/navigate/act/**screenshot** tool surface, lines
429–582) and the Discord artifact renderer
(`integrations/discord_workspace_bot.py:1275`, HTML/SVG → PNG). Both are screenshot
pipelines. Lightpanda would break both — silently, with fake PNGs. The 544 MB saving is
not recoverable this way. The honest size story: Lightpanda is **additive** (+320 MB, or
~230 MB with a self-built minimal image), which is why it must ride a non-default profile
(§5).

## 4. Integration plan — pluggable browser backend

**Phase 0 — decision gate (user).** AGPL yes/no per §7. Nothing proceeds without it.

**Phase 1 — abstraction + service (flag `HARVIS_LIGHTPANDA_URL`, unset = disabled).**

- New module `python_back_end/browsing/` with a `BrowserBackend` protocol:
  `capabilities() -> {"render_dom": bool, "screenshot": bool, "interact": bool}` and
  `render(url, *, wait_ms, headers) -> RenderedPage(html, final_url, status)`.
  Two implementations:
  - `FirefoxRunnerBackend` — thin wrapper over the existing `http://browser-runner:8765`
    API (screenshot-capable, the only backend allowed to answer screenshot requests).
  - `LightpandaBackend` — **raw CDP over WebSocket** (Target.createTarget →
    Page.navigate → Page.loadEventFired → Runtime.evaluate `outerHTML`, ~150 lines on
    the `websockets` lib). Deliberately NOT playwright-python: Lightpanda's own tracker
    documents Playwright-over-CDP assertion crashes and "silently degraded behavior"
    (#1838/#1839/#3076). Puppeteer is their first-class client but the backend has no
    Node. Raw CDP uses only the four domains Lightpanda demonstrably serves.
  - A router that dispatches by required capability; any request needing `screenshot`
    can never reach Lightpanda, structurally.
- Compose: `lightpanda` service, **profile `research-browser` (not in the default set)**,
  image pinned by digest (nightly moves; alternatively build a ~230 MB image from the
  tagged 0.3.6 release binary for reproducibility), command
  `serve --host 0.0.0.0 --port 9222`, hardened exactly like the sibling pattern:
  `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `mem_limit: 512m`,
  `pids_limit`, no volumes, **no `ports:`**, `expose: 9222` only. Network: it must have
  egress to fetch pages, so it does NOT sit on `openclaw-internal` (internal: true);
  give it the egress network + reachability from backend only.
- **Authz:** the new `web_render` action routes through `authorize_action()`
  (`python_back_end/workspace/orchestration/authz.py`) as lane 5
  (`LANE_EXTERNAL_SERVICES`) — flag-gated, default OFF, same lane as web-fetch today.
- **SSRF:** enforced in the backend *before* the URL is handed to Lightpanda — reuse the
  existing private-IP/localhost blocking from the web-fetch proxy. Residual risk:
  Lightpanda re-resolves DNS itself (rebinding window) and the *page's own JS* can fetch
  arbitrary URLs from inside the container. Mitigate at the network layer: an egress rule
  on the lightpanda network blocking RFC1918/loopback, mirroring the K8s NetworkPolicy in
  §6. Audit every render to `openclaw_tool_audit`.
- **Injection boundary:** rendered output is data, never instructions. The backend
  returns Lightpanda's DOM dump only through the same wrapping used for web-fetch
  results today — delimited untrusted-content blocks handed to the model as quoted
  material, scripts stripped, length-capped. No rendered text ever reaches a system
  prompt, tool argument, or `authorize_action` input. The model acting on hostile page
  text is contained the same way it is for the existing fetch path; Lightpanda changes
  what can be *read*, not what can be *executed*.

**Phase 2 — research pipeline wiring.** In `research/extract/router.py`: when
trafilatura extraction yields near-empty text and the flag is on, re-fetch via
`LightpandaBackend`, run trafilatura on the rendered HTML, fall back to the static
result on any error. No behavior change with the flag off.

**Phase 3 (optional) — agent tool.** Expose `web_render` through the OpenClaw proxy
alongside web-search/web-fetch, honoring `X-Live-Web` semantics and the same
allowlist/rate-limit code paths.

## 5. Size cost

| | Image on disk | Default install impact |
|---|---|---|
| browser-runner (firefox-esr) — today | 864 MB | already counted (6.28 GB total) |
| chromium swap (measured, rejected in-repo) | ~1.18 GB | +319 MB — worse |
| Lightpanda official nightly | **320 MB** | **0 MB if profile-gated (recommended)**; +320 MB if default |
| Lightpanda self-built from 0.3.6 binary | ~230 MB est. (154 MB binary + slim base) | same logic |

Recommendation: ship under the `research-browser` profile, default OFF. The default
install stays at 6.28 GB; users who enable live web research pay 320 MB. Do not add it
to the default set — it would consume ~45% of the remaining headroom to the 7 GB target
for a lane-5 feature that ships disabled anyway. RAM: their claim is ~123 MB peak across
a 100-page batch; a 512 MB `mem_limit` is comfortable (vs the firefox runner, where a
single session comfortably exceeds that).

## 6. Distro notes

- **Linux + docker compose (primary):** first-class. glibc x86_64 binary, official
  amd64 image, verified pull + run locally.
- **Windows Harvis (Docker Desktop/WSL2):** fine. There is no native Windows binary
  (README: WSL2 only), but that is irrelevant — Harvis ships it as a Linux container,
  and Docker Desktop runs Linux containers in WSL2. No Windows-specific work needed.
- **macOS dev (outside Docker):** native binaries exist for both arches if anyone wants
  to run it bare; not needed for the containerized design.
- **K8s:** plain Deployment; no privileged/GPU/SYS_ADMIN needs (unlike Chrome, no
  sandbox-related capability juggling). NetworkPolicy: ingress only from
  `app: backend`; egress allow 0.0.0.0/0 *except* RFC1918 + link-local + cluster CIDRs
  — this is the infra-level SSRF backstop.
- **arm64:** favorable groundwork — official aarch64 Linux binary and linux/arm64 image
  are published (verified via Docker Hub manifest, 75.9 MB compressed). Better arm64
  story than the current firefox-esr runner has been tested for.

## 7. Risks, license and ToS traps

- **AGPL-3.0 — the gate.** The precedent (PyMuPDF removed for AGPL) concerned an
  *imported, linked Python library*, where AGPL propagates to the combined work.
  Lightpanda as an **unmodified upstream container spoken to over a network socket** is
  the classic "separate program / mere aggregation" posture: AGPL obligations (source
  availability, §13 network clause) attach to Lightpanda itself and are satisfied by
  running the unmodified public image; Harvis's MIT code does not link against it. This
  is the same posture as shipping an AGPL database in a compose file. BUT: (a) this is a
  reasoned interpretation, not legal advice; (b) the project has so far held a
  zero-AGPL line, and holding a bright line has value; (c) if Harvis ever *patches*
  Lightpanda, §13 obligations bite immediately. Rules if adopted: unmodified upstream
  only, pinned digest, license surfaced in third-party notices. **User decision.**
- **Cloud offering is separate and proprietary** ("Request API Access", no public
  pricing/terms). Irrelevant to self-hosting the AGPL binary; never wire Harvis to the
  cloud endpoint.
- **Fake screenshot/PDF endpoints.** The single sharpest trap: CDP calls *succeed* with
  plausible fake artifacts. The capability router in §4 must make screenshot requests
  structurally unroutable to Lightpanda — not merely discouraged.
- **Young engine, silent rendering differences.** No CORS means in-page requests succeed
  that a real browser would block (and behavioral divergence generally): extracted
  content can differ from what a human's browser shows, with no error raised. Missing
  Service/Web Workers and limited WebSockets silently break some SPA frameworks. This is
  acceptable for best-effort research fetch *with fallback*, and disqualifying for
  anything that asserts "the app works."
- **Beta stability.** The README warns of crashes. Health-check the service; every
  caller must degrade to the static fetch path.
- **Nightly churn.** The `nightly` tag moves daily; pin by digest or build from a tagged
  release.
- **Verify before trusting (concrete pre-adoption checks):** run the actual research
  corpus's top-N JS-heavy domains through `LightpandaBackend` and diff extraction yield
  vs static fetch; confirm the raw-CDP client survives a Lightpanda crash mid-session;
  confirm memory under the 512 MB limit on real pages; re-check the license file at the
  pinned commit.

## 8. Open questions (user-only)

1. **AGPL:** is "unmodified AGPL sidecar container, network-isolated, never linked"
   acceptable, or does the zero-AGPL bright line from the PyMuPDF removal apply to
   containers too? This is the go/no-go.
2. **Profile placement:** agree that Lightpanda ships in a non-default
   `research-browser` profile (0 MB default cost), rather than default (+320 MB)?
3. **Image provenance:** pin the upstream `lightpanda/browser` digest, or build our own
   ~230 MB image from the tagged release binary (more reproducible, slightly more
   maintenance)?
