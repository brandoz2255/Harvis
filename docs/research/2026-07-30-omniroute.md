# OmniRoute — integration research

**Candidate:** https://github.com/diegosouzapw/OmniRoute
**Researched:** 2026-07-30 (repo state as of `pushed_at` 2026-07-31T06:08:55Z)
**Method:** shallow clone of the default branch + GitHub REST API + npm registry API + Docker Hub registry API + a real `docker pull` of the published image. All numbers below are measured or quoted from a primary source; nothing is estimated unless it says so.

---

## 1. What it actually is

OmniRoute is a self-hosted **LLM gateway**: a Next.js 16 / Node 26 application that exposes one OpenAI-compatible `/v1` endpoint and fans requests out to a large catalog of upstream providers, with quota tracking, fallback chains, a web dashboard, an MCP server, and a CLI. You point Claude Code / Cursor / Cline at `http://localhost:20128/v1` and it picks an upstream.

### Verified facts

| Fact | Value | Source |
|---|---|---|
| License | **MIT** (`Copyright (c) 2026 diegosouzapw`) | `LICENSE`, GitHub API `license.spdx_id = MIT` |
| Stars | **35,374** | GitHub API `stargazers_count` |
| Forks | 4,557 | GitHub API |
| Created | **2026-02-13** | GitHub API `created_at` |
| Last push | 2026-07-31 | GitHub API `pushed_at` |
| Default branch | `release/v3.8.50` | GitHub API |
| Commits on default branch | **5,935** | GitHub API `commits?per_page=1` Link header, last page |
| Contributors | **321** listed | GitHub API `contributors?per_page=1` Link header, last page |
| Open issues | **412** | GitHub API |
| Published security advisories | **0** | GitHub API `/security-advisories` |
| npm `omniroute@3.8.49` unpacked | **830,769,055 bytes (792 MiB), 21,765 files** | registry.npmjs.org |
| Docker image (amd64, `latest` = `runner-base`) | **2.63 GB on disk**, 483.5 MB compressed, 13 layers | `docker pull diegosouzapw/omniroute:latest` then `docker image ls` |

### Prior-work claims — CONFIRMED / CORRECTED / UNVERIFIED

| 2026-07-18 claim | Status | Evidence |
|---|---|---|
| MIT-licensed | **CONFIRMED** | `LICENSE` is a verbatim MIT text. No CLA, no dual-license, no "non-commercial" rider anywhere in the repo. |
| ~19.1K stars | **CORRECTED → 35,374** | Nearly doubled in the 12 days since the scan (~1,350 stars/day). See risk #8. |
| ~5,289 commits | **CORRECTED → 5,935** | Directionally confirmed; it moves fast. |
| ~v3.8.49 | **CONFIRMED** — npm latest is exactly `3.8.49`, default branch is `release/v3.8.50` | npm registry + GitHub API |
| 251+ providers | **CORRECTED → 205 routing entries / 305 catalog records**, and README now claims 290 | `ls open-sse/config/providers/registry` = 205 directories, each an `index.ts` exporting a typed `RegistryEntry` with `baseUrl`, `authType`, `authHeader`, `format`, `headers`, `models[]`. Separately `src/shared/constants/providers/**` holds 305 UI catalog records. 106 modules in `open-sse/executors/` handle providers needing custom request/response behavior. **This is real config, not a marketing list** — see below. |
| 90+ free tiers | **PARTIALLY CONFIRMED** | `docs/reference/FREE_TIERS.md` documents the methodology and says the headline is computed from "43 provider pools / 516 models". The 90+ figure is a catalog count, not audited by me. |
| 18 routing strategies | **CORRECTED → 19** | `src/shared/constants/routingStrategies.ts:1` — `ROUTING_STRATEGY_VALUES` is a 19-entry const tuple (`priority, weighted, round-robin, context-relay, fill-first, p2c, random, least-used, cost-optimized, reset-aware, reset-window, headroom, strict-random, auto, lkgp, context-optimized, cache-optimized, fusion, pipeline`), plus one internal-only (`quota-share`), plus 8 sub-strategies under `auto` and a separate 9-entry account-level fallback enum. Each has a dispatch path; `normalizeRoutingStrategy()` maps legacy names. **Concretely real, not aspirational.** |
| 4-tier fallback | **CONFIRMED as a documented concept** — Subscription → API key → Cheap → Free | README diagram alt-text (`docs/diagrams/tier-cascade.svg`). It is implemented via the combos + routing-strategy machinery rather than as a literal four-branch function. |
| ~1.6B free tokens/month | **CORRECTED → ~1.53B/mo steady, ~2.15B first month** | README line 20–26. The project explicitly says the number is re-audited biweekly and "moves both ways". |
| MCP server with ~94 tools | **CORRECTED → ~104–112** | `open-sse/mcp-server/README.md:3` claims 104. My own grep of unique `name: "…"` literals under `open-sse/mcp-server/tools/` returns 112. There is a real de-duplication helper (`toolCount.ts::countUniqueMcpTools`) because collections overlap, so 104 is likely the honest de-duped number. |
| Local-first, never phones home | **MOSTLY CONFIRMED, with two caveats** | Cloud sync (`src/lib/cloudSync.ts:89`) returns immediately unless `CLOUD_URL`/`NEXT_PUBLIC_CLOUD_URL` is set — unset by default, so no credential or prompt egress to the vendor. **But**: it does make unsolicited outbound calls on its own initiative to `registry.npmjs.org` and `api.github.com` for version/news checks (`src/lib/system/versionCheck.ts`). No machine identifier is attached to those, so it is not telemetry — but it is not zero-egress either. |

### Maturity read

Five and a half months old, 5,935 commits, 321 contributors, 412 open issues, a real test suite (README claims 25,000+ tests), Stryker mutation testing, Sonar, Semgrep annotations in source comments, an `.github` security policy with a 48h acknowledgment SLA, and npm provenance attestations (SLSA v1) on the published package. The engineering hygiene is genuinely above average for a project this young. It is also *young*, moving extremely fast, and has never had a published security advisory — which is not evidence of safety.

---

## 2. What problem it solves for Harvis

Harvis already has a provider fan-out, and it is thin. The whole of it lives in one function:

**`python_back_end/workspace/model_proxy.py::_resolve_route()`** (line 211) — returns `(target_url, headers, is_kimi, is_nvidia, upstream_model)` for a model name. It handles exactly four upstreams: a DB-configured provider (`openclaw_llm_config` table, Fernet-encrypted `api_key_encrypted` column), Moonshot/Kimi, NVIDIA NIM, and Ollama (local + a desktop-rig probe). Everything downstream — `execute_chat_completion()` (line 904), `_stream_from_upstream()` (line 1630) — is provider-agnostic OpenAI-compatible plumbing.

What Harvis does *not* have, and OmniRoute does:

1. **A provider catalog.** Adding a new upstream today means editing `_resolve_route` by hand. OmniRoute has 205 machine-readable `RegistryEntry` records (base URL, auth header name, wire format, model list, context lengths, unsupported-param quirks).
2. **Fallback.** `_resolve_route` returns exactly one target. If Moonshot 429s, the request fails. There is no second choice, no circuit breaker, no cooldown.
3. **Quota/limit awareness.** `_log_usage()` writes a row to `proxy_usage_log` after the fact. Nothing reads it to make a routing decision.

That is the gap. It is a real gap and worth closing.

---

## 3. Verdict

**BUILD-OURS — vendor one subsystem (the provider catalog data), write our own fallback, and offer the full container only as an opt-in profile.**

Two reasons. **(1) Size:** the published image is **2.63 GB on disk**, which on top of Harvis's current 6.28 GB puts a default install at ~8.97 GB — past the 7 GB product goal and past the 7.5 GB CI guard, for a component whose useful core is a lookup table and ~200 lines of retry logic. **(2) Trust:** OmniRoute stores every provider credential as **plaintext by default** (encryption at rest requires an env var nobody sets), and ships deliberate anti-bot-detection features (TLS fingerprint spoofing, native-CLI header/body order impersonation, 31 browser-session-cookie providers) that Harvis cannot ship to third parties without exposing its users to account bans.

---

## 4. Integration plan

### Phase 0 — vendor the catalog (no new service, no flag)

The `RegistryEntry` records are MIT-licensed data. Vendor them, not the runtime.

- **New:** `python_back_end/workspace/providers/catalog.json` — generated from `open-sse/config/providers/registry/**/index.ts`, filtered to providers we will actually ship (see the exclusion rule below). Source is 1.9 MB of TypeScript; the extracted JSON for a filtered set of ~40 providers is on the order of **200–400 KB** (estimated: the full 205-entry set is 1.9 MB of TS including comments and imports; JSON of a fifth of it, comment-stripped, lands well under 500 KB).
- **New:** `python_back_end/workspace/providers/__init__.py` — loader + a `resolve_provider(model_id) -> ProviderSpec` function.
- **New:** `scripts/regen-provider-catalog.mjs` — regeneration script pinned to a specific OmniRoute tag, so the provenance of every row is auditable and the refresh is a reviewed diff rather than a live dependency.
- **Exclusion rule, enforced in the generator:** drop every provider where `subscriptionRisk === true` (38 entries), every provider listed in OmniRoute's own `docs/reference/FREE_TIERS.md` "ToS attention" table, and every `web-cookie` auth type. Ship only providers with a normal API-key or OAuth relationship.
- **Flag gate:** none. This is inert data plus a pure function. No lane change.

### Phase 1 — fallback chain in `model_proxy`

- **Edit:** `python_back_end/workspace/model_proxy.py` — change `_resolve_route()` (line 211) to return an ordered **list** of candidate routes instead of one, and wrap the upstream call in `execute_chat_completion()` (line 904) with a walk over that list: try, on 429/5xx/timeout advance, on exhaustion return the last error.
- **Edit:** same file — add a small in-process circuit breaker keyed on `(provider, model)` with an open-state cooldown. ~150–200 lines total, no new dependency.
- **New:** a `proxy_route_health` table alongside the existing `proxy_usage_log`, so the breaker survives a backend restart.
- **Flag gate:** `HARVIS_PROVIDER_FALLBACK=1`, default **off** for one release. The behavior change is "a request that used to fail now silently costs money at a different provider" — that needs to be opt-in until it is observed working.
- **Lane:** unchanged. This is still `model_proxy` making the same kind of outbound call it already makes, with the same key handling.

### Phase 2 — quota-aware ordering (optional, only if Phase 1 proves useful)

- **Edit:** `python_back_end/workspace/model_proxy.py::_log_usage()` — already writes tokens in/out and cost. Add a read path so the fallback order in Phase 1 can demote a provider approaching a configured budget.
- **Flag gate:** `HARVIS_PROVIDER_BUDGET_ROUTING=1`, default off.

### Phase 3 — OmniRoute as an opt-in BYO sidecar (never default)

For the power user who wants all 290 providers and accepts the trade-offs.

- **Edit:** `docker-compose.yaml` — add an `omniroute` service under **`profiles: ["omniroute"]`**, image `diegosouzapw/omniroute:latest` pinned to a digest, `command` unchanged, **no `ports:` published to the host** (backend-only reachability), attached to `ollama-n8n-network` only.
  - Explicitly **do not** use OmniRoute's own `cli` or `host` compose profiles: the `cli` profile bind-mounts `/var/run/docker.sock` (host root) and the `host` profile bind-mounts `~/.claude`, `~/.codex`, `~/.cursor` read-write. Neither is acceptable in Harvis.
  - Set `STORAGE_ENCRYPTION_KEY` in the service env — **mandatory**, generated by `install.sh`. Without it OmniRoute writes every provider key to SQLite in plaintext.
  - Skip the Redis sidecar. `src/lib/quota/storeFactory.ts:13` documents a SQLite fallback when no Redis URL is present, so the 57.8 MB Redis image is avoidable.
- **New network:** OmniRoute needs unrestricted egress to reach 290 provider endpoints, so it **cannot** live on `openclaw-internal` (`internal: true`). It needs an egress-permitted network of its own, and nothing else should be attached to it beyond the backend.
- **Edit:** `_resolve_route()` — one more branch returning `("http://omniroute:20129/v1/chat/completions", {"Authorization": f"Bearer {omniroute_key}"}, False, False, None)`. The key comes from the same `openclaw_llm_config.api_key_encrypted` column that already exists. **The client never sees it** — same invariant as today, unchanged.
- **Flag gate:** `HARVIS_OMNIROUTE_ENABLED=1` **plus** the compose profile. Lane 5 (external services), default OFF, per `authorize_action()` in `python_back_end/workspace/orchestration/authz.py`.

---

## 5. Size cost

| Item | Size | Source |
|---|---|---|
| **Phase 0–2 (recommended): vendored catalog + Python fallback** | **~200–400 KB of JSON, 0 new containers, 0 new pip deps** | Estimated from the 1.9 MB TS source, filtered and comment-stripped |
| Phase 3 opt-in: `diegosouzapw/omniroute:latest` image | **2.63 GB on disk** (483.5 MB compressed) | Measured: `docker pull --platform linux/amd64` + `docker image ls` |
| Phase 3 opt-in: Redis sidecar (avoidable) | 57.8 MB | Measured: `docker image ls redis:7-alpine` |
| Phase 3 opt-in: `./data` volume | ~10–50 MB estimated (SQLite + migrations; grows with call logs) | Not measured — no long-running instance |
| Optional profiles we would never use: `web` (+Playwright/Chromium) | repo's own Dockerfile comment says **+~300 MB**; the same comment's base estimate is wrong by 5×, so treat this as a floor | `Dockerfile:192` |

**Default service set impact: zero.** That is the point of the recommendation.

**If we took the container by default instead:** 6.28 GB + 2.63 GB = **8.97 GB**, which fails the 7 GB product goal and trips the `LIMIT_GB: "7.5"` guard in `.github/workflows/docker-size-guard.yaml`. Not close, not fixable by trimming.

### Why the image is 2.63 GB when the repo says 500 MB

`Dockerfile:192` states `runner-base → ~500 MB`. The published image is 5× that. `docker history` shows why:

```
899MB  COPY /app/.build/next/standalone ./
 28MB  COPY /app/node_modules/better-sqlite3 ./node_modules/better-sqlite3
919MB  RUN chown -R node:node /app
```

The `chown -R` writes a second full copy of the 899 MB application layer — a classic Docker anti-pattern that nearly doubles the image. It is fixable upstream (`COPY --chown`), and worth an issue if we ever do adopt the sidecar, but it is what ships today.

---

## 6. Distro notes

**Linux + docker compose (primary).** Phases 0–2 add nothing. Phase 3: standard compose profile; internal DNS `http://omniroute:20129` resolves normally; no `extra_hosts` needed because the backend and OmniRoute are on the same user-defined network, not talking through the host.

**Windows Harvis (Docker Desktop / WSL2).**
- Phases 0–2: no impact. Pure Python + a JSON file.
- Phase 3: **the `./data` bind mount is the problem.** OmniRoute's compose mounts `./data:/app/data` and the app is SQLite-backed with `better-sqlite3`. SQLite over the WSL2 ⇄ Windows 9p filesystem bridge is pathologically slow and has documented locking issues. Harvis's Phase 3 service **must use a named volume** (`omniroute-data:/app/data`), never a host bind mount. This is a change from upstream's compose, not an inherited default.
- `host.docker.internal` is not needed — nothing here reaches the Windows host.
- No GPU involvement. OmniRoute is a network router; it never loads a model.
- OmniRoute's `host` compose profile mounts `~/.claude`, `~/.cursor`, `~/.codex` with Linux-style paths and is documented "Linux-first". It is unusable on Windows and we are not using it anyway.

**Kubernetes.**
- Phases 0–2: no manifest changes.
- Phase 3: a `Deployment` + `ClusterIP` Service in a dedicated namespace with a `NetworkPolicy` allowing **ingress only** from `app: backend` in the `harvis` namespace, and **egress to 0.0.0.0/0 on 443** (unavoidable — that is the whole function) **minus** the RFC1918 ranges, so a compromised OmniRoute cannot pivot into the cluster. `STORAGE_ENCRYPTION_KEY` from a Secret. `/app/data` on a PVC, `ReadWriteOnce`, single replica — the SQLite state is not shardable, so this does not scale horizontally.
- The known cluster DNS problem applies: OmniRoute resolving 290 external hostnames from a pod that cannot do outbound UDP/53 will fail on every provider. See `K8S_DNS_WORKAROUND.md`. This alone makes Phase 3 impractical on the current cluster.

---

## 7. Risks, license and ToS traps

**License itself is clean.** MIT, verbatim, no CLA, no field-of-use restriction, no AGPL anywhere in the tree. Vendoring the catalog data with attribution is unambiguously permitted. No PyMuPDF-style trap.

**Sidecar images pulled by upstream's compose carry other licenses** — `redis:7-alpine` (Redis relicensed away from BSD-3 at 7.4), `qdrant/qdrant` (Apache-2.0), `ghcr.io/maximhq/bifrost`, `ghcr.io/router-for-me/cliproxyapi`. All are opt-in profiles we would not enable. If Phase 3 ever ships, we skip Redis anyway (SQLite fallback exists) and never touch the rest. **Verify Redis's current license before shipping any compose file that pulls it**, here or elsewhere.

Now the four "check before trusting" questions, answered.

### 7.1 Does the no-client-key invariant survive? — YES, cleanly.

OmniRoute is **an HTTP sidecar**, not a Python library and not a binary we embed. It speaks OpenAI-compatible HTTP on `API_PORT` (20129) and serves a dashboard on 20128. Harvis's backend calls it server-to-server with an OmniRoute-issued API key held in `openclaw_llm_config.api_key_encrypted`, exactly like every existing upstream. The browser never sees it. `model_proxy` stays the boundary. **This is the one question that comes back clean.**

Incidental finding while checking: Harvis's own key encryption in `model_proxy.py:190` derives the Fernet key as `sha256(JWT_SECRET)` — no salt, no KDF stretching. It is not a break (the secret is high-entropy), but it is a weak derivation and it means rotating `JWT_SECRET` silently orphans every stored provider key. Worth a separate ticket.

### 7.2 Free-tier ToS — this is the disqualifying finding.

OmniRoute is unusually honest about this, and the honesty is what indicts the feature. `docs/reference/FREE_TIERS.md` contains a **"ToS attention table"** the project maintains itself, listing providers whose terms explicitly prohibit exactly what OmniRoute does. Quoting its own entries:

- `agy` (Google Antigravity) — "ToS explicitly prohibits using third-party software, tools, or services (including proxies) to access the service via OAuth"
- `fireworks` — "explicitly prohibits proxy/intermediary use, API key transfers, and sublicensing (Sections 2.1 and 2.2(i)(j))"
- `nlpcloud` — "prohibits 'setting up a proxy or other device that allows others to access the Service through it'"
- `modal` — "prohibits 'rent, resell or otherwise allow any third party direct access to or use of the Service'"
- `duckduckgo-web` — "prohibits 'automated querying and developing or offering AI services'"
- `t3-web` — "restricts accounts to personal use only, prohibits credential sharing … bans automated/bot/scraping access"

That is ~15 providers flagged outright, plus a second table of ~20 more marked `caution` or `ambiguous`.

Worse than the API-key providers: **`src/shared/constants/providers/web-cookie.ts` defines 31 providers that consume a user's browser session cookie** — `chatgpt-web` wants `__Secure-next-auth.session-token` from chatgpt.com, `gemini-web` wants `__Secure-1PSID`, `grok-web` wants the `sso`/`sso-rw` pair, `perplexity-web` the Perplexity Pro session. **38 catalog entries carry `subscriptionRisk: true`.** This is replaying a consumer subscription session as an API. It is against ChatGPT's, Gemini's, Grok's and Perplexity's terms, and the realistic consequence for a Harvis user who enables it is a **banned personal account**, not a rate-limit warning.

And `SECURITY.md`'s own "Network Security" table lists two features built specifically to defeat the providers' enforcement of those terms:

> **TLS Fingerprint** — Browser-like TLS fingerprint spoofing to reduce bot detection
> **CLI Fingerprint** — Per-provider header/body ordering to match native CLI signatures

**Assessment:** the multi-provider fallback across *legitimately-obtained API keys* is a real, defensible feature. The free-tier rotation as OmniRoute ships it is not — for a meaningful subset of its catalog, normal use violates the provider's terms, and the project has built evasion tooling to make that violation survive detection. Harvis ships to third parties. A feature that gets *users* banned is worse than no feature. **This is why the catalog gets filtered at generation time rather than adopted whole.**

### 7.3 Dependency weight — heavier than the prior scan suspected, but differently.

The prior note said "embeds Redis, Bifrost and Mux". Corrected: **Redis, Bifrost, Qdrant and CLIProxyAPI are all opt-in compose profiles, not embedded** (`docker-compose.yml`, profiles `memory`, `bifrost`, `cliproxyapi`). Redis has a documented SQLite fallback. I found no Mux.

The real weight is the application itself: **74 runtime npm dependencies** including Next.js 16, React 19, Monaco Editor, Mermaid, Recharts, Playwright, `@aws-sdk/client-bedrock-runtime`, `sql.js`, `sqlite-vec`, `better-sqlite3`, `ink` — a full IDE-grade dashboard bundled into the same artifact as the router. That is how you get **792 MiB unpacked on npm across 21,765 files** and a **2.63 GB Docker image**. There is no "headless router only" build target; `runner-base` still contains the entire Next.js dashboard.

Deployable minimum: **1 container, 2.63 GB, no Redis required.**

### 7.4 Trust surface — the second disqualifying finding.

**Credentials at rest are plaintext by default.** `src/lib/db/encryption.ts` header comment: *"If STORAGE_ENCRYPTION_KEY is not set, operates in passthrough mode (stores plaintext for development convenience)."* `getStaticKey()` returns `null` when the env var is unset, and every `encrypt()` call becomes a no-op. `SECURITY.md` confirms: *"Passthrough mode (plaintext) when STORAGE_ENCRYPTION_KEY is not set."* The README's privacy diagram nonetheless claims *"credentials encrypted at rest (AES-256-GCM)"* as an unqualified guarantee. **A default `docker compose up` of OmniRoute writes every provider API key, access token and refresh token as cleartext into a SQLite file on a Docker volume.** If Harvis ever ships Phase 3, setting that env var is not optional.

**Prompts are not logged by default — this one is good.** `isDetailedLoggingEnabled()` (`src/lib/db/detailedLogs.ts:55`) returns `false` unless the `call_log_pipeline_enabled` setting is explicitly on, and `saveRequestDetailLog()` additionally honors a per-API-key `no_log` flag. Metadata (model, tokens, cost, latency) is logged; message bodies are not.

**No telemetry, and the cloud path is genuinely off by default.** `syncToCloud()` (`src/lib/cloudSync.ts:89`) returns `{error: "…not configured"}` immediately unless `CLOUD_URL`/`NEXT_PUBLIC_CLOUD_URL` is set. Credential *overwrite* from a cloud response additionally requires `OMNIROUTE_CLOUD_SYNC_SECRETS=true` — an opt-in the project added defensively in v3.8.6 with a clear comment explaining that a hostile `CLOUD_URL` could otherwise swap OAuth tokens. Note however that **HMAC verification of cloud responses is not enforced when `OMNIROUTE_CLOUD_SYNC_SECRET` is unset** — `verifyCloudSignature()` logs a warning and returns `true`. The code comment says enforce-by-default flips in v3.9. Not our exposure if we never set `CLOUD_URL`, but it tells you where the project's threat-model maturity currently sits.

**It does make unsolicited outbound calls.** Version check hits `registry.npmjs.org` and `api.github.com` on its own schedule (`src/lib/system/versionCheck.ts`), and `getNews()` pulls from GitHub. No identifier attached, so not telemetry — but "never phones home" as an unqualified claim is not accurate.

**The structural point stands and is not fixed by any of the above.** A component holding every credential, seeing every prompt, and requiring unrestricted internet egress is the highest-value single target in the stack. 35K stars earned in five months is popularity, not an audit. Zero published advisories in a codebase this large and this new means nobody has looked hard, not that it is clean.

### 7.5 Additional risks

**#8 — Star velocity.** 19.1K on 2026-07-18 → 35,374 on 2026-07-30: ~1,350 stars/day sustained over 12 days, on a repo 5.5 months old. This is not evidence of wrongdoing and I am not alleging any. It is a reason to weight "popular" much lower than usual as a proxy for "reviewed by many eyes".

**#9 — Supply-chain surface of the catalog refresh.** If we vendor the catalog, the refresh script must pin a git tag and produce a reviewed diff. An auto-updating provider list is an auto-updating list of hostnames our backend will send API keys to. That must never be a silent dependency bump.

**#10 — Upstream compose defaults are hostile to us.** The `cli` profile mounts `/var/run/docker.sock` (host root inside the container) and the `host` profile mounts `~/.claude` / `~/.cursor` / `~/.codex` read-write. Anyone copy-pasting upstream's compose into Harvis introduces a host-root escape. If Phase 3 lands, the service definition must be written from scratch, not adapted.

### What must be verified before trusting it (if the user overrides and wants Phase 3)

1. Build `runner-base` from source at a pinned tag and diff the resulting filesystem against the published Docker Hub image — the npm package has SLSA provenance, the Docker image does not.
2. Run it with `tcpdump`/egress logging for 24h with no `CLOUD_URL` set, and confirm the only outbound destinations are configured providers, `registry.npmjs.org` and `api.github.com`.
3. Confirm `STORAGE_ENCRYPTION_KEY` is set and that `data/*.db` contains no `sk-`-prefixed plaintext.
4. Confirm the dashboard on 20128 is unreachable from anything but the backend, and that `INITIAL_PASSWORD` is not the shipped `CHANGEME` placeholder (`src/lib/auth/managementPassword.ts:9` warns about it but does not block boot).
5. Independent review of the request path for prompt handling — I read the logging gate, not every code path that touches a message body.

---

## 8. Open questions

1. **Do we want free-tier aggregation at all, in any form?** My recommendation filters out every ToS-flagged and cookie-session provider, which removes most of what makes OmniRoute's headline number impressive. If the appeal was specifically "~1.5B free tokens/month", the honest answer is that Harvis cannot ship that to third parties, and you should decide whether the remaining (legitimate API-key fallback) is worth the work.
2. **Is a 2.63 GB opt-in profile acceptable at all**, given the trim work that got the default install to 6.28 GB? Even behind a profile it is the largest single image in the project, and it will appear in `docker system df` for anyone who enables it once.
3. **Attribution posture for vendored MIT data** — do you want the generated catalog to carry a header crediting OmniRoute and linking the pinned tag (my default assumption), or do you want the provider rows re-derived from each provider's own docs so Harvis carries no upstream dependency at all?
