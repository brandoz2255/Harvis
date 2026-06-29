"""External code-engine adapter (Phase E1 + E2) — run an EXTERNAL coding CLI against a
VibeCode session clone and stream its work back as the standard ``OpenClawEvent`` stream
+ a git diff, alongside the native ``vibecode-turn`` runner.

Engines (``engine=…``):
- ``opencode``    — local Ollama, no auth (E1).
- ``codex``       — OpenAI's Codex CLI, CLOUD GPT models, per-user OpenAI key (E2).
- ``claude-code`` — Anthropic's Claude Code CLI, CLOUD Claude models, per-user key (E2).

Each runs in its own ``harvis-<engine>`` sidecar via ``docker exec`` against the session
clone (shared ``/data/artifacts`` volume). Per-engine differences are isolated to a
**command builder** (`_build_*_command`) and an **output mapper** (`_map_*_line`); the
loop (read NDJSON → map → persist/broadcast), diff collection, timeout, per-run cancel,
and path-safety are SHARED.

CLOUD engines: the user's decrypted API key is injected per-exec (`docker exec -e KEY=…`)
— NEVER baked in the image and NEVER logged. CLONE (``session``) isolation ONLY (the
caller enforces this); the clone diff is the only gate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

from ..openclaw_client import OpenClawEvent
from .isolation import SESSION_WORKSPACE_ROOT, WorkspaceIsolationManager

logger = logging.getLogger(__name__)

_CONTAINERS = {
    "opencode": os.getenv("HARVIS_OPENCODE_CONTAINER", "harvis-opencode"),
    "codex": os.getenv("HARVIS_CODEX_CONTAINER", "harvis-codex"),
    "claude-code": os.getenv("HARVIS_CLAUDE_CODE_CONTAINER", "harvis-claude-code"),
    # Phase E4B: the REAL NousResearch Hermes Agent app (full runtime: tools, memory,
    # skills, SOUL, providers). Local Ollama, no cloud key. Plain-text CLI output.
    "hermes-agent": os.getenv("HARVIS_HERMES_AGENT_CONTAINER", "harvis-hermes-agent"),
}
_CLOUD_ENGINES = {"codex", "claude-code"}
# Engines whose stdout is PLAIN TEXT (not JSON) — the loop maps each line to a `log`
# event and uses the output tail as the final summary; the git diff is the authority.
_TEXT_ENGINES = {"hermes-agent"}
_ENGINE_LABEL = {"opencode": "OpenCode", "codex": "Codex", "claude-code": "Claude Code",
                 "hermes-agent": "Hermes Agent"}
# Cloud engines default to the CLI's own default model when these are empty.
_CODEX_DEFAULT_MODEL = os.getenv("HARVIS_CODEX_DEFAULT_MODEL", "")
_CLAUDE_DEFAULT_MODEL = os.getenv("HARVIS_CLAUDE_DEFAULT_MODEL", "")
# Phase E4B Hermes Agent: local-Ollama provider + per-user profile homes (memory/SOUL).
_HERMES_HOMES_ROOT = os.getenv("HARVIS_HERMES_HOMES_ROOT", "/data/hermes-homes")
_HERMES_OLLAMA_URL = os.getenv("HARVIS_HERMES_OLLAMA_URL", "http://ollama:11434/v1")
# E4B's own default model (decoupled from E4-native's HARVIS_HERMES_DEFAULT_MODEL): the
# Hermes Agent app runs any local Ollama model — a capable coder (qwen3:4b) is the default.
_HERMES_DEFAULT_MODEL = os.getenv("HARVIS_HERMES_AGENT_DEFAULT_MODEL", "qwen3:4b")
_TIMEOUT_S = int(os.getenv("HARVIS_OPENCODE_TIMEOUT_S", "900") or "900")
_STREAM_LIMIT = 8 * 1024 * 1024  # engine JSON lines can carry large file contents


def _under_session_root(path: str) -> bool:
    """Path-safety: the workspace must resolve UNDER SESSION_WORKSPACE_ROOT so a
    malformed DB row can't point the exec at an arbitrary host path."""
    try:
        root = Path(SESSION_WORKSPACE_ROOT).resolve()
        target = Path(path).resolve()
        return target == root or str(target).startswith(str(root) + os.sep)
    except Exception:
        return False


# ── Per-engine command builders ─────────────────────────────────────────────
# Each returns the full `docker exec …` argv. For cloud engines the decrypted key is
# injected via `-e KEY=…` (NEVER logged). `-s danger-full-access` / `--dangerously-…`
# is safe: the throwaway clone is the sandbox (same posture as native clone-mode), and
# the container can't run the CLIs' bubblewrap sandbox (no namespace caps) anyway.

def _build_opencode_command(container, workspace_path, task_brief, model_name, api_key, user_id=0, auth_mode="api_key"):
    model = (model_name or os.getenv("HARVIS_OPENCODE_DEFAULT_MODEL", "qwen3:4b")).strip() or "qwen3:4b"
    model_id = model if model.startswith("ollama/") else f"ollama/{model}"
    return [
        "docker", "exec", "-u", "1001", "-w", workspace_path, container,
        "opencode", "run", task_brief,
        "--model", model_id, "--format", "json", "--dangerously-skip-permissions",
        "--dir", workspace_path,
    ], model_id


def _build_codex_command(container, workspace_path, task_brief, model_name, api_key, user_id=0, auth_mode="api_key"):
    cmd = ["docker", "exec", "-e", f"OPENAI_API_KEY={api_key or ''}",
           "-u", "1001", "-w", workspace_path, container,
           "codex", "exec", "--json", "-s", "danger-full-access", "--skip-git-repo-check"]
    if _CODEX_DEFAULT_MODEL:
        cmd += ["-m", _CODEX_DEFAULT_MODEL]
    cmd += [task_brief]
    return cmd, (_CODEX_DEFAULT_MODEL or "codex/default")


def _build_claude_command(container, workspace_path, task_brief, model_name, api_key, user_id=0, auth_mode="api_key"):
    # E4B dual-auth: inject EXACTLY ONE credential env var by mode — never both
    # (ANTHROPIC_API_KEY officially takes precedence). ALSO control CLAUDE_CODE_SIMPLE: the
    # sidecar image bakes CLAUDE_CODE_SIMPLE=1 (simple/bare mode), which reads auth STRICTLY
    # from ANTHROPIC_API_KEY and IGNORES CLAUDE_CODE_OAUTH_TOKEN — so subscription-token mode
    # MUST disable it (=empty). Never use `--bare` either; same reason.
    if auth_mode == "oauth_token":
        cred = ["-e", f"CLAUDE_CODE_OAUTH_TOKEN={api_key or ''}", "-e", "CLAUDE_CODE_SIMPLE="]
    else:
        cred = ["-e", f"ANTHROPIC_API_KEY={api_key or ''}", "-e", "CLAUDE_CODE_SIMPLE=1"]
    cmd = ["docker", "exec", *cred,
           "-u", "1001", "-w", workspace_path, container,
           "claude", "-p", task_brief,
           "--output-format", "stream-json", "--verbose",
           "--add-dir", workspace_path, "--dangerously-skip-permissions"]
    if _CLAUDE_DEFAULT_MODEL:
        cmd += ["--model", _CLAUDE_DEFAULT_MODEL]
    return cmd, (_CLAUDE_DEFAULT_MODEL or "claude/default")


def _build_hermes_command(container, workspace_path, task_brief, model_name, api_key, user_id=0, auth_mode="api_key"):
    # Phase E4B: the REAL Hermes Agent app, headless one-shot (`-z`) INSIDE the session
    # clone. HERMES_WRITE_SAFE_ROOT=<clone> confines write_file to the clone (Hermes itself
    # refuses to write outside it — defense in depth on top of the throwaway clone);
    # TERMINAL_CWD=<clone> + the docker-workspace opt-in make the clone Hermes's working
    # tree; per-user HERMES_HOME isolates memory/SOUL. Local Ollama, NO cloud key. `--yolo`
    # bypasses approval prompts (the clone is the sandbox — same posture as the others).
    model = (model_name or _HERMES_DEFAULT_MODEL).strip() or _HERMES_DEFAULT_MODEL
    home = f"{_HERMES_HOMES_ROOT}/{int(user_id) or 0}"
    cmd = [
        "docker", "exec", "-u", "1001", "-w", workspace_path,
        "-e", f"HERMES_HOME={home}",
        "-e", f"HERMES_WRITE_SAFE_ROOT={workspace_path}",
        "-e", f"TERMINAL_CWD={workspace_path}",
        "-e", "TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE=true",
        container, "hermes", "-z", task_brief, "--yolo", "-m", model,
    ]
    return cmd, model


_BUILDERS = {
    "opencode": _build_opencode_command,
    "codex": _build_codex_command,
    "claude-code": _build_claude_command,
    "hermes-agent": _build_hermes_command,
}


# ── Per-engine output mappers ───────────────────────────────────────────────
# Each takes a parsed JSON object + the root_ev factory and yields OpenClawEvents.
# Unrecognized shapes → a `log` event (never crash, never drop). The shared loop
# accumulates tool_calls (from tool_call events) + final text (from token events).

def _map_opencode_line(obj, root_ev):
    etype = obj.get("type")
    part = obj.get("part") or {}
    if etype == "text":
        txt = part.get("text")
        if txt:
            yield root_ev("token", {"content": str(txt)})
    elif etype == "tool_use":
        tool = part.get("tool") or "tool"
        state = part.get("state") or {}
        yield root_ev("tool_call", {"tool": tool, "args": state.get("input") or {}})
        status = state.get("status")
        if status in ("completed", "error"):
            yield root_ev("tool_result", {
                "output": str(state.get("output") or "")[:2000],
                "success": status == "completed",
            })
    # step_start / step_finish / other → drop


def _map_codex_line(obj, root_ev):
    # Codex `--json`: thread.started / turn.started / item.started / item.completed{item:{type:…}} / turn.completed
    etype = obj.get("type")
    if etype == "item.completed":
        item = obj.get("item") or {}
        it = item.get("type")
        if it == "agent_message":
            txt = item.get("text")
            if txt:
                yield root_ev("token", {"content": str(txt)})
        elif it == "command_execution":
            yield root_ev("tool_call", {"tool": "exec", "args": {"command": item.get("command")}})
            out = item.get("aggregated_output") or item.get("output")
            yield root_ev("tool_result", {"output": str(out or "")[:2000], "success": item.get("exit_code", 0) in (0, None)})
        elif it in ("file_change", "patch", "apply_patch"):
            yield root_ev("tool_call", {"tool": "edit", "args": {"changes": item.get("changes") or item.get("files")}})
            yield root_ev("tool_result", {"output": "applied", "success": True})
        elif it == "reasoning":
            txt = item.get("text")
            if txt:
                yield root_ev("log", {"message": ("💭 " + str(txt))[:500]})
        elif it == "error":
            yield root_ev("log", {"message": "Codex: " + str(item.get("message") or "")[:300]})
    # thread.started / turn.* / item.started → drop


def _map_claude_line(obj, root_ev):
    # Claude Code `--output-format stream-json --verbose`: system/assistant/user/result
    etype = obj.get("type")
    if etype == "assistant":
        for block in ((obj.get("message") or {}).get("content") or []):
            bt = block.get("type")
            if bt == "text" and block.get("text"):
                yield root_ev("token", {"content": str(block["text"])})
            elif bt == "tool_use":
                yield root_ev("tool_call", {"tool": block.get("name") or "tool", "args": block.get("input") or {}})
    elif etype == "user":
        for block in ((obj.get("message") or {}).get("content") or []):
            if block.get("type") == "tool_result":
                c = block.get("content")
                txt = c if isinstance(c, str) else json.dumps(c) if c is not None else ""
                yield root_ev("tool_result", {"output": str(txt)[:2000], "success": not block.get("is_error")})
    elif etype == "result":
        # Final wrap-up; the loop emits `done` separately. Surface the result text as a token.
        if obj.get("subtype") == "success" and obj.get("result"):
            yield root_ev("token", {"content": str(obj["result"])})
        elif obj.get("is_error"):
            yield root_ev("log", {"message": "Claude: " + str(obj.get("result") or obj.get("subtype") or "error")[:300]})
    # system/init → drop


def _map_hermes_line(obj, root_ev):
    # Hermes Agent (`hermes -z`) emits PLAIN TEXT, not JSON, so this JSON mapper is never
    # actually invoked — the loop's non-JSON fallback maps each line to a `log` event and
    # the output tail becomes the summary; the git diff is the authority. Present only to
    # satisfy the mapper dispatch.
    if False:  # pragma: no cover
        yield


_MAPPERS = {
    "opencode": _map_opencode_line,
    "codex": _map_codex_line,
    "claude-code": _map_claude_line,
    "hermes-agent": _map_hermes_line,
}


def _kill_run(container: str, workspace_path: str) -> None:
    """Best-effort, synchronous per-run kill INSIDE the sidecar (robust during cancel):
    match by argv (opencode --dir / claude --add-dir carry the path) AND by cwd (codex
    runs with cwd=clone). The unique clone path keys it to THIS run → cross-user safe."""
    script = (
        f'pkill -TERM -f "{workspace_path}" 2>/dev/null; '
        f'for p in /proc/[0-9]*; do '
        f'[ "$(readlink "$p/cwd" 2>/dev/null)" = "{workspace_path}" ] && kill -TERM "${{p##*/}}" 2>/dev/null; '
        f'done; true'
    )
    try:
        subprocess.run(["docker", "exec", container, "bash", "-c", script],
                       timeout=6, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def kill_run_by_marker(container: str, run_id: str) -> None:
    """Hard-kill (SIGKILL) every process in the sidecar whose ENV carries HARVIS_RUN_ID=<run_id>.

    Children inherit the env, so this kills the WHOLE subtree (e.g. a cloud `claude -p` plus any
    helpers) — which argv/cwd matching can miss (cloud chat runs with cwd=/tmp, no path in argv).
    Credit-safety backstop: on Stop / timeout / client-disconnect a subscription run must NOT keep
    billing. The marker is unique per run, so this is cross-run/cross-user safe. Best-effort, sync."""
    if not container or not run_id:
        return
    rid = "".join(ch for ch in str(run_id) if ch.isalnum() or ch in "-_")
    if not rid:
        return
    # Match the exact env line HARVIS_RUN_ID=<rid> (NUL-delimited environ → newlines), then SIGKILL.
    script = (
        f'for p in /proc/[0-9]*; do '
        f'tr "\\0" "\\n" < "$p/environ" 2>/dev/null | grep -qxF "HARVIS_RUN_ID={rid}" '
        f'&& kill -KILL "${{p##*/}}" 2>/dev/null; '
        f'done; true'
    )
    try:
        subprocess.run(["docker", "exec", container, "sh", "-c", script],
                       timeout=6, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


async def _ensure_hermes_home(container: str, user_id: int) -> None:
    """Phase E4B: ensure the per-user Hermes home (``<homes-root>/<uid>``) has a local-
    Ollama provider config.yaml, so Build runs with that HERMES_HOME find a provider.
    Idempotent; runs inside the sidecar as uid 1001. Local Ollama only — NO cloud key
    written, never logs anything sensitive."""
    home = f"{_HERMES_HOMES_ROOT}/{int(user_id) or 0}"
    script = (
        f'mkdir -p "{home}" 2>/dev/null; '
        f'if [ ! -f "{home}/config.yaml" ]; then '
        f'printf "model:\\n  provider: custom\\n  base_url: %s\\n  default: %s\\n" '
        f'"{_HERMES_OLLAMA_URL}" "{_HERMES_DEFAULT_MODEL}" > "{home}/config.yaml"; fi'
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-u", "1001", container, "sh", "-c", script,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
    except Exception as exc:
        logger.warning("engine_adapter: hermes home ensure failed (user=%s): %s", user_id, exc)


async def run_external_engine_adapter(
    task_brief: str,
    chat_history: list,  # Option A: unused — the clone (working tree) is the memory.
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
    engine: str = "opencode",
    api_key: Optional[str] = None,  # decrypted per-user credential for cloud engines (NEVER logged)
    auth_mode: str = "api_key",     # E4B: 'api_key' → ANTHROPIC_API_KEY; 'oauth_token' → CLAUDE_CODE_OAUTH_TOKEN
) -> AsyncGenerator[OpenClawEvent, None]:
    from ..workspace_router import (
        _db_create_run,
        _db_save_artifact,
        _db_set_run_repo,
        _db_set_run_source,
    )

    sess = session_id or f"ws-{parent_workspace_id}"
    label = _ENGINE_LABEL.get(engine, engine)
    run_id = parent_workspace_id
    started = time.monotonic()
    container = _CONTAINERS.get(engine, "")

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(etype, {**data, "agent_label": label, "model": model_name})
        e.run_id = run_id
        e.agent_label = label
        return e

    await _db_create_run(pool, parent_workspace_id, user_id, sess, task_brief)
    await _db_set_run_source(pool, parent_workspace_id, "vibecode")
    if repo_path:
        await _db_set_run_repo(pool, parent_workspace_id, repo_path)

    if engine not in _BUILDERS:
        yield root_ev("error", {"message": f"Unknown engine '{engine}'.", "fix_hint": "Supported: opencode, codex, claude-code."})
        return
    if not workspace_path or not _under_session_root(workspace_path):
        yield root_ev("error", {
            "message": f"{label} engine: invalid session workspace.",
            "fix_hint": "The session's working clone is missing or out of bounds — recreate the session.",
        })
        return
    if engine in _CLOUD_ENGINES and not api_key:
        yield root_ev("error", {
            "message": f"{label} isn't connected.",
            "fix_hint": f"Connect your API key for {label} in Integrations, then verify it.",
        })
        return

    iso = WorkspaceIsolationManager(
        root=SESSION_WORKSPACE_ROOT, isolation_mode="session",
        repo_config={"base_sha": base_sha, "repo_path": repo_path},
    )
    # Phase E4B: the Hermes Agent per-user profile home needs a provider config before the run.
    # Its model is the runtime's OWN preference (per-user pref → env → recommended → first), NOT
    # the generic Build session model — Hermes Agent is an agent runtime with its own model setting.
    if engine == "hermes-agent":
        await _ensure_hermes_home(container, user_id)
        try:
            from owui_compat.hermes_chat import resolve_hermes_model
            model_name = await resolve_hermes_model(pool, user_id)
        except Exception:
            pass  # fail-soft: _build_hermes_command falls back to _HERMES_DEFAULT_MODEL
    cmd, model_id = _BUILDERS[engine](container, workspace_path, task_brief, model_name, api_key, user_id=user_id, auth_mode=auth_mode)
    # Credit-safety: tag THIS run's docker-exec env so Stop/timeout can hard-kill its process
    # subtree (children inherit the env) even when argv/cwd matching misses. All builders emit
    # ["docker","exec",...]; inject the marker right after "exec".
    if run_id and len(cmd) >= 2 and cmd[0] == "docker" and cmd[1] == "exec":
        cmd = [cmd[0], cmd[1], "-e", f"HARVIS_RUN_ID={run_id}", *cmd[2:]]
    mapper = _MAPPERS[engine]
    yield root_ev("log", {"message": f"Launching {label} on {os.path.basename(workspace_path)}…"})

    proc: asyncio.subprocess.Process | None = None
    stderr_buf: list[str] = []
    tool_calls = 0
    final_text_parts: list[str] = []
    is_text_engine = engine in _TEXT_ENGINES   # plain-text stdout (Hermes) → log lines + tail summary
    text_tail: list[str] = []
    timed_out = False

    async def _drain_stderr(p: asyncio.subprocess.Process) -> None:
        try:
            async for raw in p.stderr:  # type: ignore[union-attr]
                s = raw.decode("utf-8", "replace").rstrip()
                if s:
                    stderr_buf.append(s)
                    if len(stderr_buf) > 50:
                        del stderr_buf[: len(stderr_buf) - 50]
        except Exception:
            pass

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=_STREAM_LIMIT,
            )
        except Exception as exc:
            yield root_ev("error", {
                "message": f"Could not start the {label} engine: {exc}",
                "fix_hint": f"Is the {container} sidecar running? `docker compose up -d {engine}`.",
            })
            return

        stderr_task = asyncio.create_task(_drain_stderr(proc))
        deadline = time.monotonic() + _TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)  # type: ignore[union-attr]
            except asyncio.TimeoutError:
                continue
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                yield root_ev("log", {"message": line[:500]})
                if is_text_engine:
                    text_tail.append(line)
                    if len(text_tail) > 16:
                        del text_tail[: len(text_tail) - 16]
                continue
            try:
                for ev in mapper(obj, root_ev):
                    if ev.type == "tool_call":
                        tool_calls += 1
                    elif ev.type == "token":
                        final_text_parts.append(str((ev.data or {}).get("content") or ""))
                    yield ev
            except Exception:
                yield root_ev("log", {"message": line[:300]})

        if not timed_out:
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except Exception:
                pass
        stderr_task.cancel()
    finally:
        try:
            if proc is not None and proc.returncode is None:
                proc.kill()
        except Exception:
            pass
        if container and workspace_path:
            _kill_run(container, workspace_path)          # graceful TERM, argv/cwd-keyed
        if container and run_id:
            kill_run_by_marker(container, run_id)         # SIGKILL backstop, env-marker-keyed

    # Collect the cumulative diff (working tree vs base_sha) — even on a non-zero exit.
    try:
        diff = await iso.collect_diff(workspace_path)
        files = await iso.collect_changed_files(workspace_path)
        contents = await iso.collect_file_contents(workspace_path)
    except Exception as exc:
        logger.warning("engine_adapter: diff collection failed: %s", exc, exc_info=True)
        diff, files, contents = "", [], {}

    repo_name = os.path.basename((repo_path or workspace_path).rstrip("/")) or "session"
    await _db_save_artifact(pool, parent_workspace_id, "diff", path=f"{label} · {repo_name}", content=diff or "(no changes)")
    for rel, content in contents.items():
        await _db_save_artifact(pool, parent_workspace_id, "file", path=rel, content=(content or ""))
    await _db_save_artifact(pool, parent_workspace_id, "changed_files", content="\n".join(files))

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspace_runs SET model_name=COALESCE(NULLIF($2,''), model_name) WHERE id=$1",
                parent_workspace_id, model_id,
            )
    except Exception:
        pass

    n = len(files)
    logger.info("engine_adapter: %s done (engine=%s model=%s, %d tool_calls, %d files, %.1fs)",
                parent_workspace_id, engine, model_id, tool_calls, n, time.monotonic() - started)

    if timed_out:
        yield root_ev("error", {"message": f"{label} timed out after {_TIMEOUT_S}s.", "fix_hint": "Try a smaller task."})
        return
    if n == 0 and stderr_buf:
        yield root_ev("error", {
            "message": f"{label} made no changes. " + (stderr_buf[-1][:300] if stderr_buf else ""),
            "fix_hint": "Check the engine is connected/authenticated and the task is actionable.",
        })
        return

    wrap = " ".join(p for p in final_text_parts if p).strip()
    if not wrap and is_text_engine and text_tail:
        # Hermes `-z` prints the final response as plain text — use the output tail.
        wrap = "\n".join(text_tail[-8:]).strip()
    summary = (wrap[:1500] if wrap else "") or f"{label} finished — {n} file(s) changed."
    yield root_ev("done", {"summary": summary, "changed_files": files})
