# Handoff — Kimi closed out the session that hit the limit (2026-09-02 pm → 09-03 am)

You (Claude) hit your session limit at 00:02 on 2026-09-03 mid-way through the
Chrome verification of the second OWUI build. Kimi picked the session up from
the compaction summary and closed out your pending list. Repo:
`/home/ommblitz/Projects/Recent-EX/Harvis`, branch `fixes`.

## What Kimi did

1. **Verified the rendering fixes are what is actually served.**
   - `curl http://localhost:9000/owui/` is byte-identical to
     `front_end/owui/build/index.html`.
   - Both fix chunks are served and match disk: `S1NwDLoO.js` holds the
     typewriter gate (`indexOf("<details`), `reasoningOpen` exception in
     `DIm818zy.js`), and both contain the `details type="reasoning"` marker.
2. **Verified the data path.** Live stream straight from the node
   (`POST 172.17.0.1:1919/v1/chat/completions`, `enable_thinking: true`) —
   127 `reasoning_content` deltas streamed before content. (Note: a
   `max_tokens: 128` cap was fully consumed by reasoning, so the visible
   answer was empty in that probe — reasoning itself is the verified part.)
3. **Re-ran the container tests.** `tests/test_inference_nodes.py` +
   `tests/test_ollama_hosts.py` → **32 passed**.
4. **Committed your drafted message** as `9f758eda` on `fixes` (29 files, the
   staging set from your summary — the pre-existing unrelated dirty files were
   left uncommitted). **Not pushed.** `main`/`harvis1.3` untouched.
5. **Filled the placeholders** in this cycle's docs:
   - `STREAMING_VERIFY` in `docs/handoffs/2026-09-02-freetoken-inference-nodes.md`
     now records the bundle + stream verification, and honestly notes the one
     thing not redone: the visual in-browser click-through (no Chrome MCP
     available to Kimi). If the Thinking card still misbehaves live, suspect a
     third gate in `MarkdownTokens.svelte`/`Collapsible.svelte`, not the two
     fixed ones.
   - `COMMIT_HASH` → `9f758eda` (3 spots) in the same file.
6. **Added a rule to `CLAUDE.md`:** never commit until the user has reviewed —
   the user asked for this after the commit landed. Applies to both of us
   from now on.

Items 5 and 6 are **uncommitted working-tree edits**, per that new rule.

## State right now

- FreeToken user service `active`, `/health` = `maintenance: serving`,
  16,414 KV pages, ~5.6 GB VRAM, bound to 172.17.0.1:1919 (never 0.0.0.0).
- Full harvis stack up; UI at :9000 returns 200 with the fixed bundle.
- `git status`: only `CLAUDE.md` + the 2026-09-02 handoff modified, plus the
  pre-existing unrelated dirty files (`discord_workspace_bot.py`,
  `chat_completion.py`, `fast_path.py`, `orchestration/{authz,runner}.py`,
  `agent_reach/provenance.py`, `owui_compat/system_prompt.py`,
  `test_reach_egress_guard.py`, `test_system_prompt_core.py`).

## Still open (carried from before)

1. ~~Visual confirmation of the Thinking card~~ — **done by Claude 4:58 PM
   2026-09-02** from the signed-in Chrome: spinner + *Thinking…* card live at
   19/31/51 s, then *Thought for 43 seconds* and the answer. Written up in the
   2026-09-02 handoff, root cause 1.
2. ~~Warm decode-speed re-measure~~ — **done**: 30.2 tok/s warm mean at ratio
   0.90 vs 32.9 at 0.95 (~8% slower, no OOM). Numbers in the 2026-09-02 handoff.
   Left as is; lever if it ever matters is `FT_KV_RESERVE=8192` + ratio 0.92.
3. **Hybrid-graphics reboot** — explicitly on hold.
4. **Key rotation** — deferred by user (Kimi/Anthropic, `OPENCLAW_GATEWAY_TOKEN`,
   Gemini, OpenRouter; a live `sk-kimi-…` + gateway token sit in
   `workspace_events`, run `67155356` seq 14).
5. **Push `fixes`** — only when the user says so.
6. **Security audit follow-up** — the user asked about repo vulnerabilities.
   The dependency half is done AND the cheap fixes are applied as uncommitted
   working-tree edits (Python pins + npm lockfile sweeps; every updated package
   re-verified clean on OSV; 32/32 backend tests still pass). Full writeup,
   before/after versions, and what was deliberately left (xlsx no-fix,
   sharp override, chromadb/torch/starlette/gradio hairballs, ~160 unpinned
   Python lines) in `docs/security/2026-09-03-dependency-cve-audit.md`.
   The **code-scanning (CodeQL) half is still blocked**: the page needs an
   authenticated session with write access and this box has no GitHub creds.
   Needs a PAT (`security_events`) or `gh auth login` from the user — details
   at the bottom of the audit doc. Rebuild note: manifest edits only take
   effect on image rebuild; first rebuild candidates are harvis-backend,
   harvis-voice-onnx, and the owui python backend.

## Constraints still in force

- Never commit until the user reviews (new, in `CLAUDE.md`).
- Never push without being told. Never touch `main`/`harvis1.3`.
- Don't read/print `.env`; secrets never in commits.
- Don't scan the network more than needed (campus).
- Don't stop the user's GUI apps or reboot; FreeToken restarts only via
  `systemctl --user restart freetoken`.

---

## 2026-09-02 evening (Claude, continued) — stability and limits

The user's ask: "we need to find a more solid way on making sure freetoken is stable
to use and what the limit for it is", plus "if I go to hybrid what's the odds it'll
work properly with harvis".

**Watchdog, built and installed.** `scripts/freetoken/watchdog.sh` +
`freetoken-watchdog.{service,timer}`, every 2 minutes, enabled by default and wired
into `install-user-units.sh`. It answers the dead-scheduler failure: `/health` +
`maintenance=serving`, then a scheduler worker under the main PID (this is what
catches an OOM before any user request), then a one-token completion at most every
10 minutes while idle. Two consecutive failures restart; one is a blip. Restarts are
budgeted at 3 per rolling hour, then it stops and logs. All four paths tested with a
stubbed `systemctl`; the healthy path was run against the live node.

**The envelope, measured** (`scripts/freetoken/limits.sh`, new). Real ceiling
**16,414 tokens** prompt + generation, against the 262,144 the model advertises.
Largest prompt that prefilled: **11,925 tokens in 10.9 s**. First refusal at 16,526
tokens was a **clean 400, no crash** — that is the `FT_MAX_PREFILL=2048` fix proving
itself. Decode barely cares about depth (24.1 tok/s at 723 tokens vs 22.8 at 11,924;
~30 tok/s pure decode in the journal). Two concurrent requests: 2.7 s warm, 12.9 s on
a cold MoE cache. VRAM 7.3 GB of 8.15.

**Hybrid graphics: probably works, real black-screen risk.** `card1-eDP-2` (NVIDIA) is
connected and enabled while `card0-eDP-1` (AMD) exists but is disconnected — the panel
has an eDP connector on *both* GPUs, so there is a mux and it currently points at the
discrete card. `amdgpu` is loaded, `system76-power graphics switchable` says
switchable. The risk is the mux not following a software-only switch on Gigabyte
hardware (BIOS / Advanced Optimus territory). Harvis is not the risk: both `hybrid`
and `compute` keep the dGPU available for CUDA, so FreeToken, `harvis-ollama`
(`runtime: nvidia`) and ComfyUI keep working; only the display path changes. Payoff is
bigger than the old estimate: the desktop holds **~0.8 GB**, not ~350 MB. Undo is
`sudo system76-power graphics nvidia` + reboot, which needs a working screen — so have
SSH from another box first. Not attempted; still the user's call.

All of it is written up in `docs/inference-nodes.md` (new sections: watchdog, the
measured envelope, a rewritten iGPU-offload section with the evidence). 32 tests still
pass. **Nothing committed** — the review rule stands.

## 2026-09-02 late — portability, and the question of which models this carries

David: *"the plan is to make it stable and valid enough to have on other systems … so
lets make it easy adaptable for other systems … and if it only works with moe and if we
can make it so it can work with any model."*

**Nothing in `scripts/freetoken/` is laptop-specific any more.** `autotune.sh` measures
VRAM, RAM, physical cores and checkpoint size and prints a complete `freetoken.env`;
`install-user-units.sh` runs it on a box with no env file, and `--retune` re-measures an
existing one. `plugins/inference_nodes/provision.py` used to bake `kv_reserve_tokens=4096,
memory_ratio=0.95, moe_cpu_threads=6, max_running=2` — this laptop's *pre-fix* numbers —
into every node it provisioned. It now inlines the same arithmetic and the generated
`serve.sh` reads `FT_*` from a generated `freetoken.env` that systemd also reads through
`EnvironmentFile`. The four tuning arguments default to `None` (= measure it), and a pin
is appended after the measured block with a comment saying an operator put it there.
`GET /api/inference-nodes/provision-script` grew `kv_reserve_tokens`, `memory_ratio` and
`moe_cpu_threads` query parameters, and `max_running` no longer defaults to 2.

Calibration check: the shared formula returns this laptop's measured-good settings
(ratio 0.89 against the measured 0.90, kv 16384, prefill 2048, running 2, threads 6) and
sane, different ones for 12/24/48 GB cards. Four new tests pin that, plus valid bash, no
leftover placeholder, and no hardcoded FT_* value in the generated env file. 36 pass.

**The MoE question, answered from FreeToken's own source.** The small-card trick is
sparsity, not compression: 35B parameters, ~3B active per token, all expert banks in host
RAM, the router's picks streamed over PCIe. `engine/engine.py:385` creates the MoE backend
only `if config.model_config.is_moe`. `engine.py:1101` drops all nine offload knobs for a
dense model, commenting that offload there "is worse than inert" because engine init would
build an expert cache for a model with no experts. Dense families (llama, mistral, qwen2,
qwen3, gemma4-dense) and GGUF run, but must fit in VRAM. Making it general is not a missing
feature: a dense model needs every weight for every token, so streaming a 20 GB checkpoint
over PCIe 4.0 would be well under 1 tok/s. For dense the lever is quantisation, which is
what Ollama already does — so the node is worth pointing at *another MoE checkpoint*, not
at improving the local dense models.

Also this session: `harvis-comfyui` stopped at David's request (restart policy
`unless-stopped`, so it stays down); 31 containers still up. Backend restarted once to
pick up the route signature. Nothing committed — house rule.

## 2026-09-03 — the toggle, and detecting what deserves it

Asked for: *"if it detects a moe model install it uses the freetoken stuff or activates
a toggle that turns freetoken on. like a dev menu settings or somethign."* Three pieces,
all landed on `fixes`, nothing committed.

**The power switch.** The backend is in a container and FreeToken is a `systemd --user`
service on the host, so the backend cannot start it. The channel is now two JSON files
in a `1777` directory (`/tmp/harvis-freetoken`, already bind-mounted): the container
writes `desired.json`, a `.path` unit fires `freetoken-control-agent`, and the agent
writes back `status.json`. The protocol carries a state and nothing else — there is no
field naming what to run — so the container gains no authority it did not have.
Verified end-to-end on this box: off → `inactive`, wake → serving in 38.9 s.

**Loading is not running.** FreeToken answers `/v1/models` with 200 *while the
checkpoint is still loading*, so `probe.reachable` was a false positive for readiness —
the first `wake()` returned True after 5.5 s and a chat would have sat there. Fixed by
requiring `/health` to say `maintenance: serving`; `power_state` now reports `loading`
separately from `running`, and the switch draws all three states.

**Auto-wake.** `model_proxy._resolve_route` no longer 503s for a model whose only node
is asleep — it asks the host, waits, re-probes, routes. Gated on the local node and on
the agent being installed.

**MoE detection.** `moe.py` reads `<family>.expert_count` / `expert_used_count` out of
the GGUF metadata Ollama surfaces at `/api/show`. Live on this box: 14 installed models
→ 3 `node_would_help` (35B-A3B Qwen at 8/256, `gpt-oss:20b` and `:latest` at 4/32),
11 `dense`.

**The blocker on "detect → auto-serve".** FreeToken loads its own checkpoint and its
GGUF reader maps exactly one architecture (`gemma4`), so it *cannot* take over Ollama's
blob for `gpt-oss` or `qwen35moe`. Detection can classify and recommend; it cannot
one-click. The endpoint says so in its `note` and the pane renders it.

**UI.** `Admin → Settings → Inference Nodes`. New pane + api module, wired into
`Settings.svelte`. Frontend rebuilt (`npx vite build`, 1m14s, clean).

> Gotcha worth remembering: `vite build` deletes and recreates `front_end/owui/build`,
> which breaks nginx's bind mount — every route went 500 until `docker restart
> nginx-proxy`. Always restart nginx after a frontend build.

**Tests:** 44 pass (was 36) — 8 new covering `control.py` and `moe.py`.

**Not verified:** the pane's actual rendering. The route serves 200 and the build
contains it, but seeing it needs a login I don't have.

8. **Re-look at OmniRoute** — asked for by the user 2026-09-03. Context so the
   next session does not re-derive it: the 2026-07-30 research verdict was
   **BUILD-OURS** on two measured findings — the published image is 2.63 GB
   (Harvis 6.28 GB + that = ~8.97 GB, past both the 7 GB product goal and the
   7.5 GB CI guard in `.github/workflows/docker-size-guard.yaml`), and its
   credentials are plaintext at rest by default with a catalog that includes 31
   browser-session-cookie providers plus deliberate bot-detection evasion —
   a feature that gets *third-party users banned* is worse than no feature.
   What actually shipped on 2026-08-01 was `owui_compat/free_providers.py`:
   five hand-verified providers (Groq, Cerebras, Google AI Studio, NVIDIA NIM,
   Mistral), not the planned 205-entry catalog, plus Engines-tab cards, a
   "Get free API keys" modal, and a token/cost meter in the chat composer.
   Two things were left unfinished then and are the obvious place to start:
   **#106** live E2E with a real key, and **#110** paid cloud entries still
   declare `capabilities: {}` so the meter is hidden on Claude/OpenAI/Kimi.
   Docs: `docs/design/2026-07-31-omniroute-scope.md`,
   `docs/research/2026-07-30-omniroute.md`. **Name trap:** OmniRoute is not
   openrouter.ai — a full OpenRouter BYO-key provider was built and removed on
   the same day (2026-07-31) once the mishear was caught.

9. **Look at OpenClaw Desktop** — asked for by the user 2026-09-03. Upstream
   OpenClaw (Peter Steinberger; ~68K–180K★ depending on the source, formerly
   Clawdbot/Moltbot) now ships a **one-click desktop installer for macOS and
   Windows** that bundles the same gateway Harvis already runs headless, plus
   the WhatsApp/Telegram/Slack/Discord/Feishu/Line channel adapters and a
   graphical control UI — no terminal, Node, WSL2 or config files. Docs:
   https://docs.openclaw.ai/ · https://openclaw.ai/
   **The relevant question is not "should Harvis adopt it"** — Harvis is already
   the multi-user GUI in front of that gateway, and the desktop app is
   explicitly single-machine ("your data stays on your machine"). What is worth
   mining is its **graphical control UI**: it solves channel setup and gateway
   config without a terminal, which is the same problem the Harvis admin panes
   keep re-solving one setting at a time.
   **Supply-chain note worth checking first:** the running container is
   `dulc3/openclaw-browser:latest` — a third-party image on a floating tag, not
   an official OpenClaw publication. Given the dependency audit in item 6, worth
   confirming provenance and pinning a digest before anything else here.

---

## 2026-09-03 — Developer Mode

Asked for as "a dev toggle for harvis … then I can deploy and install it for the
other machine and test it out". Built; **not tested on the second machine**, which
the user deferred until the host version of Harvis exists.

**What it is.** An instance-wide **Developer Mode** switch at **Admin → Settings →
General**, persisted server-side so it travels with a deployment rather than living
in one browser. It decides whether the experimental admin surfaces exist at all —
today exactly one, the Inference Nodes pane (FreeToken power switch + MoE detection).

**Why it is a real gate and not a label.** `owui_compat/admin_config.py` states the
house rule it inherited from `setup_flow.setup_preferences`: *a control that cannot
change the thing it names is worse than no control — adding a key here means wiring
its enforcement in the same commit.* So turning it off removes the tab from the
settings list, from the settings **search index**, and from the **URL whitelist** (a
deep link falls back to General), and the pane itself is guarded. General's existing
`saveHandler` already refetches the boot config, so it takes effect without a reload.

**Shape.** No new table, no new endpoint, no new API client — it rides what was
already there:

| Layer | Where |
|---|---|
| Storage | `instance_settings` key `dev_mode` (the table that already holds `enable_signup`) |
| Read/write | existing `GET`/`POST /api/v1/auths/admin/config`, second key `DEV_MODE` |
| Published | `/api/config` → `features.enable_dev_mode` |
| Enforced | `admin/Settings.svelte` (list + search + whitelist + pane) |

**Default is ON, deliberately.** `HARVIS_DEV_MODE` defaults `True` in code because
everything it gates is weeks old; defaulting to off would make this install silently
lose the Inference Nodes panel on a pull. **Flipping that literal to `False` in
`_env_dev_mode_default` is the 1.0 gate** — at that point experimental surfaces
become opt-in and a fresh deploy shows only what is finished. For the second machine
in the meantime: `HARVIS_DEV_MODE=false` to see the shipped shape.

**Verified.** Boot payload emits the flag; writing `dev_mode=false` into
`instance_settings` flips it with no restart, and deleting the row falls back to the
env default (the box was left with no row, exactly as found). `test_admin_config.py`
covers stored-beats-env, blank-is-unset, key isolation, and the cold-DB path that
must fall back to the env default rather than to off — **55 pass** across the three
node/config suites. Frontend rebuilt, nginx remounted, all three routes 200, and
both `enable_dev_mode` and "Developer Mode" are present in the shipped bundle.

**Files:** `owui_compat/admin_config.py`, `owui_compat/config.py`,
`owui_compat/router.py`, `tests/test_admin_config.py` (new),
`admin/Settings/General.svelte`, `admin/Settings.svelte`, `lib/stores/index.ts`,
`docs/inference-nodes.md`.

### Two things found while doing it

* **The frontend build now OOMs on this box.** The SSR bundle step wants ~6-8 GB of
  heap; FreeToken holds ~16 GB as *shared* memory, which shows against no single
  process in `ps`, so the failure reads as a bare
  `FATAL ERROR: Ineffective mark-compacts near heap limit` with no obvious cause.
  Stop FreeToken, build, restart it (~40 s back to serving). Documented in
  `docs/inference-nodes.md`.
* **`features.enable_sidebar_more` is the same idea, already shipped, env-only.** It
  hides Agent Studio / Neural Map / Model Comparison — "internal surfaces, not part
  of what a deployed user should be handed", which is Developer Mode's own sentence.
  Folding it behind the new switch is the obvious consolidation, but it changes the
  behaviour of a flag that already ships, so it was left alone. **Worth deciding
  before the second machine**, since that machine is exactly the "handed to someone
  else" case both flags exist for.

---

## 2026-09-03 — OmniRoute, re-looked (item 8)

Prompted by the user: *"they do give free models but the issue is you have to run the repo
and throw in the url cause its loop back — I did it for Hermes not too long ago today."*
Measured against the running trial, not re-derived from the docs.

**State: the trial container is up and has been for hours.** `omniroute-trial`, pinned to
digest `92c768c5…`, healthy, serving **115 models** on `:20129` — the `auto/*` combos
(`best-coding`, `best-reasoning`, `best-free`, `coding:free`, …) plus per-provider entries.
The compose file's hardening all holds: digest-pinned, ports on `127.0.0.1`,
`STORAGE_ENCRYPTION_KEY` + `API_KEY_SECRET` set, no `docker.sock`, no `~/.claude` bind.

**The loopback problem does not apply to Harvis.** This is the correction worth carrying:
binding to `127.0.0.1` limits the *host and LAN*, not container-to-container. `omniroute-trial`
shares `ollama-n8n-network` with the backend, so `harvis-backend` reaches
`http://omniroute-trial:20129/v1/models` → **200** today, with nothing configured. Hermes needed
the loopback URL because it is a desktop app on the host; Harvis is containers and uses container
DNS (or `172.17.0.1` if OmniRoute is run outside compose, the FreeToken pattern). So "throw in
the URL" is genuinely all that is required here — the URL is just `http://omniroute-trial:20129/v1`,
not `localhost`.

**⚠️ Finding: the inference API is unauthenticated.** Verified, not inferred — a
`POST /v1/chat/completions` with **no `Authorization` header** streamed a real completion (routed
to `big-pickle`). The management API is protected (`/api/api-keys`, `/api/settings` → 401) but the
OpenAI surface on `:20129` is not. `ollama-n8n-network` currently carries **20 containers**,
including the code-engine sidecars `harvis-claude-code`, `harvis-codex`, `harvis-opencode`,
`harvis-hermes-agent`, plus `harvis-openclaw` (the unpinned third-party image from item 9) and
`harvis-browser-runner`. Any of them can spend the user's provider quota with no credential.
**Fix before this goes anywhere near shipping: put OmniRoute on its own network shared only with
`harvis-backend`.** Network isolation, not OmniRoute's own auth — that is the boundary Harvis
controls.

**Nothing has been built.** The only occurrence of "omniroute" in the entire Python/Svelte tree is
a docstring reference in `owui_compat/free_providers.py:12`. Phases 1-3 of
`docs/design/2026-07-31-omniroute-scope.md` are all unstarted.

**The one thing worth building is Phase 1, and it is not really about OmniRoute.** The gap is
*model discovery*, not chat transport: chat is already a URL (`HARVIS_LLM_BASE_URL` is canonical
at `main.py:36-54`), but Harvis enumerates models through Ollama's native `/api/tags` across
28 files / 86 call sites, of which **7 are picker-critical**. The fix is one shim —
`list_upstream_models(base_url)`: try `/api/tags`, fall back to `/v1/models`, translate the shape
so callers do not change their parsing — then migrate those 7 sites.

That shim is now paying for itself **three times over**, which is the argument for doing it:

1. **Hermes** — the user wired it up today; an OpenAI-compatible upstream whose models do not
   populate the picker is exactly this bug.
2. **FreeToken** — the whole `plugins/inference_nodes/` layer exists partly because the picker and
   resolver need `/api/tags` and FreeToken speaks OpenAI dialect. Same gap, worked around once.
3. **OmniRoute** — and vLLM, LM Studio, llama.cpp for free.

It needs no flag, adds no container, and an upstream that already answers `/api/tags` behaves
exactly as it does today. **Recommendation: build the shim as its own piece of work, justified by
Hermes and FreeToken, and treat OmniRoute as the third beneficiary rather than the reason.**

**Unchanged from the original verdict:** do not ship or vendor OmniRoute (2.63 GB, and 38 catalog
entries carry `subscriptionRisk: true` — the `web-cookie` providers replay a consumer subscription
as an API and get *users* banned). Point-at only. The free tokens that are safe to use are the
normal API-key free tiers, not the cookie-session ones.

## 2026-09-03 — Admin Settings UI revamp

Three problems, all confirmed in the source before anything was changed:

1. **The selected tab had no active styling.** `Settings.svelte`'s tab link
   resolved to an empty class string when `selectedTab === tab.id`; the only
   difference between selected and unselected was that unselected got
   `text-gray-300 dark:text-gray-600` — a colour so low-contrast it read as
   disabled. The rail now uses a filled pill for the selection and lifts the
   resting state to `text-gray-500 dark:text-gray-400`.
2. **Panes did not fill.** Every pane was its own
   `flex flex-col h-full justify-between`, which pins content to the top of the
   viewport and Save to the very bottom. A pane with two switches rendered as
   two rows, several hundred pixels of nothing, and a stranded button.
3. **Rows stretched edge to edge.** No max width anywhere, so on a 1440px
   screen a label sat at the far left and its switch a long way to the right.

### Shared primitives — `admin/Settings/ui/`

| Component | Props | Slots |
| --- | --- | --- |
| `Pane.svelte` | `title`, `description` | default, `actions` (sticky bottom bar) |
| `Section.svelte` | `title`, `description` | default, `action` (header right) |
| `Row.svelte` | `label`, `description` | default (control, right), `detail` (left column) |

`Row`'s left column must keep `flex-1`, not just `min-w-0`. Without a flex
basis it sizes to its content, so a `w-full` input placed in the `detail` slot
resolves its percentage against an auto width and collapses to the browser's
default field size. Prose fills the column either way, which is why this only
shows up on panes that carry inputs.

### Migrated (8 of 14)

General, InferenceNodes, Connections, Interface, CodeExecution, Integrations,
Database, Evaluations. Verified mechanically against HEAD: every `bind:`,
`on:`, `id=` and `type=` identical, no `$i18n.t` literal removed, `<script>`
blocks differing only by the three `./ui` imports.

Two intentional non-layout changes to know about:

- **Connections** regrouped. It used to interleave switch → list → switch →
  list; the four toggles are now one card and the two connection lists follow.
- **Interface** lost the "Task Model" hover info-icon. Its text is now the
  section's `description`, so the string is intact and always visible. Revert
  is two lines if the icon is wanted back.
- **Integrations** dropped its `$i18n.t('General')` heading — it was a single
  heading over two unrelated groups, so no section could honestly carry it.
  The key is still used elsewhere, so nothing is orphaned.

### Not migrated (5)

Audio (893), Documents (1585), Images (1288), WebSearch (1230), Pipelines
(579) — all still on `flex flex-col h-full justify-between`. They inherit the
shell fixes (max width, active tab) but keep their own void. Left alone
deliberately: 5,575 lines of inherited OWUI that cannot be visually verified
from here. Models.svelte has its own list layout and never had the wrapper.

### Two bugs fixed alongside

- **Stranded sign-in logo.** `owui_compat/config.build_config()` published no
  `metadata` key, so the auth page took its fallback branch and pinned the
  favicon to the top-left corner of the viewport, nowhere near the centred
  card it was meant to brand. It now publishes
  `metadata.auth_logo_position = "center"`. Verified visually at
  `http://localhost:9000/auth`.
- **Stale chunks after a rebuild.** `svelte.config.js` keyed
  `kit.version.name` on `git rev-parse HEAD` alone, so a rebuild from a dirty
  tree produced an identical `version.json` and SvelteKit's reload mechanic
  never fired — a tab open across the rebuild kept chunk hashes the build had
  already deleted. The name now carries a build timestamp. This is *not* a
  caching bug: `nginx-harvis.conf` already serves `index.html` as `no-cache`
  and `_app/immutable/` as 1y immutable, and Harvis registers no service
  worker (`+layout.svelte` only unregisters stray ones).

### Verified

`vite build` exit 0 (FreeToken stopped first — the shared-memory OOM gotcha
above still applies), `docker restart nginx-proxy` for the bind mount,
FreeToken restarted and active. 55 backend tests pass. Auth page renders with
zero console errors.

**Not verified:** the admin panes themselves. They are behind auth and this
session cannot sign in. Someone needs to open Admin → Settings and look.

## 2026-09-04 — User Settings (profile menu → Settings)

Distinct from the Admin → Settings work above. Two separate complaints, two
separate causes.

### "Some items don't load"

`Settings → Account`'s entire Update Profile form was dead:

- `POST /api/v1/auths/update/profile` returned **404** — never implemented.
  `owui_compat/account.py` had shipped only the password route, and its own
  docstring said profile "needs schema work first". It was right.
- `users` had no `bio`, `gender` or `date_of_birth` column at all, and `avatar`
  was `VARCHAR(255)` — smaller than any data URI the avatar cropper produces.
- The read path was missing too: `harvis_user_to_owui` mapped `name` from
  `username` and returned none of the profile fields, so even a successful save
  would have repopulated four empty inputs.

Fixed across:

| File | Change |
| --- | --- |
| `migrations/017_user_profile_fields.sql` | new; adds `name`/`bio`/`gender`/`date_of_birth`, widens `avatar` to `TEXT`. Idempotent. |
| `main.py` | 017 added to the boot sweep; `UserResponse` and both `get_current_user` SELECTs widened |
| `owui_compat/translate.py` | `name` falls back to `username`; profile fields passed through; `date` → ISO string |
| `owui_compat/router.py` | `owui_session` forwards the new fields |
| `owui_compat/account.py` | the `update/profile` route |
| `all_schemas_safe.sql` | users block brought in line |

**`name` is a new column, not a reuse of `username`.** `username` is UNIQUE and
is the login identity; writing a display name to it would stop two people
sharing a first name and would silently change what they sign in with. `NULL`
means "never set" and falls back to `username`, so every existing row keeps the
name it already showed.

### Two bugs found while doing that

- **`get_current_user` logged the entire user row on every authenticated
  request** (`logger.info(f"User found: {dict(user)}")`). Harmless-ish with four
  columns; with the profile columns in the SELECT it would have written avatar
  data URIs and dates of birth into the container log on every call. Now logs
  the id only.
- **`migrations/` was not bind-mounted.** It was baked into the image while
  `owui_compat/` and `plugins/` are mounted, so the running image lagged the
  repo: boot logged "Migration file missing" for `016_inference_nodes.sql`, and
  `inference_nodes` existed only because an earlier session had `docker cp`'d
  the file in by hand. A fresh deploy from that image would have come up without
  the table. `./python_back_end/migrations:/app/migrations:ro` added to the
  backend service. Note the runner is an explicit tuple in `main.py`, not a
  glob — a new migration still has to be named there.

### "Some aren't taking up enough space"

The modal shell was already fine (`md:w-[min(1150px,96vw)]`, 220px rail,
`flex-1 min-w-0 md:px-7 md:py-6` content pane). The problem was a half-finished
migration: 7 panes used the shared `SettingsSection`/`SettingRow`, 5 did not, so
they rendered cramped beside their neighbours.

Migrated: Account (+ `UpdatePassword`, `UserProfileImage`), Connections
(+ `Connection`), Integrations (+ `Terminals`), WorkspaceSettings,
`Tools/Connection`. **All 11 top-level panes are now on the primitives.**

Gotcha worth keeping: a non-stacked `SettingRow`'s left column is content-sized,
so a `w-full` input beside it will not fill. Use `stack={true}` for textareas,
URL/key inputs, lists and sliders.

Still unmigrated: `Skills/SkillsManager.svelte` (574) and
`agent-studio/customize/ConnectorsPanel.svelte` (958, outside the Settings dir).

Judgement calls the agents flagged, all one-line reverts: the avatar's
Remove/Initials/Gravatar buttons are now always visible instead of hover-only
(hover-only was unreachable on touch); section descriptions moved above their
lists rather than below, per the primitive's idiom; the Open Terminal
"Experimental" badge moved to the right of its heading because
`SettingsSection`'s title is a plain string prop.

### Verified

Migration applied and confirmed idempotent; `UPDATE ... RETURNING` exercised
against a real row inside a rolled-back transaction (4000-char avatar stored,
date parsed, row left untouched). Backend boots with **zero** migration
warnings and the container's `migrations/` now matches the repo exactly. Route
answers 401 instead of 404. All 9 changed Svelte files compile; every `bind:`,
`on:`, `aria-*` and `type=` multiset identical to HEAD; no `$i18n.t` string
removed. `vite build` exit 0, nginx restarted, FreeToken back up. `/`, `/auth`
and `/api/config` all 200.

**Not verified:** the panes themselves. The modal is behind auth and this
session cannot sign in.

## 2026-09-04 — Admin Settings UI revamp, completed

Finishes the pass started earlier (see the Admin Settings section above) and
resumed after a detour into the user Settings modal. **All 14 tabs under
`/admin/settings/*` are now on the shared primitives** in
`components/admin/Settings/ui/` — `Pane` (header + sticky actions bar),
`Section` (titled card), `Row` (label/description left, control right).

Migrated in this pass: Documents (1585→1512), Images (1288→1094),
WebSearch (1230→1052), Audio (893→863), Models (780→775),
Pipelines (579→556). Previously done: General, Connections, Interface,
CodeExecution, Integrations, Database, Evaluations, InferenceNodes.

### Two gotchas worth keeping

**`svelte-check` is not a gate in this repo.** It reports 9,699 errors and 301
warnings across 444 files at baseline (implicit-`any` and `SessionUser` drift in
routes and chat components), so a new error does not stand out. Worse, it
reported *zero* errors on `Pipelines.svelte` while the Svelte compiler rejected
the file outright. Only `vite build` tells the truth.

**A conditional `slot="actions"` does not compile.** Pipelines had
`{#if PIPELINES_LIST?.length}<svelte:fragment slot="actions">`; Svelte requires
a slot fragment to be a direct child of the component. The condition moved
inside the fragment, and `Pane`'s bar became `hidden has-[>*]:flex` — because
`$$slots.actions` is compile-time, a pane whose Save button sits behind an
`{#if}` still reports the slot as filled and would otherwise leave an empty
bordered strip pinned to the bottom. `{#if}` anchors are comment nodes, which
`:has(> *)` ignores, so the bar collapses correctly. Requires Tailwind 4 (in
use).

### Verified

Every migrated file diffed against HEAD as multisets of `bind:`, `on:`, `id`,
`type`, `placeholder`, `aria-*`, `{#if}`/`{#each}` expressions and `$i18n.t`
strings — all identical; the only differences flagged were re-indentation
inside multi-line string literals. Each script block differs from HEAD by
exactly the three `./ui/` imports. Documents keeps all 27 Tooltips with every
`content=` verbatim. `vite build` exit 0. nginx restarted, FreeToken back
`active` and answering on 172.17.0.1:1919. `/`, `/auth`,
`/admin/settings/general` and `/api/config` all 200.

**Not verified:** the panes themselves. `/admin/settings/*` is behind auth and
this session cannot sign in.

### Pre-existing bugs found in Documents, deliberately NOT fixed

- **Reset Vector DB always reports success.** `ResetVectorDBConfirmDialog`'s
  `on:confirm` does not await `resetVectorDB(...)`, so `res` is a Promise —
  always truthy — and the success toast fires even on failure, alongside the
  error toast. The other two confirm dialogs await correctly.
- **Embedding-model download button double-submits.** The button beside the
  Embedding Model input has no `type="button"`, so inside the `<form>` a click
  runs `embeddingModelUpdateHandler()` and also submits, running it again plus
  `updateRAGConfig`.

Both are one-line fixes, held back to keep this diff presentation-only.

## 2026-09-04 — Dependency vulnerability remediation

### The headline is not a CVE

`requirements-core.txt` pinned `python-jose[cryptography]==3.4.0` **in the
working tree only**. Both `main` and the `fixes` HEAD still said `3.3.0`, which
carries CVE-2024-33663 (CRITICAL, algorithm confusion with OpenSSH ECDSA keys).
The fix had been written in an earlier session and never committed, so the
built image installed the vulnerable version. Same for `python-multipart`.

This is the third instance today of one failure class: **what runs is not what
the repo describes.** The other two were `migrations/` not being bind-mounted
and the backend image being five weeks stale.

### Fixed

| Package | Was | Now | Why |
| --- | --- | --- | --- |
| python-jose | 3.3.0 | 3.5.0 | CVE-2024-33663 (critical), CVE-2024-33664 |
| pyasn1 | 0.4.8 | 0.6.4 | four HIGH DoS advisories |
| cryptography | 49.0.0 | 50.0.1 | CVE-2026-69247 (high) |
| pypdf | 6.14.2 | 6.17.0 | 8 advisories; parses every uploaded PDF |
| nltk | 3.10.0 | 3.10.3 | critical + 2 high, arrives via newspaper3k |
| h2 | 4.4.0 | 4.4.1 | CVE-2026-71554 request smuggling |
| python-multipart | ==0.0.31 | ==0.0.32 | the pin was *below* what was running |
| dompurify | 3.2.6 | 3.4.14 | the sanitizer between model output and XSS |

Backend advisories: **6 packages → 2**. Both survivors have no upstream fix and
are documented inline: `ecdsa` (CVE-2024-23342 Minerva timing attack — inert,
Harvis is HS256-only and every `jwt.decode` passes `algorithms=[...]`) and one
`nltk` model-artifact path escape reachable only through download APIs Harvis
never calls.

### 3.5.0, not 3.4.0 — and why re-scanning matters

The first rebuild looked like a clean success and was not. `python-jose 3.4.0`
declares `pyasn1<0.5.0`, which walked pyasn1 from 0.6.4 back to **0.4.8** and
reintroduced four HIGH DoS advisories. One critical traded for four highs.
`3.5.0` relaxed the constraint to `pyasn1>=0.5.0`. This was caught only by
re-running the OSV scan *after* the rebuild. Never assume a security bump is a
net improvement — measure it.

### The larger problem the rebuild exposed

`requirements-core.txt` is almost entirely unpinned. A `--no-cache` rebuild
floated **80 packages**, including majors nobody chose: `openai` 2.50.0→3.8.0,
`anthropic` 0.120.2→1.3.0, `starlette` 1.3.1→1.6.0, `primp` 1.3.1→2.0.0,
`xxhash` 3.8.1→4.0.1. Nothing broke — 679 passed, 13 skipped, and
`test_engine_auth_modes` exercises the Claude credential path — but that is luck,
not design. Any fresh deploy gets whatever is newest that day. The real fix is a
compiled lockfile (pip-compile or uv) for the backend.

### On a scanner reporting ~2000

It is not application code. All four node subprojects total **34** npm
advisories (owui 23, of which 16 are dev-only; newjfrontend 9; open-notebook 1;
harvis-web-search 1) and the backend now has 2. The volume is OS packages in
base images: `model-downloader` on `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime`
(~15.4 GB) and `tts-service` on `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`.
Also unpatchable by pinning: `Dockerfile.executor` on `node:18-alpine` (EOL
Apr 2025) and six services on `node:20` (EOL Apr 2026). The backend already
escaped this via `Dockerfile.core` on `python:3.12-slim` (Debian 13, 325 OS
packages).

### Left alone, deliberately

- **xlsx (SheetJS)** — high, prototype pollution, reachable at
  `excelToTable.ts:41` on user-uploaded spreadsheets. No fixed version exists on
  npm; SheetJS stopped publishing there at 0.20.x and moved to their own CDN.
  Remediation changes where a dependency comes from — a supply-chain decision.
- **vite 5→8, vitest 1→5, cypress 13→16** — the loudest labels in `npm audit`,
  all `devDependencies`. Vite 5→8 would likely break the SvelteKit build and
  none of them ship.
- **uuid 9→14** — advisory is specific to v3/v5/v6 with a `buf` argument. All 45
  call sites use `v4`. Not applicable.
- **qs** — dev-only, reached solely through cypress.

### Pre-existing, found while verifying

`tests/test_chat_sandbox.py` imports `_cli_visible_delta` from
`owui_compat.cloud_chat`; that function exists nowhere in the repo. Both files
match HEAD, so the module has been failing to import for some time. Excluded
from the run; needs its own fix.

### Verified

`vite build` exit 0 and backend image rebuilt twice from scratch. 679 tests
pass. JWT round-trips on 3.5.0 with wrong-key and algorithm-mismatch both
rejected; bad token gives 401, not 500. `/`, `/auth`,
`/admin/settings/general`, `/api/config`, `/health` all 200; FreeToken back
`active` and answering on 172.17.0.1:1919.

## 2026-09-04 — The app was not booting at all

Found while setting up the visual review of the Settings panes. Every route
returned 200 and the page never left the splash screen.

`TypeError: Cannot read properties of undefined (reading 'data')`, thrown inside
`kit.start()`. Through the sourcemap: `@sveltejs/kit/src/runtime/client/client.js:337`,
reading `globalThis.__sveltekit_txodb1.data` — while the bootstrap script in
`index.html` declared `__sveltekit_denurp`. Same build, two different globals.

### Cause

`svelte.config.js` had `kit.version.name` built from `Date.now().toString(36)`.
SvelteKit derives the `__sveltekit_<hash>` bootstrap global from that name, and
**Vite evaluates the config once per build pass** — once for the client, once
for the server. Two evaluations, two timestamps, two names, two globals. The
runtime read one, the HTML defined the other.

This was an uncommitted working-tree change, not something from `main`.

### Why it wasn't caught

`export const ssr = false` in `src/routes/+layout.js` and `fallback: 'index.html'`
in the adapter config mean nginx answers **200 with the same shell for every
path**, including routes that don't exist and builds whose JS dies on boot. The
curl loop over `/`, `/auth`, `/admin/settings/general` that had been used as the
verification step all session proves only that nginx found `index.html`.

Verifying this app requires the browser: load it, confirm `#splash-screen` is
gone, read the console.

### Fix

`version.name` still has to change when the tree changes — a commit-only name
means a dirty-tree rebuild writes a byte-identical `version.json`, so a tab open
across the rebuild keeps chunk names the build already deleted and 404s on the
next lazy route. It just must not be a clock. It is now the short sha plus a
sha256 of `git status --porcelain=v1 && git diff HEAD`: stable across the two
passes of one build, different whenever the output would differ.

Verified — three separate config evaluations return `9f758eda-683b4e569b1a`, the
rebuild puts `__sveltekit_8erwbv` in both `index.html` and the chunks, and the
sign-in page renders with no console errors.

### Build check worth keeping

    grep -o '__sveltekit_[a-z0-9]*' build/index.html | sort -u
    grep -rho '__sveltekit_[a-z0-9]*' build/_app/immutable/ | sort -u

These must agree (chunks also legitimately contain `__sveltekit_fetch`).

## 2026-09-04 — Four bugs fixed ahead of the visual review

- `common/SensitiveInput.svelte` — `id` defaulted to the literal
  `'password-input'`, so every instance shared it. WebSearch renders 28 in one
  pane; the change-password form renders three; each `sr-only <label for>`
  resolved to the first field. Now unique per instance. Safe because the app is
  SPA-only, so there is no hydration pass to mismatch.
- `admin/Settings/Documents.svelte` — `resetVectorDB` was not awaited, so `res`
  held the Promise (always truthy) and a failed reset fired the error toast and
  the success toast together.
- `admin/Settings/Documents.svelte` — the embedding-model download button had no
  `type="button"` inside the form, so one click ran the handler and then
  submitted, running it again plus `updateRAGConfig`.
- `chat/Settings/WorkspaceSettings.svelte` — a non-ok GET fell through silently,
  leaving the form showing hard-coded `ollama` / `http://ollama:11434` as if
  they were the saved config; Save then wrote those over the real one. Now an
  error banner with Retry, Save and Reset disabled while errored, and a failed
  DELETE no longer swallowed.
- `chat/Settings/Account/UpdatePassword.svelte` — removed three inert `class=`
  attributes. `SensitiveInput` takes `inputClassName`/`outerClassName` and never
  declared `class`, so they were silently dropped.
- Four systemd units under `scripts/freetoken/` had `Documentation=` pointing at
  `/home/ommblitz/Projects/Recent-EX/Harvis/...`; now the GitHub URL.

Still open: the inert-`class`-on-`SensitiveInput` pattern is repo-wide and
pre-existing at HEAD (`AddUserModal`, `EditUserModal`, `AddToolServerModal`).
Making the component accept `class` fixes all of them but changes styling in
~70 places, so it wants its own pass.
