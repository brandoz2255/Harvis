"""Cumulative multi-turn VibeCode session turn — ONE agent on the persistent
session workspace (clone-mode).

Unlike ``run_orchestrated`` (which fans out to N isolated sub-agents, each in its
own throwaway clone), a VibeCode turn runs a SINGLE ``SubAgentRunner`` directly on
the session's PERSISTENT working clone. So each follow-up turn builds on prior
turns' edits — they're already sitting in the working tree the agent reads — and
the diff accumulates against the session's fixed ``base_sha``. This is the natural
Claude-Code model: sequential, iterative, one evolving working copy.

Emitted events use the same ``OpenClawEvent`` shape selected by
``agent_id="vibecode-turn"`` in workspace_router._run_workspace_bg, so persistence
(workspace_runs/workspace_events), SSE streaming, and the RunView UI render it
unchanged. The bg loop owns ``_db_complete_run`` (its ``finally``), so this turn
only yields ``done`` — it must NOT complete the run itself.

Turns on one session are serialized by a per-session ``asyncio.Lock`` — two turns
must never edit one working tree at once (corruption + a meaningless diff).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from typing import AsyncGenerator

from ..openclaw_client import OpenClawEvent
from .conversation import conversation_prefix
from .isolation import SESSION_WORKSPACE_ROOT, WorkspaceIsolationManager
from .syntax_gate import SYNTAX_REPAIR_ROUNDS, gate_check, repair_task
from .runner import SubAgentRunner

logger = logging.getLogger(__name__)

# How every vibecode turn is required to sign off, shared by both system prompts
# below so the two can never drift on the one thing the chat bubble renders.
_FINISH_CONTRACT = (
    "When the task is fully done, call finish with `summary` — a warm, "
    "talkative wrap-up written as a MESSAGE TO THE USER (several sentences, not a "
    "log line). Walk through what you changed and why, go file by file when more "
    "than one changed, mention the result of any tests or commands you ran "
    "(passing/failing counts), call out anything worth knowing, and recommend a "
    "sensible next step. Finish by clearly stating whether the task is complete. "
    "Be conversational and thorough — like a teammate explaining their work — "
    "never a terse \"done\"."
)

# Session-variant system prompt: the runner's default says "initially-empty
# workspace"; here the workspace is an existing repo tree that prior turns may have
# already modified. Tell the agent to read before it edits + build on the state.
_VIBECODE_SYSTEM = (
    "You are {label}, an autonomous coding agent working on an EXISTING git "
    "repository working tree. Earlier turns in THIS session may already have made "
    "changes — they are present in the working tree, so read what is there before "
    "you edit. You can ONLY use the provided tools, and ONLY touch files inside the "
    "workspace using RELATIVE paths. To CHANGE an existing file, use str_replace: "
    "read_file it first, then replace the exact snippet you want to change. This "
    "keeps the rest of the file intact. Use edit_file ONLY to create a brand-new "
    "file — it OVERWRITES the whole file, so using it on an existing file deletes "
    "everything you don't re-type. Run exec / run_tests to check your work. Build "
    "on the current state — do NOT recreate files that already exist. Do NOT ask "
    "questions. " + _FINISH_CONTRACT
)

# Scratch variant: a Build/Code session started with no repo at all, on a turn where
# nothing has been written yet. The prompt above opens by asserting an EXISTING repo,
# which is simply false here — and a model told to "read what is there before you
# edit" does exactly that, finds an empty directory, and reports on it instead of
# building. That is the whole of "I've reviewed the current state of the workspace".
#
# The runnability rules are not style advice: the Run tab serves a root index.html
# with `python3 -m http.server` and no install step, so a page that needs a bundler
# is the difference between code that runs in Harvis and code that only exists in
# Harvis.
#
# But "self-contained" used to be written first and read as "put it all in one file",
# so every build came back as a single 900-line index.html with the styles and the
# whole game inlined — unreadable in the editor, unreviewable in the diff, and one
# stray brace away from taking the entire app down with it. The real constraint was
# never "one file"; it is "no build step". Sibling .css and .js files load over plain
# HTTP with no install step at all, so ask for the project a person would actually
# write and state the two limits that genuinely matter.
_VIBECODE_SYSTEM_SCRATCH = (
    "You are {label}, an autonomous coding agent working in an EMPTY workspace. "
    "There is no existing project here and nothing to read first — your job is to "
    "CREATE the files this task needs, from nothing. You can ONLY use the provided "
    "tools, and ONLY write files inside the workspace using RELATIVE paths. Use "
    "edit_file to create each new file with its complete contents; once a file "
    "exists, change it with str_replace rather than rewriting the whole thing. "
    "Start writing immediately — do NOT explore the workspace, do NOT report that "
    "it is empty, and do NOT ask questions. "
    "Write a REAL project laid out in SEPARATE FILES, the way you would in an "
    "editor — not one enormous file with everything inlined. For anything web that "
    "means index.html for the markup only, styles.css for the styling, and one or "
    "more .js files for the behaviour, as sibling files at the workspace root "
    "linked with relative paths: <link rel=\"stylesheet\" href=\"styles.css\"> and "
    "<script src=\"game.js\"></script> before </body>. Once a piece of the program "
    "is big enough to have a name, give it its own file. "
    "Exactly two hard limits, because of how the Run tab serves what you write: "
    "there MUST be an index.html at the workspace ROOT, and the whole thing must "
    "open in a browser with NO build step and NO packages installed — no npm "
    "imports, no bundler, and no CDN, because the sandbox has no internet. Plain "
    "ES modules (<script type=\"module\" src=\"main.js\">) are fine and load over "
    "the same static server. "
    "Then make it actually WORK end to end: every control you draw must be wired "
    "to real behaviour before you finish. Run exec to check your work — at minimum "
    "list the files you wrote and confirm index.html references each one by the "
    "name you actually used. "
    + _FINISH_CONTRACT
)




def _workspace_is_scratch(workspace_path: str, repo_path: str) -> bool:
    """True when this turn is starting from literally nothing.

    Both halves matter. No `repo_path` means the session was created with no source
    repo — Harvis's answer to "code without a repo, like VS Code". An otherwise empty
    tree means no earlier turn has written anything yet: the isolation manager still
    `git init`s the directory, so `.git` is present from the start and is not content.
    On the next turn the files exist and the normal existing-tree prompt takes over,
    which is what keeps a follow-up from recreating what turn one wrote.
    """
    if repo_path:
        return False
    try:
        return not [e for e in os.listdir(workspace_path) if e != ".git"]
    except OSError:
        return False  # unreadable ⇒ assume the established path, never the new one

# Per-session locks — serialize turns so two never edit one working tree at once.
_session_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _session_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[key] = lock
    return lock


def release_session_lock(key: str) -> None:
    """Drop a session's lock entry (called on session delete) so _session_locks doesn't
    accumulate one entry per distinct session over a long-lived process."""
    _session_locks.pop(key, None)


_PLAN_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$")


def _parse_plan_steps(text: str) -> list[dict]:
    """Turn a Plan-mode finish summary into PlanPanel steps. Prefer numbered/bulleted
    lines; fall back to non-empty prose lines; last resort = the whole summary as one
    step. Robust to small models that don't emit clean JSON — we parse the text."""
    def _clean(s: str) -> str:
        s = re.sub(r"^[*_`#>\s]+", "", s)        # strip leading markdown / quote markers
        s = s.replace("**", "").replace("`", "")  # strip inline bold + code ticks
        s = re.sub(r"[*_`]+$", "", s).strip()     # strip trailing emphasis
        return s[:200]

    steps: list[dict] = []
    for line in (text or "").splitlines():
        m = _PLAN_ITEM_RE.match(line)
        if m:
            label = _clean(m.group(1))
            if label:
                steps.append({"label": label})
    if not steps:
        for line in (text or "").splitlines():
            s = _clean(line)
            if s and not s.startswith("#"):
                steps.append({"label": s})
            if len(steps) >= 12:
                break
    if not steps and (text or "").strip():
        steps.append({"label": _clean(text.strip())})
    return steps[:20]


def _plan_chat_summary(text: str, n_steps: int) -> str:
    """A SHORT, conversational wrap-up for the CHAT bubble — the FULL detailed plan lives
    in the Plan panel (the `plan` event). Uses the model's intro sentence (the prose before
    the numbered list) if it wrote one, then points at the panel. Never dumps the step list
    into the chat, so a long plan stays detailed on the right and simple in the thread."""
    intro_lines: list[str] = []
    for line in (text or "").splitlines():
        if _PLAN_ITEM_RE.match(line):
            break
        s = line.strip()
        if s:
            intro_lines.append(s)
    intro = " ".join(intro_lines).strip()
    if intro:
        intro = re.split(r"(?<=[.!?])\s+", intro, maxsplit=1)[0].strip().rstrip(":")  # first sentence
    if not intro or len(intro) < 12:
        intro = "I drafted a plan for that"
    plural = "s" if n_steps != 1 else ""
    return (
        f"{intro} — I've laid out {n_steps} step{plural} in the Plan panel on the right, "
        "and made no changes to your files. Switch to Auto to carry it out."
    )[:600]


async def run_vibecode_turn(
    task_brief: str,
    chat_history: list,
    *,
    model_name: str = "",
    pool=None,
    parent_workspace_id: str = "",
    user_id: int = 0,
    session_id: str = "",
    vibecode_session_id: str = "",
    workspace_path: str = "",
    base_sha: str = "",
    repo_path: str = "",
    isolation_mode: str = "session",   # 'session' (clone) | 'inplace' (real repo on a branch)
    permission_mode: str = "ask",      # in-place permission ladder: plan|ask|auto-accept|full-auto
    persona_engine: str = "",          # Phase E4: "hermes" → SOUL persona + Hermes model; "" → plain native
    launch_mode: str = "user",         # "auto" (auto-detected launch) → heavy tools withheld from the offered schema
    attachments: list[dict] | None = None,  # user's raw attachment refs; images become multimodal parts
) -> AsyncGenerator[OpenClawEvent, None]:
    # Lazy import (avoid circular import at module load) — the FUNCTIONS, not the
    # re-exported APIRouter in workspace/__init__.py.
    from ..workspace_router import (
        _db_create_run,
        _db_save_artifact,
        _db_set_run_repo,
        _db_set_run_source,
    )

    sess = session_id or f"ws-{parent_workspace_id}"
    label = "VibeCode"
    run_id = parent_workspace_id  # the turn run == this run
    started = time.monotonic()

    # Phase E4: Hermes native engine — default to a Hermes model if the selected model
    # isn't one, then reassign model_name so EVERY event + the run row reflect the model
    # actually used (amendment: record which Hermes model ran when overriding a selection).
    _persona_override_from = ""
    if persona_engine == "hermes-native" and "hermes" not in (model_name or "").lower():
        _persona_override_from = model_name or "(none)"
        model_name = os.getenv("HARVIS_HERMES_DEFAULT_MODEL", "hermes3:3b")

    # No model selected → resolve against what this box actually has installed.
    #
    # There used to be a literal `model_name or "llama3.1:8b"` at the dispatch below AND
    # again at the usage-persist. On this dev box that tag happens to be pulled so it
    # worked; on a fresh clone that never pulled it, every unselected turn 404'd, and the
    # composer's meter recorded a model that had never run. Resolving ONCE here — before
    # root_ev captures it — is also what keeps the run events, the dispatch and the
    # persisted row from disagreeing about which model ran.
    if not model_name:
        try:
            from plugins.models.resolver import resolve_default_local_model
            model_name = await resolve_default_local_model(pool=pool, user_id=user_id) or ""
        except Exception:
            logger.exception("vibecode: local model resolution failed")
            model_name = ""

    # Ensure the turn run row exists, tag it source='vibecode' (keeps it out of
    # generic history), and carry repo_path (for later Create-PR resolution).
    await _db_create_run(pool, parent_workspace_id, user_id, sess, task_brief)
    await _db_set_run_source(pool, parent_workspace_id, "vibecode")
    if repo_path:
        await _db_set_run_repo(pool, parent_workspace_id, repo_path)

    # Diff the working copy vs the fixed base_sha (cumulative) — same logic for clone
    # ("session") and in-place ("inplace"); only the workspace target differs. root only
    # matters for cleanup (never called per-turn).
    iso = WorkspaceIsolationManager(
        root=SESSION_WORKSPACE_ROOT,
        isolation_mode=isolation_mode if isolation_mode in ("session", "inplace") else "session",
        repo_config={"base_sha": base_sha, "repo_path": repo_path},
    )
    runner = SubAgentRunner()

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(etype, {**data, "agent_label": label, "model": model_name})
        e.run_id = run_id
        e.agent_label = label
        return e

    tool_calls = 0
    final_summary = ""
    ok_overall = True
    turn_usage: dict = {}

    if not workspace_path:
        yield root_ev("error", {
            "message": "VibeCode session has no workspace.",
            "fix_hint": "The session's working clone is missing — recreate the session.",
        })
        return

    # The resolver returns nothing only when the provider has zero models AND there is no
    # env override AND no saved pick. Say that, rather than dispatching an empty model name
    # and letting it surface as an opaque 404 from the provider.
    if not model_name:
        yield root_ev("error", {
            "message": "No model is available to run this turn.",
            "fix_hint": (
                "Pick a model in the composer, or pull one into your local model server "
                "(e.g. `ollama pull qwen3:4b`). Nothing is installed and no default is set."
            ),
        })
        return

    # ── Multimodal attachments ────────────────────────────────────────────────
    # An image attachment used to reach the model as a LINE OF TEXT naming the
    # file. Screenshot-to-code on a model that can't see the screenshot produces
    # a confident page invented from the filename, which is worse than refusing.
    # So: resolve the bytes into real image parts, and refuse when the selected
    # model is known not to accept them.
    task_images: list[dict] = []
    if attachments:
        try:
            from vision_to_code.attachments import build_image_parts

            # `user_id or None`: 0 is this signature's "nobody" default, and an
            # unauthenticated turn must not be able to read a stored upload.
            task_images, skipped = await build_image_parts(
                attachments, owner_id=user_id or None
            )
        except Exception as exc:
            logger.exception("vibecode: attachment image build failed")
            task_images, skipped = [], [f"attachments could not be read ({exc})"]

        for note in skipped:
            yield root_ev("log", {"message": f"Image not sent to the model — {note}"})

        if task_images:
            from vision_to_code.vision_gate import build_refusal, model_can_see

            can_see, reason = await model_can_see(model_name)
            if can_see is False:
                yield root_ev("error", await build_refusal(model_name, reason, len(task_images)))
                return
            if can_see is None:
                logger.info("vibecode: vision capability unknown for %r — %s", model_name, reason)
            yield root_ev("log", {
                "message": (
                    f"Sent {len(task_images)} image"
                    f"{'' if len(task_images) == 1 else 's'} to {model_name}"
                ),
            })

    # ── Non-image attachments ─────────────────────────────────────────────────
    # A PDF, a CSV, a source file can't become an image part, and naming it in the
    # brief tells this agent about a file it has no way to open. Write it into the
    # working tree instead, where read_file actually reaches it.
    if attachments:
        try:
            from vision_to_code.attachments import (
                is_image_attachment,
                materialize_attachments,
                staged_attachment_brief,
            )

            non_images = [
                a for a in attachments
                if isinstance(a, dict) and not is_image_attachment(a)
            ]
            if non_images:
                staged, not_staged = await materialize_attachments(
                    non_images, workspace_path, owner_id=user_id or None
                )
                if staged or not_staged:
                    task_brief = staged_attachment_brief(staged, not_staged) + task_brief
                if staged:
                    yield root_ev("log", {
                        "message": "Staged in the workspace: "
                        + ", ".join(s["name"] for s in staged),
                    })
                for note in not_staged:
                    yield root_ev("log", {"message": f"Attachment not staged — {note}"})
        except Exception:
            logger.exception("vibecode: non-image attachment staging failed")

    # The permission pyramid is honored in BOTH clone and in-place (the web lane is
    # clone-only, so every rung must work there). plan = read-only; ask/auto-accept =
    # the per-action approval gate; full-auto (or unset) = run freely with no gate.
    gate_mode = permission_mode if permission_mode in ("plan", "ask", "auto-accept") else None
    _scratch = _workspace_is_scratch(workspace_path, repo_path)
    _base_system = _VIBECODE_SYSTEM_SCRATCH if _scratch else _VIBECODE_SYSTEM
    if _scratch:
        logger.info(
            "vibecode: turn %s starts from an empty workspace — scratch system prompt",
            parent_workspace_id,
        )
    sys_prompt = _base_system
    # Seed default Build skill discipline into every vibecode turn (filesystem).
    try:
        from owui_compat.skills import load_bundled_skill_body

        _build_skill = load_bundled_skill_body("harvis-build")
        if _build_skill:
            sys_prompt = (
                _base_system
                + "\n\n## Bundled skill: harvis-build\n\n"
                + _build_skill
            )
    except Exception:
        logger.debug("vibecode: harvis-build skill load skipped", exc_info=True)
    if gate_mode == "plan":
        sys_prompt = sys_prompt + (
            "\n\nPLAN MODE: this turn is READ-ONLY — file edits and shell commands are "
            "BLOCKED and will fail, so do NOT attempt them. First explore with read_file "
            "/ dir_list to ground yourself in the actual code, then call finish with "
            "`summary` = a NUMBERED, step-by-step PLAN written in PLAIN ENGLISH PROSE. "
            "Each step is a FULL SENTENCE describing WHAT you would do and WHY, naming the "
            "file in words — for example: \"1. Create SUMMARY.md at the repository root "
            "with a short paragraph explaining what hello.txt contains and its purpose.\" "
            "Do NOT write tool calls, function names, JSON, or code in the plan (no "
            "edit_file or str_replace syntax) — describe each action in words a person "
            "can read. Use AS MANY steps as the task genuinely needs: for a multi-file or "
            "multi-part change, give each file or part its own step, and add steps for "
            "tests or verification where they apply — a bigger task deserves a longer, "
            "more thorough plan. Open with one sentence of context, then the numbered "
            "steps. You are proposing the work, not doing it."
        )

    # Phase E4: Hermes engine — PREPEND the user's SOUL persona to whatever system prompt
    # we composed above (base or plan-augmented). This is what makes Hermes a DISTINCT
    # engine vs "pick a hermes model on Native", and it finally wires the otherwise chat-
    # only plugins/soul/loader.py into a Build prompt builder. Fail-soft: any load error →
    # plain native behavior. SECURITY: never log the raw persona / system prompt — only a
    # length + truncated hash as a safe marker.
    if persona_engine == "hermes-native":
        persona = ""
        if pool is not None and user_id:
            try:
                from plugins.soul.loader import build_persona_block
                persona = await build_persona_block(
                    pool, int(user_id), include_default_when_unset=True
                )
            except Exception as exc:
                logger.warning("vibecode: hermes SOUL persona load failed (user=%s): %s", user_id, exc)
                persona = ""
        if persona:
            sys_prompt = persona + "\n\n" + sys_prompt
            _phash = hashlib.sha256(persona.encode("utf-8")).hexdigest()[:12]
            logger.info(
                "vibecode: hermes persona applied (user=%s, chars=%d, sha256=%s)",
                user_id, len(persona), _phash,
            )

    # Serialize turns on this session's single working tree.
    lock = _lock_for(vibecode_session_id or sess or parent_workspace_id)
    async with lock:
        yield root_ev("log", {"message": f"VibeCode turn on {os.path.basename(workspace_path)}"})
        if persona_engine == "hermes-native":
            # Record the Hermes model actually used (and what it overrode, if anything) so
            # it's visible in the run stream — not just the persisted run row.
            _msg = f"Hermes engine: running {model_name}"
            if _persona_override_from:
                _msg += f" (overrode selected model {_persona_override_from})"
            yield root_ev("log", {"message": _msg})
        async for ev in runner.run(
            run_id=run_id,
            parent_run_id=run_id,
            label=label,
            # The clone carries file memory across turns; this carries intent memory.
            # Without it a follow-up ("now make it dark", "fix the second one") arrived
            # as a sentence about nothing even though the files it referred to were
            # sitting in the same workspace.
            task=conversation_prefix(task_brief, chat_history),
            task_images=task_images,
            model_name=model_name,
            workspace_path=workspace_path,
            system_prompt=sys_prompt,
            permission_mode=gate_mode,
            launch_mode=launch_mode,
            pool=pool,
            user_id=user_id,
            session_id=vibecode_session_id or None,  # approve-for-session scope
        ):
            if ev.type == "tool_call":
                tool_calls += 1
            elif ev.type == "agent_end":
                d = ev.data or {}
                final_summary = d.get("summary") or final_summary
                if d.get("success") is False:
                    ok_overall = False
                turn_usage = {
                    "prompt_tokens": d.get("prompt_tokens"),
                    "completion_tokens": d.get("completion_tokens"),
                    "context_window": d.get("context_window"),
                    "usage_detail": d.get("usage_detail"),
                }
            yield ev

        # Collect the CUMULATIVE diff (working tree vs base_sha) + changed files +
        # current contents → turn artifacts, while still under the lock (so a
        # concurrent turn can't mutate the tree between the run and the diff).
        try:
            diff = await iso.collect_diff(workspace_path)
            files = await iso.collect_changed_files(workspace_path)
            contents = await iso.collect_file_contents(workspace_path)
        except Exception as exc:
            logger.warning("vibecode: diff collection failed: %s", exc, exc_info=True)
            diff, files, contents = "", [], {}

        # ── Syntax gate ──────────────────────────────────────────────────────
        # The agent can finish a turn convinced it succeeded while the file it wrote
        # cannot be parsed at all — every tool call returned OK, the diff was clean,
        # and the page was dead. Check what actually landed, and spend one round
        # fixing it rather than handing the user a confident summary over broken code.
        #
        # `check_links` is the same failure reached the other way round, and asking
        # for a multi-file project makes it the LIKELIER of the two: a measured run
        # wrote an index.html correctly linking styles.css and main.js, rewrote that
        # same index.html seven times, and never created either sibling. Both defects
        # go into one map so a page missing its script and holding a broken brace is
        # one repair round, not two.
        broken, weight = gate_check(contents, files, workspace_path)
        first_broken = dict(broken)
        repair_round = 0
        repair_summary = ""
        # Repair until the workspace is clean, it stops improving, or the budget runs
        # out. A LOOP rather than the single round this started as, because the two
        # defect kinds fail differently: a model that cannot close its own brace on
        # the first re-read will not close it on the third, but a model writing the
        # files it forgot makes real, additive progress every round — a measured run
        # produced styles.css on round one and would have produced main.js on round
        # two, and stopping at one handed the user a page that still did nothing. The
        # no-progress break is what keeps the stuck case from paying for the additive
        # one: strictly fewer broken files, or the loop ends.
        while broken and repair_round < SYNTAX_REPAIR_ROUNDS and gate_mode != "plan":
            repair_round += 1
            listed = ", ".join(sorted(broken))
            logger.info(
                "vibecode: turn %s left %d broken file(s) (%s) — repair round %d/%d",
                parent_workspace_id, len(broken), listed,
                repair_round, SYNTAX_REPAIR_ROUNDS,
            )
            yield root_ev("log", {
                "message": (
                    f"Code check failed on {listed} — repair round {repair_round} "
                    f"of {SYNTAX_REPAIR_ROUNDS}."
                ),
            })
            async for ev in runner.run(
                run_id=run_id,
                parent_run_id=run_id,
                label=label,
                task=repair_task(broken, native=True),
                model_name=model_name,
                workspace_path=workspace_path,
                system_prompt=sys_prompt,
                permission_mode=gate_mode,
                launch_mode=launch_mode,
                pool=pool,
                user_id=user_id,
                session_id=vibecode_session_id or None,
            ):
                if ev.type == "tool_call":
                    tool_calls += 1
                elif ev.type == "agent_end":
                    d = ev.data or {}
                    repair_summary = d.get("summary") or ""
                    # Tokens are cumulative for the turn; the context window is a
                    # ceiling, not a total, so it takes the larger of the two.
                    for k in ("prompt_tokens", "completion_tokens"):
                        if d.get(k):
                            turn_usage[k] = (turn_usage.get(k) or 0) + d[k]
                    if d.get("context_window"):
                        turn_usage["context_window"] = max(
                            turn_usage.get("context_window") or 0, d["context_window"]
                        )
                    # Billed tokens add up across rounds; occupancy does NOT — a repair
                    # round is its own conversation, so the LAST round's reading is the
                    # current one. Summing them made a 3-round turn look 3× as full.
                    _rd = d.get("usage_detail")
                    if isinstance(_rd, dict):
                        _acc = turn_usage.get("usage_detail")
                        if not isinstance(_acc, dict):
                            turn_usage["usage_detail"] = dict(_rd)
                        else:
                            for k in ("input", "cache_read", "cache_write", "output"):
                                _acc[k] = (_acc.get(k) or 0) + (_rd.get(k) or 0)
                            _acc["context_tokens"] = _rd.get("context_tokens") or _acc.get("context_tokens")
                            if _rd.get("cost_usd") is not None:
                                _acc["cost_usd"] = (_acc.get("cost_usd") or 0) + _rd["cost_usd"]
                yield ev
            try:
                diff = await iso.collect_diff(workspace_path)
                files = await iso.collect_changed_files(workspace_path)
                contents = await iso.collect_file_contents(workspace_path)
            except Exception as exc:
                logger.warning("vibecode: post-repair diff failed: %s", exc, exc_info=True)
            still, still_weight = gate_check(contents, files, workspace_path)
            if still and still_weight >= weight:
                # No fewer defects than we started this round with — another round
                # would cost a request and repeat the same failure. Stop.
                logger.info(
                    "vibecode: turn %s repair round %d made no progress (%d -> %d)",
                    parent_workspace_id, repair_round, weight, still_weight,
                )
                broken = still
                break
            broken, weight = still, still_weight

        if SYNTAX_REPAIR_ROUNDS > 0 and gate_mode != "plan" and first_broken:
            still = broken
            if still:
                # Say so plainly. A summary that claims success over a file the browser
                # will refuse to run is the exact failure this gate exists to end.
                detail = "; ".join(f"{rel} ({err})" for rel, err in sorted(still.items()))
                final_summary = (
                    (final_summary + "\n\n") if final_summary else ""
                ) + (
                    f"⚠ Heads up: {detail}. The page will not work in a browser until "
                    f"that is resolved — I tried {repair_round} "
                    f"time{'s' if repair_round != 1 else ''} and could not. Ask me to "
                    "try again, or open the files and fix it directly."
                )
                ok_overall = False
                yield root_ev("log", {"message": f"Still broken after repair: {detail}"})
            else:
                fixed = ", ".join(sorted(first_broken))
                if repair_summary:
                    final_summary = (
                        (final_summary + "\n\n") if final_summary else ""
                    ) + f"Then I caught and fixed a problem in {fixed}: {repair_summary}"
                yield root_ev("log", {"message": f"Repaired {fixed}."})

    repo_name = os.path.basename((repo_path or workspace_path).rstrip("/")) or "session"
    await _db_save_artifact(
        pool, parent_workspace_id, "diff",
        path=f"VibeCode · {repo_name}", content=diff or "(no changes)",
    )
    for rel, content in contents.items():
        await _db_save_artifact(
            pool, parent_workspace_id, "file", path=rel, content=(content or ""),
        )
    await _db_save_artifact(
        pool, parent_workspace_id, "changed_files", content="\n".join(files),
    )

    n = len(files)
    # Plan mode: the FULL detailed plan goes to the Plan panel (the `plan` event below); the
    # chat bubble gets a SHORT summary that points at it (longer plan ⇒ richer panel, simple
    # thread). Auto mode: the bubble is the agent's own wrap-up, unchanged.
    plan_steps = _parse_plan_steps(final_summary) if gate_mode == "plan" else []
    if gate_mode == "plan":
        summary = _plan_chat_summary(final_summary, len(plan_steps))
    else:
        summary = final_summary or f"Turn complete — {n} file(s) changed."
    logger.info(
        "vibecode: turn %s done (session=%s, %d tool_calls, %d files, %.1fs)",
        parent_workspace_id, vibecode_session_id, tool_calls, n, time.monotonic() - started,
    )
    # Persist this turn's real token usage + the model it used — the composer's
    # context/token gauge reads these straight off the turn rows.
    try:
        async with pool.acquire() as conn:
            _detail = turn_usage.get("usage_detail")
            await conn.execute(
                "UPDATE workspace_runs SET prompt_tokens = $2, completion_tokens = $3, "
                "context_window = $4, model_name = COALESCE(NULLIF($5, ''), model_name), "
                "usage_detail = COALESCE($6::jsonb, usage_detail) "
                "WHERE id = $1",
                parent_workspace_id,
                turn_usage.get("prompt_tokens"),
                turn_usage.get("completion_tokens"),
                turn_usage.get("context_window"),
                model_name,
                json.dumps(_detail) if isinstance(_detail, dict) else None,
            )
    except Exception as exc:
        logger.warning("vibecode: token usage persist failed: %s", exc)

    # Plan mode made NO edits (writes were blocked) — the agent drafted a plan in its
    # summary. Surface the FULL step list as a structured `plan` event so the right-rail
    # Plan panel fills; it persists in workspace_events (steps is whitelisted) → replays.
    if plan_steps:
        yield root_ev("plan", {"steps": plan_steps, "plan_only": True})

    # The bg loop's `finally` calls _db_complete_run — we only signal terminal here.
    yield root_ev("done", {"summary": summary, "changed_files": files})
