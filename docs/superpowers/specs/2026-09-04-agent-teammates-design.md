# Agent Teammates — design spec

Date: 2026-09-04. Branch: `fixes` (never `main`). Status: design approved in
conversation by David; **not committed** — David commits after review.

Written for two readers: David (product owner, non-technical on the internals)
and the implementing model (Claude Opus 5 or later). Read it end to end before
writing a plan. Everything a planner would otherwise have to rediscover is in
here, with file paths.

---

## 1. The goal, in plain words

Harvis is a self-hosted AI workspace running on David's own hardware. It
already hosts several real agent engines as Docker sidecars (Hermes, Claude
Code, Codex, OpenCode, OpenClaw) next to chat, voice, documents, research, CAD
and a messaging gateway. Today those engines are tools you point at a task.

**The goal is to turn Harvis into the place where AI teammates live and work:
named agents with a personality and a job, each with its own room, its own
memory, and its own computer that you can watch, so you can hand them real
tasks and trust the result.**

### What "done" looks like for David

- Open the Agents area, see a roster of Harvis heads. Each has a name, title,
  one-line job, instructions, model, engine, and an autonomy setting.
- Open an agent's room and say what you want. It restates the goal, shows a
  short plan, works on its own browser and workspace while you watch or walk
  away, and comes back with the finished thing (file, report, link). Then it
  suggests what it would do next and waits.
- Safe actions just happen and are logged. Sending, deleting, paying and
  signing in stop and ask, in the room and on your phone. If you said "just do
  all of it," your word wins.
- @-mention an agent in any normal chat and it answers alongside whatever
  model is already there. Agents can hand each other work.
- Optionally an agent checks in on a schedule and reports via Discord or
  Telegram. Off by default.
- Nothing leaves the machine unless David connected a cloud model or service.

### The one acceptance test

Tell an agent: "research the top ten alternatives to X and put them in a
spreadsheet in my workspace." Walk away. Come back to: the spreadsheet in the
agent's workspace, a two-line summary, a log of everything it touched, and a
next-step suggestion — with no gated action skipped.

### What we are NOT doing

- Not writing a new agent loop to compete with Hermes. We add a coordinator
  above the loops that exist.
- Not building a cloud service. Not touching `main`.
- Not chasing every Odysseus feature now (email triage, calendar come later).
- Not scanning the LAN (campus network). Outbound HTTPS is fine.

---

## 2. Why this target (competitive context, verified 2026-09-04)

Everyone is converging on "agent = persona + its own computer + memory + a
room". Harvis is the only one that already has multiple engines, voice,
research and a messaging gateway on local hardware. The missing pieces are
the **governed computer** and the **roster**.

| Product | What it is | What Harvis takes from it |
|---|---|---|
| Anthropic computer use | Client-side tool: the app supplies the environment, model returns actions. Claude in Chrome reads pages as an accessibility tree with element refs. | Refs-over-pixels observation; the host owns the environment. |
| OpenAI Operator / ChatGPT Agent | Hosted VM browser the user watches and can take over. (General knowledge, not verified this session.) | Watch + take-the-wheel. |
| Hermes v0.17 (`/opt/hermes/tools/` in `harvis-hermes-agent`) | `browser_camofox.py`: Camoufox browser over REST, a11y snapshot with refs, click-by-ref, VNC URL from `/health`, persistent tab per task, loopback rewrite. `computer_use_tool.py` is macOS-only (cua-driver). `set_approval_callback` gates actions. `mixture_of_agents_tool.py`, `budget_config.py`. | Set `CAMOFOX_URL` on the Hermes sidecar so Hermes uses the Harvis-hosted browser. Borrow budget and approval-callback shapes, and its **self-improving loop**: the agent writes a new tool or skill when it hits a gap, then reuses it on later runs against a memory store that keeps growing. Nous Research ships it MIT-licensed, reaching 15+ chat platforms from one gateway across 5+ sandbox backends, cheap enough to run on a $5 VPS. That is evidence this shape does not need our hardware, so our moat is the governance, not the compute. |
| Grok Bot (xAI, beta 2026-08-11) | Bot profile (name, title, description, avatar), memories, skills, routines, own persistent cloud computer with own logins, keeps working when laptop closed. Templates (2026-08-28) bundle instructions + memories + skills + routines. Routines are taught **by demonstration**: the user does the task once with the bot watching, and the bot saves the replayable procedure. Sold bundled into Cursor and SuperGrok at about $30/month. | Profile shape, templates, "one focused job per bot", and routines-by-demonstration as the stronger form of our self-written skills (§6, M10). |
| Perplexity Computer (2026-02-25; Portable/Personal local versions 2026-08) | Orchestrator + subagents across 19 models, sandbox with real FS + browser, 100+ connectors (OAuth/MCP), persistent memory, runs hours-to-months, **checks in only when truly stuck**, delivers finished deliverables not summaries. Local versions still require approval for sensitive actions + kill switch. | The run shape (§5). Orchestrator dispatches per step to the best engine — with our five engines instead of their nineteen models. |
| Odysseus (PewDiePie, 1.0, 2026-05-31; copy at `~/Projects/Odysseus/odysseus`) | One FastAPI app + ChromaDB + SearXNG + ntfy. **CrewMember**: name, avatar, personality, model, endpoint, greeting, enabled_tools, pinned session. Personal assistant = a CrewMember with three daily **check-in** ScheduledTasks (morning/midday/evening), pushed via ntfy/browser/email. Task kinds: `llm`, `action`, `research`. Safety is a per-crew toggle (`allow_autonomous_email`), no gate, no audit, no watched browser, single loop. | CrewMember shape, check-in rhythm, tasks the agent acts on. Do better on: gate + audit instead of toggle, multi-engine, watched browser, agent-to-agent hand-off. |
| OpenBot (CopilotKit; `~/Projects/resource-grabber/vendor/openbot`) | Every browser/file/MCP action goes through one gateway: resolve target → evaluate CEL policy → write audit row → then act. Fails closed. One container per agent with own Chromium, profile, workspace. AG-UI protocol. | The governance model verbatim: policy at the gateway, audit before act, fail closed. |
| OpenMausBot (`vendor/openmausbot`) | "AI as a messaging app": sidebar roster of bots, each with personality, model, thread memory, own computer; bots are the `claude`/`codex` CLIs run locally. | The roster UX. Same sidecar trick Harvis already uses. |
| Rakazo (`vendor/rakazo`) | Persistent bots with routines/history; shared "team computers" + private ones; bots delegate to peer bots or subagents. | Team vs private computer (later), delegation (later). |
| OpenClaw (positions itself as "an OS for AI agents"; 180k+ GitHub stars reported by Feb 2026) | Hub-and-spoke: one local-first Gateway on port 18789 that every client and plugin talks to. Four plugin extension points, 35+ model providers behind one interface. | The single-door idea. Harvis already has it in `plugins/agents/intake.py` — chat, `POST /run`, cron and Discord all go through one function, so governance cannot be sidestepped by picking a different door. |
| ChatGPT 6 "Astra" (reported ~Sept 2026) | OpenAI **self-reported** ARC-AGI-3 99.9%, OSWorld 2.0 72.6% at roughly 40 minutes per task, ExploitBench 100% with release gated to trusted defenders. "Opaque recurrence" in Codex. Pricing about 2.5x prior. The accompanying AGI framing is disputed. | Two things only. Long-horizon computer use is now the benchmark that matters, so our run-length target is tens of minutes, not tens of seconds. And capability gating by trust tier is a real shipped product pattern, which is what `cleared_limits` is. Treat every number in this row as unverified vendor marketing and do not design against it. |

Full notes: `~/Projects/resource-grabber/docs/FINDINGS.md` §1–4.

---

## 3. What Harvis already has (do not rebuild these)

Verified in the tree on 2026-09-04. Paths relative to repo root.

- **Native loop**: `python_back_end/workspace/orchestration/runner.py` (1322
  lines; `max_steps=12`, wall-clock cap, step loop at ~line 773). Tools in
  `orchestration/tools.py` (880 lines): `exec`, `screenshot_preview`, five
  `agent_reach_*` research tools. **No browser tool is exposed to the model.**
- **Engine adapter**: `orchestration/engine_adapter.py` (1525 lines). Drives
  `opencode`, `codex`, `claude-code`, `hermes-agent` (and `kimi-code`) as CLI
  subprocesses inside their containers (`docker exec`). Hermes is invoked as
  `hermes -z <brief> --yolo -m <model>`.
- **Run event log**: `workspace_events` table (run id + seq). Runs are
  already recorded step by step — resume/interrupted logic builds on this.
  ⚠ Run `67155356` seq 14 contains a live Kimi key and gateway token; David
  deferred rotation. Never print it.
- **Browser runner**: `browser_runner/app.py` — Selenium Firefox,
  `/health /session /navigate /act /close /screenshot`. Healthy, but
  pixel-oriented, no a11y snapshot, no VNC, no per-agent profile. Only
  consumer today is `python_back_end/vision_to_code/preview.py`.
- **Terminal container**: `python_back_end/workspace/terminal_container.py`
  (`HARVIS_TERMINAL_ENABLED` default false; ubuntu:24.04, 1 CPU / 512 MB).
- **Research tools**: `python_back_end/agent_reach/tools.py` (SSRF-pinned;
  never mounted in the OpenClaw pod).
- **Persona storage**: `python_back_end/plugins/soul/` — per-user SOUL.md
  (`GET/PUT/DELETE`, `POST /seed-default`). Storage only; nothing composes it
  into a prompt yet. Adapted from Hermes `default_soul.py`.
- **Skills bridge**: `python_back_end/owui_compat/hermes_skills.py`,
  `skill_audit.py`. UI `Skills/SkillsManager.svelte` is unmigrated.
- **Vector store**: `python_back_end/rag_corpus/` (pgvector via
  `embedding_adapter.py`, `init_tables.py`).
- **Job queue**: `python_back_end/job_queue.py` (`Job`, `JobQueue`,
  `enqueue_*`). Used for TTS/whisper today; extend for scheduled check-ins.
- **Messaging gateway**: `plugins/messaging-gateway` (compose service
  `harvis-messaging-gateway`). Code references Discord, Slack, Signal,
  Telegram, email. Use it for approvals and "I'm stuck" pings.
- **MCP catalog**: `python_back_end/owui_compat/mcp_catalog.py` (installable
  MCP servers; `puppeteer_*` entries are catalog, not wired tools).
- **Cookbook backend**: compose service `llmfit` (pinned 0.9.30) — the same
  thing Odysseus's Cookbook is built on.
- **Frontend (SvelteKit, OWUI fork, `front_end/owui`)**:
  - Multi-model chat exists: `selectedModels` and `atSelectedModel` in
    `src/lib/components/chat/Chat.svelte` (~227, 558, 3039, 3214) and
    `MessageInput.svelte` (~193). `@model` already routes a message to one
    model; `Messages/MultiResponseMessages.svelte` renders several replies
    side by side. **This is the "invite an agent" mechanic — reuse it.**
  - Channel UI exists with **no Harvis backend**:
    `src/lib/components/channel/{Channel,Thread,Messages,MessageInput,
    Navbar,ChannelInfoModal,PinnedMessagesModal}.svelte`, `lib/apis/channels`.
    These are the "rooms".
  - Agent Studio: `src/lib/agent-studio/` — `AgentSession.svelte`
    (props `agent: RunNode, events, running, parentId`), `Brain.svelte`
    (`mode: 'full' | 'dock'`). Dock-ready run view.
  - Only one avatar asset: `static/harvis-logo.svg`. Harvis heads need to be
    drawn.
  - Two Settings primitive sets: admin `ui/Pane|Section|Row` vs user
    `SettingsSection|SettingRow`. Never cross-import.
- **Sidecars in `docker-compose.yaml`** (30ish services): backend,
  browser-runner, preview-runner, frontend, nginx (:9000), open-notebook,
  document-worker, pgsql, openclaw (+db-init, surrealdb), harvis-mcp,
  tts/voice-onnx/stt, messaging-gateway, opencode, codex, claude-code,
  hermes-agent, cad-engine, agent-reach-sandbox, sentrysearch-mcp, llmfit.

---

## 4. Section 1 — What an agent is (approved)

An **agent** is a saved profile plus the things it owns.

**Profile** (persisted, per Harvis user; multi-tenant):

| Field | Notes |
|---|---|
| `name`, `title`, `job` (one line), `instructions` (long) | Odysseus CrewMember + Grok Bot profile shape. |
| `avatar` | A Harvis head. Needs a small set of drawn variants; fallback = logo with a colour. |
| `engine` | `harvis-native` \| `hermes-agent` \| `claude-code` \| `codex` \| `opencode` (OpenClaw later; it stays isolated). |
| `model` | From the model manager. Per-agent, switchable mid-conversation. |
| `tools` | Enabled tool list (explicit allow-list; empty = nothing). |
| `autonomy` | See below. |
| `budget` | Default time + token cap per run (borrow Hermes `budget_config` shape). |
| `check_ins` | Optional schedule + prompt list. Off by default. |
| `is_default_assistant` | One per user, like Odysseus. |

**Owned by the agent**: one **room** (persistent chat = the channel UI), one
**workspace folder**, one **browser profile** (cookies persist between runs),
its **memory** (§6), its **skills** (§6), its **run history**.

**Autonomy — one default, one override.** "Safe" means any action that is
not one of the four hard limits below and is within the agent's tool list;
there is no third category.
- Default: safe actions run and are logged; the four hard limits (**send,
  delete, pay, sign in**) pause and ask; at the end the agent **proposes
  what's next and waits**.
- Override: if the user says "just do all of it" / "don't stop to ask" in the
  request, run straight through and only pause for the four hard limits,
  unless the user cleared those too *for that task*. **The user's instruction
  in the moment always beats the profile setting.**

**Templates**: export an agent as a bundle (profile, instructions, chosen
memories, skills, routines); import to clone. Grok Bot template shape.

---

## 5. Section 2 — The life of a run (approved)

A **run** is the unit of work. One record, one event stream, one room card.

1. **Intake.** Four sources create the same run record through the same door:
   a message in the agent's room; an `@agent` mention in any chat; a scheduled
   check-in firing; another agent handing off. The record carries who asked,
   which agent, and any override words. The agent restates the goal in one
   line so a wrong reading is caught early.
2. **Plan.** A short numbered plan, visible in the room, updated as it goes.
   Small tasks get a one-step plan and go straight to work.
3. **Dispatch.** The **coordinator** (new; sits above the loops, replaces
   nothing) routes each step to the engine that fits: quick lookups and file
   edits → native loop; long coding → Claude Code / Codex; browsing and
   research → Hermes on the shared governed browser. Engine down → swap to
   another that can do the step, and say so on the card.
4. **Act.** Steps run on the agent's governed computer (§7). Safe actions go
   straight through the gateway and get an audit row. Hard-limit actions pause
   the run and send an approval request to the room **and** through the
   messaging gateway (Discord/Telegram), where Approve/Deny replies work too.
5. **Deliver.** A **delivery card** in the room: the artifact (file, report,
   link, screenshot), a two-line summary, a log of what it touched, and the
   "next I'd do" line with Approve. Built from recorded events, not from the
   model's claim. Artifact saved in the agent's workspace.
6. **Propose next.** One to three suggestions, one-click approve, then back to
   standby — unless told to keep going.

**Ask-versus-assume rule** (goes in every agent's system prompt): make the
reasonable assumption and state it; ask only when two readings would produce
different work, or when a hard-limit action is next. Perplexity's "only when
truly stuck".

**When things go wrong**: a failed step retries once with the error in view;
second failure asks the user. Budget hit or Stop click ends the run with a
card. On backend restart, any run marked `running` is resumed from its last
completed event or marked `interrupted` with a card — never silently lost.

---

## 6. Memory and skills that grow (approved)

- **Three memory layers**, all in the existing vector store, namespaced:
  1. shared "about you" (preferences, boundaries, how David likes things) —
     every agent reads it; seeded from the soul plugin's SOUL.md;
  2. per-agent facts learned about its job;
  3. searchable run history so "do it like last time" works.
- **Skills the agent writes itself**: after a non-trivial successful run the
  agent may save the steps as a named skill in its own folder. Readable
  through the Hermes-skills bridge so a skill written under one engine is
  usable by another.
- **Editable**: memory and skills are plain files in the agent's workspace,
  shown in its room. The user can correct, delete, pin. **An agent never
  rewrites text the user wrote.** (Same rule as the Nexusys vault.)
- **Templates** bundle chosen memories and skills (§4).
- **Prior art to read before building this (M10).** Hermes' self-improving loop — write the missing tool, then reuse it — is the closest working example of an agent that grows its own skills, it is MIT-licensed, and it is already a Harvis sidecar. Grok Bot's routines-by-demonstration is the same idea with a better teaching gesture: the user performs the task once and the agent saves the procedure instead of inferring it from a transcript. Ship the Hermes shape first, where a skill is drafted from a successful run and never auto-applied. Keep demonstration capture as a later upgrade, because the governed browser already records every action by element ref, and that trace is exactly what a demonstration needs.

---

## 7. The governed computer

Replace/upgrade `browser-runner` with a Camofox-style service:
- a11y **snapshot with element refs**, click/type/scroll **by ref**,
  screenshot on demand (refs-over-pixels: cheaper, more reliable);
- **VNC/noVNC live view** for the room, with a **take-the-wheel** toggle
  (user drives, agent waits, hand back);
- **per-agent browser profile** (cookies persist; signing in stays a
  hard-limit action; David signs in once inside the live view);
- loopback rewrite so agents can drive Harvis's own local apps;
- exposed as a native tool in `orchestration/tools.py` **and** as
  `CAMOFOX_URL` for the Hermes sidecar, so every engine shares one watched
  browser. Terminal via the existing `terminal_container.py`.

**Gateway (OpenBot model)**: every browser / file / shell / MCP action from
any engine resolves its target → is evaluated against the agent's tool list
and the four hard limits → writes an audit row → then acts or refuses naming
the rule. **Fails closed**: no policy = nothing allowed. The computer never
decides policy.

**Stop**: a Stop on every running card kills the run at the next step.

---

## 8. Gaps found and how each is closed

| Gap | Plan |
|---|---|
| Where a task comes from | One intake, four sources (§5.1). The room is just the view of that agent's runs. |
| Ask vs assume | Written rule in every system prompt (§5). Personality text sits on top, never replaces it. |
| What "done" looks like | Delivery card built from run events (§5.5). |
| Stop / take over | Stop button; take-the-wheel on the live view (§7). |
| Reaching David when away | Approvals and "stuck" via messaging gateway; replies work from there (§5.4). |
| Limits per run | Per-agent default time+token budget; override can raise for one task (§4). |
| Its own logins | Per-agent browser profile; sign-in gated (§7). |
| Resume after crash | Built on `workspace_events` (§5, §3). |

---

## 9. Build order (sub-projects; each gets its own spec → plan → implementation)

1. **Agent identity + governed computer** — this spec's core: agent records,
   coordinator, gateway + audit, governed browser, delivery card, propose-next,
   memory/skills namespacing, messaging-gateway approvals. Functionality first.
2. **Rooms and invites** — backend for the existing channel UI; `@agent`
   mention in a normal chat pulls the agent in (reuse `atSelectedModel` +
   `MultiResponseMessages`); agent-to-agent hand-off.
3. **Roster UI** — Agents area with Harvis heads, room view with live screen,
   approvals inbox, memory/skills panels, templates import/export.

Later (not in these three): shared team computer, learn-by-demonstration,
email/calendar via gateway, blind-compare mode, Cookbook UI on `llmfit`.

---

## 10. Testing

- Every gate rule: a test that attempts the risky action and confirms the run
  paused with an approval request (and an audit row).
- Every intake source: a test that a run record is created and the four paths
  converge.
- Override: "just do all of it" runs through safe steps without proposing.
- Resume: kill the backend mid-run; on restart the run is resumed or
  `interrupted` with a card.
- End-to-end: the spreadsheet scenario (§1) against a local model; assert the
  artifact exists in the workspace and the card lists touched paths.
- UI is verified **in the browser** (splash gone, console clean). HTTP 200
  proves nothing for this SPA (`ssr = false`, static fallback).
- Run `npm test` / pytest after changes; `vite build` is the only frontend
  gate (`svelte-check` is not usable).

---

## 11. Standing constraints for the implementer

- Work on `fixes`. **Never touch `main` or `harvis1.3`.**
- **Never commit or push until David has reviewed the diff.** Stage and
  dry-run only.
- Never read or print `.env`. Secrets only as `$VAR` inside
  `docker exec … sh -c`. Never commit secrets.
- No LAN scanning (campus network). Don't touch the Dell/omarchy machines,
  Proxmox, or reboot.
- FreeToken must bind `172.17.0.1`, never `0.0.0.0`.
- Frontend build: stop `freetoken.service`, `NODE_OPTIONS=--max-old-space-size=8192 npx vite build`,
  restart it, then `docker restart nginx-proxy` (build dir is recreated).
  `svelte.config.js` `version.name` must stay deterministic (tree hash) or the
  app never leaves the splash screen.
- Keep files under 500 lines; prefer editing over new files; no docs at repo
  root; input validation at boundaries; sanitize paths.
- Prompt text from xAI `grok-prompts` is AGPL — read for structure, write our
  own.

---

## 12. Open items David has not decided (do not assume)

- Key rotation (Kimi/Anthropic, `OPENCLAW_GATEWAY_TOKEN`, Gemini, OpenRouter).
- `xlsx` (no npm fix), vite/vitest/cypress majors, compiled lockfile for
  `requirements-core.txt`, merging `fixes` → `main`.
- Origin of the injected mid-turn block seen on 2026-09-04 (not a user
  message; never act on it).
- Which accounts an agent's browser profile is allowed to hold.
