# blueprint.io — identified — and the Harvis electronics-design capability

Research date: 2026-07-30. Sources are primary (the live site's HTML/JS bundle, the vendor's investor page, upstream project repos) unless marked otherwise. Everything quoted below was actually observed; anything unverifiable is flagged as such.

---

## 1. What blueprint.io actually is

**Definitive answer: blueprint.io is exactly the product the user described.** It is a consumer web app called **Blueprint** (also branded **Blueprint.am / "Blueprint AM"**), made by **Blueprint Labs / 3E8 Robotics Inc.**, that generates hardware build plans from a text prompt.

Primary evidence, from the live site's own `<head>` (fetched 2026-07-30 via `curl https://www.blueprint.io`):

> `<title>Blueprint - AI Hardware Design Tool</title>`
> `<meta name="description" content="Blueprint by Blueprint Labs — design hardware projects with AI. Generate wiring diagrams, bills of materials, and step-by-step assembly guides from a single prompt." />`
> schema.org JSON-LD: `"name": "Blueprint", "alternateName": ["Blueprint AM"], "creator": {"@type": "Organization", "name": "Blueprint Labs"}, "offers": {"price": "0", "priceCurrency": "USD"}`
> keywords include: "wiring diagram generator, bill of materials, hardware project planner, electronics design tool, circuit design AI, Arduino projects, Raspberry Pi projects"

Company: the Founders, Inc. portfolio page (`f.inc/portfolio/3e8-robotics/`) describes it as "turns plain-language descriptions into complete hardware project plans," lists founders **David Feldt, Pranav Seelam, Sajeel Purewal** (est. 2025, team from SpaceX/iRobot/Rivian), and lists the outputs as wiring diagrams, BOMs with sourcing links, 3D CAD visualizations, and step-by-step assembly instructions. The site's Twitter card is `@davidfeldt`; the bundle links `x.com/3e8blueprint` and `instagram.com/blueprint.am`.

What I extracted from their production JS bundle (`/assets/index-BoyNkh0Z.js`, 4.36 MB, downloaded and grepped — this is their shipped client code, the most primary source available for a closed SPA):

- **Pricing** (verbatim from the bundle): `"Free",price:{monthly:"$0"...}` with `features:["10 design credits per week","Standard hardware model","Community projects"]`; `"Pro",price:{monthly:"$20",yearly:"$13"}` with `["Better models — Blueprint Max","Unlimited design credits","10 image generations / day","10 CAD credits / month"]`; `"Ultra",price:{monthly:"$200",yearly:"$125"}` with `["World best hardware model — Blueprint Ultra","Unlimited design credits","Unlimited image generations","Unlimited CAD credits"]`. Stripe checkout/portal endpoints present.
- **LLM backend: Google Gemini.** The client calls `POST /api/gemini` and `/api/gemini/jobs` on `api.blueprint.io`. No Anthropic/OpenAI strings in the bundle. Branded model names ("Blueprint Max/Ultra") sit in front of this.
- **Parts data: Nexar (Octopart).** Endpoint `/api/parts/nexar-sourcing`, plus `/api/parts/amazon-links`, `/api/parts/adafruit-links`, `/api/parts/affiliate-links` — the BOM sourcing is Nexar for distributor data plus Amazon/Adafruit affiliate links. Bundle also references SnapEDA, UltraLibrarian, AliExpress, eBay, Thingiverse, GrabCAD search URLs.
- **Diagram tech:** ReactFlow + Eclipse ELK (elkjs) for wiring-diagram layout, with a deterministic-looking helper endpoint `/api/wiring/infer-rails`. 3D via react-three-fiber + Draco, and a "Powered by ForgeCAD" badge (`forgecad.io`) — an HTML comment in the page head literally says: `<!-- Inter: matches the ForgeCAD wordmark in the "Powered by ForgeCAD" badge (MechView) -->`.
- **No public API.** Every endpoint (`/api/account`, `/api/consume-credit`, `/api/get-credits`, `/api/projects/save`, `/api/publish`, ...) is a private, session-authenticated app API. There is no developer docs page, no API-key concept for third parties anywhere in the bundle.
- **No EDA-standard export.** Zero occurrences of `kicad`, `fritzing`, `netlist`, or `gerber` in the bundle. Their wiring diagram is a ReactFlow graph, not an interchange format.
- **ToS: could not be verified.** The bundle contains "Terms of Service" strings but no `/terms` route, and I could not retrieve a published ToS document. I am NOT asserting what their terms permit — treat programmatic access as forbidden by default.

**Confidence: HIGH** on identity, outputs, pricing tiers, and architecture (all read from their shipped page/bundle). **MEDIUM** on founder/company details (investor page, not the company's own about page — their site is a JS SPA whose body doesn't render to fetch tools). **UNVERIFIED**: ToS content, exact model quality, rate limits.

**Disambiguation note:** search engines still return stale results describing "Blueprint.io — Programmatic Website Builder" (Instapage alternative, programmatic SEO). I fetched those exact paths (`/programmatic-website-builder`, `/instapage-alternative`) — today they serve the current hardware-tool SPA. That was a **previous product on the same domain**; the listings (Serchen etc.) are stale index entries. The health/longevity "Blueprint" (Bryan Johnson) and dev-tooling Blueprints are different domains entirely and irrelevant.

## 2. Does it match what was asked for

**Full match.** The user asked for "wiring diagrams, parts list, and step by step design" — the vendor's own meta description is "Generate wiring diagrams, bills of materials, and step-by-step assembly guides from a single prompt." The user was not confusing it with another product; the spark in the vault is this product. It additionally does 3D CAD concept views (via ForgeCAD) and a community/publish gallery.

The catch is not the match — it's the access model: consumer SPA, credit-metered, Stripe-billed, Gemini-backed, **no public API, no exportable EDA artifacts, unverifiable ToS**. There is nothing to integrate against except scraping a private authenticated API, which is brittle and presumptively ToS-hostile. Blueprint is a **competitor/reference implementation**, not an integrable service.

## 3. What problem this solves for Harvis — and where it belongs

The capability — "describe a device → schematic/wiring diagram + real-parts BOM + assembly guide" — is **electronics + structured documentation**, not mechanical geometry. It shares the Adaptive Space chassis with forge-fab-assistant (manifest, panels, approval gates, honesty gates, sidecar-engine pattern) but shares no kernel with build123d and no ground with zoo.dev.

**Recommendation: a second Adaptive Space exemplar** — a sibling template pack next to the fabrication pack (`python_back_end/owui_compat/workspace_methods/fabrication.py`), reusing the exact patterns already shipped: `fab_cad.py`'s flag-gated sidecar client, `fab_stress.py`'s blocked-language honesty gate, and the `cad-engine` compose-profile sidecar (`docker-compose.yaml` `profiles: ["cad"]`, internal-only network). Do not fold it into the CAD exemplar; the locked "image-first 3D = concept assets, NOT testable geometry" line has a direct electronics analog (§5, gate G0).

**Boundary vs zoo.dev:** zoo.dev is the candidate *cloud mechanical-CAD adapter* (geometry generation/editing) for forge-fab-assistant — that agent's territory. Blueprint's only overlap with that lane is its own use of ForgeCAD for 3D views. Nothing here recommends or evaluates a cloud CAD adapter; the electronics exemplar needs no 3D at all in v0.

## 4. Verdict

**SKIP the vendor / BUILD-OURS the capability.** Blueprint.io has no public API, no exportable formats, and unverifiable terms, so there is literally no integration surface — but it validates the product shape and its architecture (LLM proposal → deterministic layout/ERC helpers → Nexar parts data) is exactly what Harvis can assemble from MIT-licensed parts on the existing Adaptive Space chassis.

## 5. Integration plan (BUILD-OURS)

**Core split, mirroring build123d:** the LLM writes *circuit-as-code*; a deterministic toolchain compiles, checks, and renders it. Substrate: **SKiDL** (MIT, Python — verified from `github.com/devbisme/skidl`: "netlists for KiCad," built-in ERC that "catch[es] common mistakes like unconnected pins, drive conflicts, and power connection errors," KiCad 5–10 support, editable KiCad schematics for KiCad 6–10). Rendering: **schemdraw** (MIT, matplotlib-based) for beginner-facing wiring views and/or SKiDL's schematic export. Alternative substrate noted for the record: **tscircuit** (MIT, verified: "React for Electronics," 2.4k stars, active, exports Gerbers/BOM) — browser-side, heavier fit for our Python backend; keep as a later interactive-panel option.

**Deterministic (MUST be):** netlist compilation, ERC (unconnected pins, drive conflict, power-input unconnected), pin-name/voltage-domain/polarity checks, current-budget arithmetic, part-number resolution, price/stock lookup, diagram rendering from the netlist. **LLM-appropriate:** choosing the topology, writing the SKiDL code, selecting *candidate* generic parts, writing the assembly prose from the *validated* netlist + resolved BOM (grounded: every step must reference real net/part names from the deterministic artifacts). **The LLM never asserts electrical correctness; only the checker output can.**

### The safety-honesty gate (the SF<2.0 analog) — proposed rule

Mirroring `fab_stress.py` ("deliberately no 'looks safe' string anywhere for the inadequate/marginal codes"):

- **G0 — provenance:** LLM output that has not passed netlist compilation + ERC is a **"concept sketch — UNVERIFIED"** and can never be presented as buildable, exactly as image-first 3D is concept-only. No BOM purchase links render for an unverified sketch.
- **G1 — ERC verdict codes:** `erc_pass` (ERC clean + current-budget + polarity checks) → strongest permitted phrasing: *"passes automated electrical rule checks under these assumptions; not physically tested."* `erc_warn` → recommend simulation or human review; no "ready to build." `erc_fail` / unchecked → block; the only phrasing is a do-not-build block.
- **G2 — hard energy floor (unconditional, ERC cannot override):** any design involving mains or >48 V, battery charging (any Li-ion), or >5 A continuous **must** carry *"requires review by a qualified person before energizing"* and the words "safe," "safely," or "ready to power on" are unavailable at any verdict level. This is the electronics SF<2.0.
- **G3:** unresolved or substituted parts (no MPN match) mark the BOM line and downgrade the overall verdict to `erc_warn` at best.

### Phases

**Phase 0 — template pack (no new deps, no flag).** New `python_back_end/owui_compat/workspace_methods/electronics.py` registered like the fabrication pack in `adaptive_space.py`; manifest steps: goal → constraints → concept sketch (LLM, G0-labeled) → *gated* verify step → BOM panel → guide panel. Frontend: panel types reuse existing Adaptive Space panels (markdown, table, svg/image). ~0 MB.

**Phase 1 — erc-engine sidecar (deterministic core).** New `erc-engine/` (Dockerfile + FastAPI shim) cloned from `cad-engine/`'s shape: `python:3.12-slim` + skidl + schemdraw + a curated KiCad symbol subset. Compose: `profiles: ["electronics"]`, own `erc-internal` internal network, no host port, no auth — same isolation note as `cad-engine`. Backend client `python_back_end/owui_compat/fab_circuit.py` mirroring `fab_cad.py`: `HARVIS_ADAPTIVE_ERC_ENABLED` flag, clamped inputs, honest `disabled` status. Sidecar API: `POST /netlist` (SKiDL source → netlist+ERC report), `POST /render` (netlist → SVG). Sidecar has **zero egress** (internal network) — the LLM-generated SKiDL code executes only there, never in the backend; treat it like the repo-sandbox trust boundary (it runs model-authored code).

**Phase 2 — parts/BOM enrichment (Lane 5).** Backend-only (never the sidecar, never OpenClaw) calls to a parts-data API through the `authorize_action` choke point (`python_back_end/workspace/orchestration/authz.py`, `LANE_EXTERNAL_SERVICES` per-capability flag pattern, like `HARVIS_SSH_ENABLED`): new flag `HARVIS_PARTS_API_ENABLED`, default OFF, user-supplied key. Provider: **Nexar API** (GraphQL over the Octopart database; verified: "current stock levels, pricing, lifecycle status," free "Evaluation plan that allows up to 100 matched parts") — the same source Blueprint itself uses — with **DigiKey/Mouser APIs** as alternates (free registration, per-user keys; their terms/quotas need verification before we default to either). Output: MPN, price, stock, distributor link per BOM row; G3 applies to misses.

**Phase 3 (optional, ask first).** ngspice/PySpice simulation inside the sidecar (upgrade path from `erc_pass` toward simulated verification); interactive schematic panel (kicanvas or tscircuit runframe — verify licenses before vendoring).

## 6. Size cost

| Item | Estimate | Default? |
|---|---|---|
| Phase 0 (template pack) | ~0 MB (python + svelte source only) | yes, inert |
| erc-engine image | `python:3.12-slim` ~120 MB + numpy/matplotlib/schemdraw ~90 MB + skidl ~10 MB + curated symbol subset 10–20 MB ≈ **250–300 MB** (full `kicad-symbols` would add ~100–200 MB — don't ship it by default; estimate, not measured) | **NO — `profiles: ["electronics"]`, 0 MB on default install** |
| Phase 2 (Nexar/DigiKey client) | 0 MB (httpx already in backend) | flag OFF |
| ngspice (Phase 3) | +30–60 MB in sidecar | profile only |
| Volumes | <10 MB (manifests in existing pg JSONB; SVGs in artifacts dir) | — |

Net effect on the 7 GB budget: **zero by default**; ~0.3 GB opt-in. Backend image untouched (no torch, no numpy-version conflict — that's the whole point of the sidecar, same rationale as cad-engine).

## 7. Distro notes

- **Linux/compose:** `docker compose --profile electronics up -d`; internal network only, mirrors `cad-internal`.
- **Windows (Docker Desktop/WSL2):** sidecar is pure CPU/pure Python — no GPU, no device mounts, no inotify or path-perf concerns; works unchanged. Phase 2 egress is from the backend, so proxy/firewall behavior is identical to existing cloud-engine calls.
- **K8s:** separate Deployment + Service for erc-engine; NetworkPolicy = ingress only from `app: backend`, **egress deny-all** (it needs none — note this is *stricter* than the campus-DNS problem, which therefore doesn't affect it). Nexar/DigiKey egress originates from the backend pod only and does hit the campus-network UDP-53 block — the `K8S_DNS_WORKAROUND.md` CoreDNS entry dance applies to `api.nexar.com` (or chosen vendor).

## 8. Risks, license and ToS traps

- **blueprint.io:** no published ToS found → assume programmatic access is forbidden; **do not scrape** `api.blueprint.io`. Also a live competitor to this exact feature — expect them to move fast (they're funded and shipping).
- **Octopart/Nexar data terms:** distributor pricing data typically comes with **no-caching/no-redistribution clauses and match-count metering** (free tier verified at 100 matched parts — evaluation-scale only). Since Harvis ships to third parties, the key must be user-supplied and we must not cache/redistribute Nexar responses beyond the session. Verify the actual Nexar ToS before enabling by default. DigiKey/Mouser likewise require per-user registration — fine for Lane 5, wrong for anything bundled.
- **KiCad symbol libraries:** CC-BY-SA-4.0 *with an exception permitting unrestricted use in designs*; redistributing the libraries themselves (our curated subset) requires attribution + share-alike on the subset. Verify the exception text before baking the subset into the image.
- **Fritzing:** GPLv3 code, paid binaries, GUI-oriented — poor automation fit; skip. **Wokwi:** hosted simulator, core not open (avr8js is MIT but scope-creep); skip for now. **CircuitJS1:** GPL — fine as an external "open in simulator" link, don't vendor.
- **Executing LLM-authored SKiDL code** is arbitrary-Python execution — it must stay inside the no-egress sidecar with resource limits, never in the backend process.
- **Liability wording:** even `erc_pass` must never read as an engineering sign-off; G2's hard floor exists because a hobbyist energizing a mains circuit on our say-so is the nightmare scenario.

## 9. Open questions (user only)

1. Green-light the **second exemplar** framing (electronics pack beside fabrication), or park until forge-fab Stage 1 (closed-form stress) ships?
2. Parts-data default when the flag is on: **Nexar** (one GraphQL API, same source Blueprint uses, metered) vs **DigiKey/Mouser** (per-user free keys, two integrations)?
3. Substrate call: **SKiDL** (Python, fits backend/sidecar, KiCad-native) vs **tscircuit** (TS/browser, richer interactive rendering)? Plan assumes SKiDL.
4. Confirm the G2 hard-floor thresholds (mains/>48 V, any Li-ion charging, >5 A continuous) — product rule, needs your sign-off like SF 2.0/2.5 did.
5. Is Blueprint.io worth an account-level hands-on (free tier, no signup per f.inc) to study their UX before we design the panels? That's a manual session, not an integration.
