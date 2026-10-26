# Free / aggregated access to high-end models — research + plan

Date: 2026-07-30 · Researcher: Fable 5 subagent · Scope: `cheahjs/free-llm-api-resources` + the "area ai" question + the product question "how does a fresh Harvis install get good models without the user paying?"

---

## 1. What it actually is

### 1a. `cheahjs/free-llm-api-resources`

All facts below verified against the GitHub API and raw repo files on 2026-07-30.

- **What**: a curated list of LLM inference services with a free API tier or trial credits. Two sections: 13 "Free Providers" (OpenRouter, Google AI Studio, NVIDIA NIM, Mistral La Plateforme, Mistral Codestral, HuggingFace Inference Providers, Vercel AI Gateway, Kilo Gateway, OpenCode Zen, Cerebras, Groq, Cohere, Cloudflare Workers AI) and 13 "Providers with trial credits" (Fireworks, Baseten, Nebius, Novita, AI21, Upstage, NLP Cloud, Alibaba Model Studio, Modal, Inference.net, Hyperbolic, SambaNova, Scaleway). Source: https://github.com/cheahjs/free-llm-api-resources (README.md).
- **Activity/maturity**: 28,857 stars, last push **2026-07-29** (the day before this research), 58 open issues, not archived. It is actively maintained and the July 2026 content is current (e.g. Mistral limits section says "As of July 2026"). Source: GitHub API `repos/cheahjs/free-llm-api-resources`.
- **Structure / machine-readability**: the README is **generated**, not hand-written. `src/pull_available_models.py` (39.8 KB) queries each provider's live model-list API (using the maintainer's own keys) and renders `src/README_template.md`; `src/data.py` (18.4 KB) is a Python dict of model-id → display-name mappings. A GitHub Action (`.github/workflows/update-readme.yml`) regenerates it. **There is no published JSON/YAML artifact.** To consume it mechanically you either parse the README markdown or run their script with your own provider keys.
- **License**: **NONE.** The GitHub API reports `license: null` and the repo root contains only `.github`, `.gitignore`, `README.md`, `src`. Default copyright applies — Harvis may read it as a reference but may **not** vendor the README or `data.py` into the repo. (Precedent: PyMuPDF was removed from Harvis purely for AGPL; "no license at all" is stricter than AGPL.)
- **The real terms behind the "free" tiers** (as recorded in the README itself; provider docs are the linked primary sources):
  - **Google AI Studio**: "Data is used for training when used outside of the UK/CH/EEA/EU." I verified this against the primary source: Google's Gemini API terms state for Unpaid Services, "Google uses the content you submit to the Services and any generated responses to provide, improve, and develop Google products and services and machine learning technologies" (https://ai.google.dev/gemini-api/terms).
  - **OpenRouter**: free models limited to 20 requests/min, **50 requests/day** (1,000/day only after a $10 lifetime top-up) (https://openrouter.ai/docs/api/reference/limits).
  - **NVIDIA NIM**: 40 requests/min, models "tend to be context window limited". Note Harvis already carries an `NVIDIA_API_KEY` route in `model_proxy.py`.
  - **Mistral La Plateforme**: free "Experiment" plan **requires opting into data training**.
  - **Mistral Codestral**: 30 req/min, 2,000 req/day.
  - **Kilo Gateway**: "All free models may use your prompts for training"; 200 req/hour per IP.
  - **Cohere**: 20 req/min, 1,000 req/**month**. **Cloudflare Workers AI**: 10,000 neurons/day. **HuggingFace**: $0.10/month credits. **Vercel AI Gateway**: $5/month.
  - The README's own banner: "Please don't abuse these services, else we might lose them," and it explicitly excludes illegitimate services (reverse-engineered chatbot APIs).
- **Free-in-a-product vs free-for-experimentation**: every entry is a **per-developer-account** free tier. The quotas are hobby-scale (50 req/day, 1,000 req/month) and most of the genuinely useful ones pay for themselves with training data. None of them is licensed or sized to be a shared backend for an app's whole user base. The correct reading for Harvis: this is a map of *where each individual user can get their own free key*, not a supply of free inference for Harvis to distribute.

### 1b. "area ai" — identification

Candidates checked, 2026-07-30:

| Candidate | What it is | Match? |
|---|---|---|
| `area.ai` (literal domain) | Redirects (302) to an Atom.com domain-for-sale listing. **No product exists there.** Verified by fetch. | No |
| Areal AI (areal.ai) | Mortgage/title document automation for lenders. | No |
| **LMArena** (lmarena.ai) | Free, no-signup access to frontier models via side-by-side "battles"; users vote, labs pay for the resulting evaluation data; raised $150M at a $1.7B valuation in Jan 2026 (secondary source: Contrary Research, research.contrary.com/company/lmarena). Free usage, but **no credits mechanic**. | Partial — phonetically "arena ai" ≈ "area ai" |
| **Yupp.ai** | 800+ models including frontier ones (Claude Opus, GPT-5-class); **5,000 credits at signup**; users **earn more credits by rating model responses** (preference feedback), can even cash out. Data-for-credits ("train-to-earn"), VC-backed (secondary sources: blog.yupp.ai/launch, maketecheasier.com, tomsguide.com). | **Best functional match** for "gives users free credits on a bunch of high end AI" |
| Poe (Quora) | Daily free compute points across many models; subsidized by Quora subscriptions. | Partial |
| OpenRouter `:free` | Free model collection; OpenRouter states it onboards providers and covers some costs to promote free models. No user credits. | Partial |

**Verdict on identity**: most likely **Yupp.ai** (the credits mechanic matches exactly) or **LMArena** (the name matches phonetically). Confidence: moderate — this needs one confirmation question to David. Functionally it barely matters, because both run the **same economic engine**:

- **Where the credits come from**: venture capital fronts the inference bill; the durable revenue is **selling human preference/evaluation data to the model labs** (LMArena sells eval services; Yupp pays users for feedback and monetizes the data). The user pays with their prompts and their judgments.
- **What the user gives up**: their conversations and preference signals become training/eval data; accounts, tracking, and (for cash-out) identity.
- **Is it replicable by Harvis?** **No.** It requires (a) capital to front inference, (b) a standing buyer for the data, (c) users consenting to data sale. An open-source, local-first, privacy-positioned project has none of these, and building (c) would invert Harvis's core premise. This is the honest "you cannot ethically do the thing being imagined" answer — the closest legitimate equivalents are in §3/§4.

---

## 2. What problem it solves for Harvis

The first-run problem: a fresh install has only small local Ollama models (dev-box GPU reality: 8 GB VRAM), and every cloud lane (`MOONSHOT_API_KEY`, `NVIDIA_API_KEY`, Claude/Kimi engines) assumes the operator already owns a paid key. There is no guided path from "installed Harvis" to "talking to a frontier-class model for $0".

Existing surfaces this plugs into (all verified in-repo):

- **`python_back_end/workspace/model_proxy.py`** — the security boundary. Already routes by model prefix to Moonshot, NVIDIA NIM, and external Ollama, with keys held server-side and usage logged to `proxy_usage_log`. This is where any new provider routing lands.
- **`python_back_end/main.py` ~lines 3040–3180** — a complete, encrypted, per-user BYO-key store already exists: `user_api_keys` table + `POST/GET/DELETE /api/user/api-keys/{provider_name}` (key encrypted at rest, never returned to the client). Today `model_proxy.py` reads only env-level keys and does **not** consult this table — that's the gap.
- **`python_back_end/workspace/harvis_readiness.py`** — `GET /api/harvis/providers`, the read-only unified provider catalog ("the inventory a future capability PLANNER consumes"). A `cloud_llm` provider kind slots in here.
- **Frontend**: the plugins/skills storefront's `connect` taxonomy (`external` cards) and the owui Settings → Connections area are where "get a free key" onboarding cards belong.
- Adjacent standing decision: the OmniRouter memory note already concluded provider aggregation should be **adopted behind `model_proxy`, not built** — this plan is consistent with that.

## 3. Verdict

**WRAP** the free-provider knowledge (use the list as an upstream *reference* to hand-build a small, licensed-clean provider catalog inside Harvis, wired to the existing BYO-key store and `model_proxy`) and **SKIP** the "area ai" credits mechanism entirely. The list cannot be vendored (no license) and the credits model cannot be replicated (no inference budget, no data buyer, and it would break Harvis's privacy positioning) — but a first-run "get your own free frontier key in 2 minutes" flow captures ~90% of the user value with zero inference cost and zero ToS exposure.

## 4. The product question, answered directly

Ranked options for "new user gets working access to good models on first run":

1. **BYO free-tier key with excellent onboarding (RECOMMENDED).** Harvis ships a curated catalog of 5–8 vetted free-tier providers (Google AI Studio, Groq, OpenRouter, Cerebras, Mistral, NVIDIA NIM, Cloudflare) with signup deep-links, honest rate-limit numbers, and a **"trains on your data" badge** where applicable. User pastes their own key; it lands in the encrypted `user_api_keys` store; `model_proxy` uses it server-side. ToS-clean (each user has their own account), $0 to Harvis, preserves the no-client-key invariant. Trade-off: 2 minutes of signup friction and hobby-scale quotas.
2. **Local Ollama models (already the default).** The genuine zero-friction floor. Trade-off: not frontier-quality on an 8 GB GPU.
3. **OpenRouter as the single aggregation point.** One key → hundreds of models including the `:free` collection; 50 req/day free, 1,000/day after a one-time $10. Best "one signup, many models" story; recommend making it the *featured* card in option 1 rather than a separate mechanism.
4. **Provider partnerships / referral programs.** Possible later (the upstream list itself uses an affiliate link for Novita), but requires David to negotiate, and referral links in an open-source repo need disclosure. Park it.
5. **Hosted Harvis tier with bundled credits.** The only way to truly replicate the "it just works free" feel — and it's a business, not a feature. Out of scope for this repo.

Never do:
- **Ship any API key in the repo** — GitHub secret scanning auto-revokes leaked provider keys, scrapers harvest them within minutes, and it burns the project's accounts.
- **A shared/rotating key pool** (one account's free tier proxied to many users) — this is multi-user resale of a per-account tier, exactly the "abuse" the upstream list warns kills these programs, and for Google-class providers it silently feeds *all users'* chats into training data without their individual consent.

## 5. Integration plan (phased)

- **Phase 1 — catalog data (lane 1, no flag).** New file `python_back_end/workspace/provider_catalog.py`: a static dict of vetted providers — `{id, display_name, signup_url, key_url, base_url, openai_compatible, free_limits, trains_on_data, notes}` — with facts hand-verified against each provider's own docs (NOT copied from the unlicensed repo). Surface it as `kind: "cloud_llm"` entries in `provider_catalog()` in `python_back_end/workspace/harvis_readiness.py`, marked `ready` when a matching row exists in `user_api_keys` (or env). ~200 lines, no new deps.
- **Phase 2 — onboarding UI (lane 1–2).** A "Free model access" panel in owui Settings → Connections (and a card in the storefront `connect`/`external` taxonomy): provider cards with limits + data-training badges, a paste-key field posting to the existing `POST /api/user/api-keys/{provider_name}`, and a "test key" button that round-trips through the backend. Svelte only; respect the compile-gate rule for `front_end/owui`.
- **Phase 3 — routing (lane 5, flag `HARVIS_BYO_CLOUD_PROVIDERS_ENABLED`, default OFF).** Extend `python_back_end/workspace/model_proxy.py`: on request, resolve the calling user's key from `user_api_keys` (fall back to env), route by model prefix (`gemini/*` → `generativelanguage.googleapis.com` OpenAI-compat endpoint, `groq/*`, `openrouter/*`, `cerebras/*` — all OpenAI-compatible, all already reachable with the existing `httpx` client), log to `proxy_usage_log` with cost 0. Keys never leave the backend — invariant preserved. Per-user client-side rate-limit hints from the catalog so the UI can warn before the provider 429s.
- **Phase 4 (optional) — staleness check (lane 5, flag `HARVIS_CATALOG_REFRESH_ENABLED`, default OFF).** A weekly backend task fetches the upstream README, diffs the limit strings for our catalog's providers, and raises an admin notice when they drift. Read-only outbound HTTPS; alternative is a manual pre-release checklist item. Do not auto-apply upstream content (unlicensed).

## 6. Size cost

- **Image delta: ~0 MB.** Everything runs in the existing backend core image (`python:3.12-slim`, 2.42 GB). Dependencies needed — `httpx`, `asyncpg`, `fastapi`, `cryptography` (key encryption) — are all already imported by `model_proxy.py` / `main.py`; I checked the imports rather than estimating. No new pip packages.
- **Volume delta: ~0.** Catalog is a <50 KB source file; per-user keys are rows in the existing Postgres.
- **No new service, no new container, no new compose entry.** Belongs in the **DEFAULT** service set (Phases 1–2 are inert data + UI; Phase 3 is flag-gated code inside the existing backend). Stays comfortably inside the 7 GB budget because the footprint is a source file.

## 7. Distro notes

- **Linux/compose**: nothing changes — backend already makes outbound HTTPS calls (Moonshot/NVIDIA routes). No new networks, ports, or mounts.
- **Kubernetes**: backend pod must be able to resolve/reach ~6 new HTTPS domains (`generativelanguage.googleapis.com`, `api.groq.com`, `openrouter.ai`, etc.). Two real constraints: (a) if a NetworkPolicy ever restricts backend egress (today only OpenClaw is restricted), these domains must be allowed; (b) the documented campus-network **UDP/53 block** (`K8S_DNS_WORKAROUND.md`) means each provider domain may need a CoreDNS entry, exactly like `registry.ollama.ai` did. Flag this in the Phase 3 docs.
- **Windows (Docker Desktop/WSL2)**: no host networking, no GPU, no Docker socket, no bind-mount sensitivity — all calls originate inside the backend container, so behavior is identical. The only Windows-specific note is cosmetic: signup flows open in the user's browser, which works the same.

## 8. Risks, license and ToS traps

1. **No license on the upstream repo** — hard blocker on vendoring. Mitigation: our catalog stores independently verified facts (facts aren't copyrightable; the upstream *compilation and prose* are). Never copy `data.py`, the README tables, or its wording.
2. **"Free" = training data** for the most useful tiers (Google verified verbatim; Mistral opt-in; Kilo). For a privacy-positioned product this must be a visible badge, not a footnote — otherwise Harvis silently launders users' chats into training sets.
3. **Key sharing / resale clauses**: I verified Google's Gemini training clause from the primary source, but the fetched terms page did **not** surface an explicit key-sharing/resale clause (those live in the incorporated Google APIs ToS, which I did not verify). Before Phase 3 ships, verify per provider: Google APIs ToS sublicense clause, OpenRouter ToS on account sharing, Groq/Cerebras data policies. Until then, per-user keys only; no admin "shared key for all users" toggle.
4. **Quota reality**: 50 req/day (OpenRouter) or 1,000 req/month (Cohere) will feel broken in an agentic Build loop that fires dozens of calls per task. The UI must set expectations and the router should prefer local models for high-call-volume lanes.
5. **Staleness**: the list changed the day before this research; limits shift monthly. Any number we bake in must carry a "verified YYYY-MM-DD" field and a re-verification step per release (or Phase 4).
6. **Reputational**: if Harvis ever ships anything resembling a key pool, it becomes the "abuse" that gets these tiers killed for everyone — the upstream README warns about exactly this.

## 9. Open questions (for David only)

1. **What did you actually mean by "area ai"?** Best guesses are Yupp.ai (credits-for-feedback) or LMArena (free arena). If the wish was "Harvis users get free credits like that platform," the answer is that their model is data-sale-subsidized and not replicable — confirm you're satisfied with the BYO-free-tier direction instead.
2. **Featured provider**: make OpenRouter the headline "one key, many models" card, or lead with Google AI Studio (most generous, but trains on data)? This is a positioning call about how loudly Harvis endorses a train-on-your-data tier.
3. **Admin shared key for small family/team installs**: technically trivial, ToS-gray (one account serving several people). Allow behind an explicit "I accept this is my quota and my data" admin toggle, or forbid outright?
4. **Referral/affiliate links** in the catalog cards (some providers offer them): acceptable for an open-source project with disclosure, or off-brand?
