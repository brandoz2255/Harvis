"""Per-action risk classification + the approval gate for in-place VibeCode sessions.

The permission ladder (per session): plan | ask | auto-accept | full-auto. Each tool
action gets a risk tier (low | med | high); the rung maps (tier → decision):

    rung          low      med      high
    plan          allow    block    block      (read-only — writes are refused)
    ask           allow    gate     gate
    auto-accept   allow    allow    gate       (the irreversible acknowledge-popup)
    full-auto     allow    allow    allow

The runner consults ``gate_decision`` before every tool dispatch; on 'gate' it emits an
``approval_request`` event and blocks on an asyncio.Event until the UI resolves it
(``resolve_action``). In-memory + single-process, matching the rest of the orchestration
layer (clone-mode + the orchestrator never set permission_mode, so they're unaffected).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

# Exec commands that are IRREVERSIBLE or destroy real work → high. Gated even under
# auto-accept (the acknowledge-popup names the consequence); only full-auto lets them
# through unprompted. The big one for in-place: a working-tree-destructive command hits
# the user's REAL files (branch-isolation protects commits, not the tree).
_HIGH_EXEC = re.compile(
    r"(?:"
    # any sudo at all (bare `sudo rm` etc.) — privilege escalation is always high
    r"\bsudo\b"
    # destructive commands at a shell boundary (start / ; & | backtick)
    r"|(?:^|[;&|`])\s*(?:"
    r"rm\s+-[a-z]*[rf]|rm\s+--recursive|"            # rm -rf / -r / -f
    r"git\s+reset\s+--hard|git\s+checkout\s+(?:--\s+)?\.|git\s+clean\b|"  # destroy working tree
    r"git\s+push\b|git\s+branch\s+-D\b|"             # push / force-delete branch
    r"chmod\b|chown\b|dd\b|mkfs|truncate\b|"
    r"find\b[^;&|]*-delete|\btee\b|\bmv\b|\bcp\s+-[a-z]*f|"  # recursive delete / file clobber
    r"docker\b|kubectl\b|helm\b|terraform\s+apply|"  # deploy
    r"shutdown\b|reboot\b|:\s*\(\s*\)\s*\{"          # fork bomb
    r")"
    # output redirect to a file (write/truncate/append) — `> f`, `>> f`, but not `2>&1`
    r"|(?:^|\s)>>?\s*[^&|\s]"
    # pipe to a shell — `curl … | sh`, `| bash`
    r"|\|\s*(?:sudo\s+)?(?:ba|z|k)?sh\b"
    r")",
    re.IGNORECASE,
)
_ENV_WRITE = re.compile(r"(?:^|[\s/'\"=>])\.?env(?:\.|['\"\s]|$)|\.env\b", re.IGNORECASE)

_READ_TOOLS = {"read_file", "read", "dir_list", "dir_fetch", "file_fetch", "list_dir", "cat", "ls"}
_EDIT_TOOLS = {"edit_file", "str_replace", "write", "file_write", "create_file", "apply_patch"}
_EXEC_TOOLS = {"exec", "run_code", "run_tests", "shell", "bash"}


def classify_action_risk_with_reason(tool: str, args: dict) -> tuple[str, str]:
    """(tier, reason): the tier plus a human-readable WHY — which rule tripped
    (e.g. the _HIGH_EXEC fragment that matched). The reason rides the
    approval_request payload so the acknowledge-popup can say what was flagged."""
    t = (tool or "").lower()
    args = args or {}
    if t in _READ_TOOLS or t == "finish":
        return "low", "read-only action"
    if t in _EDIT_TOOLS:
        path = str(args.get("path") or args.get("file") or args.get("filename") or "")
        if _ENV_WRITE.search(path):
            return "high", f"writes a secret-looking file ({path or '.env'})"
        return "med", "edits the working tree"
    if t in _EXEC_TOOLS:
        cmd = str(args.get("command") or args.get("cmd") or args.get("code") or args.get("script") or "")
        m = _HIGH_EXEC.search(cmd)
        if m:
            frag = (m.group(0) or "").strip() or "destructive command"
            return "high", f"irreversible/destructive command pattern matched: {frag!r}"
        if _ENV_WRITE.search(cmd):
            return "high", "command touches a secret-looking file (.env)"
        return "med", "runs a shell command"
    if t == "git_commit":
        # Local-only by construction (the tool never pushes and refuses main/master);
        # still med so the ladder gates it under 'ask' like any worktree-affecting action.
        return "med", "creates a LOCAL git commit on the session work branch (never pushes)"
    # Unknown tool → treat as med (gated under ask, auto under auto-accept).
    return "med", "unrecognized tool (default medium risk)"


def classify_action_risk(tool: str, args: dict) -> str:
    """'low' (read / finish), 'med' (worktree edit / ordinary command), 'high'
    (irreversible: rm -rf, git reset --hard / checkout ., push, .env write, deploy, sudo)."""
    return classify_action_risk_with_reason(tool, args)[0]


def gate_decision_ex(tool: str, args: dict, permission_mode: str) -> tuple[str, str, str]:
    """Return (decision, risk_tier, reason). decision ∈ {'allow', 'gate', 'block'}
    per the ladder; reason = the matched-rule explanation (why this tier)."""
    tier, reason = classify_action_risk_with_reason(tool, args)
    mode = (permission_mode or "ask").lower()
    if mode == "full-auto":
        return "allow", tier, reason
    if mode == "plan":
        return ("allow" if tier == "low" else "block"), tier, reason
    if mode == "auto-accept":
        return ("gate" if tier == "high" else "allow"), tier, reason
    # 'ask' (default for in-place)
    return ("allow" if tier == "low" else "gate"), tier, reason


def gate_decision(tool: str, args: dict, permission_mode: str) -> tuple[str, str]:
    """Return (decision, risk_tier). decision ∈ {'allow', 'gate', 'block'} per the ladder."""
    decision, tier, _reason = gate_decision_ex(tool, args, permission_mode)
    return decision, tier


# ── Per-action approval gate ──────────────────────────────────────────────────
# action_id → {event, approved}. The runner registers + awaits; the approve/deny
# endpoint resolves. In-memory, single-process (matches the rest of orchestration).
_PENDING_ACTIONS: dict[str, dict] = {}


def register_pending(action_id: str, meta: dict | None = None) -> asyncio.Event:
    ev = asyncio.Event()
    _PENDING_ACTIONS[action_id] = {"event": ev, "approved": False, "meta": meta or {}}
    return ev


def get_pending_for_run(run_id: str) -> dict | None:
    """The current UNRESOLVED gated action for a run (or None) — for the poll endpoint
    that drives the acknowledge-popup (reload-safe: the entry lives until resolved)."""
    for aid, entry in _PENDING_ACTIONS.items():
        if aid.startswith(f"{run_id}-") and not entry["event"].is_set():
            return {"action_id": aid, **(entry.get("meta") or {})}
    return None


async def await_action_decision(action_id: str, timeout: float = 1800.0) -> bool:
    """Block until the action is approved/denied (or timeout → treated as deny)."""
    entry = _PENDING_ACTIONS.get(action_id)
    if not entry:
        return False
    try:
        await asyncio.wait_for(entry["event"].wait(), timeout=timeout)
        return bool(entry.get("approved"))
    except asyncio.TimeoutError:
        return False
    finally:
        _PENDING_ACTIONS.pop(action_id, None)


def resolve_action(action_id: str, approved: bool) -> bool:
    """Resolve a pending action (called by the approve/deny endpoint). True if it existed."""
    entry = _PENDING_ACTIONS.get(action_id)
    if not entry:
        return False
    entry["approved"] = approved
    entry["event"].set()
    return True


# ── Durable approvals (Build Space Phase 2) ───────────────────────────────────
# The in-memory registry above stays the FAST PATH (the awaiting coroutine can only
# live in this process anyway). The DB layer beneath it is a DURABILITY mirror:
# pending rows survive a backend restart so the UI can still SHOW what was gated
# (instead of a silent deny), and per-session approved patterns persist so a
# re-run auto-approves without re-prompting. Every DB call here is fail-open —
# a DB hiccup logs a warning and never hard-blocks an interactive turn.

def action_pattern(tool: str, args: dict) -> str:
    """Canonical pattern string for approve-for-session matching. exec → the
    whitespace-normalized command; edit → tool:path; other → tool + sorted args."""
    t = (tool or "").lower()
    args = args or {}
    if t in _EXEC_TOOLS:
        cmd = str(args.get("command") or args.get("cmd") or args.get("code") or args.get("script") or "")
        return f"exec:{' '.join(cmd.split())}"
    if t in _EDIT_TOOLS:
        path = str(args.get("path") or args.get("file") or args.get("filename") or "")
        return f"{t}:{path}"
    try:
        return f"{t}:{json.dumps(args, sort_keys=True, default=str)[:400]}"
    except Exception:
        return f"{t}:"


# session_id → set of approved patterns (write-through cache over
# vibecode_sessions.approved_patterns JSONB).
_SESSION_APPROVED: dict[str, set[str]] = {}


async def _load_session_approvals(pool, session_id: str) -> set[str]:
    if session_id in _SESSION_APPROVED:
        return _SESSION_APPROVED[session_id]
    patterns: set[str] = set()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                raw = await conn.fetchval(
                    "SELECT approved_patterns FROM vibecode_sessions WHERE id = $1", session_id
                )
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, list):
                patterns = {str(p) for p in raw}
        except Exception as exc:
            logger.warning("risk: load session approvals failed (%s): %s", session_id, exc)
            return patterns  # fail-open: don't cache a failed load — retry next time
    _SESSION_APPROVED[session_id] = patterns
    return patterns


async def is_session_approved(pool, session_id: str | None, tool: str, args: dict) -> bool:
    """True iff this action matches a pattern the user already approved for the
    WHOLE session ('approve for session') — the gate consults this FIRST."""
    if not session_id:
        return False
    try:
        return action_pattern(tool, args) in await _load_session_approvals(pool, session_id)
    except Exception as exc:
        logger.warning("risk: session-approval check failed (%s): %s", session_id, exc)
        return False  # conservative: fall through to the normal gate


async def add_session_approval(pool, session_id: str, tool: str, args: dict) -> None:
    """Record 'approve for session': cache write-through + persist on the session row."""
    if not session_id:
        return
    pattern = action_pattern(tool, args)
    patterns = await _load_session_approvals(pool, session_id)
    patterns.add(pattern)
    _SESSION_APPROVED[session_id] = patterns
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE vibecode_sessions SET approved_patterns = $2::jsonb, updated_at = NOW() "
                "WHERE id = $1",
                session_id, json.dumps(sorted(patterns)),
            )
    except Exception as exc:
        logger.warning("risk: persist session approval failed (%s): %s", session_id, exc)


async def persist_pending(
    pool, action_id: str, run_id: str, session_id: str | None,
    tool: str, args: dict, risk: str | None, reason: str | None,
) -> None:
    """Mirror a just-registered pending approval into the DB (durability layer)."""
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_pending_approvals
                    (id, session_id, run_id, tool, args, reason, risk)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                ON CONFLICT (id) DO NOTHING
                """,
                action_id, session_id, run_id, tool,
                json.dumps(args or {}, default=str), reason or "", risk or "",
            )
    except Exception as exc:
        logger.warning("risk: persist pending approval failed (%s): %s", action_id, exc)


async def mark_pending_resolved(pool, action_id: str, decision: str) -> None:
    """Mark the durable row resolved ('approved'|'approved-session'|'denied').
    Called from BOTH the resolve endpoint and the runner (covers timeout-deny)."""
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspace_pending_approvals SET resolved = TRUE, decision = $2 "
                "WHERE id = $1 AND NOT resolved",
                action_id, decision,
            )
    except Exception as exc:
        logger.warning("risk: mark pending resolved failed (%s): %s", action_id, exc)


async def get_pending_row(pool, action_id: str) -> dict | None:
    """The durable pending row (resolved or not) — the resolve endpoint uses it to
    recover tool/args/session after a restart wiped the in-memory registry."""
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, session_id, run_id, tool, args, reason, risk, resolved, decision "
                "FROM workspace_pending_approvals WHERE id = $1",
                action_id,
            )
        if not row:
            return None
        d = dict(row)
        if isinstance(d.get("args"), str):
            try:
                d["args"] = json.loads(d["args"])
            except Exception:
                d["args"] = {}
        return d
    except Exception as exc:
        logger.warning("risk: get pending row failed (%s): %s", action_id, exc)
        return None


async def get_pending_for_run_db(pool, run_id: str) -> dict | None:
    """DB fallback for get_pending_for_run — after a restart the in-memory entry is
    gone but the row survives, so the UI can still show WHAT was gated (with its
    reason) instead of the request silently vanishing."""
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, tool, args, reason, risk FROM workspace_pending_approvals "
                "WHERE run_id = $1 AND NOT resolved ORDER BY created_at ASC LIMIT 1",
                run_id,
            )
        if not row:
            return None
        args = row["args"]
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        return {
            "action_id": row["id"], "tool": row["tool"], "args": args,
            "risk": row["risk"], "reason": row["reason"], "stale": True,
        }
    except Exception as exc:
        logger.warning("risk: pending-for-run DB fallback failed (%s): %s", run_id, exc)
        return None
