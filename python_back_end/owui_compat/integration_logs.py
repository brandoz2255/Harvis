"""Harvis Integrations — per-integration recent activity (read-only logs).

GET /api/owui/integrations/{integration_id}/logs?limit=N

Feeds the Integrations dashboard "Logs" drawer with a small, normalized recent-events
view per integration, sourced ONLY from EXISTING tables (no new writes, SELECT-only,
parameterized SQL):

  · Agent engines (openclaw / opencode / codex-app / claude-code / hermes-agent)
      → workspace_runs joined to vibecode_sessions.engine (user-scoped)
  · openclaw additionally → openclaw_tool_audit (web-tool proxy audit; the table is
      deploy-global — only tool name, status code, and a url/query summary are exposed)
  · ollama → proxy_usage_log (deploy-global model usage; token counts only)
  · mcp → mcp_servers config rows (user-scoped)
  · github → github_tokens presence + branch-producing runs (user-scoped)
  · discord → workspace_runs with a discord-* session (user-scoped)
  · cloud APIs (anthropic-api / openai-api → user_engine_auth; kimi-api →
      user_api_keys presence) — credential EVENTS only, never values

Security: auth-gated like the neighboring integrations endpoints; every string that
leaves this module passes through a secret-redaction regex + a hard length cap; the
tables' secret columns (access_token, api_key_encrypted, …) are never selected.
Fail-soft: any per-source query error degrades to an empty slice, never a 500.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable, Optional

import re

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

_MAX_LIMIT = 100
_DEFAULT_LIMIT = 40
_DETAIL_MAX = 220

# Anything that *looks* like a credential gets replaced before leaving the API.
_SECRET_RE = re.compile(
    r"(?i)("
    r"sk-ant-[A-Za-z0-9_\-]{8,}"                      # Anthropic keys
    r"|sk-[A-Za-z0-9_\-]{16,}"                        # OpenAI-style keys
    r"|gh[pousr]_[A-Za-z0-9]{16,}"                    # GitHub tokens
    r"|github_pat_[A-Za-z0-9_]{16,}"                  # GitHub fine-grained PATs
    r"|xox[baprs]-[A-Za-z0-9\-]{8,}"                  # Slack-style tokens
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}"  # JWTs
    r"|(?:api[_-]?key|apikey|token|secret|password|passwd|authorization|bearer)"
    r"[\"']?\s*[=:]\s*[\"']?[^\s\"',;&]{6,}"          # key=value shapes
    r")"
)


def _redact(text: Optional[str]) -> str:
    """Redact token-looking substrings + cap length. Safe on None."""
    if not text:
        return ""
    out = _SECRET_RE.sub("[redacted]", str(text))
    if len(out) > _DETAIL_MAX:
        out = out[: _DETAIL_MAX - 1].rstrip() + "…"
    return out


def _iso(ts) -> Optional[str]:
    try:
        return ts.isoformat() if ts is not None else None
    except Exception:
        return None


def _entry(ts, kind: str, title: str, detail: str = "", status: str = "info") -> dict:
    return {
        "ts": _iso(ts),
        "kind": kind,           # 'run' | 'tool' | 'usage' | 'config' | 'auth'
        "title": _redact(title),
        "detail": _redact(detail),
        "status": status,       # 'ok' | 'error' | 'running' | 'info'
    }


def _run_status(status: Optional[str], error: Optional[str]) -> str:
    s = (status or "").lower()
    if error or "error" in s or "fail" in s or "cancel" in s or "stopp" in s:
        return "error"
    if s == "running":
        return "running"
    return "ok"


# Integration card id → vibecode_sessions.engine values whose runs belong to it.
# Runs without a vibecode session (chat-lane workspace tasks) count as 'native' =
# the OpenClaw runtime, which is where they actually execute.
_ENGINE_OF: dict[str, tuple[str, ...]] = {
    "openclaw": ("native",),
    "opencode": ("opencode",),
    "codex-app": ("codex",),
    "claude-code": ("claude-code",),
    "hermes-agent": ("hermes-agent", "hermes-native"),
}

# Integration card id → user_engine_auth.engine row holding its credential events.
_AUTH_ENGINE_OF: dict[str, str] = {
    "claude-code": "claude-code",
    "codex-app": "codex",
    "anthropic-api": "claude-code",
    "openai-api": "codex",
}

_KNOWN_IDS = (
    set(_ENGINE_OF)
    | set(_AUTH_ENGINE_OF)
    | {"ollama", "mcp", "github", "discord", "kimi-api", "ssh",
       "pack-local-coder", "pack-repo-review"}
)


async def _engine_run_logs(conn, user_id: int, engines: tuple[str, ...], limit: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT r.status, r.task_brief, r.role, r.model_name,
               r.started_at, r.duration_ms, r.error_message
        FROM workspace_runs r
        LEFT JOIN vibecode_sessions vs ON vs.id = r.session_id
        WHERE r.user_id = $1 AND COALESCE(vs.engine, 'native') = ANY($2::text[])
        ORDER BY r.started_at DESC
        LIMIT $3
        """,
        user_id, list(engines), limit,
    )
    out = []
    for r in rows:
        bits = []
        if r["role"]:
            bits.append(str(r["role"]))
        if r["model_name"]:
            bits.append(str(r["model_name"]))
        if r["duration_ms"]:
            bits.append(f"{round(r['duration_ms'] / 1000, 1)}s")
        title = f"Run {(r['status'] or 'unknown')}" + (f" · {' · '.join(bits)}" if bits else "")
        detail = (r["task_brief"] or "").strip()
        if r["error_message"]:
            detail = f"{detail} — {r['error_message']}" if detail else str(r["error_message"])
        out.append(_entry(r["started_at"], "run", title, detail,
                          _run_status(r["status"], r["error_message"])))
    return out


async def _openclaw_tool_logs(conn, limit: int) -> list[dict]:
    """openclaw_tool_audit has no user column (deploy-global web-tool audit); expose
    only the tool name, status code, and a url/query summary — never full inputs."""
    rows = await conn.fetch(
        """
        SELECT ts, tool, status_code, error, input
        FROM openclaw_tool_audit
        ORDER BY ts DESC
        LIMIT $1
        """,
        limit,
    )
    out = []
    for r in rows:
        summary = ""
        try:
            inp = r["input"]
            if isinstance(inp, str):
                inp = json.loads(inp)
            if isinstance(inp, dict):
                summary = str(inp.get("url") or inp.get("query") or "")
        except Exception:
            summary = ""
        code = r["status_code"]
        title = f"{r['tool']}" + (f" · HTTP {code}" if code else "")
        detail = summary if not r["error"] else (f"{summary} — {r['error']}" if summary else str(r["error"]))
        status = "error" if (r["error"] or (code and int(code) >= 400)) else "ok"
        out.append(_entry(r["ts"], "tool", title, detail, status))
    return out


async def _ollama_usage_logs(conn, limit: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT model, tokens_in, tokens_out, ts
        FROM proxy_usage_log
        ORDER BY ts DESC
        LIMIT $1
        """,
        limit,
    )
    return [
        _entry(
            r["ts"], "usage", str(r["model"]),
            f"{int(r['tokens_in'] or 0)} in · {int(r['tokens_out'] or 0)} out tokens", "ok",
        )
        for r in rows
    ]


async def _mcp_config_logs(conn, user_id: int, limit: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT name, transport, enabled, created_at, updated_at
        FROM mcp_servers
        WHERE user_id = $1
        ORDER BY updated_at DESC
        LIMIT $2
        """,
        user_id, limit,
    )
    return [
        _entry(
            r["updated_at"] or r["created_at"], "config",
            f"{r['name']} · {'enabled' if r['enabled'] else 'disabled'}",
            f"transport {r['transport'] or 'stdio'}",
            "ok" if r["enabled"] else "info",
        )
        for r in rows
    ]


async def _github_logs(conn, user_id: int, limit: int) -> list[dict]:
    out: list[dict] = []
    row = await conn.fetchrow(
        "SELECT created_at FROM github_tokens WHERE user_id = $1", user_id
    )
    if row:
        out.append(_entry(row["created_at"], "auth", "GitHub token connected", "", "ok"))
    rows = await conn.fetch(
        """
        SELECT status, task_brief, branch_name, started_at, error_message
        FROM workspace_runs
        WHERE user_id = $1 AND branch_name IS NOT NULL
        ORDER BY started_at DESC
        LIMIT $2
        """,
        user_id, limit,
    )
    for r in rows:
        out.append(_entry(
            r["started_at"], "run",
            f"Branch {r['branch_name']} · {(r['status'] or 'unknown')}",
            (r["task_brief"] or "").strip(),
            _run_status(r["status"], r["error_message"]),
        ))
    return out


async def _discord_run_logs(conn, user_id: int, limit: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT status, task_brief, started_at, duration_ms, error_message
        FROM workspace_runs
        WHERE user_id = $1 AND session_id LIKE 'discord-%'
        ORDER BY started_at DESC
        LIMIT $2
        """,
        user_id, limit,
    )
    return [
        _entry(
            r["started_at"], "run",
            f"Discord run {(r['status'] or 'unknown')}",
            (r["task_brief"] or "").strip(),
            _run_status(r["status"], r["error_message"]),
        )
        for r in rows
    ]


async def _engine_auth_logs(conn, user_id: int, engine: str) -> list[dict]:
    """Credential lifecycle events from user_engine_auth — NEVER the credential."""
    row = await conn.fetchrow(
        """
        SELECT auth_mode, verified_at, last_error, created_at, updated_at
        FROM user_engine_auth
        WHERE user_id = $1 AND engine = $2
        """,
        user_id, engine,
    )
    if not row:
        return []
    out = [
        _entry(row["updated_at"] or row["created_at"], "auth",
               f"Credential saved ({row['auth_mode'] or 'api_key'})", "", "info")
    ]
    if row["verified_at"]:
        out.append(_entry(row["verified_at"], "auth", "Credential verified", "", "ok"))
    if row["last_error"]:
        out.append(_entry(row["updated_at"] or row["created_at"], "auth",
                          "Last verification error", str(row["last_error"]), "error"))
    return out


async def _kimi_auth_logs(conn, user_id: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT provider_name, is_active, created_at, updated_at
        FROM user_api_keys
        WHERE user_id = $1 AND provider_name IN ('moonshot', 'nvidia')
        ORDER BY updated_at DESC
        """,
        user_id,
    )
    return [
        _entry(
            r["updated_at"] or r["created_at"], "auth",
            f"{r['provider_name']} API key {'active' if r['is_active'] else 'inactive'}",
            "", "ok" if r["is_active"] else "info",
        )
        for r in rows
    ]


def register_integration_logs_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.get("/api/owui/integrations/{integration_id}/logs")
    async def integration_logs(
        integration_id: str,
        request: Request,
        user=Depends(get_current_user),
        limit: int = _DEFAULT_LIMIT,
    ):
        if integration_id not in _KNOWN_IDS:
            raise HTTPException(status_code=404, detail="Unknown integration")
        limit = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))

        pool = getattr(request.app.state, "pg_pool", None)
        logs: list[dict] = []
        sources: list[str] = []
        if pool is not None:
            uid = int(user.id)

            async def collect(source: str, coro_factory):
                """Run one source query fail-soft; record the source on success."""
                try:
                    async with pool.acquire() as conn:
                        rows = await coro_factory(conn)
                    logs.extend(rows)
                    sources.append(source)
                except Exception:
                    logger.debug(
                        "integration_logs: source %s failed for %s", source, integration_id,
                        exc_info=True,
                    )

            if integration_id in _ENGINE_OF:
                engines = _ENGINE_OF[integration_id]
                await collect("workspace_runs",
                              lambda c: _engine_run_logs(c, uid, engines, limit))
            if integration_id == "openclaw":
                await collect("openclaw_tool_audit",
                              lambda c: _openclaw_tool_logs(c, limit))
            if integration_id == "ollama":
                await collect("proxy_usage_log",
                              lambda c: _ollama_usage_logs(c, limit))
            if integration_id == "mcp":
                await collect("mcp_servers",
                              lambda c: _mcp_config_logs(c, uid, limit))
            if integration_id == "github":
                await collect("github_tokens + workspace_runs",
                              lambda c: _github_logs(c, uid, limit))
            if integration_id == "discord":
                await collect("workspace_runs",
                              lambda c: _discord_run_logs(c, uid, limit))
            if integration_id in _AUTH_ENGINE_OF:
                engine = _AUTH_ENGINE_OF[integration_id]
                await collect("user_engine_auth",
                              lambda c: _engine_auth_logs(c, uid, engine))
            if integration_id == "kimi-api":
                await collect("user_api_keys",
                              lambda c: _kimi_auth_logs(c, uid))

        # Merge sources newest-first, then cap. Missing timestamps sink to the bottom.
        logs.sort(key=lambda e: e.get("ts") or "", reverse=True)
        return {
            "integration": integration_id,
            "generated_at": int(time.time()),
            "sources": sources,
            "logs": logs[:limit],
        }
