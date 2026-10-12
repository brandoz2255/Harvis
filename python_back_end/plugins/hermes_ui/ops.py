"""Admin diagnostics behind the Hermes UI's Logs pane and "Run doctor" button.

Logs: a ring buffer on the root logger, filled from the moment this module is
imported (at plugin load), so /api/logs can tail the backend's own log lines
without a log file. Lines pass through the same redaction the kubectl proxy
uses before they leave the process.

Doctor: a handful of real checks (database, Ollama, disk, voice) whose output is
parked in a tiny in-memory registry so the UI's existing "start action, then tail
/api/actions/{name}/status" flow works unchanged. The checks finish before the
start request returns, so status is always "not running, exit 0 or 1".
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from collections import deque
from typing import Any

import httpx

MAX_LINES = 2000
_buffer: deque[tuple[float, int, str, str]] = deque(maxlen=MAX_LINES)  # (ts, level, logger, message)


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _buffer.append((record.created, record.levelno, record.name, record.getMessage()))
        except Exception:  # a log handler must never raise into the caller
            pass


def install() -> bool:
    """Attach the ring buffer once the app has configured logging.

    Adding a handler to a root logger that has none would make a later
    ``logging.basicConfig`` a no-op and silence the app's stdout logging, so this
    waits until a handler exists; /api/status and /api/logs call it again.
    """
    root = logging.getLogger()
    if any(isinstance(h, _RingHandler) for h in root.handlers):
        return True
    if not root.handlers:
        return False
    root.addHandler(_RingHandler(level=logging.INFO))
    return True


install()


def _redact(text: str) -> str:
    try:
        from plugins.hosting.workloads import redact
    except Exception:
        return text
    return redact(text)


def tail(lines: int = 200, level: str = "", search: str = "", component: str = "") -> list[str]:
    """The newest ``lines`` log lines at or above ``level``, redacted, oldest first."""
    lines = max(1, min(int(lines or 200), MAX_LINES))
    floor = getattr(logging, (level or "").upper(), 0) if level and level.upper() != "ALL" else 0
    floor = floor if isinstance(floor, int) else 0
    needle = (search or "").lower()
    comp = (component or "").lower()
    out: list[str] = []
    for ts, lvl, name, msg in reversed(_buffer):
        if lvl < floor or (comp and comp != "all" and comp not in name.lower()):
            continue
        row = f"{time.strftime('%H:%M:%S', time.localtime(ts))} {logging.getLevelName(lvl):<7} {name}: {msg}"
        if needle and needle not in row.lower():
            continue
        out.append(_redact(row))
        if len(out) >= lines:
            break
    out.reverse()
    return out


# ---- doctor ----------------------------------------------------------------------

_actions: dict[str, dict[str, Any]] = {}


def action_status(name: str, lines: int = 200) -> dict[str, Any] | None:
    row = _actions.get(name)
    if row is None:
        return None
    return {"name": name, "running": False, "exit_code": row["exit_code"], "pid": None,
            "lines": row["lines"][-max(1, lines):]}


async def _check_db(pool) -> tuple[bool, str]:
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True, "database: reachable"
    except Exception as exc:
        return False, f"database: FAILED ({type(exc).__name__})"


async def _check_ollama() -> tuple[bool, str]:
    base = (os.getenv("OLLAMA_URL") or "http://ollama:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            res = await client.get(f"{base}/api/tags")
        if res.status_code != 200:
            return False, f"ollama: HTTP {res.status_code}"
        count = len(res.json().get("models", []))
        return True, f"ollama: reachable, {count} model{'s' if count != 1 else ''} installed"
    except Exception as exc:
        return False, f"ollama: FAILED ({type(exc).__name__})"


def _check_disk() -> tuple[bool, str]:
    try:
        usage = shutil.disk_usage("/")
    except OSError as exc:
        return False, f"disk: FAILED ({type(exc).__name__})"
    free_gb, pct = usage.free / 1e9, usage.used * 100 / usage.total
    return pct < 95, f"disk: {free_gb:.0f} GB free ({pct:.0f}% used)" + ("" if pct < 95 else " - nearly full")


def _check_voice() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []
    for label, mod, key in (("speech-to-text", "transcription", "server_transcribes"),
                            ("text-to-speech", "synthesis", "server_synthesizes")):
        try:
            info = __import__(mod).status()
            rows.append((bool(info.get("available")),
                         f"voice {label}: {info.get('provider')} "
                         f"({'serves on the server' if info.get(key) else 'handled in the browser'})"))
        except Exception as exc:
            rows.append((False, f"voice {label}: FAILED ({type(exc).__name__})"))
    return rows


async def run_doctor(pool) -> dict[str, Any]:
    checks = [await _check_db(pool), await _check_ollama(), _check_disk(), *_check_voice()]
    failed = sum(1 for ok, _ in checks if not ok)
    lines = [("ok   " if ok else "FAIL ") + text for ok, text in checks]
    lines.append("All checks passed." if not failed else f"{failed} of {len(checks)} checks failed.")
    _actions["doctor"] = {"lines": lines, "exit_code": 1 if failed else 0}
    return {"name": "doctor", "ok": True, "pid": 0}


# ---- what this server can do for this person --------------------------------------

def capabilities(user) -> dict[str, bool]:
    """Feature flags the UI reads from /api/status so a control is shown only when it works.

    A flag is true only when the backend implements the call AND this user may use it.
    Everything not implemented here is listed explicitly as false so the UI has one
    place (``store/server-capabilities.ts``) to read and no guessing.
    """
    from owui_compat.authz import is_admin, user_id_of
    from plugins.exposure.gate import build_space_allowed

    from . import sandbox

    admin = is_admin(user)
    can_run = sandbox.enabled() and build_space_allowed(user_id_of(user))
    return {
        # implemented
        "git": can_run,
        "sandbox": can_run,
        "session_search": True,
        "memory_reset": True,
        "logs": admin,
        "doctor": admin,
        "provider_validate": True,
        # not provided by Harvis: the UI hides these controls
        "git_remote": False,
        "git_worktrees": False,
        "projects": False,
        "pets": False,
        "wake_word": False,
        "browser_control": False,
        "kanban": False,
        "provider_oauth": False,
        "memory_provider_config": False,
        "curator": False,
        "skills_hub": False,
        "gateway_restart": False,
        "hermes_update": False,
        "security_audit": False,
        "backup": False,
        "debug_share": False,
        "toolset_setup": False,
        "computer_use_grant": False,
    }
