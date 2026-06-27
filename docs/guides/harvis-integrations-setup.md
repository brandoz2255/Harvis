# Harvis Integrations — Setup & Testing Guide

> **One-line summary:** Today you can fully use **Ollama models + OpenClaw-based Build/Chat**, connect
> **GitHub / MCP**, and set a **default model** that pre-fills and routes your sessions. **Claude Code,
> Codex, and OpenCode are catalog references** you install on your own machine — Harvis cannot launch or
> stream them from Build yet. Per-provider "Save preference" is **stored for a future engine-selection
> feature; it does not switch your engine today.**

This guide explains what actually runs, how to connect your stack, and how to test "did I configure it
right?" separately from "does this stack perform well?".

---

## 1. The three layers (what's built vs what runs)

| Layer | What it is | Status |
|-------|-----------|--------|
| **Catalog** | The Integrations page — everything that *could* plug in | ✅ Built |
| **Connect + preferences** | Your OpenClaw gateway, GitHub, MCP, default model | ✅ Built |
| **Runtime** | Who *does the work* when you chat or code | **OpenClaw (+ Ollama for models) only** |

- **Build / Vibe Code** runs through **OpenClaw** (the bundled pod, or your BYO gateway) using a **local
  model** you pick (or your Integrations **default model**), via Harvis's native `vibecode-turn` runner.
- **Chat** uses the same model + workspace-agent path.
- **Claude Code / Codex / OpenCode** appear as **`code_engine_candidate`** cards. Harvis does **not**
  launch, authenticate, or stream from them. Their modal shows install commands for **you** to run on your
  machine. There is no Harvis adapter for them yet.

So today: **OpenClaw is the coding-agent engine inside Harvis.** The external CLIs are roadmap references.

---

## 2. Prerequisites

- The stack is up and reachable at **`http://localhost:9000`** (Nginx → backend + OWUI frontend).
  - Laptop/dev: `docker-compose up -d` (or the K8s deployment for hosted).
- You can **sign up / log in** at `:9000` (JWT auth; everything below is per-user).
- **Ollama** is running and reachable from the backend (`OLLAMA_URL`, default `http://ollama:11434`),
  with at least one model pulled.

---

## 3. What actually runs your code

| Engine | In Harvis? | How to use |
|--------|-----------|------------|
| **OpenClaw** (bundled pod) | ✅ Yes — default | Nothing to do; Build uses it out of the box |
| **OpenClaw** (your BYO gateway) | ✅ Yes | Integrations → OpenClaw → enter URL + token → **Verify** |
| **Ollama** (models) | ✅ Yes | Pull models; pick one as your default |
| **Claude Code** | ❌ Not yet | Install locally (`claude`); use in your own terminal |
| **Codex CLI** | ❌ Not yet | Install locally (`codex`); use in your own terminal |
| **OpenCode** | ❌ Not yet | Catalog reference only |

---

## 4. Connect your stack (per-user)

All of this lives on **Integrations** (`/harvis/integrations`). Click a card → the detail modal has a
**Connection** section where it applies.

### 4.1 Ollama (models)
Pull models on the Ollama host. Integrations → **Rescan** → the Ollama card shows **Ready · N models**.

### 4.2 OpenClaw (the engine)
- **Bundled** (default): nothing to do — the OpenClaw card shows **Ready / Detected**.
- **BYO gateway**: OpenClaw card → **Connection** →
  1. Enter your gateway **URL** (`ws://…` or `wss://…`).
  2. Enter your **token** (write-only — never displayed back).
  3. Click **Verify & connect**. ⚠️ **Verify is what enables routing.** *Save connection* persists the
     settings but your sessions keep using the bundled runtime **until you Verify** — that's the
     `byo_verified` state. (See also [`docs/byo-openclaw-setup.md`](../byo-openclaw-setup.md).)
- Honest status: a card may still read "Detected" at the deploy level even after you connect BYO — the
  **modal** is the source of truth for your per-user connection (`Current runtime: Your gateway · Verified`).

### 4.3 GitHub (repos / PRs — optional)
GitHub card → **Connect GitHub** → OAuth popup → it shows **Connected as @you**. Used by Vibe Code for
clone / Create-PR.

### 4.4 MCP tools (optional)
MCP card → **Manage connections** → Agent Studio → Customize. Add servers there; the card shows
**N servers connected**. (MCP runtime wiring into the agent toolset is still being completed — see the
card's note.)

---

## 5. Preferences: what's used *now* vs *later*

This is the most common point of confusion, so be precise:

| Setting | Where | Effect today |
|---------|-------|--------------|
| **Default model** | Integrations → "Default model" selector | ✅ **Used now.** Pre-fills new **Chat & Code** sessions, and is used by **backend auto-routing** when a request arrives with no model (`model:"auto"`). |
| **Save preference** (per provider) | Card/modal → "Save preference" | 🕓 **Saved for later.** Stored as your preferred provider for a capability and shown in **Agent Studio → Brain → Capabilities**, but **surfaces do not switch engines/providers from it yet.** The button's tooltip says "no effect yet." |

**Concretely:** saving "prefer Claude Code as my code engine" only stores the preference — **Build still
runs on OpenClaw.** Choosing a **default model** *does* change which model your next Chat/Code session
starts with.

---

## 6. First Build session (works today)

1. **Ollama** has your coder model pulled; Integrations shows it ready.
2. **OpenClaw** is bundled, or BYO + **Verified**.
3. (optional) **GitHub** connected for repo/PR.
4. **Integrations → Default model** → pick your coder model.
5. Go to **Vibe Code** (`/harvis/vibecode`) → the composer pre-fills your default model.
6. Attach a repo (or start a session), send a small task (e.g. *"add a function `add(a,b)` and a test"*).
7. Watch the run stream → review the **diff** → (optional, GitHub) **Create PR**.

---

## 7. What each surface uses

| Surface | Model | Agent / runtime |
|---------|-------|-----------------|
| **Chat** | your selected model (or default) | model proxy → Ollama / configured providers |
| **Vibe Code / Build** | selected model (or default) | OpenClaw (bundled/BYO) + native `vibecode-turn` runner |
| **Agent Studio → Brain** | — | **read-only** view of what's ready/connected (the Capabilities card) |
| **Notebooks** | configured notebook models | open-notebook backend (separate from Build) |

---

## 8. External CLIs (Claude Code, Codex) — install locally

These run on **your machine**, not inside Harvis (yet):

```bash
# Claude Code
curl -fsSL https://claude.ai/install.sh | bash
claude --version

# Codex CLI
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex --version
```

Use them in a normal terminal. The Integrations card shows these commands for convenience — installing
them does **not** make them runnable from the Harvis Build UI. A Harvis **engine adapter** (detect →
spawn the CLI against the repo → stream logs/diff back) is the roadmap item that would change this.

---

## 9. Verify your setup via the API

Authenticated (`Authorization: Bearer <token>`):

```bash
# The registry — what's ready/connected + your preferences. NO secrets are returned.
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:9000/api/owui/capabilities | jq

# Expect, for a fully-connected power user:
#   capabilities.agent_runtime.providers[openclaw]  ready:true  connection:"byo_verified"
#   capabilities.repo_provider.providers[github]     ready:true  source:"configured"
#   capabilities.tool_provider.providers[mcp]        ready:true  detail:"N servers"
#   capabilities.code_engine_candidate               claude-code/codex/opencode → ready:false
#   default_model: "<your pick>"
```

Other relevant endpoints (all per-user, JWT):
`GET/POST /api/workspace/config/openclaw` + `POST /api/workspace/config/byo/verify` (OpenClaw BYO),
`GET /api/vibecode/github/status` (GitHub), `GET /api/owui/mcp/connections` (MCP),
`POST /api/owui/capabilities/preference` + `POST /api/owui/capabilities/default-model` (prefs).

**Privacy check:** the `/capabilities` response must never contain `byo_url`, tokens, `access_token`,
or MCP `command`/`env` — only ids, statuses, booleans, counts, and the `connection` enum.

---

## 10. Testing playbook — config vs performance

Split testing so you don't confuse "configured correctly" with "fast / good output."

### Track A — Configuration (one test account)

| # | Step | Pass if |
|---|------|---------|
| 1 | Integrations → **Rescan** | Ollama green; OpenClaw detected or BYO verified |
| 2 | OpenClaw modal → **Verify** | shows `byo_verified` (if using your gateway) |
| 3 | GitHub → **Connect** | shows `@login` |
| 4 | MCP → **Manage** | ≥1 server appears in Customize |
| 5 | **Default model** | saves; survives a reload |
| 6 | **Save preference** on Ollama/OpenClaw | persists on the server (reload Integrations) |
| 7 | Agent Studio → Brain → **Capabilities** | matches what you connected |
| 8 | `GET /api/owui/capabilities` | reflects reality; **no tokens/URLs leaked** |

### Track B — Optimal run (vary ONE knob per run, same task each time)

Pick one repo + one fixed task; change only one variable per run and log: **workspace id, model,
`tool_calls`, duration, diff/PR acceptable?**

| Knob | Try | Measure |
|------|-----|---------|
| **Model** | small vs large coder model | time-to-done, tool calls, diff quality |
| **OpenClaw** | bundled vs BYO gateway | latency, stability (same brief) |
| **Isolation** | clone vs in-place (if enabled) | safety vs speed |
| **Agents** | single vs multi-agent Build | tokens, time, correctness |
| **MCP** | tools on/off | does the agent use tools correctly |

Fixed task examples: *"add a function X + a test"* (small) · *"fix the failing test in file Y"* (medium)
· a multi-step task with **Agents** on (stress). **Use the identical brief** when comparing models —
otherwise you're testing the task, not the stack.

### Track C — Preference behavior (the Integrations arc)

| Scenario | Expected |
|----------|----------|
| Set default model → open **Vibe Code** | composer pre-fills that model (if still installed) |
| User who already has an OWUI chat default | the Integrations default **must not** override it |
| Chat/API with `model:"auto"` | uses the saved default (Phase D backend routing) |
| Default model removed from Ollama | UI does **not** pre-fill the broken model |
| "Save preference" on a code engine | **saved only** — Build still uses OpenClaw (no engine switch yet) |

### Suggested personas (run the same Build task across each)

| Persona | Setup | Proves |
|---------|-------|--------|
| **Minimal** | bundled OpenClaw + one Ollama model | baseline works |
| **Power user** | BYO OpenClaw + GitHub + MCP + default model | full Integrations path |
| **Fresh browser** | new user, empty localStorage | server prefs + registry hydrate |
| **Stale config** | default model removed from Ollama | UI doesn't pick a broken model |

---

## 11. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| OpenClaw card "Detected" after BYO connect | deploy-level health probe; check the **modal** for `Your gateway · Verified` |
| BYO gateway not used | you clicked **Save** but not **Verify** — Verify sets `byo_verified_at` |
| Default model not pre-filling | model not installed / not in the model list; or you already have an explicit chat model set |
| "Save preference" didn't change Build | expected — provider prefs are **stored for later**, not acted on yet |
| Capabilities show nothing | backend/DB down — the registry fails soft; re-check `/api/owui/capabilities` |
| Brain badges blank | registry fetch failed; reload, or check the backend is up |

---

## 12. Roadmap (not built)

1. **Engine adapter phase** — drive an external engine (likely a subprocess wrapper for `claude`/`codex`,
   or OpenCode) from Build, so "prefer Claude Code" actually launches it. This is the work that turns the
   candidate cards into real engines.
2. **Surfaces honoring provider preferences** — once adapters exist, the per-capability "Save preference"
   becomes active (today it's display + future-routing only).
3. A **"Test my setup"** button (hits `/capabilities` + a smoke workspace run).

---

*Related: [`docs/byo-openclaw-setup.md`](../byo-openclaw-setup.md) · `docs/HARVIS_CLAW_SETUP.md` ·
the Integrations changelog in `front_end/newjfrontend/changes.md`.*
