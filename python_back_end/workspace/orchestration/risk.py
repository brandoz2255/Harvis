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
import re

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
_EDIT_TOOLS = {"edit_file", "str_replace", "write", "file_write", "create_file"}
_EXEC_TOOLS = {"exec", "run_code", "run_tests", "shell", "bash"}


def classify_action_risk(tool: str, args: dict) -> str:
    """'low' (read / finish), 'med' (worktree edit / ordinary command), 'high'
    (irreversible: rm -rf, git reset --hard / checkout ., push, .env write, deploy, sudo)."""
    t = (tool or "").lower()
    args = args or {}
    if t in _READ_TOOLS or t == "finish":
        return "low"
    if t in _EDIT_TOOLS:
        path = str(args.get("path") or args.get("file") or args.get("filename") or "")
        return "high" if _ENV_WRITE.search(path) else "med"
    if t in _EXEC_TOOLS:
        cmd = str(args.get("command") or args.get("cmd") or args.get("code") or args.get("script") or "")
        # _ENV_WRITE on the command too (not just edit paths) so `echo x > .env`,
        # `tee .env`, `cp .env …` are elevated like edit_file(.env) is.
        return "high" if (_HIGH_EXEC.search(cmd) or _ENV_WRITE.search(cmd)) else "med"
    # Unknown tool → treat as med (gated under ask, auto under auto-accept).
    return "med"


def gate_decision(tool: str, args: dict, permission_mode: str) -> tuple[str, str]:
    """Return (decision, risk_tier). decision ∈ {'allow', 'gate', 'block'} per the ladder."""
    tier = classify_action_risk(tool, args)
    mode = (permission_mode or "ask").lower()
    if mode == "full-auto":
        return "allow", tier
    if mode == "plan":
        return ("allow" if tier == "low" else "block"), tier
    if mode == "auto-accept":
        return ("gate" if tier == "high" else "allow"), tier
    # 'ask' (default for in-place)
    return ("allow" if tier == "low" else "gate"), tier


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
