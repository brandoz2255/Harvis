"""External code-engine adapter (Phase E1) — run an EXTERNAL coding CLI against a
VibeCode session clone and stream its work back as the standard ``OpenClawEvent``
stream + a git diff, alongside the native ``vibecode-turn`` runner.

E1 ships ONE engine: **OpenCode** (``engine="opencode"``), run in the
``harvis-opencode`` sidecar via ``docker exec`` against a LOCAL Ollama model
(zero cloud credentials). The sidecar shares the ``/data/artifacts`` volume, so it
edits the session clone in place; this adapter (in the backend) then collects the
diff with the SAME ``WorkspaceIsolationManager`` path ``run_vibecode_turn`` uses.

Selected by ``agent_id="engine-adapter"`` in ``_run_workspace_bg`` → persistence,
SSE streaming, and the RunView UI all render it unchanged. The bg loop owns
``_db_complete_run`` (its ``finally``) and emits ``cancelled`` on task cancel, so
this generator only yields ``done`` / ``error`` and kills its subprocess on exit.

SCOPE: clone (``session``) isolation ONLY — never in-place (an external CLI can't
honor the per-action permission ladder; the clone diff is the only gate). The
caller (workspace_router turn dispatch) enforces this.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import AsyncGenerator

from ..openclaw_client import OpenClawEvent
from .isolation import SESSION_WORKSPACE_ROOT, WorkspaceIsolationManager

logger = logging.getLogger(__name__)

_CONTAINER = os.getenv("HARVIS_OPENCODE_CONTAINER", "harvis-opencode")
_DEFAULT_MODEL = os.getenv("HARVIS_OPENCODE_DEFAULT_MODEL", "qwen3:4b")
_TIMEOUT_S = int(os.getenv("HARVIS_OPENCODE_TIMEOUT_S", "900") or "900")
_STREAM_LIMIT = 8 * 1024 * 1024  # OpenCode JSON lines can carry large file contents


def _under_session_root(path: str) -> bool:
    """Path-safety: the workspace must resolve UNDER SESSION_WORKSPACE_ROOT so a
    malformed DB row can't point the exec at an arbitrary host path."""
    try:
        root = Path(SESSION_WORKSPACE_ROOT).resolve()
        target = Path(path).resolve()
        return target == root or str(target).startswith(str(root) + os.sep)
    except Exception:
        return False


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
) -> AsyncGenerator[OpenClawEvent, None]:
    from ..workspace_router import (
        _db_create_run,
        _db_save_artifact,
        _db_set_run_repo,
        _db_set_run_source,
    )

    sess = session_id or f"ws-{parent_workspace_id}"
    label = "OpenCode"
    run_id = parent_workspace_id
    started = time.monotonic()

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(etype, {**data, "agent_label": label, "model": model_name})
        e.run_id = run_id
        e.agent_label = label
        return e

    await _db_create_run(pool, parent_workspace_id, user_id, sess, task_brief)
    await _db_set_run_source(pool, parent_workspace_id, "vibecode")
    if repo_path:
        await _db_set_run_repo(pool, parent_workspace_id, repo_path)

    # Guardrails: workspace must exist + be a real session clone under the root.
    if not workspace_path or not _under_session_root(workspace_path):
        yield root_ev("error", {
            "message": "OpenCode engine: invalid session workspace.",
            "fix_hint": "The session's working clone is missing or out of bounds — recreate the session.",
        })
        return
    if engine != "opencode":
        yield root_ev("error", {
            "message": f"Unknown engine '{engine}'.",
            "fix_hint": "Only 'opencode' is supported in this release.",
        })
        return

    model = (model_name or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    model_id = model if model.startswith("ollama/") else f"ollama/{model}"

    iso = WorkspaceIsolationManager(
        root=SESSION_WORKSPACE_ROOT,
        isolation_mode="session",
        repo_config={"base_sha": base_sha, "repo_path": repo_path},
    )

    yield root_ev("log", {
        "message": f"Launching OpenCode ({model_id}) on {os.path.basename(workspace_path)}…"
    })

    # `--dir <clone>` is a UNIQUE per-run marker (each session has a distinct clone),
    # so `pkill -f <clone>` on the sidecar kills ONLY this run — safe with concurrent
    # users. `-w` sets cwd inside the (shared-volume) sidecar; `-u 1001` matches the
    # artifact_data owner so OpenCode can write the clone.
    cmd = [
        "docker", "exec", "-u", "1001", "-w", workspace_path, _CONTAINER,
        "opencode", "run", task_brief,
        "--model", model_id,
        "--format", "json",
        "--dangerously-skip-permissions",
        "--dir", workspace_path,
    ]

    proc: asyncio.subprocess.Process | None = None
    stderr_buf: list[str] = []
    tool_calls = 0
    final_text_parts: list[str] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
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
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT,
            )
        except Exception as exc:
            yield root_ev("error", {
                "message": f"Could not start the OpenCode engine: {exc}",
                "fix_hint": "Is the harvis-opencode sidecar running? `docker compose up -d opencode`.",
            })
            return

        stderr_task = asyncio.create_task(_drain_stderr(proc))
        deadline = time.monotonic() + _TIMEOUT_S

        # Read OpenCode's NDJSON stdout line-by-line. readline() buffers partial lines
        # across reads; the large `limit` avoids LimitOverrunError on big content lines.
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
                break  # EOF
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue

            # Defensive mapping (don't assume OpenCode's shape == OpenClaw): map only
            # recognized fields; EVERYTHING else (unknown type, non-JSON) → a log event.
            try:
                obj = json.loads(line)
            except Exception:
                yield root_ev("log", {"message": line[:500]})
                continue
            etype = obj.get("type")
            part = obj.get("part") or {}
            if etype == "text":
                txt = part.get("text")
                if txt:
                    final_text_parts.append(str(txt))
                    yield root_ev("token", {"content": str(txt)})
            elif etype == "tool_use":
                tool = part.get("tool") or "tool"
                state = part.get("state") or {}
                tool_calls += 1
                yield root_ev("tool_call", {"tool": tool, "args": state.get("input") or {}})
                status = state.get("status")
                if status in ("completed", "error"):
                    yield root_ev("tool_result", {
                        "output": str(state.get("output") or "")[:2000],
                        "success": status == "completed",
                    })
            elif etype == "step_finish":
                tok = part.get("tokens") or {}
                try:
                    usage["prompt_tokens"] += int(tok.get("input") or 0)
                    usage["completion_tokens"] += int(tok.get("output") or 0)
                except Exception:
                    pass
            # step_start / other → drop (not interesting to the UI)

        rc = await asyncio.wait_for(proc.wait(), timeout=10) if not timed_out else None
        stderr_task.cancel()
    finally:
        # Best-effort, synchronous kill (robust during CancelledError unwinding):
        # local docker-exec child + the REMOTE opencode for THIS clone only.
        try:
            if proc is not None and proc.returncode is None:
                proc.kill()
        except Exception:
            pass
        try:
            subprocess.run(
                ["docker", "exec", _CONTAINER, "pkill", "-f", workspace_path],
                timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    # Collect the cumulative diff (working tree vs base_sha) — even on a non-zero exit.
    try:
        diff = await iso.collect_diff(workspace_path)
        files = await iso.collect_changed_files(workspace_path)
        contents = await iso.collect_file_contents(workspace_path)
    except Exception as exc:
        logger.warning("engine_adapter: diff collection failed: %s", exc, exc_info=True)
        diff, files, contents = "", [], {}

    repo_name = os.path.basename((repo_path or workspace_path).rstrip("/")) or "session"
    await _db_save_artifact(
        pool, parent_workspace_id, "diff",
        path=f"OpenCode · {repo_name}", content=diff or "(no changes)",
    )
    for rel, content in contents.items():
        await _db_save_artifact(
            pool, parent_workspace_id, "file", path=rel, content=(content or "")[:200_000],
        )
    await _db_save_artifact(
        pool, parent_workspace_id, "changed_files", content="\n".join(files),
    )

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspace_runs SET prompt_tokens=$2, completion_tokens=$3, "
                "model_name=COALESCE(NULLIF($4,''), model_name) WHERE id=$1",
                parent_workspace_id, usage["prompt_tokens"], usage["completion_tokens"], model_id,
            )
    except Exception as exc:
        logger.warning("engine_adapter: token usage persist failed: %s", exc)

    n = len(files)
    logger.info(
        "engine_adapter: %s done (engine=%s model=%s, %d tool_calls, %d files, %.1fs)",
        parent_workspace_id, engine, model_id, tool_calls, n, time.monotonic() - started,
    )

    # A hard timeout, or a non-zero exit with zero changes, is a real failure.
    if timed_out:
        yield root_ev("error", {
            "message": f"OpenCode timed out after {_TIMEOUT_S}s.",
            "fix_hint": "Try a smaller task or a faster local model.",
        })
        return
    if n == 0 and stderr_buf:
        yield root_ev("error", {
            "message": "OpenCode made no changes. " + (stderr_buf[-1][:300] if stderr_buf else ""),
            "fix_hint": "Check the model is installed in Ollama and the task is actionable.",
        })
        return

    wrap = " ".join(final_text_parts).strip()
    summary = (wrap[:1500] if wrap else "") or f"OpenCode finished — {n} file(s) changed."
    yield root_ev("done", {"summary": summary, "changed_files": files})
