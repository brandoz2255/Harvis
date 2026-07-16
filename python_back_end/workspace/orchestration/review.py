"""Agent Review Conversation — an OPT-IN coder ↔ reviewer dialogue over a
VibeCode session's ACCUMULATED diff, run in the session's OWN workspace.

Two personas alternate for up to ``_MAX_REVIEW_ROUNDS`` rounds:

  • REVIEWER — one plain LLM completion (no tools) with a code-reviewer system
    prompt; input = the session's cumulative diff + the original task. Its
    critique ends with a structured verdict line (``VERDICT: APPROVED`` or
    ``VERDICT: CHANGES_REQUESTED``) and is emitted as an ``agent_message``
    event {role:'reviewer'}.
  • CODER — when changes are requested, a BOUNDED SubAgentRunner step on the
    session workspace addresses the feedback. It goes through the exact same
    machinery as a normal turn (authorize_action lane/risk gates, approval
    prompts, the Phase-3 isolated exec runner), so review-driven edits are
    never less gated than user-driven ones. Its wrap-up is emitted as an
    ``agent_message`` event {role:'coder'}.

Outcome → vibecode_sessions.review_status: reviewer APPROVED ⇒ 'agreed';
round cap without agreement ⇒ 'needs_human'; ANY internal error ⇒
'needs_human' (fail-open — a broken review must never crash the session or
permanently wedge the PR gate; the human override on Create-PR always works).

Events use the same ``OpenClawEvent`` shape as a vibecode turn, selected by
``agent_id="vibecode-review"`` in workspace_router._run_workspace_bg, so
persistence (workspace_runs/workspace_events), SSE streaming, the Build
transcript, and the Discord thread all render it unchanged. The new
``agent_message`` type is a CONVERSATION post (the agents talking to each
other) — distinct from ``final_message`` (the run's answer to the user).
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import AsyncGenerator

from ..openclaw_client import OpenClawEvent
from .isolation import SESSION_WORKSPACE_ROOT, WorkspaceIsolationManager
from .model_router import ModelRouter
from .runner import SubAgentRunner
from .session_turn import _lock_for

logger = logging.getLogger(__name__)

# Reviewer↔coder round cap: reviewer(1) → coder(1) → reviewer(2) → coder(2) →
# reviewer(3) → still CHANGES_REQUESTED ⇒ 'needs_human' (the last critique is
# left standing for the human to act on).
_MAX_REVIEW_ROUNDS = max(1, int(os.getenv("HARVIS_REVIEW_MAX_ROUNDS", "5")))
# Diff budget for the reviewer prompt — keeps local-model contexts sane.
_REVIEW_DIFF_CHARS = int(os.getenv("HARVIS_REVIEW_DIFF_CHARS", "48000") or 48000)
# agent_message payload cap (persisted + streamed; Discord re-chunks anyway).
_MSG_CHARS = 6000
# Bounded coder fix-up step (tighter than a full turn's 12/600).
_CODER_MAX_STEPS = max(2, int(os.getenv("HARVIS_REVIEW_CODER_MAX_STEPS", "10")))
_CODER_MAX_SECONDS = max(60, int(os.getenv("HARVIS_REVIEW_CODER_MAX_SECONDS", "480")))

_REVIEWER_SYSTEM = (
    "You are Reviewer, a rigorous senior code reviewer. You are given the task a "
    "coding agent was asked to do and the FULL accumulated git diff of its work. "
    "Review the diff for correctness, security, and whether it actually fulfils "
    "the task. Be specific: name files and lines, and for every problem say "
    "exactly what change you want. Do not invent problems — if the work is good, "
    "approve it. Keep the critique under 300 words. Your reply MUST end with "
    "exactly one final line, on its own line, of ONE of:\n"
    "VERDICT: APPROVED   (the work is good — no changes needed)\n"
    "VERDICT: CHANGES_REQUESTED   (a real code change is needed — say exactly what)\n"
    "VERDICT: COMMENT   (a non-blocking note or minor observation that does NOT require a "
    "code change — use this INSTEAD of CHANGES_REQUESTED whenever there is nothing important "
    "to fix, so the review isn't forced into a needless fix-up loop)"
)

_CODER_REVIEW_SYSTEM = (
    "You are Coder, an autonomous coding agent addressing CODE-REVIEW FEEDBACK on "
    "an EXISTING git repository working tree you already worked on. Your earlier "
    "changes are present in the working tree — read what is there before you "
    "edit. Address ONLY the reviewer's points; do not start unrelated work. You "
    "can ONLY use the provided tools, and ONLY touch files inside the workspace "
    "using RELATIVE paths. To CHANGE an existing file, use str_replace: read_file "
    "it first, then replace the exact snippet you want to change. Use edit_file "
    "ONLY to create a brand-new file. Run exec / run_tests to check your work. Do "
    "NOT ask questions. When every point is addressed, call finish with `summary` "
    "= a short reply TO THE REVIEWER listing, point by point, what you changed "
    "(or why a point needed no change)."
)

_VERDICT_RE = re.compile(r"VERDICT\s*[:\-]\s*(APPROVED|CHANGES[_ ]REQUESTED|COMMENT)", re.IGNORECASE)


def _parse_verdict(text: str) -> str:
    """'approved' | 'changes' | 'comment'. CONSERVATIVE: anything unparseable counts as
    'changes' (after the round cap that lands on 'needs_human', never a silent green light).
    'comment' = a NON-BLOCKING note (no code change needed) — it does not trigger a coder
    fix-up and does not block agreement, so trivial observations don't churn the loop."""
    matches = _VERDICT_RE.findall(text or "")
    if not matches:
        return "changes"
    last = matches[-1].upper().replace(" ", "_")
    if last == "APPROVED":
        return "approved"
    if last == "COMMENT":
        return "comment"
    return "changes"


def _reviewer_max_tokens(model_name: str) -> int:
    """Token cap for a reviewer critique. Many local models (gemma4, deepseek-r1, qwq, …) are
    THINKING models: they spend a big chunk of the budget in a hidden reasoning phase BEFORE the
    visible answer, so too small a cap truncates them before the review + VERDICT ever appear —
    which surfaces as an EMPTY reviewer message. Give everyone room for a reasoning pass (verified:
    gemma4:12b needs ~4k to emit content); bound it so a slow non-streaming call still can't run
    all the way to the read-timeout."""
    m = (model_name or "").lower()
    if any(k in m for k in ("r1", "qwq", "reason", "deepseek", "o1", "o3", "think")):
        return 8192
    return 4096


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.IGNORECASE | re.DOTALL)


def _clean_critique(text: str) -> str:
    """Strip a model's <think>…</think> block if it leaked into the answer channel, so a
    thinking model's chain-of-thought never ends up in the posted review."""
    return _THINK_RE.sub("", text or "").strip()


async def set_review_status(pool, vibecode_session_id: str, status: str) -> None:
    """Best-effort review_status write (fail-open: a DB error only logs)."""
    if pool is None or not vibecode_session_id:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE vibecode_sessions SET review_status = $2, updated_at = NOW() "
                "WHERE id = $1",
                vibecode_session_id, status,
            )
    except Exception as exc:
        logger.warning("review: status write '%s' failed for %s: %s",
                       status, vibecode_session_id, exc)


async def _setup_github_review(pool, user_id, workspace_path, vibecode_session_id, task_brief, base_branch=""):
    """Open (or reuse) the DRAFT PR the review conversation happens on. Returns a gh
    context dict {owner, repo, token, branch, base, number, url, node_id} or None
    (→ the review continues thread-only). Fail-soft."""
    try:
        from .review_github import resolve_owner_repo, push_session_branch, open_or_reuse_draft_pr
        from ..repo_manager import _get_github_token, _resolve_pr_base

        owner, repo = await resolve_owner_repo(workspace_path)
        if not owner or not repo:
            return None
        token = await _get_github_token(pool, user_id)
        if not token:
            return None
        branch = f"harvis/vibecode/{vibecode_session_id}"
        pushed = await push_session_branch(workspace_path, owner, repo, branch, token)
        if not pushed.get("ok"):
            logger.warning("review_github: push failed: %s", pushed.get("error"))
            return None
        # Prefer the SESSION's base branch (e.g. harvis1.1) over the repo's default (main).
        base = (base_branch or "").strip() or await _resolve_pr_base(pool, user_id, owner, repo, token)
        title = f"Harvis review: {(task_brief or 'session changes').strip()[:70]}"
        body = ("Draft PR for the Harvis coder↔reviewer review conversation. The agents "
                "discuss the changes in the comments below and mark it ready-for-review when "
                "they agree. A human merges.")
        pr = await open_or_reuse_draft_pr(token, owner, repo, branch, base, title, body)
        if pr.get("error"):
            logger.warning("review_github: %s", pr["error"])
            return None
        gh = {"owner": owner, "repo": repo, "token": token, "branch": branch, "base": base,
              "number": pr["number"], "url": pr.get("url", ""), "node_id": pr.get("node_id", "")}
        await _upsert_review_pr(pool, vibecode_session_id, gh, "draft")
        return gh
    except Exception as exc:
        logger.warning("review_github: setup failed (%s)", type(exc).__name__)
        return None


async def _upsert_review_pr(pool, vibecode_session_id, gh, status):
    """Persist the review PR into code_pull_requests (best-effort, fail-soft)."""
    if pool is None:
        return
    try:
        import uuid as _uuid
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO code_pull_requests "
                "(id, session_id, provider, pr_url, pr_number, base_branch, head_branch, title, status) "
                "VALUES ($1,$2,'github',$3,$4,$5,$6,'Harvis review',$7) "
                "ON CONFLICT (session_id, head_branch) DO UPDATE "
                "SET pr_url=EXCLUDED.pr_url, pr_number=EXCLUDED.pr_number, "
                "status=EXCLUDED.status, updated_at=NOW()",
                str(_uuid.uuid4())[:16], vibecode_session_id, gh.get("url", ""),
                gh.get("number"), gh.get("base", ""), gh.get("branch", ""), status,
            )
    except Exception as exc:
        logger.warning("review_github: pr persist failed: %s", exc)


async def run_review_conversation(
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
    base_branch: str = "",
    repo_path: str = "",
    isolation_mode: str = "session",
    permission_mode: str = "ask",
    launch_mode: str = "user",
    mode: str = "thread",
    reviewer_ids: list[str] | None = None,
) -> AsyncGenerator[OpenClawEvent, None]:
    # Lazy import (avoid circular import at module load), same as session_turn.
    from ..workspace_router import (
        _db_create_run,
        _db_save_artifact,
        _db_set_run_repo,
        _db_set_run_source,
    )

    sess = session_id or f"ws-{parent_workspace_id}"
    run_id = parent_workspace_id
    started = time.monotonic()
    model = model_name or "llama3.1:8b"

    # ── Reviewer roster ──────────────────────────────────────────────────────────
    # Default = the one built-in reviewer (zero behavior change). If the caller passed custom
    # sub-agent ids, each ENABLED one becomes a reviewer with its OWN persona + (local) model —
    # with the mandatory VERDICT line appended so _parse_verdict keeps working. Agreement then
    # requires EVERY reviewer to approve. Each is a dict: {label, system_prompt, model}.
    reviewers: list[dict] = [{"label": "Reviewer", "system_prompt": _REVIEWER_SYSTEM, "model": model}]
    if reviewer_ids:
        try:
            from .subagent_defs import load_subagents
            _defs = {d["id"]: d for d in (await load_subagents(pool, user_id))}
            _picked: list[dict] = []
            for _rid in reviewer_ids:
                d = _defs.get(_rid)
                if not d:
                    continue
                _rm = (d.get("model") or "").strip()
                # Local-model pin only; cloud/sentinel → the shared session model.
                if not _rm or _rm.lower() in ("auto", "default") or _rm.startswith(("anthropic/", "openai/")):
                    _rm = model
                _sp = (d.get("system_prompt") or "").strip() or _REVIEWER_SYSTEM
                _sp += (
                    "\n\nYou are reviewing the git diff below. Stay fully in the voice, persona, and "
                    "SCOPE described above — review only at the depth your role calls for; a quick look is "
                    "perfectly fine. Write ONLY your review, as one short paragraph, and:\n"
                    "- do NOT think out loud or narrate your reasoning,\n"
                    "- do NOT restate the task or re-quote the diff,\n"
                    "- do NOT enumerate every file/line unless a specific one is actually a problem.\n"
                    "Then end with exactly one final line, on its own line, of ONE of:\n"
                    "VERDICT: APPROVED\nVERDICT: CHANGES_REQUESTED   (a real code change is needed)\n"
                    "VERDICT: COMMENT   (just an observation — no code change needed; PREFER this when your "
                    "role is to observe/comment rather than demand fixes, so the review can settle)"
                )
                _picked.append({
                    "label": (d.get("name") or "Reviewer").strip()[:40] or "Reviewer",
                    "system_prompt": _sp,
                    "model": _rm,
                })
            if _picked:
                reviewers = _picked
        except Exception:
            logger.warning("review: custom reviewer load failed; using the default reviewer", exc_info=True)

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(etype, {**data, "agent_label": "Review", "model": model})
        e.run_id = run_id
        e.agent_label = "Review"
        return e

    def agent_msg(role: str, label: str, content: str, pr_url: str | None = None) -> OpenClawEvent:
        _p = {
            "role": role, "label": label,
            "content": (content or "").strip()[:_MSG_CHARS],
            "run_id": run_id,
        }
        if pr_url:
            _p["pr_url"] = pr_url  # bubble links to the PR (github mode), but the text still shows in-app
        return root_ev("agent_message", _p)

    # The review run is a session-thread row like any turn (source='vibecode').
    await _db_create_run(pool, parent_workspace_id, user_id, sess, task_brief)
    await _db_set_run_source(pool, parent_workspace_id, "vibecode")
    if repo_path:
        await _db_set_run_repo(pool, parent_workspace_id, repo_path)

    if not workspace_path or not os.path.isdir(workspace_path):
        await set_review_status(pool, vibecode_session_id, "needs_human")
        yield root_ev("error", {
            "message": "Review needs the session workspace, but it is missing.",
            "fix_hint": "Recreate the session, run a turn, then start the review again.",
        })
        return

    iso = WorkspaceIsolationManager(
        root=SESSION_WORKSPACE_ROOT,
        isolation_mode=isolation_mode if isolation_mode in ("session", "inplace") else "session",
        repo_config={"base_sha": base_sha, "repo_path": repo_path},
    )
    router = ModelRouter()
    runner = SubAgentRunner(router)

    # The coder step honors the SAME permission ladder as a normal turn ('plan'
    # would make the fix-up step pointless, so it degrades to 'ask').
    gate_mode = permission_mode if permission_mode in ("ask", "auto-accept") else (
        "ask" if permission_mode == "plan" else None
    )

    outcome = "needs_human"
    rounds_done = 0
    summary = ""
    gh = None  # review-on-GitHub context (set below when mode == 'github')
    await set_review_status(pool, vibecode_session_id, "pending")

    # Same per-session lock as turns — the coder edits / reviewer diffs the ONE
    # working tree, so a concurrent turn must never interleave.
    lock = _lock_for(vibecode_session_id or sess or parent_workspace_id)
    try:
        async with lock:
            yield root_ev("log", {
                "message": f"Agent review on {os.path.basename(workspace_path)} "
                           f"(up to {_MAX_REVIEW_ROUNDS} rounds)",
            })
            if mode == "github":
                gh = await _setup_github_review(
                    pool, user_id, workspace_path, vibecode_session_id, task_brief,
                    base_branch=base_branch,
                )
                if gh:
                    yield agent_msg(
                        "reviewer", "Reviewer",
                        f"Opened a draft PR for this review: {gh['url']}\n"
                        "I'll post my review there; the coder will push fixes and reply on the PR.",
                    )
                else:
                    yield root_ev("log", {
                        "message": "Review-on-GitHub setup failed — continuing as an in-thread review.",
                    })
            for round_no in range(1, _MAX_REVIEW_ROUNDS + 1):
                rounds_done = round_no
                diff = await iso.collect_diff(workspace_path)
                if not (diff or "").strip() or diff.strip() == "(no changes)":
                    # Nothing to review — deterministic approve, no LLM call.
                    yield agent_msg(
                        "reviewer", "Reviewer",
                        "There are no changes in this session's diff — nothing to "
                        "review or object to.\nVERDICT: APPROVED",
                    )
                    outcome = "agreed"
                    summary = "No changes to review — approved."
                    break

                # ── REVIEWERS: each participant reviews the accumulated diff this round ──
                truncated = len(diff) > _REVIEW_DIFF_CHARS
                review_input = (
                    f"TASK the coding agent was given:\n{task_brief.strip()[:4000]}\n\n"
                    f"ACCUMULATED DIFF (round {round_no} of {_MAX_REVIEW_ROUNDS}"
                    + (", truncated" if truncated else "")
                    + f"):\n```diff\n{diff[:_REVIEW_DIFF_CHARS]}\n```"
                )
                critiques: list[tuple[str, str, str]] = []  # (label, critique, verdict: approved|changes|comment)
                for _rv in reviewers:
                    # Resilient per-reviewer call: a single reviewer's model timing out or
                    # erroring must NOT crash the whole review (that stalled the loop after the
                    # first message). On failure we record a conservative CHANGES_REQUESTED so
                    # the loop keeps going — the coder addresses it and other reviewers still run.
                    try:
                        msg = await router.complete(
                            model_name=_rv["model"],
                            messages=[
                                {"role": "system", "content": _rv["system_prompt"]},
                                {"role": "user", "content": review_input},
                            ],
                            temperature=0.2,
                            # bound the critique so a slow non-streaming call can't run to the
                            # read-timeout — but give reasoning models room for their <think> budget
                            # so the trailing VERDICT line isn't truncated.
                            max_tokens=_reviewer_max_tokens(_rv["model"]),
                        )
                        # Use the ANSWER channel only + strip any leaked <think> block. Do NOT fall
                        # back to the raw `reasoning` channel — that dumps the model's chain-of-thought
                        # ("Wait, let me… let's refine…") into the review, which is exactly the wall of
                        # noise we don't want. A truncated/empty answer lands on the clean placeholder
                        # below instead.
                        critique = _clean_critique(msg.get("content") or "")
                    except Exception as _rexc:  # noqa: BLE001 — one reviewer's failure is non-fatal
                        logger.warning("review: reviewer '%s' (%s) model call failed: %s: %s",
                                       _rv["label"], _rv["model"], type(_rexc).__name__, _rexc)
                        critique = (
                            f"(This reviewer's model didn't respond — {type(_rexc).__name__}. "
                            "Treating as changes-requested so the review can continue; a human "
                            "should confirm.)\nVERDICT: CHANGES_REQUESTED"
                        )
                    if not critique:
                        critique = "(the reviewer model returned no text)\nVERDICT: CHANGES_REQUESTED"
                    _verdict = _parse_verdict(critique)  # 'approved' | 'changes' | 'comment'
                    critiques.append((_rv["label"], critique, _verdict))
                    if gh:
                        # GitHub mode: post the FULL critique to the PR AND show it in the Harvis app
                        # (previously only a "posted on the PR" pointer showed in-app, so the critique —
                        # incl. a custom reviewer's voice — was invisible unless you opened the PR).
                        from .review_github import post_comment as _gh_comment
                        _tag = {"approved": "APPROVED", "comment": "COMMENT"}.get(_verdict, "CHANGES REQUESTED")
                        await _gh_comment(gh["token"], gh["owner"], gh["repo"], gh["number"],
                                          f"### \U0001f50e {_rv['label']} — **{_tag}**\n\n{critique}")
                        yield agent_msg("reviewer", _rv["label"], critique, pr_url=gh["url"])
                    else:
                        yield agent_msg("reviewer", _rv["label"], critique)

                # Agreement = NO reviewer requested changes (approved OR a non-blocking comment
                # both unblock; only an explicit CHANGES_REQUESTED holds the PR).
                if not any(v == "changes" for (_lbl, _c, v) in critiques):
                    outcome = "agreed"
                    _who = "Reviewer" if len(reviewers) == 1 else f"All {len(reviewers)} reviewers"
                    _commented = any(v == "comment" for (_lbl, _c, v) in critiques)
                    summary = (
                        f"{_who} {'left comments but requested no changes' if _commented else 'approved'} "
                        f"after {round_no} round(s)."
                    )
                    break
                if round_no >= _MAX_REVIEW_ROUNDS:
                    # Cap hit — leave the last critiques standing for the human.
                    outcome = "needs_human"
                    summary = (
                        f"No agreement after {round_no} rounds — a reviewer still "
                        "requests changes. A human should review and decide."
                    )
                    break

                # ── CODER: bounded, fully-gated fix-up step on the session tree ──
                # Only feed the CHANGES_REQUESTED critiques to the coder — non-blocking comments
                # aren't work items. (We only reach here when ≥1 reviewer requested changes, since
                # an all-approved/comment round agreed above, so this is always non-empty.)
                _feedback = "\n\n".join(
                    f"[{_lbl}]\n{_c}" for (_lbl, _c, v) in critiques if v == "changes"
                ) or "\n\n".join(f"[{_lbl}]\n{_c}" for (_lbl, _c, _v) in critiques)
                coder_task = (
                    "Code reviewer(s) examined your accumulated changes for this task:\n"
                    f"{task_brief.strip()[:2000]}\n\nTheir review feedback:\n{_feedback[:4000]}\n\n"
                    "Address each requested change in the working tree, then call "
                    "finish with a point-by-point reply to the reviewer(s)."
                )
                coder_summary = ""
                async for ev in runner.run(
                    run_id=run_id,
                    parent_run_id=run_id,
                    label="Coder",
                    task=coder_task,
                    model_name=model,
                    workspace_path=workspace_path,
                    max_steps=_CODER_MAX_STEPS,
                    max_runtime_seconds=_CODER_MAX_SECONDS,
                    system_prompt=_CODER_REVIEW_SYSTEM,
                    permission_mode=gate_mode,
                    launch_mode=launch_mode,
                    pool=pool,
                    user_id=user_id,
                    session_id=vibecode_session_id or None,
                ):
                    if ev.type == "agent_end":
                        coder_summary = (ev.data or {}).get("summary") or coder_summary
                    yield ev
                if gh:
                    # GitHub mode: push the fix + post the FULL reply on the PR; thread just points there.
                    from .review_github import push_session_branch as _gh_push, post_comment as _gh_comment
                    await _gh_push(workspace_path, gh["owner"], gh["repo"], gh["branch"], gh["token"])
                    await _gh_comment(gh["token"], gh["owner"], gh["repo"], gh["number"],
                                      f"### \U0001f9d1‍\U0001f4bb Harvis Coder\n\n"
                                      f"{coder_summary or 'Addressed the review feedback.'}")
                    yield agent_msg("coder", "Coder",
                                    coder_summary or "Addressed the review feedback and pushed a fix.",
                                    pr_url=gh["url"])
                else:
                    yield agent_msg(
                        "coder", "Coder",
                        coder_summary or "I made changes for the review feedback (no summary was produced).",
                    )

            # Cumulative diff artifacts, same as a turn (still under the lock).
            try:
                diff = await iso.collect_diff(workspace_path)
                files = await iso.collect_changed_files(workspace_path)
            except Exception as exc:
                logger.warning("review: diff collection failed: %s", exc)
                diff, files = "", []
    except Exception as exc:
        # FAIL-OPEN: a review crash must never take the session down or wedge the
        # gate in 'pending' — land on 'needs_human' (human override always works).
        logger.warning("review: conversation failed for session %s: %s",
                       vibecode_session_id, exc, exc_info=True)
        await set_review_status(pool, vibecode_session_id, "needs_human")
        yield root_ev("log", {"message": f"Review errored: {str(exc)[:300]}"})
        yield root_ev("done", {
            "summary": "The agent review hit an error and stopped — review status is "
                       "'needs a human'. You can re-run the review or override on Create-PR.",
        })
        return

    await set_review_status(pool, vibecode_session_id, outcome)
    if mode == "github" and gh:
        from .review_github import mark_ready as _gh_ready, post_comment as _gh_comment
        if outcome == "agreed":
            await _gh_ready(gh["token"], gh["node_id"])
            await _gh_comment(gh["token"], gh["owner"], gh["repo"], gh["number"],
                              "✅ The Harvis reviewer approved — marking this PR **ready for review**. "
                              "A human still merges.")
            await _upsert_review_pr(pool, vibecode_session_id, gh, "open")
        else:
            await _gh_comment(gh["token"], gh["owner"], gh["repo"], gh["number"],
                              "⚠️ The agents didn't reach agreement in the review rounds — "
                              "a human should take a look.")
    repo_name = os.path.basename((repo_path or workspace_path).rstrip("/")) or "session"
    await _db_save_artifact(
        pool, parent_workspace_id, "diff",
        path=f"Review · {repo_name}", content=diff or "(no changes)",
    )
    await _db_save_artifact(
        pool, parent_workspace_id, "changed_files", content="\n".join(files),
    )
    logger.info(
        "review: session %s finished '%s' after %d round(s) in %.1fs",
        vibecode_session_id, outcome, rounds_done, time.monotonic() - started,
    )
    # The bg loop owns _db_complete_run — only signal terminal here.
    yield root_ev("done", {
        "summary": summary or f"Review finished ({outcome}).",
        "changed_files": files,
        "review_status": outcome,
    })
