# Session handoff — context-hygiene fix + the harness that cracked the saga (2026-05-29)

## ⭐ TODO FOR YOU (don't lose this)
- **Scroll up in the OTHER Claude chat** (the one whose memory got compressed) to recover the ideas you wanted from it — they didn't survive the compaction, so you have to read them yourself.
- **PUSH IS PENDING YOUR AUTH.** Everything's committed on `feat/hermes-integration`, cold-verified, ready. This sandbox has no GitHub creds. From your own authenticated terminal:
  ```bash
  cd /home/ommblitz/Projects/Recent-EX/Harvis
  git push -u origin feat/hermes-integration
  ```
  (First push of this branch — creates it on origin github.com/brandoz2255/Harvis.)

## The headline

The multi-session "qwen3.5:9b is a flaky 33% coin-flip model" conclusion was **wrong**, and a harness we built this session proved it in its first hour. **Root cause of the entire flaky-model saga: context contamination.** Once a conversation's history contains a completed-task signal ("All 5 hashes cracked successfully" + a tool result), the model refuses to re-emit tool calls and narrates stale results instead. This is **universal** — measured 0% tool emission on qwen3:14b, qwen3.5:9b, AND granite4.1:8b (IBM, non-Qwen). Clean context = ~100% on all three. It was never the model.

## What shipped (5 commits on `feat/hermes-integration`, cold-verified, NOT pushed)

```
11f9fd1  docs(handoffs): scope1 close-out, lever1/path-b results, scope3 deferral
5584f6a  feat(diagnostics): model-agnosticism harness + sessions.reset probe
ce692c4  feat(discord): failure escalation (dark) + context-hygiene history drop
63e013b  feat(model_proxy): reasoning->content hoist for thinking-mode models
848ccf8  feat(workspace): tool-task reliability — Lever 1 + Path B + session-reset hygiene
```

| Change | File | What |
|---|---|---|
| **Lever 1** | `openclaw_client.py` | hash_hint 213→50 lines: model dispatches to on-disk `crack_all.py` instead of authoring Python in a heredoc. Closes gemma4/hermes4 indent-collapse. |
| **Path B retry** | `openclaw_client.py` | hash no-tool corrective now fires on any `looks_hash_task` + no executing tool_call, cap 1→2. |
| **Context-hygiene Piece 1** | `openclaw_client.py` | `_reset_session_turns()` calls OpenClaw `sessions.reset` before the (self-contained) hash corrective. `_suppress_res_ids` guard makes it best-effort. |
| **Reasoning hoist** | `model_proxy.py` | hoist `message.reasoning`→`content` when content empty + reasoning present + no tool_calls + finish=stop. |
| **Scope 1 escalation (DARK)** | `discord_workspace_bot.py` | failure-driven model escalation, behind `HARVIS_ESCALATE_ON_FAILURE` (default OFF — never live-tested, dark code). |
| **Context-hygiene Piece 2** | `discord_workspace_bot.py` | drop `prior_history` when a fresh tool session fires (mirrors attachment-fresh). No phrase regex. |
| **Harness + probe** | `scripts/diagnostics/` | `model_harness.py` (replay a captured request body N× vs a model, score tool emission) + `probe_sessions_reset.py`. |

## Verification (complete)

- **Harness, content hypothesis:** contaminated body 0/8 → reset-to-`[system,task]` 7-8/8 → proven the completed-task turn is the killer and removing it (what `sessions.reset` does) restores emission.
- **Discord E2E across 4 models:** qwen3:14b, qwen3.5:9b, granite4.1:8b, gemma4:e4b — all pass hash dispatch + cross-message hygiene (Piece 2 fires: `dropped N prior history turns`). gemma4 (the original indent-collapse offender) **fully redeemed** — dispatches `crack_all.py` cleanly + does web search.
- **Web search (B7 plugin):** works across models (both `web_search` tool and exec/curl paths). Answer *quality* varies by model (prior-anchoring noise on smaller models) — that's the known reasoning-override limitation (Phase 3 Scope 2, accepted best-effort), not an architecture bug.
- **Cold-retest PASSED:** fresh containers (`docker compose down && up --build`), the full suite on qwen3:14b — single hash, back-to-back (hygiene fired cold), decode, web search, "hi" (boundary held, no false-fire). Every mechanism fires from cold.

## Architecture change (host-local, NOT in git)

- **Rig OpenClaw dropped.** It ran an older protocol and always fell back to the laptop bundled anyway. `docker-compose.override.yml` (gitignored) now points `OPENCLAW_URL` at the laptop bundled; **rig is inference-only (Ollama)**.
- Inference routing: `model_proxy → DESKTOP_OLLAMA_URL (rig Ollama)` for desktop-preferred/rig-only models; laptop Ollama for models it has (laptop-first). gemma4 → rig (confirmed); granite → laptop (it's installed there too).

## Open threads (none blocking; ranked)

1. **PUSH** — pending your auth (top of doc).
2. **`crack_all.py` deployment gap** 🔴 — the entire `openclaw/skills/` tree is gitignored/pipeline-managed (`git ls-files` shows ZERO skill files tracked). The pushed hash_hint dispatches to `crack_all.py`, which isn't in git → a clean deploy gets the hint but not the script → hash cracking breaks. **Two options you raised:** (a) convert crack_all into a RAG-corpus Harvis pulls, or (b) ship as-is and fix-if-it-breaks. You leaned (b) "push and push another fix if it messes up." Still needs the rig mirror regardless. **Decide before anyone deploys from a clean clone.**
3. **decode/crypto Lever-1 follow-up** 🟠 — qwen3.5:9b re-authors decoder/cipher scripts instead of dispatching (4 calls vs 1). Works, but the same fragility Lever 1 fixed for hash. Extend the dispatch shape to decode/crypto.
4. **Context-change edge (known, low):** chained tool ops by reference ("now decode THAT result") lose context because Piece 2 drops history on the trigger word. Was already mostly broken by pre-existing fresh-session-per-tool-message; Piece 2 extends it a sliver. Workaround: paste the intermediate value. Real fix later = structural prior-tool-completion carve-out (NOT a phrase match).
5. **Capture dumper still armed** 🟡 — `HARVIS_CAPTURE_REQUESTS=true` in the override, writing `/tmp/harvis-diagnostics` every request. Diagnostic's done — turn off.
6. **`.env.bak.1776723944`** in repo root 🟠 — untracked env backup, likely secret-bearing. Remove / gitignore (security hygiene).
7. **OpenClaw connect-chain stale** 🟡 — primary still tries dead `ws://host.docker.internal:18790` → fallback to bundled. ~1s wasted/task + log noise. The override edit didn't fully land (something still prefers the host URL first). Cosmetic.
8. **docker-compose.yaml `version:` obsolete** 🔵 — trivial warning, remove the attribute.
9. **Granite routing** — leave laptop-local or make desktop-preferred (`HARVIS_DESKTOP_PREFERRED_MODELS`). Your call.

## Next phase (your stated direction)

Weak-point check = done (infra health green; weak points catalogued in thread #2-8 above). Then:
- **UI overhaul** — needs frontend recon first; `front_end/jfrontend` (Next.js) not yet explored this session.
- **Terminal access for Harvis** — scaffolding ALREADY EXISTS: `HARVIS_TERMINAL_*` env in docker-compose.yaml (sandboxed `ubuntu:24.04` container, mem/cpu/timeout limits, kill-switch). "Starting" = building on this, not blank-slate.

## Memory edits to make (overturned by this session)

- `project_model_task_pairing.md` is now **outdated** — qwen3.5:9b is NOT flaky; it's 100% on clean context, same as every model. The "task pairing" framing was masking context contamination.
- **Add:** context-contamination root cause — completed-task turn in history → 0% tool emission, universal across model families. Fix = clear the session (sessions.reset) / drop the rendered history for tool tasks.
- **Add:** the harness exists at `scripts/diagnostics/model_harness.py` — replay a captured request body against any model to get tool-emission numbers. The "turn vibes into numbers" tool.

## How to resume

1. Do the PUSH (top).
2. Decide `crack_all.py` deployment (#2) before any clean deploy.
3. Read the OTHER Claude chat for the ideas you wanted (scroll up — its memory compressed).
4. Pick next phase: UI overhaul (recon `front_end/jfrontend` first) or terminal access (build on `HARVIS_TERMINAL_*`).
5. The harness is your friend for any future model question — `python3 scripts/diagnostics/model_harness.py --body <captured request.json> --model <name> --target ollama --ollama-url http://192.168.20.58:11434 --runs 8`.

Branch: `feat/hermes-integration`, 11 commits ahead of session open, **unpushed**. Working tree clean (tracked). Backend healthy on the committed code.
