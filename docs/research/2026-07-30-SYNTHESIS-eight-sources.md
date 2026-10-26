# Eight sources, one decision — synthesis (2026-07-30)

Eight candidate integrations researched in parallel from primary sources. Per-source docs sit
beside this file; this one exists so the eight plans don't have to be reconciled by hand.

Judged at the **whole-Harvis** level — what capability the product gains — rather than against
whichever subsystem each source superficially resembles.

| # | Source | Verdict | Default cost | Opt-in cost |
|---|---|---|---|---|
| 1 | MODSetter/SurfSense | **HARVEST** (MCP OAuth client) | 0 MB | — (full adoption rejected) |
| 2 | abi/screenshot-to-code | **HARVEST** (prompts + verify loop) | ~0 MB | — (adoption rejected) |
| 3 | zoo.dev | **WRAP** (cloud CAD adapter) | ~0 MB | build123d ~250–350 MB |
| 4 | lightpanda.io | **WRAP** (render-then-extract fetch) | 0 MB | 320 MB profile |
| 5 | blueprint.io | **BUILD-OURS** (electronics exemplar) | 0 MB | ~250–300 MB profile |
| 6 | cheahjs/free-llm-api-resources | **WRAP as reference** | ~0 MB | — |
| 7 | diegosouzapw/OmniRoute | **BUILD-OURS** (vendor catalog only) | 0 MB | 2.63 GB profile |
| 8 | ssrajadh/sentrysearch | **SKIP** unless video search is wanted | 0 MB | ~450–600 MB profile |

**The headline number: every recommended action adds ~0 MB to the default install.** Current fresh
clone is 6.28 GB against a 7.5 GB CI guard. Nothing here spends that headroom. Enabling *every*
optional profile at once would add ~4.15 GB — all opt-in, none in the default set.

---

## Five findings that cut across the whole batch

**1. Licensing was the decisive axis in four of eight, and only one was the obvious kind.**
`free-llm-api-resources` has **no license file at all** (GitHub API: `license: null`) — legally
unusable to vendor, stricter than the AGPL rule that removed PyMuPDF. SurfSense is a **hybrid**:
Apache-2.0 except `app/proprietary/**`, which is **BUSL 1.1** and happens to contain the entire
flagship scraper feature — a boundary the vendor can move at will. Lightpanda is **AGPL-3.0**, but
as an unmodified sidecar spoken to over a socket the obligation attaches to it, not to Harvis.
OmniRoute is cleanly **MIT** and still disqualifying, because the license was never the problem —
its provider terms were. License checks have to run per-directory and per-feature, not per-repo.

**2. Three of the eight were not what the name said.** `area.ai` redirects to a domain-for-sale
page; the products matching the description are Yupp.ai and LMArena. "SentrySearch" is Tesla
**Sentry Mode dashcam** video search, not security or threat intel. And blueprint.io's search
results still describe a *previous* product on the same domain — the current one is the hardware
tool. Identification before evaluation is not a formality.

**3. Measured beat claimed, twice, in opposite directions.** OmniRoute's own `Dockerfile:192` says
"~500 MB"; pulling it measures **2.63 GB**, because a 899 MB `COPY` is followed by a
`RUN chown -R node:node /app` that writes a 919 MB duplicate layer. Lightpanda's CDP
`Page.captureScreenshot` returns a **fake static placeholder PNG** so client tools don't error —
a smoke test built on it would report success with a fabricated image.

**4. The "free credits" product category is data-for-inference, and is not replicable.** Yupp and
LMArena front the inference with VC money and earn on selling users' preference/eval data to labs.
An open-source, privacy-premised project cannot copy that without inverting its own premise. The
honest closest path is BYO free-tier keys with excellent onboarding.

**5. Harvis already had more than expected twice, and less than claimed once.** `browser_runner`
already exposes `POST /screenshot` and is already in the DEFAULT set; an encrypted per-user API-key
store already exists. But **"vision-to-code" is plumbing only** — image→vision-part conversion in
`chat_completion.py` / `moonshot_api.py`, with no pipeline, prompts, or loop behind it.

---

## What to do, ranked

### Tier 1 — do first. Zero size, unblocks things already built.

**1a. Port SurfSense's MCP OAuth 2.1 client.** Apache-2.0, ~2,300 lines, httpx-only:
`.well-known` discovery, Dynamic Client Registration, PKCE S256, token exchange. This is exactly
task #97, it unblocks the **15 `remote_oauth` storefront cards** whose UI already ships, and it
pairs with the MCP stdio runtime built earlier today — which together take the storefront from
"14 of 71 cards can work" to "29 of 71." Pin to commit `4e9225b1` with attribution; keep well
clear of `app/proprietary/**`.

**1b. Harvest screenshot-to-code's prompts and verify loop.** MIT (pin `d026163f` — the repo has
zero releases). The prize is the **screenshot-verify-fix loop**: after each file write the model is
required to call `screenshot_preview`, which renders at desktop *and* mobile viewports and returns
PNGs as multimodal parts, then fixes defects with exact-string edits rather than regenerating.
Harvis can run this with **no new services**. Two traps: the stock frontend puts provider API keys
in the browser (violates `model_proxy` outright — do not port that path), and its frontend
Dockerfile is broken, `COPY`ing a `yarn.lock` that a pnpm repo doesn't have.

### Tier 2 — high value, blocked on one decision each.

**2a. zoo.dev cloud CAD adapter** — *the user's stated priority.* The export question is answered
**yes**: STEP/STL/OBJ/PLY/glTF/GLB/FBX out, KCL source with every generation, and the spec states
STEP is the source of truth. The STEP is **true analytic B-rep, not a baked mesh**; the caveat is
that STEP carries no feature tree, so parameters live only in the KCL and re-execution needs Zoo's
cloud. Auth is a plain bearer token, so the missing OAuth client is **not** a blocker here.
$0.0083/compute-second with $10 free credits/month. Use a plain-httpx adapter; **reject the
`kittycad` SDK** (drags pymongo + phonenumbers, ~30–60 MB). Composes with the locked decision: Zoo
generates, build123d re-imports the STEP locally and runs the Stage-1 gates before any claim.
*Blocked on:* the free tier trains on your data with no opt-out, and the ToS resale prohibition
makes BYO-key-per-user mandatory. Also corrects the prior scan — standard Zoo is **not** an ITAR
environment; that's a separate enterprise product.

**2b. Lightpanda as render-then-extract fetch.** The whole-Harvis framing matters here.
`browser_runner/app.py` is Selenium+Firefox exposing `/session`, `/navigate`, `/act`, `/close`,
`/screenshot` — **no content-extraction endpoint** — and only three backend files reference it
(`discord_workspace_bot.py`, `tools/openclaw_proxy.py`, `main.py`). `research/` doesn't touch it at
all. So "render a JS page, return its post-JS DOM as text" is done by **nothing in Harvis today**,
and that gap sits under the `research/` pipeline, the web-fetch proxy, the Web Research toggle
(which reaches sites via `exec` + `curl`, i.e. pre-JS HTML), `/api/fact-check`,
`/api/comparative-research`, K3 URL ingestion, open-notebook web sources, and Discord research —
roughly eight surfaces, all silently returning thin content on JS-rendered sites. Lightpanda
measures **320 MB vs browser-runner's 864 MB**, but it is *additive*, never a replacement: both
existing consumers are screenshot pipelines it would break silently. *Blocked on:* the AGPL call.
Also note it's Beta by its own README, and arm64 is first-class — favorable for the deferred ARM
work.

### Tier 3 — real capability, larger build.

**3a. Electronics as a second Adaptive Space exemplar** (from blueprint.io's validated shape, not
its code — it has no public API and no EDA export). Sibling template pack beside
`workspace_methods/fabrication.py`, reusing `fab_cad.py`'s flag-gated sidecar pattern and
`fab_stress.py`'s blocked-language gate. The split is the point: **the LLM writes circuit-as-code,
a deterministic checker owns correctness** — SKiDL for netlist + electrical-rule checking,
schemdraw for rendering, then Nexar/DigiKey BOM enrichment at lane 5. Safety gate to keep verbatim:
unverified output is labelled "concept sketch — UNVERIFIED," ERC verdict codes gate all phrasing,
and mains / >48 V / Li-ion charging / >5 A always force "requires qualified review before
energizing," with "safe" never available.

**3b. BYO-key provider catalog.** Worth doing on its own merits independent of source #6: the real
gap found is that **`model_proxy.py` reads env keys only**, while an encrypted per-user key store
already exists (`user_api_keys` + `/api/user/api-keys/*`). Hand-build the catalog — the upstream
list is unlicensed and cannot be vendored — and take OmniRoute's **205 typed `RegistryEntry`
records** (MIT, no CLA) as the data seed instead.

### Tier 4 — skip.

**4a. OmniRoute the container: SKIP.** 2.63 GB pushes 6.28 → 8.97 GB, past both the goal and the
CI guard. More decisive than size: its own `docs/reference/FREE_TIERS.md` maintains a ToS-attention
table naming ~15 providers whose terms **explicitly ban proxying**, plus ~20 more ambiguous; and
`src/shared/constants/providers/web-cookie.ts` defines **31 providers driven by the user's browser
session cookie** (ChatGPT Plus, Gemini, Grok, Perplexity Pro) with 38 entries flagged
`subscriptionRisk: true`. `SECURITY.md` lists TLS-fingerprint spoofing and CLI header-order
impersonation as features. For software shipped to third parties the realistic outcome is banned
personal accounts. Separately: `src/lib/db/encryption.ts` runs in **passthrough (plaintext) mode**
whenever `STORAGE_ENCRYPTION_KEY` is unset, while the README advertises AES-256-GCM
unconditionally. Take the catalog; leave the router. (Claims corrected: 35,374 stars — not 19.1K,
nearly doubled in 12 days — 5,935 commits, 19 routing strategies, 205 registry entries, ~104 MCP
tools. The no-client-key invariant does survive: it's an HTTP sidecar, so `_resolve_route()` at
`workspace/model_proxy.py:211` is a one-branch seam.)

**4b. SurfSense as a whole: SKIP.** 2.20 GB compressed / ~5.5–7 GB on disk, nine services including
pg17 with `wal_level=logical`, Redis, Celery worker+beat and Rocicorp zero-cache. `sentence-transformers`
is mandatory so torch always comes in. It exceeds the entire budget alone and its notebook core
duplicates open-notebook and K3. Secondary harvest worth noting: its hybrid retriever does pgvector
+ `ts_rank_cd` + reciprocal rank fusion **entirely in SQL** — torch-free and portable onto the
existing pgvector.

**4c. sentrysearch: SKIP** unless video search is genuinely wanted. Apache-2.0 and better-engineered
than its profile suggests (~5,171 LOC against ~4,000 LOC of tests, CI on three OSes × two Pythons),
but it's v0.1.0, effectively single-maintainer, and has **zero relevance to the NCL/CTF angle** that
was its plausible home. If wanted: MCP-wrap it as a sibling stdio container (~1–2 days now that the
runtime exists); do **not** use its bundled OpenClaw skill, since the OpenClaw pod is egress-denied
and the default backend needs the Gemini API.

---

## Distro impact

| | Linux (compose) | Windows Harvis (WSL2) | K8s |
|---|---|---|---|
| MCP OAuth port | native | unaffected | needs a public callback URL / ingress |
| screenshot-to-code harvest | native | unaffected | unaffected |
| zoo.dev adapter | native | unaffected | **CoreDNS entry for `api.zoo.dev`** (some networks block UDP/53); CDN-backed, so pinned IPs drift |
| Lightpanda | native | ships as a Linux container — **no native Windows binary needed**; arm64 first-class | fine |
| electronics sidecar | native | unaffected | fine |
| provider catalog | native | unaffected | **CoreDNS entries per provider domain** |
| sentrysearch (if taken) | native | unaffected | local-model backend needs GPU passthrough — excluded from default anyway |

Nothing in this batch requires GPU passthrough in its recommended form, and nothing needs a native
Windows binary — every recommended component ships as a Linux container or as Python inside the
existing backend image. The recurring K8s cost is the CoreDNS workaround for outbound DNS.

---

## Open questions — user only

1. **Does the MCP OAuth port jump the queue?** It's self-contained, Apache-2.0, zero size, and
   unblocks 15 cards whose UI already ships.
2. **zoo.dev free tier trains on prompts with no opt-out** — acceptable behind a consent dialog, or
   should the docs steer users to Plus at $20/mo?
3. **Approval to spend a few free-tier dollars** verifying a generated STEP round-trips into
   build123d and measuring real per-generation cost. Without it the plan rests on the spec.
4. **Is an AGPL sidecar acceptable?** It's the gate on the only Lightpanda use case that survives.
5. **Green-light electronics as a second Adaptive Space exemplar** now, or after forge-fab Stage 1?
6. **Do you want video search at all** — or was that slot meant for a real security/threat-intel tool?
7. **Catalog default: OpenRouter or Google AI Studio?** Google's free tier is more generous but
   trains on user data.
8. **Attribution posture** for vendored catalog rows: credit OmniRoute at a pinned tag, or re-derive
   each row from the provider's own docs so Harvis carries no upstream link.

## Still unanswered from before

**"Agent reach"** — zero hits anywhere in the vault or the repo. The closest thing on record is the
Repo Runner's autonomy ladder (observe → prepare → sandbox action → modify workspace → external
service → real-world device).
