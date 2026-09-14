"""Native tools for P5 sub-agents — path-safe file + shell ops inside the
agent's isolated workspace. Every tool validates its target against the
workspace boundary BEFORE acting (see isolation.validate_agent_path). These run
IN-PROCESS in Harvis (not OpenClaw), which is what lets us enforce path safety,
risk gating (later), and diff collection.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from collections.abc import Iterable

from owui_compat.workspace_method import (
    DEFAULT_SAFE_LANE,
    LANE_CONTAINER_TERMINAL,
    LANE_EXTERNAL_SERVICES,
    LANE_UI_MOCK,
    LANE_WORKSPACE_FILES,
)

from .isolation import validate_agent_path
from .syntax_gate import check_source

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 8000
_EXEC_TIMEOUT = 60

_FALSY = {"0", "false", "no", "off"}


def _syntax_note(rel: str, content: str) -> str:
    """A loud suffix for a write whose result cannot run — '' when it parses.

    The write itself SUCCEEDED (the bytes are on disk), so this never turns into a
    tool error; it rides along on the success message. The wording is imperative
    because a warning phrased as an observation gets read past: a turn once wrote
    an Asteroids page whose <script> was never closed, called finish, and reported
    it as done — the browser ran none of it and the START button just flashed.
    """
    err = check_source(rel, content)
    if not err:
        return ""
    return (
        f"\n\n⚠ BUT {rel} DOES NOT PARSE — {err}.\n"
        "Nothing in that file will run until this is fixed. Re-read it, find the "
        "unbalanced or malformed part, and repair it NOW before you do anything "
        "else. Do not call finish while this stands."
    )


def _isolated_runner_enabled() -> bool:
    """Build Space Phase 3 flag — ``HARVIS_BUILD_ISOLATED_RUNNER``, default ON.

    ON routes a vibecode session's exec/run_tests through the hardened,
    socket-less per-session container (terminal_container.exec_isolated)
    instead of the backend process. Unset/'1'/'true'/'yes'/'on' → ON; only an
    EXPLICIT falsy value ('0'/'false'/'no'/'off') turns it OFF — the deliberate
    instant-rollback lever back to in-process exec. Unrecognized values stay ON
    (fail secure)."""
    raw = (os.getenv("HARVIS_BUILD_ISOLATED_RUNNER") or "").strip().lower()
    return raw not in _FALSY


async def _exec_isolated(workspace_path: str, session_id: str, cmd: str) -> tuple[str, bool]:
    """Run a vibecode-session command in the HARDENED per-session runner
    container (cap_drop=ALL, no-new-privileges, pids limit, uid 1001, NO
    docker.sock — see terminal_container.exec_isolated).

    FAIL CLOSED: any failure to create/reach the runner returns an exec ERROR
    result — it NEVER falls back to in-process exec, because that path runs in
    the backend (which mounts docker.sock → effectively host root). The flag
    OFF is the only deliberate escape hatch; a runtime failure is not."""
    try:
        from ..terminal_container import get_terminal_manager

        result = await get_terminal_manager().exec_isolated(
            session_id=session_id,
            workspace_path=workspace_path,
            cmd=cmd,
            timeout_s=_EXEC_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — every failure is a refusal, not a fallback
        logger.error(
            "isolated runner exec failed (session=%s): %s", session_id, exc, exc_info=True
        )
        return (
            "EXEC ERROR: the isolated runner container is unavailable "
            f"({exc}). The command was NOT run — in-process execution is "
            "disabled for security while HARVIS_BUILD_ISOLATED_RUNNER is on.",
            False,
        )
    exit_code = int(result.get("exit_code", -1))
    text = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    if stderr:
        text = f"{text}\n{stderr}" if text else stderr
    if exit_code == 124:  # coreutils `timeout` wrapper tripped
        text = (text + f"\n[command timed out after {_EXEC_TIMEOUT}s]").strip()
    return (text[:_MAX_OUTPUT], exit_code == 0)

def _git_blob_sha(fp: str) -> str | None:
    """Short git blob id (the `git hash-object` of the file's content, computed
    in-process) — None if the file is absent/unreadable. Used for the
    before/after shas on code_file_changes audit rows."""
    try:
        with open(fp, "rb") as f:
            data = f.read()
    except OSError:
        return None
    h = hashlib.sha1(b"blob %d\x00" % len(data) + data)  # noqa: S324 — git object id, not crypto
    return h.hexdigest()[:12]


async def _record_file_change(
    pool,
    session_id: str | None,
    run_id: str | None,
    file_path: str,
    change_type: str,
    patch_id: str,
    before_sha: str | None,
    after_sha: str | None,
) -> None:
    """Write ONE code_file_changes audit row. FAIL-OPEN by contract: a logging
    failure (no pool, DB down, missing table) must NEVER block the edit itself."""
    if pool is None or not session_id:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO code_file_changes "
                "(id, session_id, run_id, file_path, change_type, patch_id, before_sha, after_sha) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                uuid.uuid4().hex, session_id, run_id, file_path, change_type,
                patch_id, before_sha, after_sha,
            )
    except Exception as exc:  # noqa: BLE001 — fail-open on audit logging
        logger.warning("code_file_changes audit insert failed (fail-open): %s", exc)


async def _git_commit_workspace(workspace_path: str, message: str) -> tuple[str, bool]:
    """LOCAL-ONLY commit of the session workspace's current changes on its WORK
    branch. Locked policy: the AI may commit locally; it NEVER pushes (no push
    command exists here), and it REFUSES to commit on main/master."""
    from .isolation import _run_git

    if not os.path.isdir(os.path.join(workspace_path, ".git")):
        return ("git_commit: this workspace is not a git repository.", False)
    rc, branch, err = await _run_git(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace_path
    )
    branch = (branch or "").strip()
    if rc != 0 or not branch:
        return (f"git_commit: could not resolve the current branch: {(err or '')[:200]}", False)
    if branch.lower() in ("main", "master"):
        return (
            f"REFUSED: git_commit will not commit on '{branch}'. Commits are only allowed "
            "on the session's work branch — main/master is protected, and pushes/PRs stay "
            "human-approved.",
            False,
        )
    await _run_git(["git", "config", "user.name", "Harvis"], cwd=workspace_path)
    await _run_git(["git", "config", "user.email", "agent@harvis.local"], cwd=workspace_path)
    rc, _o, err = await _run_git(["git", "add", "-A"], cwd=workspace_path)
    if rc != 0:
        return (f"git_commit: staging failed: {(err or '')[:200]}", False)
    rc, _o, _e = await _run_git(["git", "diff", "--cached", "--quiet"], cwd=workspace_path)
    if rc == 0:
        return (json.dumps({"committed": False, "sha": None, "message": "no changes to commit"}), True)
    rc, _o, err = await _run_git(["git", "commit", "-m", message], cwd=workspace_path)
    if rc != 0:
        return (f"git_commit: commit failed: {(err or '')[:200]}", False)
    rc, sha, _e = await _run_git(["git", "rev-parse", "HEAD"], cwd=workspace_path)
    sha = (sha or "").strip()[:12]
    return (json.dumps({"committed": True, "sha": sha, "message": message}), True)


# OpenAI-format tool schema advertised to the model each step. Each entry also
# carries its Harvis permission ``lane`` (Execution Core Phase 2) — stripped
# before the schema goes on the wire (see WIRE_TOOL_SCHEMA below).
TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside your workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to your workspace."}},
                "required": ["path"],
            },
        },
        "lane": LANE_WORKSPACE_FILES,
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Create a NEW file, or fully REWRITE one, with `content`. ⚠ This OVERWRITES the "
                "whole file — anything you omit is deleted. To change part of an EXISTING file, "
                "use str_replace instead. Use edit_file only for brand-new files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to your workspace."},
                    "content": {"type": "string", "description": "The COMPLETE file content to write."},
                },
                "required": ["path", "content"],
            },
        },
        "lane": LANE_WORKSPACE_FILES,
    },
    {
        "type": "function",
        "function": {
            "name": "str_replace",
            "description": (
                "Edit an EXISTING file in place: replace the single exact occurrence of `old_str` "
                "with `new_str`, leaving the rest of the file untouched. PREFER THIS for any change "
                "to an existing file. `old_str` must match exactly (including indentation) and occur "
                "exactly once — include a few surrounding lines to make it unique. ALWAYS copy "
                "WHOLE lines into old_str and new_str (start at a line beginning, end at a line end) "
                "— never cut a line mid-token, or you will leave broken leftover text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to your workspace."},
                    "old_str": {"type": "string", "description": "Exact text to replace (unique in the file)."},
                    "new_str": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
        "lane": LANE_WORKSPACE_FILES,
    },
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Run a shell command in your workspace directory and return its output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        "lane": LANE_CONTAINER_TERMINAL,
    },
    {
        "type": "function",
        "function": {
            "name": "propose_skill",
            "description": (
                "Save a reusable procedure you just demonstrated as a DRAFT skill for the human to "
                "review. Use ONLY when you completed a genuinely reusable, repeatable procedure worth "
                "keeping. The draft is NOT active and grants nothing — a human must mark it 'supported' "
                "in Customize → Skills before it can ever be applied. Give a short kebab-case name, a "
                "one-line description of WHEN to use it, and the procedure as markdown steps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "kebab-case skill name, e.g. 'reset-postgres-schema'"},
                    "description": {"type": "string", "description": "One line: when should this skill be used?"},
                    "content": {"type": "string", "description": "The procedure, as markdown steps."},
                },
                "required": ["name", "description", "content"],
            },
        },
        "lane": LANE_UI_MOCK,
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate an image from a text prompt (local diffusion). Use when the user "
                "asks you to CREATE/DRAW/MAKE a picture/image. Returns a saved image "
                "artifact shown in the run."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the image should show."},
                    "negative_prompt": {"type": "string", "description": "What to avoid in the image."},
                    "width": {"type": "integer", "description": "Width in px (256-1024, default 512)."},
                    "height": {"type": "integer", "description": "Height in px (256-1024, default 512)."},
                },
                "required": ["prompt"],
            },
        },
        "lane": LANE_UI_MOCK,
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": (
                "Apply ONE tracked change to a file in your workspace, recorded in the "
                "session's per-file audit trail (Changes list). Modes: pass `content` to "
                "create or fully rewrite the file; pass `old_str`+`new_str` to replace one "
                "exact occurrence in an existing file; pass `delete`:true to remove it. "
                "Prefer this over edit_file/str_replace in coding sessions so every change "
                "is auditable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to your workspace."},
                    "content": {"type": "string", "description": "COMPLETE new file content (create/rewrite mode)."},
                    "old_str": {"type": "string", "description": "Exact text to replace — must occur exactly once (edit mode)."},
                    "new_str": {"type": "string", "description": "Replacement text (edit mode)."},
                    "delete": {"type": "boolean", "description": "true to delete the file."},
                },
                "required": ["path"],
            },
        },
        "lane": LANE_WORKSPACE_FILES,
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": (
                "Stage and commit ALL current changes in your session workspace as ONE "
                "LOCAL git commit on the session's WORK branch, with `message`. LOCAL "
                "ONLY — this NEVER pushes, and it refuses to run on main/master (pushes "
                "and pull requests stay human-approved). Use after a coherent unit of work."
            ),
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string", "description": "Commit message."}},
                "required": ["message"],
            },
        },
        "lane": LANE_WORKSPACE_FILES,
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_preview",
            "description": (
                "Render an HTML file from your workspace at desktop AND mobile viewports "
                "(full-page) via the headless browser, and return the PNGs for visual "
                "comparison against the user's screenshot. Use after create/edit of the "
                "HTML. PNGs are for seeing, not keeping — they are not saved as artifacts. "
                "Requires HARVIS_VISION_SELF_CHECK_ENABLED. Prefer str_replace to fix "
                "issues after preview; do not regenerate the whole file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative HTML path (usually index.html).",
                    },
                },
                "required": ["path"],
            },
        },
        "lane": LANE_EXTERNAL_SERVICES,
    },
    {
        "type": "function",
        "function": {
            "name": "agent_reach_web_search",
            "description": (
                "Search the web and get back numbered results (title, url, snippet) — no page "
                "bodies. USE THIS FIRST for anything you cannot answer from memory: a release, a "
                "version, a price, a model card, anything current. Never guess a URL for "
                "agent_reach_web_read — search for it, then read the result you want. "
                "Lane 5 / HARVIS_AGENT_REACH_ENABLED. Not available inside OpenClaw."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                    "max_results": {"type": "integer", "description": "1-10 (default 5)."},
                },
                "required": ["query"],
            },
        },
        "lane": LANE_EXTERNAL_SERVICES,
    },
    {
        "type": "function",
        "function": {
            "name": "agent_reach_web_read",
            "description": (
                "Read a public web page as text (Jina reader via Harvis backend). Pass a URL you "
                "got from agent_reach_web_search — a URL assembled from memory is usually a 404. "
                "Lane 5 / HARVIS_AGENT_REACH_ENABLED. No cookies. Not available inside OpenClaw."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Public http(s) URL."},
                },
                "required": ["url"],
            },
        },
        "lane": LANE_EXTERNAL_SERVICES,
    },
    {
        "type": "function",
        "function": {
            "name": "agent_reach_yt_transcript",
            "description": (
                "Fetch YouTube captions/transcript for a public video URL. "
                "Requires HARVIS_AGENT_REACH_ENABLED."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "YouTube watch/shorts URL."},
                },
                "required": ["url"],
            },
        },
        "lane": LANE_EXTERNAL_SERVICES,
    },
    {
        "type": "function",
        "function": {
            "name": "agent_reach_gh_view",
            "description": (
                "Read a public GitHub file (raw). Pass a github.com/raw URL or "
                "owner/repo/path[@ref]. Requires HARVIS_AGENT_REACH_ENABLED."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "GitHub URL or owner/repo/path."},
                    "path": {"type": "string", "description": "Alias for url."},
                },
            },
        },
        "lane": LANE_EXTERNAL_SERVICES,
    },
    {
        "type": "function",
        "function": {
            "name": "agent_reach_rss_read",
            "description": (
                "Read items from a public RSS/Atom feed URL. "
                "Requires HARVIS_AGENT_REACH_ENABLED."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Feed URL."},
                    "max_items": {"type": "integer", "description": "Max items (1-25)."},
                },
                "required": ["url"],
            },
        },
        "lane": LANE_EXTERNAL_SERVICES,
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Finish the task. `summary` is the ONLY thing the user reads. "
                "If the task was a question, a comparison, or a research request, "
                "put the COMPLETE answer here — the tables, the numbers, the "
                "sources — not a description of the work you did to find it. "
                "If you created files, keep it short: what you built, one line "
                "per file."
            ),
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
        "lane": LANE_UI_MOCK,
    },
]

# What actually goes ON THE WIRE to the model API — TOOL_SCHEMA minus Harvis-
# internal keys ("lane"). Strict OpenAI-compatible upstreams can reject unknown
# keys inside a tool entry, so the request body must stay byte-identical to the
# pre-lane schema. Dict comprehension preserves key order → identical JSON.
WIRE_TOOL_SCHEMA = [
    {k: v for k, v in entry.items() if k != "lane"} for entry in TOOL_SCHEMA
]

# Every wire name must match OpenAI's function-name grammar. Local Ollama does not
# enforce it, so a name it accepts can still 400 on OpenRouter, Groq, Cerebras,
# Mistral and OpenAI itself — the reason the agent_reach tools lost their dots.
# Logged rather than raised: a bad name must not take the backend down at import.
_WIRE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
for _entry in WIRE_TOOL_SCHEMA:
    _n = ((_entry.get("function") or {}).get("name") or "")
    if not _WIRE_NAME_RE.match(_n):
        logger.error(
            "tools: wire tool name %r is not ^[a-zA-Z0-9_-]{1,64}$ — strict "
            "OpenAI-compatible providers will reject the whole request",
            _n,
        )


def wire_tool_names() -> set[str]:
    """Every tool NAME actually offered on the wire (function.name). Used to turn a
    sub-agent's allowed-tools ALLOWLIST into the offer-time WITHHOLD set the runner
    consumes (disabled = all_offered - allowed). authorize_action stays the dispatch
    authority regardless."""
    return {
        ((entry.get("function") or {}).get("name") or "")
        for entry in WIRE_TOOL_SCHEMA
    } - {""}


def filter_wire_schema(disabled: set[str]) -> list[dict]:
    """WIRE_TOOL_SCHEMA minus any tool whose function.name is in ``disabled``.
    Returns a NEW list (the module constant is never mutated); whole entries are
    dropped, nothing else changes. With an empty ``disabled`` set the result is
    element-wise identical to WIRE_TOOL_SCHEMA (same entries, same order)."""
    return [
        entry
        for entry in WIRE_TOOL_SCHEMA
        if ((entry.get("function") or {}).get("name") or "") not in disabled
    ]

# Tool names dispatched / risk-classified elsewhere but not advertised in
# TOOL_SCHEMA (dispatch_tool accepts run_tests; risk.py knows these aliases).
_EXTRA_TOOL_LANES = {
    "run_tests": LANE_CONTAINER_TERMINAL,
    "run_code": LANE_CONTAINER_TERMINAL,
    "shell": LANE_CONTAINER_TERMINAL,
    "bash": LANE_CONTAINER_TERMINAL,
    # Phase 4 SSH target registry (lane 5, external services). Governed by
    # HARVIS_SSH_ENABLED at the lane gate; probe/exec live on remote.ssh_manager.
    "ssh.targets.list": LANE_EXTERNAL_SERVICES,
    "ssh.probe": LANE_EXTERNAL_SERVICES,
    "ssh.exec": LANE_EXTERNAL_SERVICES,
}


def lane_for_tool(name: str) -> int:
    """Permission lane for a tool name. Unknown tools default to the safe
    ceiling (lane 3, sandbox terminal) — never accidentally lane-1 trivial."""
    n = (name or "").lower()
    # MCP connector tools (mcp__<server>__<tool>) run third-party server code
    # and usually reach an external service, so they sit in lane 5 by
    # definition — never in the ungated lanes, whatever the tool claims to do.
    if n.startswith("mcp__"):
        return LANE_EXTERNAL_SERVICES
    for entry in TOOL_SCHEMA:
        if ((entry.get("function") or {}).get("name") or "").lower() == n:
            try:
                return int(entry.get("lane", DEFAULT_SAFE_LANE))
            except (TypeError, ValueError):
                return DEFAULT_SAFE_LANE
    return _EXTRA_TOOL_LANES.get(n, DEFAULT_SAFE_LANE)


async def dispatch_tool(
    workspace_path: str,
    name: str,
    args: dict,
    *,
    session_id: str | None = None,
    pool=None,
    run_id: str | None = None,
) -> tuple[str, bool]:
    """Run one tool. Returns (output, ok). Never raises — failures come back as
    (message, False) so the agent loop can react.

    ``session_id`` is set ONLY for VibeCode-session turns (session_turn.py); it
    routes exec/run_tests into the hardened per-session runner container when
    HARVIS_BUILD_ISOLATED_RUNNER is on, and it enables the SESSION-ONLY tools
    (apply_patch, git_commit). Generic/orchestrated runs pass None and keep
    their current in-process path unchanged. ``pool``/``run_id`` are optional
    context for the code_file_changes audit trail (fail-open when absent)."""
    args = args if isinstance(args, dict) else {}
    try:
        if name == "read_file":
            rel = str(args.get("path") or "")
            if not validate_agent_path(workspace_path, rel):
                return (f"DENIED: path '{rel}' is outside your workspace.", False)
            fp = os.path.join(workspace_path, rel)
            if not os.path.isfile(fp):
                return (f"No such file: {rel}", False)
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                # Bound the read itself (not read-all-then-slice) so a huge file can't
                # block the event loop / blow up memory before we truncate.
                return (f.read(_MAX_OUTPUT), True)

        if name == "edit_file":
            rel = str(args.get("path") or "")
            content = args.get("content")
            content = "" if content is None else str(content)
            if not validate_agent_path(workspace_path, rel):
                return (f"DENIED: path '{rel}' is outside your workspace.", False)
            fp = os.path.join(workspace_path, rel)
            os.makedirs(os.path.dirname(fp) or workspace_path, exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)
            return (f"Wrote {len(content)} bytes to {rel}" + _syntax_note(rel, content), True)

        if name == "str_replace":
            rel = str(args.get("path") or "")
            old = args.get("old_str")
            new = args.get("new_str")
            old = "" if old is None else str(old)
            new = "" if new is None else str(new)
            if not validate_agent_path(workspace_path, rel):
                return (f"DENIED: path '{rel}' is outside your workspace.", False)
            fp = os.path.join(workspace_path, rel)
            if not os.path.isfile(fp):
                return (f"No such file: {rel} (use edit_file to create it).", False)
            if not old:
                return ("str_replace needs a non-empty old_str.", False)
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
            count = data.count(old)
            if count == 0:
                return (
                    f"old_str not found in {rel}. read_file it and copy the exact text "
                    "(including indentation).",
                    False,
                )
            if count > 1:
                return (
                    f"old_str matches {count} places in {rel}; add surrounding lines so it "
                    "is unique (exactly one match).",
                    False,
                )
            updated = data.replace(old, new, 1)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(updated)
            return (f"Replaced 1 occurrence in {rel}" + _syntax_note(rel, updated), True)

        if name == "apply_patch":
            # SESSION-ONLY (Phase 4): the tracked edit primitive. Same path safety
            # as edit_file/str_replace + ONE code_file_changes audit row per edit.
            if not session_id:
                return ("apply_patch is only available inside a coding session.", False)
            rel = str(args.get("path") or "")
            if not validate_agent_path(workspace_path, rel):
                return (f"DENIED: path '{rel}' is outside your workspace.", False)
            fp = os.path.join(workspace_path, rel)
            existed = os.path.isfile(fp)
            before_sha = _git_blob_sha(fp) if existed else None
            patch_id = uuid.uuid4().hex[:12]

            if args.get("delete"):
                if not existed:
                    return (f"No such file: {rel}", False)
                os.remove(fp)
                await _record_file_change(
                    pool, session_id, run_id, rel, "delete", patch_id, before_sha, None
                )
                return (f"Deleted {rel} (patch {patch_id})", True)

            old = args.get("old_str")
            if old is not None and str(old):
                # In-place replace (str_replace semantics), tracked as 'modify'.
                old = str(old)
                new = args.get("new_str")
                new = "" if new is None else str(new)
                if not existed:
                    return (f"No such file: {rel} (pass `content` to create it).", False)
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    data = f.read()
                count = data.count(old)
                if count == 0:
                    return (
                        f"old_str not found in {rel}. read_file it and copy the exact text "
                        "(including indentation).",
                        False,
                    )
                if count > 1:
                    return (
                        f"old_str matches {count} places in {rel}; add surrounding lines so it "
                        "is unique (exactly one match).",
                        False,
                    )
                updated = data.replace(old, new, 1)
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(updated)
                await _record_file_change(
                    pool, session_id, run_id, rel, "modify", patch_id,
                    before_sha, _git_blob_sha(fp),
                )
                return (
                    f"Replaced 1 occurrence in {rel} (patch {patch_id})"
                    + _syntax_note(rel, updated),
                    True,
                )

            content = args.get("content")
            if content is None:
                return ("apply_patch needs `content`, `old_str`+`new_str`, or `delete`:true.", False)
            content = str(content)
            os.makedirs(os.path.dirname(fp) or workspace_path, exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)
            await _record_file_change(
                pool, session_id, run_id, rel, ("modify" if existed else "add"),
                patch_id, before_sha, _git_blob_sha(fp),
            )
            return (
                f"Wrote {len(content)} bytes to {rel} (patch {patch_id})"
                + _syntax_note(rel, content),
                True,
            )

        if name == "git_commit":
            # SESSION-ONLY (Phase 4): local commit on the session's work branch.
            # Never pushes; refuses main/master (see _git_commit_workspace).
            if not session_id:
                return ("git_commit is only available inside a coding session.", False)
            message = str(args.get("message") or "").strip()
            if not message:
                return ("git_commit needs a non-empty `message`.", False)
            return await _git_commit_workspace(workspace_path, message)

        if name.startswith(("agent_reach_", "agent_reach.")):
            from agent_reach import dispatch_agent_reach

            out = await dispatch_agent_reach(name, args)
            # Contract: dispatch_agent_reach converts any {"ok": false} payload
            # into an "ERROR: ..." string before returning, so this prefix test
            # is the whole success signal. It used to see the raw JSON and read
            # {"ok": false, "error": ...} as a successful tool call.
            ok = not out.startswith("ERROR:") and not out.startswith("DENIED:")
            return (out, ok)

        if name in ("exec", "run_tests"):
            cmd = str(args.get("command") or ("pytest -q" if name == "run_tests" else ""))
            if not cmd.strip():
                return ("No command provided.", False)
            # Build Space Phase 3 (SECURITY): a VIBECODE SESSION command runs in
            # the hardened, socket-less per-session container — never inside the
            # backend process (which mounts docker.sock → host root). Scope =
            # session runs only (session_id set); the flag OFF restores the
            # legacy in-process path everywhere (instant rollback). A runner
            # failure while the flag is ON returns an error — it never falls
            # through to create_subprocess_shell below (fail closed).
            if session_id and _isolated_runner_enabled():
                return await _exec_isolated(workspace_path, session_id, cmd)
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=_EXEC_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return (f"Command timed out after {_EXEC_TIMEOUT}s.", False)
            text = (out or b"").decode("utf-8", "replace")
            return (text[:_MAX_OUTPUT], (proc.returncode == 0))

        return (f"Unknown tool: {name}", False)
    except Exception as exc:
        logger.warning("orchestration tool %s failed: %s", name, exc, exc_info=True)
        return (f"Tool error: {exc}", False)


def _json_objects_in(text: str) -> list[dict]:
    """Every top-level JSON object embedded in ``text``, in order.

    Brace-counting rather than a regex, because a tool call's arguments are themselves
    an object and a regex that can be written in one line cannot count. String literals
    are tracked so a ``}`` inside a path or a snippet of code does not close the object
    early — which is exactly the content these calls carry.
    """
    out: list[dict] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text or ""):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                    except Exception:
                        obj = None
                    if isinstance(obj, dict):
                        out.append(obj)
                    start = -1
    return out


def parse_tool_calls(msg: dict, known: Iterable[str] | None = None) -> list[dict]:
    """Extract tool calls from a completion message. Primary path = the OpenAI
    `tool_calls` array; fallback = a JSON tool object embedded in content (small
    local models sometimes narrate one instead of using the tool channel).

    ``known`` is the caller's tool universe. When given, the content fallback only
    accepts names from it — otherwise an unrelated JSON object in prose, say
    ``{"name": "Alice", "age": 3}``, reads as a call to a tool named Alice. Callers
    each have a different universe (workspace wire tools, CAD tools, chat_reach's
    two), so the list comes from the caller rather than a constant here.
    """
    out: list[dict] = []
    for tc in (msg.get("tool_calls") or []):
        fn = (tc or {}).get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        raw = fn.get("arguments")
        if isinstance(raw, str):
            try:
                args = json.loads(raw)
            except Exception:
                args = {}
        elif isinstance(raw, dict):
            args = raw
        else:
            args = {}
        out.append({"id": tc.get("id"), "name": name, "args": args})
    if out:
        return out

    # Fallback: a fenced/bare JSON tool object in the content. Small local models
    # narrate the call instead of using the tool channel, and llama3.1:8b does it with
    # no fence at all — a whole reply that is just
    # ``{"name": "edit_file", "parameters": {...}}``.
    #
    # This used to be one regex ending in ``[\s\S]*?\}``. Lazy, so it stopped at the
    # FIRST closing brace — which is the one closing the arguments object, not the one
    # closing the call. Every candidate therefore arrived at json.loads() one brace
    # short, threw, and was swallowed by the bare except: a narrated tool call with an
    # object argument, i.e. every real one, could never be recovered. Measured on
    # workspace b5142379, where the dropped call surfaced to the user as the raw JSON
    # printed as the run's summary instead of a file being written.
    content = msg.get("content") or ""
    for obj in _json_objects_in(content):
        name = obj.get("tool") or obj.get("name")
        if not isinstance(name, str) or not name:
            continue
        if known is not None and name not in known:
            continue
        # ``arguments`` is the OpenAI spelling; the others are what models actually
        # emit when they are writing the call out by hand.
        args = None
        for key in ("arguments", "args", "parameters", "input"):
            if isinstance(obj.get(key), dict):
                args = obj[key]
                break
        if args is None:
            args = {k: v for k, v in obj.items() if k not in ("tool", "name")}
        out.append({"id": None, "name": name, "args": args})
    return out
