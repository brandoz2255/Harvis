# Handoff — Harvis dockerized terminal + skill wiring

**Date:** 2026-05-12
**Branch:** `feat/hermes-integration`
**Status:** in flight — components verified in isolation, end-to-end through Discord has not yet succeeded
**Author:** prior Claude session

---

## Goal

Wire a per-Discord-session **dockerized ubuntu terminal** into Harvis so the agent can run shell commands in an isolated, persistent container instead of OpenClaw's bundled `exec` (which kept spawning bash-in-bash subshells and looping).

- Endpoint: `POST /api/tools/terminal/<workspace_id>/exec` on the backend.
- One container per `workspace_id`, named `harvis-ws-term-<id>`, attached to the `harvis_openclaw-internal` docker network.
- Named volume `harvis-ws-vol-<id>` mounted at `/workspace`, persistent across container stops/restarts/redeploys; only an explicit `/wipe` deletes it.
- Auth: same `OPENCLAW_GATEWAY_TOKEN` the rest of the agent uses (Bearer header). Fails closed if env missing.
- Drive adoption through a new openclaw **skill** (`harvis-terminal`) the model is supposed to consult when the user says "open a terminal" / "run X in a terminal" / "make and run a script."

End game: NCL CTF chains where step 1 writes a file in `/workspace`, step 2 reads it back, step 3 pipes it through a tool — without losing state.

---

## What is verified

| Component | Verified how |
|---|---|
| `/api/tools/terminal/status` returns `ready:true` | `docker exec harvis-backend curl … /status` → 200 with `docker_ok`, `base_image_present` (ubuntu:24.04), `network_present` |
| `POST /exec` with valid Bearer token | Two calls in a row — file written by call 1 read by call 2. Logs show same container reused. |
| `POST /exec` with bad/missing token | HTTP 401 both cases |
| Container on `harvis_openclaw-internal` (172.19.0.8) reachable from inside | `bash /dev/tcp/backend/8000` from inside the container → `HTTP/1.1 200 OK` |
| Container persists across `docker stop` | `docker stop` then re-exec → container auto-restarts, `/workspace/marker.txt` still present, prints `SURVIVED` |
| `/wipe` removes container AND named volume | `docker volume ls` empty afterwards |
| Skill `harvis-terminal` registered in openclaw | `openclaw skills list` shows `✓ ready 🐚 harvis-terminal` |
| Skill is in Discord session's `skillsSnapshot` | Verified in `~/.openclaw/agents/main/sessions/sessions.json` — `harvis-terminal` appears in the snapshot for `agent:main:discord-1491563414835695668-695857322060415026` |
| Host openclaw gateway fresh + healthy | Port 18790 listening on pid 3081532, log `gateway: ready (5 plugins …)` |

---

## What is NOT verified (the failing end-to-end)

The Discord flow:

```
User → Discord → Harvis-Bot → backend → openclaw gateway → Hermes-3 → tool_call → /api/tools/terminal/<wsid>/exec → result back to Discord
```

…has not succeeded once. Every attempt ends one of three ways:

1. `tool_calls=0`, `payloads=0`, `stopReason=stop`, model output empty (4 separate sessions).
2. `tool_calls=8+`, all identical: `bash -lc 'cd <typo-path> && bash'` (bash-in-bash loop on the bundled `exec` tool, before the loop guard was added). One run repeated 8x before user cancelled — workspace `ab921562`.
3. Single text-only turn: `"Executing the command to open a terminal:"` then stop. No `<tool_call>` block emitted (workspace `bdf3322a`, run `bd0e172a`).

Latest direct gateway smoke test (no Discord involved, fresh `smoke-skill-<ts>` sessionId, prompt explicitly naming the skill by name) still produces `payloads=0 stopReason=stop` with `input=15310 output=3`. Same bailout pattern with the model itself.

**Root cause hypothesis:** Hermes-3-Llama-3.1-8B chokes on the workspace task brief shape (15k+ token system prompt with skill list + tool schemas + multi-section identity/memory blocks). It generates `<|im_end|>` immediately, 0 payloads. The bare model works fine in isolation (`reply with PONG` → returns `PONG` cleanly, 3 tokens, done_reason=stop).

---

## Files in flight (UNCOMMITTED — `git status` will show these)

### New files
- `python_back_end/workspace/terminal_routes.py` — FastAPI router with `/status`, `/{wsid}/exec`, `/{wsid}/teardown`, `/{wsid}/wipe`, `/{wsid}/info`. Auth via `gateway_auth._BUNDLED_TOKEN || _LEGACY_TOKEN`. Emits `workspace_events` rows for live Discord progress display.
- `python_back_end/workspace/terminal_container.py` — `WorkspaceTerminalManager` class. Lazy spawn, named-volume persistence, idle sweep that STOPS not removes, `restart_policy=unless-stopped`, mem/cpu limits per `HARVIS_TERMINAL_*` env. (Existed as a draft before this session; modifications: `HARVIS_TERMINAL_IDLE_TIMEOUT_S` default bumped to 86400, added `HARVIS_TERMINAL_PERSISTENT` flag, added `_volume_name()`, `_spawn()` now mounts the volume + `auto_remove=False` + `restart_policy` in persistent mode, `sweep_idle()` stops instead of removes.)
- `skills/Harvis/harvis-terminal/SKILL.md` — full SKILL.md with frontmatter (`name`, `description` that triggers on "terminal/shell/run/execute"), copy-pasteable curl template, antipatterns table, examples.
- `~/.openclaw/skills/harvis-terminal/SKILL.md` — mirror (NOT in repo, but referenced by `~/.openclaw/openclaw.json`).
- `docs/handoffs/2026-05-12-terminal-skill-handoff.md` — this file.

### Modified files
- `python_back_end/main.py` (line 57 + line 1200) — `from workspace.terminal_routes import router as workspace_terminal_router` and `app.include_router(workspace_terminal_router)`.
- `python_back_end/workspace/openclaw_client.py` —
  - line 46: added `from collections import deque` and `Deque, Tuple` to `typing` imports
  - lines ~975-1005: replaced 6-line dense terminal hint with one-sentence hint + one literal `exec` template that the model can mimic verbatim. URL auto-selects `http://localhost:8000` (when gateway URL is `host.docker.internal`, i.e. BYO mode) vs `http://backend:8000` (docker openclaw fallback). Honors `HARVIS_TERMINAL_AGENT_URL` env override.
  - lines ~1462-1474: added `_LOOP_GUARD_N = 3` and `_recent_tool_calls: Deque` to track recent tool calls.
  - lines ~1595-1635: loop-detection guard. If the last 3 tool calls have identical `(tool, args)`, emit `error` event explaining the abort, `self._cancelled.set()`, break.
- `python_back_end/integrations/discord_workspace_bot.py` —
  - new `_BOT_FALLBACK_SIGNALS` tuple of substrings that identify our own failure-fallback bot messages.
  - in `_fetch_discord_chat_history`: filter out `role=assistant` history turns containing any of those substrings, so the model doesn't condition on its own past empty turns.
- `docker-compose.override.yml` — sets `OPENCLAW_URL` to `ws://host.docker.internal:18790` (BYO), `OPENCLAW_FALLBACK_URL` to dockerized openclaw, `OPENCLAW_HOME=/home/user`. **No `HARVIS_TERMINAL_AGENT_URL` here** — the autodetect in `openclaw_client.py` handles it. Also has `ollama` service env tuning (FLASH_ATTENTION, KV_CACHE_TYPE=q8_0, NUM_PARALLEL=1, etc.).
- `~/.openclaw/openclaw.json` — added top-level `skills.load.extraDirs: ["~/.openclaw/skills"]`. Backup at `~/.openclaw/openclaw.json.bak.before-skill-1778520602`. (NOT in repo.)

### Other state changes (not files)
- `~/.openclaw/agents/main/sessions/`:
  - `58781ce3-…jsonl` archived as `.poisoned-<ts>` (had 5 prior empty-payload turns).
  - `9d20e5ec-…jsonl` archived as `.poisoned-<ts>` (had 1 empty-payload turn).
  - `sessions.json` had `agent:main:discord-1491563414835695668-695857322060415026` removed twice (so it re-bootstrapped fresh both times).
- Host openclaw gateway restarted from scratch via `nohup ~/.openclaw/run-gateway.sh > /tmp/openclaw-gateway.log 2>&1 &`. PIDs 3081522 / 3081532. Old stuck pids cleaned up.

---

## Failed attempts (do not repeat)

| Attempt | What happened | Lesson |
|---|---|---|
| Hardcode `http://backend:8000` in the terminal hint | Host-BYO openclaw's `exec` runs on the user's host, where docker DNS doesn't exist. `curl backend:8000` fails. | Autodetect from `self.gateway_url`. |
| Use `HARVIS_TERMINAL_AGENT_URL` env override only | Two paths to maintain (BYO override file + default). Brittle. | Autodetect first, env override second. |
| Verbose 6-line terminal hint with JSON spec / headers / response shape | Hermes-3 emitted `payloads=0`. Memory pattern: dense bootstrap = small models bail. | Tiny hint + one literal `exec` template. |
| Restrict bundled `exec` to refuse `bash -lc … && bash` | User said no — BYO is their box, restrictions aren't the answer. | Skill-based steering (the path we took). |
| Just clear the poisoned session | Helped briefly but Discord's own channel history re-injected the fallback messages on the NEXT turn, re-poisoning. | Filter Discord history at `_fetch_discord_chat_history`. |
| `kill -USR1 <gateway-pid>` to restart for skill reload | The internal restart handoff broke; spawned child never bound port 18790. Stuck in `ep_poll`. | Kill both `openclaw` parent + `openclaw-gateway` child, relaunch via `~/.openclaw/run-gateway.sh`. |

---

## Open hypothesis for the next session

**Hermes-3-Llama-3.1-8B on Ollama is the bottleneck**, not anything in this session's plumbing. Evidence:
- Bare model handles plain prompts (`PONG` test passed).
- Same Hermes-3 in agent mode with the workspace brief consistently emits 0 payloads and stops immediately.
- Token budget is fine (15k of 128k context).
- Skill is properly registered AND in the session snapshot.

**The smoke test that proves this:** direct `openclaw agent --session-id smoke-skill-…` with prompt naming the skill by name, fresh session — still `payloads=0 stopReason=stop`. No Discord involvement.

---

## Next steps (in order)

1. **Pick an alternative agent model and swap the primary in `~/.openclaw/openclaw.json`.** Candidates already declared in that file:
   - `gpt-oss:latest` (OpenAI open-weight, strong tool use)
   - `batiai/qwen3.5-9b:latest` (Qwen3.5 — previously seen producing thinking tokens, so it engages)
   - Keep `finalend/hermes-3-llama-3.1:8b` as a fallback so we can A/B.
   This is a config edit + gateway restart, ~2 min. **Do not bypass — get user approval on which model to try first.**

2. **Re-run smoke test through gateway CLI** (no Discord noise):
   ```bash
   TOK=$(grep '^OPENCLAW_GATEWAY_TOKEN=' /home/user/Harvis/.env | cut -d= -f2)
   OPENCLAW_GATEWAY_TOKEN="$TOK" /home/user/.npm-global/bin/openclaw agent \
       --agent main --session-id "smoke-$(date +%s)" \
       --message 'use the harvis-terminal skill: make a script that prints the date, save it to /workspace/d.sh, and run it. Report the date.'
   ```
   Pass criterion: `tail -50 /tmp/openclaw-gateway.log` shows a `tool_call` for `exec` with `curl … /api/tools/terminal/…/exec` in the args, not `bash -lc 'cd … && bash'`.

3. **Verify in Discord** with the same prompt. Pass criterion: backend logs show `tool_call args=` containing the curl command pointing at the new endpoint. The bot replies with the date.

4. **Only then, commit.** Order:
   - `feat(workspace): persistent dockerized terminal endpoint` — `terminal_container.py`, `terminal_routes.py`, `main.py` wiring.
   - `feat(workspace): autodetect agent terminal URL + loop guard + trim hint` — `openclaw_client.py`.
   - `fix(discord): drop bot-fallback messages from history` — `discord_workspace_bot.py`.
   - `feat(skills): harvis-terminal skill` — `skills/Harvis/harvis-terminal/SKILL.md`.
   - Possibly: `docs/handoffs/...` archived to a different location once the work lands.
   - Per user's hard rule: **no `git push` until end-to-end Discord run is verified**.

5. **Then come back to this handoff and amend** with what worked, what model is now primary, and updated commit hashes.

---

## Gotchas for the next session

- **Discord sessionId** `agent:main:discord-1491563414835695668-695857322060415026` poisons easily. If you see `stopReason=stop payloads=0` repeatedly, clear:
  ```bash
  # archive the session file
  mv ~/.openclaw/agents/main/sessions/<sessionId>.jsonl ~/.openclaw/agents/main/sessions/<sessionId>.jsonl.poisoned-$(date +%s)
  # drop from sessions.json
  python3 -c "import json,pathlib; p=pathlib.Path('/home/user/.openclaw/agents/main/sessions/sessions.json'); d=json.loads(p.read_text()); d.pop('agent:main:discord-1491563414835695668-695857322060415026', None); p.write_text(json.dumps(d, indent=2))"
  ```
- **Gateway hot-reload for `skills.load.extraDirs` is incomplete.** The skills snapshot invalidates but the gateway requires a full restart to bind the new dir. Use the relaunch dance, not `kill -USR1`.
- **8 GB GPU.** Stay 8-9B class. `qwen3-coder:30b` would not fit reliably without heavy CPU swap.
- **Backend `/openapi.json` returns HTTP 500** due to a pre-existing pydantic `SearchRequest` ForwardRef issue in an unrelated router. **Not from this work.** Don't chase it.
- **Discord channel history is the long-term poisoner**, not the openclaw session file. The `_BOT_FALLBACK_SIGNALS` filter in `discord_workspace_bot.py` handles known fallback strings, but if a new failure-fallback wording gets introduced, add it to that tuple.
- **Bundled `exec` tool stays available.** The skill is a steering hint, not a restriction. If you find yourself wanting to restrict `exec` to force the new endpoint — user has explicitly said no, BYO is their box.

---

## Quick references

- Backend dir: `/home/user/Harvis/python_back_end/`
- Repo skills: `/home/user/Harvis/skills/Harvis/`
- Host openclaw config: `/home/user/.openclaw/openclaw.json`
- Host openclaw sessions: `/home/user/.openclaw/agents/main/sessions/`
- Host gateway log: `/tmp/openclaw-gateway.log` (current); `~/.openclaw/logs/gateway-*.log` (older)
- Backend container: `harvis-backend`
- Recreate backend: `docker compose up -d --force-recreate backend`
- Workspace events SQL: `docker exec pgsql-db psql -U pguser -d database -c "SELECT seq, event_type, substring(payload::text, 1, 250) FROM workspace_events WHERE workspace_id='<id>' ORDER BY seq"`
- Recent workspaces: `docker exec pgsql-db psql -U pguser -d database -c "SELECT id, status, started_at, error_message FROM workspace_runs WHERE session_id LIKE 'discord-%' ORDER BY started_at DESC LIMIT 5"`
