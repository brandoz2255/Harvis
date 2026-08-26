# OmniRoute — scope

**Target:** https://github.com/diegosouzapw/OmniRoute (MIT · 36.1K★ · v3.8.50 · self-hosted)
**Date:** 2026-07-31
**Builds on:** `docs/research/2026-07-30-omniroute.md` — measured research (real `docker pull`, npm
registry, shallow clone). Every line reference in that doc was re-verified against the tree today and
is still exact. This scope does not re-derive it; it answers the question that doc did not ask.

> **Name trap.** OmniRoute is not openrouter.ai. A full OpenRouter BYO-key provider was built on
> 2026-07-31, then removed on the same day once the mishear was caught. If "open router" comes up
> again, it means this.

---

## 1. What the research doc settled, and what it left open

The research verdict was **BUILD-OURS**: vendor the provider catalog data, write our own fallback,
offer the container only as an opt-in profile. Two measured findings drove it:

- **Size.** The published image is **2.63 GB**. On top of Harvis's 6.28 GB that is ~8.97 GB — past
  the 7 GB product goal and past the 7.5 GB CI guard in `.github/workflows/docker-size-guard.yaml`.
- **Trust.** Credentials are **plaintext at rest by default** (`STORAGE_ENCRYPTION_KEY` unset =
  passthrough mode), and the catalog includes 31 browser-session-cookie providers plus deliberate
  bot-detection evasion (TLS fingerprint spoofing, per-provider CLI header ordering). Harvis ships
  to third parties; a feature that gets *users* banned is worse than no feature.

Both findings stand. But they are answers to a question you did not ask. The doc evaluated OmniRoute
as **something Harvis ships or vendors**. Your framing was different:

> *"a recommendation option within the settings that ties into the engine too probably cause it uses
> api keys."*

That is a third shape, and it is the one worth building.

---

## 2. The shape that actually fits: point-at, don't ship

**Harvis never ships OmniRoute. The user installs it themselves, on their own machine, and Harvis
offers to point at it.**

This is not a compromise — it dissolves both disqualifying findings rather than mitigating them:

| Finding | Ship-it shape | Point-at shape |
|---|---|---|
| 2.63 GB image | Enters our install, trips the CI guard | Never enters our install. It is on their disk, by their choice. |
| Plaintext keys at rest | We would be shipping that default to third parties | Their instance, their config. We *warn*; we do not impose. |
| ToS-violating free-tier rotation | Harvis would be distributing it | They chose which providers to enable. Not our distribution. |
| Trust surface | A component we ship holds every credential | A component *they* already run holds *their* credentials. |

It also matches what OmniRoute actually is. It installs via `npm i -g omniroute`, a Docker image, an
Electron desktop app, or Termux on a Raspberry Pi. It is a thing people run, like Ollama. Harvis
already has a first-class story for "point at the inference server you already run" — this is that
story, with one more entry in it.

**The honest framing in the UI is: "if you already run OmniRoute, Harvis can use it."** Not
"install this." Not a bundled service. A recommendation with a text field.

---

## 3. The one real code gap: model discovery

Chat transport is nearly free. `main.py:36-54` already makes `HARVIS_LLM_BASE_URL` canonical:

```python
HARVIS_LLM_BASE_URL = os.getenv("HARVIS_LLM_BASE_URL") or os.getenv("OLLAMA_URL") or _LLM_DEFAULT_BASE_URL
```

and force-writes it back into `os.environ` so every module inherits it at import. OmniRoute serves an
OpenAI-compatible `/v1` surface on **port 20129** (the dashboard is 20128 — the research doc has this
right; earlier notes said 20128 for both). Pointing chat at it is a URL.

**Discovery is not.** Harvis enumerates models through Ollama's native `/api/tags`, and it does so in
**28 files / 86 call sites** — measured today, not estimated. My earlier notes recorded 2 sites; that
was wrong by an order of magnitude.

Not all 86 matter equally. They split into two groups:

**Picker-critical** — these decide which models a user can select, and each returns empty against an
OpenAI-native upstream:

| Site | Role |
|---|---|
| `main.py:1244`, `main.py:7232` | the `/api/models` endpoints behind the chat picker |
| `workspace/workspace_router.py:145`, `:175`, `:292` | workspace model list (local, laptop, external) |
| `workspace/model_proxy.py:975` | route resolution model check |
| `integrations/discord_workspace_bot.py:3066` | Discord `/model` picker |

**Per-feature probes** — availability checks inside notebooks, RAG, vibecoding, cookbook, n8n, plugins.
These degrade to "feature unavailable" rather than breaking, and are genuinely Ollama-specific in
several cases (`ollama_cli/`, `ollama_n8n_optimizer.py`).

**The fix is a shim, not 28 edits.** One function that returns an Ollama-shaped tags payload
regardless of what the upstream speaks: try `/api/tags`, fall back to `/v1/models` and translate the
response shape. Migrate the seven picker-critical sites to it; leave the probes alone until something
actually asks for them.

Precedent already exists in the tree for this exact split — the external-Ollama lane posts chat to
`model_proxy.py:335` (`EXTERNAL_OLLAMA_URL + "/v1/chat/completions"`, OpenAI-shaped) while reading
tags from `workspace_router.py:292` (`+ "/api/tags"`, Ollama-shaped). The two wire formats are already
mixed in one lane; the shim just makes that deliberate instead of incidental.

---

## 4. Proposed phases

Each is independently shippable and independently revertible. Nothing here adds a container to the
default set, and nothing changes the security boundary: **`model_proxy` stays the choke point, the
browser never sees a key.**

### Phase 1 — the discovery shim (no OmniRoute yet, useful on its own)

- **New:** a `list_upstream_models(base_url)` helper — `/api/tags`, falling back to `/v1/models` with
  shape translation. Ollama-shaped output either way, so callers do not change their parsing.
- **Edit:** the seven picker-critical sites above.
- **Flag gate:** none needed. Pure widening — an upstream that answers `/api/tags` behaves exactly as
  today.
- **Ships value alone:** this also fixes any OpenAI-compatible server (vLLM, LM Studio, llama.cpp,
  Hermes) whose models currently do not populate the picker. That is a standing plug-and-play gap,
  independent of whether OmniRoute is ever adopted.

### Phase 2 — the Settings recommendation surface (your actual ask)

- **New:** an Integrations card, category `service`, tone in `BRAND_TONE`, glyph in `BrandGlyph`.
  Copy is honest: what OmniRoute is, that the user runs it, that Harvis points at it. Link to the
  repo. **No install button.**
- **New:** two fields — base URL (default `http://localhost:20129/v1`) and an optional API key, stored
  in the existing `openclaw_llm_config.api_key_encrypted` column that every other provider already
  uses. A "Test connection" button hits `/v1/models` through the Phase 1 shim and reports the model
  count, so the user gets a real answer rather than a saved-and-hoped state.
- **The warning is part of the feature, not a footnote:** the card must say that OmniRoute stores
  provider keys in plaintext unless `STORAGE_ENCRYPTION_KEY` is set, and that some of its bundled
  free-tier providers violate their own terms of service. A user who reads the card and proceeds has
  made an informed choice. One who is not told has been handed a banned account.
- **Flag gate:** `HARVIS_OMNIROUTE_ENABLED`, default off for one release.

### Phase 3 — provider fallback in `model_proxy` (independent of OmniRoute)

The research doc identified the genuine capability gap, and it is ours to close regardless:
`_resolve_route()` (`model_proxy.py:211` — verified today) returns exactly one target. If Moonshot
429s, the request fails. No second choice, no breaker, no cooldown.

- **Edit:** `_resolve_route()` returns an ordered *list*; `execute_chat_completion()` (`:904`) walks
  it — on 429/5xx/timeout advance, on exhaustion return the last error.
- **New:** a `proxy_route_health` table beside the existing `proxy_usage_log`, so a circuit breaker
  survives restart.
- **Flag gate:** `HARVIS_PROVIDER_FALLBACK`, default off. The behavior change is "a request that used
  to fail now silently costs money somewhere else" — that must be opt-in until observed working.
- **~150–200 lines, no new dependency, no new container.**

### Explicitly not proposed

- **Shipping the container**, default or profiled. 2.63 GB for a lookup table and retry logic.
- **Vendoring the 205-entry provider catalog** (the research doc's Phase 0). It is a real option and
  MIT-clean, but it is a standing supply-chain obligation — an auto-updating list of hostnames our
  backend sends API keys to — bought to serve a fallback feature we have not shipped yet. Revisit
  after Phase 3 proves the fallback is worth having.
- **Anything touching free-tier rotation, `web-cookie` providers, or the 38 `subscriptionRisk: true`
  entries.** Not now, not behind a flag.

---

## 5. What Phase 2 does not resolve

Pointing at a user-run OmniRoute moves the trust decision to the user; it does not make it disappear.
The instance still holds every provider credential and sees every prompt Harvis routes through it.
Harvis's obligation reduces from "do not ship this" to "do not let someone enable it without
understanding it" — which is why the warning copy is a Phase 2 deliverable and not a follow-up.

On Kubernetes, Phase 2 is effectively unusable today: OmniRoute must resolve hundreds of external
hostnames, and the cluster blocks outbound UDP/53 from pods (`K8S_DNS_WORKAROUND.md`). Docker and
laptop installs are unaffected. Worth saying plainly in the card rather than letting someone discover
it.
