# Phase E4 — Hermes native Build engine: recon + verification report (2026-06-27)

**Branch:** `harvis1.1` · **State:** built, deployed (`:9000`, flag on), **UNCOMMITTED** · **Method:** 18-agent independent recon (5 dimensions reviewed → every finding adversarially re-verified by a fresh agent), plus a live `/api/owui/capabilities` check.

## What E4 is (one line)
Hermes is a **specialized *native* Build engine** — the in-process `vibecode-turn` `SubAgentRunner` defaulted to a local Hermes model and carrying the per-user **SOUL persona**. It is **not** a sidecar/gateway (none exists). Own flag `HARVIS_OWUI_HERMES_ENGINE` (default OFF), excluded from `EXTERNAL_ENGINE_IDS`, clone-mode only.

---

## Headline verdict
- **Wiring: clean.** Routing, flags, session-create coerce/reject, persona injection, model default/override, registry, selector, regression — all verified correct (big green list below). The **security must-fix (never log raw persona/prompt) is verified clean** across every log/event/DB path.
- **One real correctness gap:** the tool-call **rescue only catches *fenced* tool calls** (hermes4-style ```json blocks); `hermes3:3b`'s observed **un-fenced** form isn't caught. This is the actual root cause of the flaky file-edit — even with the rescue, the installed 3B's un-fenced output slips through. **[HIGH]**
- **One false alarm:** an adversarial verifier claimed a HIGH "frontend `hermes` vs backend `hermes-engine` key mismatch." **It's wrong** — `capabilities.py:213` emits `engine_readiness["hermes"]` (output key = `_eng`; `hermes-engine` is only the *read-from* service key), and live `/api/owui/capabilities` returns `engine_readiness.hermes={ready:true}`. No bug.
- A few **defensive/observability/doc polish** items (medium→info), none blocking.

---

## Findings (post adversarial-verification)

| # | Sev | Real? | Area | Finding | Action |
|---|-----|-------|------|---------|--------|
| 1 | **HIGH** | ✅ real | rescue | **Rescue ineffective for un-fenced hermes3:3b output** — `_RESCUE_TOOL_CALL_MD_RE` (`model_proxy.py:508`) requires triple-backtick fences; `hermes3:3b` emitted `{"arguments":{…},"name":"edit_file"}` un-fenced → no match. Rescue works for hermes4's fenced form only. (Secondary: the regex's one-level brace-nesting can also miss deeply-nested args.) | Add a **hermes-gated un-fenced fallback** (lift bare `{…"name"…"arguments"…}` JSON), OR accept that reliable edits need a fenced/clean tool-caller (hermes4). Closes the flaky-edit E2E. |
| 2 | medium | ✅ real | routing | **Implicit** mutual exclusion of hermes vs the cloud-key decrypt path (`workspace_router.py:~3383-3402`). Correct today (hermes ∉ `EXTERNAL_ENGINE_IDS` ⇒ `_use_engine` False ⇒ no decrypt), but relies on implicit logic — fragile to future edits. | Defensive: `elif _use_hermes:` or guard the decrypt with `if _use_engine and not _use_hermes`. |
| 3 | low | ✅ real | routing | `_installed_hermes_models()` logs probe failures only at **DEBUG** (`workspace_router.py:137-138`); operators at INFO can't distinguish a transient Ollama outage (fail-open → accept) from misconfig. | INFO log when **all** endpoints fail ("failing open"). |
| 4 | info | ✅ real | routing | **Silent coercion** external/hermes→native (flag-off / in-place) leaves no trace in logs or the create response (`workspace_router.py:~3069-3101`). | Doc the coercion in the endpoint docstring; optionally return `coerced_to_native` so the UI can hint. |
| 5 | info | ✅ real | rescue / regression | The `finish_reason` flip in `model_proxy` is **not** needed in `ModelRouter` (the runner decides on `msg["tool_calls"]`, never `finish_reason` — `runner.py:135-142`), and the rescue lives at the native-runner level by design (it bypasses model_proxy). Correct as-is. | One-line maintainer comment noting the asymmetry. |
| — | ~~HIGH~~ | ❌ **false positive** | registry | Verifier claimed `engine_readiness` key is `hermes-engine` not `hermes`. **Refuted:** `capabilities.py:213` outputs key `"hermes"`; live curl confirms `engine_readiness.hermes={ready:true}`. | None. |
| — | ~~info~~ | ❌ refuted | frontend | "Registry fetched unconditionally on mount." **Refuted** — guarded by `if (!enabled) return;` (`+page.svelte:1130`). | None. |
| — | low | ❌ not-an-issue | routing | "Desktop-only hermes model would fail at runtime." **Refuted** — `model_proxy._resolve_route` already falls back to the desktop Ollama; validation + execution agree. | None. |
| — | low | ✅ intentional | frontend | Hermes has **no `code_engine_candidate` preference mapping** → opt-in only, never auto-defaults. Deliberate (Hermes ≠ swappable sidecar). | None. |

---

## Confirmed correct (independently re-read)

**Security (the must-fix — fully clean):**
- Persona logged **only** as `chars=N, sha256=…` (`session_turn.py:252-255`); raw persona/composed prompt **never** hits logs, events, artifacts, or the DB. Verified the runner (`runner.py`) and `ModelRouter` (`model_router.py`) don't log `system_prompt`/messages, and `build_persona_block` returns text without logging it. `hashlib` imported; hash truncated.
- Persona is fail-soft (load error → plain native, logged without text); `pool`/`user_id` guarded; prepended **after** the plan-mode block so plan mode keeps the persona.

**Routing / dispatch:** `_hermes_engine_enabled()` + `_installed_hermes_models()` fail-OPEN (None on total probe failure → accept); `NATIVE_ENGINE_IDS={"hermes"}` (not external); session-create truth table correct (unknown→400, flag-off/in-place→coerce native, no-model→400 reject, probe-fail→accept); `engine="hermes"` persisted; turn dispatch keeps `agent_id="vibecode-turn"` + threads `vibecode_persona_engine="hermes"`, never reaches `engine-adapter` or the cloud-key decrypt; `_start_workspace`/`_workspaces`/`_run_workspace_bg` thread it end-to-end, default `""`.

**Model handling:** override to `HARVIS_HERMES_DEFAULT_MODEL` only when `persona_engine=="hermes"` and the selected model isn't a hermes tag; `model_name` reassigned **before** `root_ev` so all events + the run row reflect the real model; override emitted as a `log` event.

**Registry / frontend:** `hermes-engine` readiness gated on the flag + an installed hermes model (reasons `disabled`/`no_hermes_model`), kept **separate** from the `hermes` model-provider status; `engine_readiness.hermes` reads `hermes-engine` but is keyed `hermes` (matches the selector); `hermes-agent` provides `model_provider`+`agent_runtime` in **both** the Python mirror and `catalog.ts` (drift test green); `showEngineSelector` drop of the external-flag check is **equivalent** (backend readiness already encodes each flag → `readyEngineIds` empty when off); no orphan `externalEnginesEnabled` refs.

**Rescue (within its scope):** gating on `"hermes" in model_name` is precise/case-insensitive/None-safe; idempotent + exception-safe (double-guarded); the runner dispatches purely on `tool_calls`.

**Regression / integration:** native path byte-equivalent when `persona_engine==""`; orchestrate + in-place still force native (hermes can't sneak in); external engines unchanged; `docker-compose.yaml:228-229` both flags default OFF/empty (committed-safe); **no DB migrations** (reuses `user_soul` + `vibecode_sessions.engine`).

---

## Recommendations (close-out, prioritized)

1. **(HIGH — makes the engine deliver)** Extend the rescue to the **un-fenced** hermes form. Low-risk because it's hermes-gated and the lift only fires on `{…"name"…"arguments"…}` shaped JSON. This is what flips `hermes3:3b` from "tries but no tool_call" to a real edit → unblocks the file-edit→diff E2E. *Alternative:* leave the rescue fenced-only and require a clean tool-caller (hermes4) — but then hermes3:3b stays unreliable.
2. **(medium)** Defensive `elif _use_hermes` / decrypt guard (finding #2).
3. **(low)** INFO-level "failing open" probe log (finding #3).
4. **(info)** Doc the silent coercion + the rescue/`finish_reason` asymmetry comments (findings #4, #5).
5. **Then:** confirm a completed Hermes turn→diff (with the un-fenced rescue, `hermes3:3b` should land it; else hermes4), and **commit E4** on `harvis1.1` (no push until the user approves) — per the standing no-push gate.

## Pointers
- Memory: `project_hermes_engine_e4.md` · Changelog: `front_end/newjfrontend/changes.md` · Guide: `docs/guides/vibecode-external-engines.md` (Hermes section).
- Live dev box: backend up with `HARVIS_OWUI_HERMES_ENGINE=1` + `HARVIS_HERMES_DEFAULT_MODEL=hermes3:3b`; OWUI build deployed.
