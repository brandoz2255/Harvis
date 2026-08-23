"""External code-engine adapter (Phase E1 + E2) — run an EXTERNAL coding CLI against a
VibeCode session clone and stream its work back as the standard ``OpenClawEvent`` stream
+ a git diff, alongside the native ``vibecode-turn`` runner.

Engines (``engine=…``):
- ``opencode``    — local Ollama, no auth (E1).
- ``codex``       — OpenAI's Codex CLI, CLOUD GPT models, per-user OpenAI key (E2).
- ``claude-code`` — Anthropic's Claude Code CLI, CLOUD Claude models, per-user key (E2).
- ``kimi-code``   — the SAME Claude Code CLI + sidecar with ANTHROPIC_BASE_URL repointed at
  the Kimi Code membership API, per-user verified membership key.

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
    # Kimi Code MEMBERSHIP runs the SAME sidecar and the SAME `claude` CLI as claude-code —
    # only ANTHROPIC_BASE_URL and the credential differ (see _build_kimi_code_command).
    "kimi-code": os.getenv("HARVIS_CLAUDE_CODE_CONTAINER", "harvis-claude-code"),
    # Phase E4B: the REAL NousResearch Hermes Agent app (full runtime: tools, memory,
    # skills, SOUL, providers). Local Ollama, no cloud key. Plain-text CLI output.
    "hermes-agent": os.getenv("HARVIS_HERMES_AGENT_CONTAINER", "harvis-hermes-agent"),
}
_CLOUD_ENGINES = {"codex", "claude-code", "kimi-code"}
# The compose SERVICE that provides each engine's sidecar. Not derivable from the engine
# name: `kimi-code` has no service of its own — it runs inside the `claude-code` sidecar
# (see _CONTAINERS above), so telling an operator to `up -d kimi-code` sends them after a
# service that does not exist. All of these live behind the `engines` profile, which a
# default install deliberately leaves out.
_ENGINE_SERVICE = {
    "opencode": "opencode",
    "codex": "codex",
    "claude-code": "claude-code",
    "kimi-code": "claude-code",
    "hermes-agent": "hermes-agent",
}


def _engine_install_hint(engine: str, container: str) -> str:
    """The exact command that makes `engine` runnable, naming the real service."""
    svc = _ENGINE_SERVICE.get(engine, engine)
    # "isn't running" would be wrong on a fresh clone: engine services BUILD their image
    # rather than pulling one, so the first `up -d` is a build (~1 GB, a couple of minutes),
    # not a start. Saying "running" sends the operator looking for a stopped container.
    return (
        f"The {container} sidecar isn't available on this Harvis. Engines ship as an opt-in "
        f"pack: run `docker compose --profile engines up -d {svc}` from the Harvis repo root, "
        f"on the Docker host — the first run builds the image, so allow a couple of minutes."
    )


def _missing_sidecar(stderr_lines: list[str], container: str) -> bool:
    """Did `docker exec` fail because the sidecar container isn't there?

    This has to be sniffed out of stderr rather than caught as an exception: the docker
    CLI itself launches fine, so create_subprocess_exec succeeds. Docker then prints
    "Error response from daemon: No such container: <name>" and exits 125 with an EMPTY
    stdout — which reads to a naive stream loop exactly like a model that had nothing
    to say.
    """
    blob = " ".join(stderr_lines[-10:]).lower()
    return "no such container" in blob or f"no such container: {container}".lower() in blob
# Engines whose stdout is PLAIN TEXT (not JSON) — the loop maps each line to a `log`
# event and uses the output tail as the final summary; the git diff is the authority.
_TEXT_ENGINES = {"hermes-agent"}
_ENGINE_LABEL = {"opencode": "OpenCode", "codex": "Codex", "claude-code": "Claude Code",
                 "hermes-agent": "Hermes Agent", "kimi-code": "Kimi Code"}
# Cloud engines default to the CLI's own default model when these are empty.
_CODEX_DEFAULT_MODEL = os.getenv("HARVIS_CODEX_DEFAULT_MODEL", "")
_CLAUDE_DEFAULT_MODEL = os.getenv("HARVIS_CLAUDE_DEFAULT_MODEL", "")
# Phase E4B Hermes Agent: local-Ollama provider + per-user profile homes (memory/SOUL).
_HERMES_HOMES_ROOT = os.getenv("HARVIS_HERMES_HOMES_ROOT", "/data/hermes-homes")
_HERMES_OLLAMA_URL = os.getenv("HARVIS_HERMES_OLLAMA_URL") or (
    (
        os.getenv("HARVIS_LLM_BASE_URL")
        or os.getenv("OLLAMA_URL")
        or "http://host.docker.internal:11434"
    ).rstrip("/")
    + "/v1"
)
# E4B's own default model (decoupled from E4-native's HARVIS_HERMES_DEFAULT_MODEL): the
# Hermes Agent app runs any local Ollama model — a capable coder (qwen3:4b) is the default.
_HERMES_DEFAULT_MODEL = os.getenv("HARVIS_HERMES_AGENT_DEFAULT_MODEL", "qwen3:4b")
# A run dies from SILENCE, not from length. This used to be a total-run deadline: a
# healthy build that was still streaming tool calls got killed at 15 minutes purely for
# taking a while, and the user saw "timed out" on work that was going fine. What actually
# identifies a wedged engine is producing no output at all, so the clock below resets on
# every line the engine emits.
#
# HARVIS_OPENCODE_TIMEOUT_S is still read so existing deployments keep a knob that means
# "how long before we give up on a quiet engine" — its original intent.
_IDLE_TIMEOUT_S = int(
    os.getenv("HARVIS_ENGINE_IDLE_TIMEOUT_S", "")
    or os.getenv("HARVIS_OPENCODE_TIMEOUT_S", "")
    or 600
)
# Absolute backstop. An engine stuck in a chatty loop never goes idle, so the watchdog
# alone can't stop it. This is the seatbelt, not the speed limit — keep it generous.
_MAX_RUN_S = int(os.getenv("HARVIS_ENGINE_MAX_RUN_S", "") or 14400)
_STREAM_LIMIT = 8 * 1024 * 1024  # engine JSON lines can carry large file contents


def _timeout_event(label: str, kind: str) -> dict:
    """Say which clock ran out. "Took too long" and "stopped responding" are different
    failures with different fixes, and reporting both as the same one sent people off
    shrinking tasks that were never too big."""
    if kind == "max":
        return {
            "message": f"{label} hit the {_MAX_RUN_S}s maximum run time and was stopped.",
            "fix_hint": "The engine kept producing output but never finished — narrow the "
                        "task, or raise HARVIS_ENGINE_MAX_RUN_S.",
        }
    return {
        "message": f"{label} stopped responding — no output for {_IDLE_TIMEOUT_S}s.",
        "fix_hint": "The engine went silent rather than running long. Check the sidecar is "
                    "healthy, or raise HARVIS_ENGINE_IDLE_TIMEOUT_S.",
    }


def _under_session_root(path: str) -> bool:
    """Path-safety: the workspace must resolve UNDER SESSION_WORKSPACE_ROOT so a
    malformed DB row can't point the exec at an arbitrary host path."""
    try:
        root = Path(SESSION_WORKSPACE_ROOT).resolve()
        target = Path(path).resolve()
        return target == root or str(target).startswith(str(root) + os.sep)
    except Exception:
        return False


async def _stage_attachments(
    task_brief: str,
    attachments: Optional[list[dict]],
    workdir: str,
    owner_id: Optional[int] = None,
) -> tuple[str, str]:
    """Write the turn's attachments into `workdir` and put their REAL paths at the
    top of the brief. Returns (brief, status_line); status_line is "" when there
    was nothing to stage.

    Why this exists: an external CLI runs inside a sidecar that mounts /data/artifacts
    and nothing else — no route to the Harvis API, no uploads volume, often no curl.
    Handed only the file's URL (which is what the generic attachment block carries),
    it spends the whole run hunting for a file it can never reach and then reports
    itself blocked. Staging the bytes next to its working tree is what makes an
    attached screenshot work on EVERY engine, not just the lanes that can take a
    multimodal image part.
    """
    if not attachments or not workdir:
        return task_brief, ""
    try:
        from vision_to_code.attachments import materialize_attachments, staged_attachment_brief
    except Exception as exc:
        logger.warning("engine_adapter: attachment staging unavailable: %s", exc)
        return task_brief, ""
    try:
        staged, skipped = await materialize_attachments(
            attachments, workdir, owner_id=owner_id
        )
    except Exception as exc:
        logger.exception("engine_adapter: attachment staging failed")
        return task_brief, f"Attachments could not be staged ({exc}) — the engine will not see them."
    block = staged_attachment_brief(staged, skipped)
    if not block:
        return task_brief, ""
    names = ", ".join(str(s["name"]) for s in staged)
    status = (
        f"Staged {len(staged)} attachment{'' if len(staged) == 1 else 's'} in the workspace: {names}"
        if staged else "No attachment could be staged"
    )
    if skipped:
        # Say WHY, not just how many. A bare count sent me looking at the CLI's behaviour
        # when the real cause — the bytes lived in the other upload store — was already
        # known here and thrown away.
        status += " · could not stage: " + "; ".join(skipped)
    return block + task_brief, status


# How much prior conversation a one-shot CLI turn may carry, and how far back to look.
# The budget is characters rather than turns because one pasted stack trace can be worth
# more than ten short exchanges; oldest turns are dropped first so the most recent context
# — the part a follow-up like "make it viewable" actually refers to — always survives.
_CTX_MAX_TURNS = int(os.getenv("HARVIS_ENGINE_CTX_TURNS", "12") or "12")
_CTX_MAX_CHARS = int(os.getenv("HARVIS_ENGINE_CTX_CHARS", "12000") or "12000")
_CTX_MAX_PER_MSG = int(os.getenv("HARVIS_ENGINE_CTX_PER_MSG", "2000") or "2000")


def _conversation_prefix(task_brief: str, chat_history: list | None) -> str:
    """Prepend the recent conversation to a one-shot CLI prompt.

    `claude -p` starts with an empty head every turn, so without this the brief is the
    ONLY thing the model ever sees. That is why a follow-up that refers to the previous
    turn — "make it viewable", "now add a dark mode", "fix the second one" — arrived as a
    sentence about nothing and the model asked what the user meant. The Kimi and Ollama
    lanes already build the same block (`kimi_workspace._build_context_message`); this
    lane was the outlier, not the design.

    The trailing user turn is dropped when it is the brief, so the ask is not stated twice
    (`_resolve_task_brief` usually promotes exactly that message into the brief).
    """
    msgs = [
        m for m in (chat_history or [])
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m["content"].strip()
    ]
    brief_head = task_brief.strip()[:200]
    while msgs and msgs[-1]["role"] == "user" and msgs[-1]["content"].strip()[:200] == brief_head:
        msgs.pop()
    if not msgs:
        return task_brief

    lines: list[str] = []
    used = 0
    for m in reversed(msgs[-_CTX_MAX_TURNS:]):
        body = m["content"].strip()
        if len(body) > _CTX_MAX_PER_MSG:
            body = body[:_CTX_MAX_PER_MSG] + " …[truncated]"
        line = f"{m['role'].upper()}: {body}"
        if used + len(line) > _CTX_MAX_CHARS:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return task_brief
    lines.reverse()

    return (
        "[RECENT CONVERSATION — earlier turns in this chat, for reference only]\n"
        + "\n".join(lines)
        + "\n\n[YOUR TASK — this is what to do now]\n"
        + task_brief
    )


def _sidecar_mcp_args(user_id, *, artifact_run_id=None, **context) -> list[str]:
    """One `--mcp-config` carrying every Harvis MCP server this run should see.

    A single config holds many servers, so the CAD tools and the brokered artifact
    door travel together in one argument rather than fighting over the flag — the
    CLI keeps only the last `--mcp-config` it is given.

    ``artifact_run_id`` opens :mod:`artifact_mcp` for that run. Pass it wherever the
    sidecar runs with ``Write`` withheld, because otherwise a model that composed a
    finished HTML page has no way to hand it over and the run ends with nothing to
    preview. Omit it and the tool is not registered at all, which is right for a lane
    that already writes into a real workspace clone.
    """
    servers: dict = {}
    try:
        from owui_compat.cad_mcp import sidecar_mcp_config
        cfg = sidecar_mcp_config(user_id, **context)
        if cfg:
            servers.update(cfg.get("mcpServers") or {})
    except Exception:
        # A run that could have had CAD and did not is worth far less than a run that
        # refused to start, so this never raises into the launch path.
        logger.debug("cad mcp config unavailable for this run", exc_info=True)

    try:
        # Whatever this user connected themselves — Higgsfield, GitHub, an MCP
        # server they added by URL. Without this a sidecar sees only the two
        # servers Harvis authors, and a model asked to use a connector correctly
        # reports that it has no such tool.
        from plugins.mcp.sidecar_bridge import sidecar_bridge_config
        # The run id rides along so a connector's image can be saved against
        # THIS run — without it the bridge can fetch the bytes but has nowhere
        # to put them, and the model gets back a Docker-only URL.
        cfg = sidecar_bridge_config(user_id, run_id=artifact_run_id or "")
        if cfg:
            servers.update(cfg)
    except Exception:
        logger.debug("connector mcp config unavailable for this run", exc_info=True)

    if artifact_run_id:
        try:
            from .artifact_mcp import sidecar_artifact_mcp_server
            entry = sidecar_artifact_mcp_server(user_id, artifact_run_id)
            if entry:
                servers.update(entry)
        except Exception:
            logger.debug("artifact mcp config unavailable for this run", exc_info=True)

    return ["--mcp-config", json.dumps({"mcpServers": servers})] if servers else []


def _artifact_delivery_note(mcp_args: list[str]) -> list[str]:
    """`--append-system-prompt` describing the delivery door, or nothing at all.

    Registering the tool is not the same as the model knowing it exists. Without this
    note the first move is `Write`, which the auto lane refuses, and the tool is only
    found by searching afterwards — a wasted turn on every run, observed live.
    """
    try:
        from .artifact_mcp import SERVER_NAME, TOOL_NAME
    except Exception:
        return []
    if not any(SERVER_NAME in arg for arg in mcp_args):
        return []
    return ["--append-system-prompt", (
        "File delivery: this run has no durable filesystem, and `Write` is refused. "
        f"Hand a finished file back by calling `mcp__{SERVER_NAME}__{TOOL_NAME}` with a "
        "relative path, the complete content, and its media type. A file named "
        "`index.html` becomes a preview the user can open, so inline all CSS and "
        "JavaScript into that single file rather than delivering siblings."
    )]


def _cad_mcp_args(user_id, **context) -> list[str]:
    """`--mcp-config` for the CAD tools, or nothing at all.

    A Claude Code sidecar is not part of a Harvis chat turn, so it never receives the
    native tool definitions the chat lanes hand their models. MCP is the only door it
    has, and without these two arguments the CAD tools do not exist for it — which is
    exactly what was true until now.

    ``context`` is the server-side truth the sidecar cannot know and the model may not
    claim — the conversation, the user's own words, which model is driving. See
    :func:`owui_compat.cad_mcp.sidecar_mcp_config`. A launch site that has none of it
    passes none, which is the behaviour every caller had before.

    Deliberately NOT `--strict-mcp-config`: that flag ignores every other MCP server
    the sidecar is configured with, so adding CAD would silently take away whatever
    the user had already connected. Adding one server should add one server.
    """
    return _sidecar_mcp_args(user_id, **context)


def _cad_write_tool_names() -> list[str]:
    """The CAD tools that change something, spelled the way the CLI names them.

    Derived from the registry rather than listed here, so a tool added later is
    withheld from read-only runs by default instead of being quietly allowed —
    the failure that a hardcoded list produces is the dangerous direction.
    """
    try:
        from owui_compat import cad_tools
        return [f"mcp__harvis-cad__{n}" for n in cad_tools.TOOL_NAMES
                if n not in cad_tools.READ_ONLY_TOOLS]
    except Exception:
        logger.debug("cad tool registry unavailable", exc_info=True)
        return []


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
    cmd += _cad_mcp_args(user_id)
    if _CLAUDE_DEFAULT_MODEL:
        cmd += ["--model", _CLAUDE_DEFAULT_MODEL]
    return cmd, (_CLAUDE_DEFAULT_MODEL or "claude/default")


def _build_kimi_code_command(container, workspace_path, task_brief, model_name, api_key, user_id=0, auth_mode="api_key"):
    """Kimi Code MEMBERSHIP against the session clone: the REAL Claude Code CLI, in the same
    sidecar as claude-code, with its base URL repointed at Kimi Code and the membership key
    injected. Running the genuine CLI rather than a proxy that imitates it is deliberate —
    Kimi Code's terms require third-party coding tools to keep their true client identity.

    Every model slot is pinned, not just ANTHROPIC_MODEL: Claude Code resolves its own
    aliases internally (a Sonnet-tier model for the main loop, Haiku-tier for cheap side
    calls, a separate subagent model for Task), and each of those would otherwise request an
    ANTHROPIC model id Kimi Code does not serve — so the run fails PARTWAY THROUGH with a
    model-not-found, long after the first token made it look healthy. Mirrors the chat lane's
    env block in run_claude_chat_workspace; keep the two in agreement."""
    from owui_compat.engine_auth import (
        KIMI_CODE_BASE_URL, KIMI_CODE_CONTEXT_TOKENS, KIMI_CODE_DEFAULT_MODEL, KIMI_CODE_MODELS,
    )
    model = (model_name or "").split("/", 1)[-1].strip()  # strip the 'kimi-code/' catalog prefix
    if model not in KIMI_CODE_MODELS:
        model = KIMI_CODE_DEFAULT_MODEL
    cred = [
        "-e", f"ANTHROPIC_BASE_URL={KIMI_CODE_BASE_URL}",
        "-e", f"ANTHROPIC_API_KEY={api_key or ''}",
        "-e", f"ANTHROPIC_MODEL={model}",
        "-e", f"ANTHROPIC_DEFAULT_OPUS_MODEL={model}",
        "-e", f"ANTHROPIC_DEFAULT_SONNET_MODEL={model}",
        "-e", f"ANTHROPIC_DEFAULT_HAIKU_MODEL={model}",
        "-e", f"CLAUDE_CODE_SUBAGENT_MODEL={model}",
        # Kimi Code is API-key only, so simple/bare mode (which reads auth STRICTLY from
        # ANTHROPIC_API_KEY and ignores CLAUDE_CODE_OAUTH_TOKEN) is correct here — unlike
        # claude-code's subscription mode, which must clear it.
        "-e", "CLAUDE_CODE_SIMPLE=1",
    ]
    ctx = KIMI_CODE_CONTEXT_TOKENS.get(model)
    if ctx:
        cred += ["-e", f"CLAUDE_CODE_MAX_CONTEXT_TOKENS={ctx}",
                 "-e", f"CLAUDE_CODE_AUTO_COMPACT_WINDOW={ctx}"]
    cmd = ["docker", "exec", *cred,
           "-u", "1001", "-w", workspace_path, container,
           "claude", "-p", task_brief,
           "--output-format", "stream-json", "--verbose",
           "--add-dir", workspace_path, "--dangerously-skip-permissions",
           "--model", model]
    # Same CLI, same door: Kimi Code reads MCP exactly as claude-code does, and the
    # tools are Harvis's, not Anthropic's — nothing about them is provider-specific.
    cmd += _cad_mcp_args(user_id)
    return cmd, f"kimi-code/{model}"


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
    "kimi-code": _build_kimi_code_command,
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
        # `is_error` is checked FIRST because `subtype` lies: a 401 comes back as
        # {"subtype":"success","is_error":true,"api_error_status":401,"result":"Failed to
        # authenticate…"}. Testing subtype first sent that straight down the success path and
        # rendered the auth failure as the model's answer.
        if obj.get("is_error"):
            yield root_ev("log", {"message": "Claude: " + str(obj.get("result") or obj.get("subtype") or "error")[:300]})
        elif obj.get("subtype") == "success" and obj.get("result"):
            # `final` marks this as the CLI's own answer, not one more streamed chunk. The
            # assistant blocks above already carried this exact text, so a caller that
            # appends it prints the answer twice with the between-tool narration in front.
            yield root_ev("token", {"content": str(obj["result"]), "final": True})
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
    # Same CLI, same `--output-format stream-json` shape → the same mapper.
    "kimi-code": _map_claude_line,
    "hermes-agent": _map_hermes_line,
}


def _extract_usage(engine: str, obj: dict):
    """Best-effort (prompt_tokens, completion_tokens) from a streamed engine line — so the Build
    usage meter has real token counts for the cloud engines. Claude's `result` line carries
    `usage`; others may not (then None → no capture, free/local engines just show 0). Cumulative
    cache-read/creation input tokens count toward the prompt (they bill as input)."""
    try:
        # kimi-code runs the same CLI, so its `result` line carries the same usage shape.
        if engine in ("claude-code", "kimi-code") and obj.get("type") == "result":
            u = obj.get("usage") or {}
            p = (int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
                 + int(u.get("cache_creation_input_tokens") or 0))
            c = int(u.get("output_tokens") or 0)
            if p or c:
                return p, c
        u = obj.get("usage")  # generic fallback (codex/opencode if they emit it)
        if isinstance(u, dict):
            p = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
            c = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
            if p or c:
                return p, c
    except Exception:
        pass
    return None


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
    chat_history: list,  # prior turns — the clone is file memory, this is intent memory.
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
    attachments: Optional[list[dict]] = None,  # staged into the clone so the CLI can READ them
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
        yield root_ev("error", {
            "message": f"Unknown engine '{engine}'.",
            "fix_hint": "Supported: " + ", ".join(sorted(_BUILDERS)) + ".",
        })
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

    # Attachments become REAL FILES in the clone before the CLI starts — the sidecar
    # cannot fetch a URL, so bytes-on-disk is the only delivery that works here.
    task_brief, _stage_status = await _stage_attachments(
        task_brief, attachments, workspace_path, user_id or None
    )
    if _stage_status:
        yield root_ev("log", {"message": _stage_status})

    # The clone carries what the files look like; only the transcript carries what the user
    # meant. A follow-up that names neither a file nor a symbol ("make it viewable", "now do
    # the other one") is unreadable without it, so the prompt carries both.
    task_brief = _conversation_prefix(task_brief, chat_history)

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
    # See the note in run_claude_chat_workspace: a rejected credential is reported on STDOUT
    # as a result line, leaving stderr empty, so stderr alone can't tell a failed run apart
    # from a successful one that touched no files.
    cli_error: str = ""
    cli_error_status: int = 0
    tool_calls = 0
    usage_p = 0  # captured input tokens (cloud engines: the result line's `usage`) — for the meter
    usage_c = 0  # captured output tokens
    final_text_parts: list[str] = []
    streamed_text = False
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
                "fix_hint": _engine_install_hint(engine, container),
            })
            return

        stderr_task = asyncio.create_task(_drain_stderr(proc))
        hard_deadline = time.monotonic() + _MAX_RUN_S
        idle_deadline = time.monotonic() + _IDLE_TIMEOUT_S
        while True:
            now = time.monotonic()
            hit_hard = hard_deadline <= idle_deadline
            remaining = (hard_deadline if hit_hard else idle_deadline) - now
            if remaining <= 0:
                timed_out = "max" if hit_hard else "idle"
                break
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)  # type: ignore[union-attr]
            except asyncio.TimeoutError:
                continue
            if not raw:
                break
            # The engine is alive: push the idle deadline out. The hard ceiling does not move.
            idle_deadline = time.monotonic() + _IDLE_TIMEOUT_S
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
            _u = _extract_usage(engine, obj)
            if _u:
                usage_p, usage_c = _u
            if obj.get("type") == "result" and obj.get("is_error"):
                cli_error = str(obj.get("result") or "").strip()
                try:
                    cli_error_status = int(obj.get("api_error_status") or 0)
                except Exception:
                    cli_error_status = 0
            try:
                for ev in mapper(obj, root_ev):
                    if ev.type == "tool_call":
                        tool_calls += 1
                    elif ev.type == "token":
                        text = str((ev.data or {}).get("content") or "")
                        if (ev.data or {}).get("final"):
                            final_text_parts = [text]
                            if streamed_text:
                                continue  # already shown live; don't render it a second time
                        else:
                            streamed_text = True
                            final_text_parts.append(text)
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
                "UPDATE workspace_runs SET model_name=COALESCE(NULLIF($2,''), model_name), "
                "prompt_tokens=COALESCE(NULLIF($3,0), prompt_tokens), "
                "completion_tokens=COALESCE(NULLIF($4,0), completion_tokens) WHERE id=$1",
                parent_workspace_id, model_id, int(usage_p or 0), int(usage_c or 0),
            )
    except Exception:
        pass

    n = len(files)
    logger.info("engine_adapter: %s done (engine=%s model=%s, %d tool_calls, %d files, %.1fs)",
                parent_workspace_id, engine, model_id, tool_calls, n, time.monotonic() - started)

    if timed_out:
        yield root_ev("error", _timeout_event(label, timed_out))
        return
    # `n == 0` alone can't distinguish the three ways a run ends with nothing changed:
    # the engine ran and had nothing to do (fine), the sidecar was never there (install gap),
    # or the credential was rejected (auth gap). Gating on stderr only caught the second —
    # a 401 arrives on STDOUT as a result line, so stderr is empty and the run used to fall
    # through to `done — 0 file(s) changed`. The exit code separates them.
    # A non-zero exit is only FATAL when nothing came of the run. If the engine changed files
    # before dying, the diff is real and already saved — dropping it to show an error would
    # lose the user's work, so that case surfaces as a warning alongside the normal result.
    rc = proc.returncode if proc is not None else None
    if rc not in (0, None) and n > 0 and not cli_error:
        yield root_ev("log", {
            "message": f"{label} exited with code {rc} after changing {n} file(s) — "
                       f"review the diff before applying."
        })
    elif cli_error or rc not in (0, None) or (n == 0 and stderr_buf):
        if _missing_sidecar(stderr_buf, container):
            yield root_ev("error", {
                "message": f"{label} isn't installed on this Harvis.",
                "fix_hint": _engine_install_hint(engine, container),
            })
            return
        if cli_error_status in (401, 403):
            yield root_ev("error", {
                "message": f"{label} rejected the credential: {cli_error[:300]}",
                "fix_hint": f"Re-verify the {label} credential in Integrations.",
            })
            return
        detail = cli_error or (stderr_buf[-1] if stderr_buf else f"exit code {rc}")
        yield root_ev("error", {
            "message": f"{label} made no changes. {detail[:300]}",
            "fix_hint": "Check the engine is connected/authenticated and the task is actionable.",
        })
        return

    wrap = " ".join(p for p in final_text_parts if p).strip()
    if not wrap and is_text_engine and text_tail:
        # Hermes `-z` prints the final response as plain text — use the output tail.
        wrap = "\n".join(text_tail[-8:]).strip()
    summary = (wrap[:1500] if wrap else "") or f"{label} finished — {n} file(s) changed."
    yield root_ev("done", {"summary": summary, "changed_files": files})


# Baseline marker for the per-run artifact sweep. Hidden so it stays out of the model's way,
# and a fixed name so it never accumulates: each run re-touches it, and `find -newer` on a file
# never matches that file itself.
_RUN_MARK = ".harvis-runmark"


class _NoBaseline(Exception):
    """No artifact baseline for this run — capture nothing instead of guessing."""


async def run_claude_chat_workspace(
    task_brief: str,
    chat_history: list,  # `claude -p` is one-shot, so prior turns ride in the prompt.
    *,
    model_name: str = "",
    pool=None,
    parent_workspace_id: str = "",
    user_id: int = 0,
    session_id: str = "",
    launch_mode: str = "user",
    engine: str = "claude-code",
    attachments: Optional[list[dict]] = None,  # staged into the scratch workdir so the CLI can READ them
) -> AsyncGenerator[OpenClawEvent, None]:
    """Run a CHAT workspace task through a cloud model's OWN agentic loop — ``claude -p``
    with its built-in tools (web_search, exec, file ops). No repo clone: a scratch workdir
    under the shared artifact volume. This makes the workspace a universal tool runtime that
    the model drives, using the user's VERIFIED per-user credential. Zero GPU — runs in the
    harvis-claude-code sidecar.

    ``engine`` selects WHOSE model answers, not which loop runs:
      * ``claude-code`` — Anthropic, via subscription OAuth token or API key.
      * ``kimi-code``   — Kimi Code membership, via its Anthropic-compatible Messages API.
        Same sidecar, same CLI, same tool loop; only ANTHROPIC_BASE_URL and the credential
        differ. Running the REAL CLI (rather than a proxy that imitates it) is deliberate:
        Kimi Code's terms require third-party coding tools to keep their true client identity,
        so Harvis only injects the documented env vars and lets the CLI speak for itself."""
    from ..workspace_router import _db_create_run, _db_save_artifact
    from .isolation import _is_secret_artifact
    try:
        from owui_compat.engine_auth import get_verified_engine_auth
    except Exception:
        get_verified_engine_auth = None  # type: ignore

    is_kimi = engine == "kimi-code"
    label = "Kimi Code" if is_kimi else "Claude"
    run_id = parent_workspace_id
    container = _CONTAINERS.get("claude-code", "harvis-claude-code")
    sess = session_id or f"ws-{parent_workspace_id}"

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(etype, {**data, "agent_label": label, "model": model_name})
        e.run_id = run_id
        e.agent_label = label
        return e

    await _db_create_run(pool, parent_workspace_id, user_id, sess, task_brief)

    auth = None
    if get_verified_engine_auth is not None:
        try:
            auth = await get_verified_engine_auth(pool, user_id, engine)
        except Exception:
            auth = None
    if not auth:
        yield root_ev("error", {
            "message": f"{label} isn't connected.",
            "fix_hint": (
                "Connect + verify your Kimi Code Console key in Integrations."
                if is_kimi else
                "Connect + verify your Claude subscription or API key in Integrations."
            ),
        })
        return
    secret, auth_mode = auth

    # Persistent per-user sandbox on the artifact volume (notes.md survives turns).
    # Fall back to a per-run dir only when we have no user id.
    if user_id:
        workdir = f"/data/artifacts/harvis-chat/u{int(user_id)}"
    else:
        workdir = f"/data/artifacts/claude-chat/{run_id or 'run'}"
    try:
        mk = await asyncio.create_subprocess_exec(
            "docker", "exec", "-u", "1001", container, "mkdir", "-p", workdir,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(mk.wait(), timeout=10)
        try:
            from owui_compat.chat_files import seed_sandbox
            await seed_sandbox(workdir)
        except Exception:
            logger.debug("claude chat sandbox seed skipped", exc_info=True)
    except Exception:
        pass

    # Same reason as the Build lane: nothing hands the CLI the bytes, so an attached
    # screenshot only exists for it if we write it into the workdir. (The sidecar CAN
    # reach the Harvis API over the Docker network — that is how `_cad_mcp_args` works
    # — but it has no route to a stored attachment and no credential of its own.)
    task_brief, _stage_status = await _stage_attachments(
        task_brief, attachments, workdir, user_id or None
    )
    if _stage_status:
        yield root_ev("log", {"message": _stage_status})

    # Baseline for the end-of-run artifact sweep. The workdir is PERSISTENT per user, so a
    # bare `find` there returns every file the sandbox has ever held — and the narrator then
    # tells the user this run "created" eleven files it never touched. Touching a marker now
    # gives the sweep something to compare against; `find -newer` on it returns only what
    # this run actually wrote. It goes AFTER attachment staging on purpose: a file the user
    # attached is an input, not something the run produced.
    _mark_ok = False
    try:
        _mk2 = await asyncio.create_subprocess_exec(
            "docker", "exec", "-u", "1001", container, "touch", f"{workdir}/{_RUN_MARK}",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        _mark_ok = (await asyncio.wait_for(_mk2.wait(), timeout=10)) == 0
    except Exception:
        _mark_ok = False
    if not _mark_ok:
        logger.warning(
            "claude chat workspace: could not set the artifact baseline in %s — "
            "skipping file capture rather than reporting stale sandbox files as new",
            workdir,
        )

    # The prompt carries the recent conversation, not just this turn's ask. Staging runs
    # first so an attachment note stays attached to the task, not buried in the transcript.
    task_brief = _conversation_prefix(task_brief, chat_history)

    claude_model = (model_name or "").split("/", 1)[-1].strip()  # strip 'anthropic/'|'kimi/' prefix
    if is_kimi:
        from owui_compat.engine_auth import (
            KIMI_CODE_BASE_URL, KIMI_CODE_DEFAULT_MODEL, KIMI_CODE_CONTEXT_TOKENS, KIMI_CODE_MODELS,
        )
        if claude_model not in KIMI_CODE_MODELS:
            claude_model = KIMI_CODE_DEFAULT_MODEL
        # Point the real CLI at Kimi Code and pin EVERY model slot to the chosen Kimi model.
        # Claude Code resolves its own aliases internally (sonnet for the main loop, haiku for
        # cheap side calls, a subagent model for Task) — each of those would otherwise request
        # an Anthropic model id that Kimi Code does not serve, so the run would fail partway
        # through with a model-not-found rather than at the first token.
        cred = [
            "-e", f"ANTHROPIC_BASE_URL={KIMI_CODE_BASE_URL}",
            "-e", f"ANTHROPIC_API_KEY={secret}",
            "-e", f"ANTHROPIC_MODEL={claude_model}",
            "-e", f"ANTHROPIC_DEFAULT_OPUS_MODEL={claude_model}",
            "-e", f"ANTHROPIC_DEFAULT_SONNET_MODEL={claude_model}",
            "-e", f"ANTHROPIC_DEFAULT_HAIKU_MODEL={claude_model}",
            "-e", f"CLAUDE_CODE_SUBAGENT_MODEL={claude_model}",
            "-e", "CLAUDE_CODE_SIMPLE=1",
        ]
        ctx = KIMI_CODE_CONTEXT_TOKENS.get(claude_model)
        if ctx:
            cred += ["-e", f"CLAUDE_CODE_MAX_CONTEXT_TOKENS={ctx}",
                     "-e", f"CLAUDE_CODE_AUTO_COMPACT_WINDOW={ctx}"]
    elif auth_mode == "oauth_token":
        cred = ["-e", f"CLAUDE_CODE_OAUTH_TOKEN={secret}", "-e", "CLAUDE_CODE_SIMPLE="]
    else:
        cred = ["-e", f"ANTHROPIC_API_KEY={secret}", "-e", "CLAUDE_CODE_SIMPLE=1"]
    cmd = ["docker", "exec", "-e", f"HARVIS_RUN_ID={run_id}", *cred,
           "-u", "1001", "-w", workdir, container,
           "claude", "-p", task_brief,
           "--output-format", "stream-json", "--verbose",
           "--add-dir", workdir, "--dangerously-skip-permissions"]
    # Persistent per-user sandbox on the artifact volume. Auto/read-only still
    # withholds Write; user-initiated runs can write notes and scripts here.
    _mcp_args = _sidecar_mcp_args(user_id, artifact_run_id=parent_workspace_id)
    cmd += _mcp_args
    # Only lie about Write when this run really cannot write (auto / read-only).
    if launch_mode == "auto":
        cmd += _artifact_delivery_note(_mcp_args)
    else:
        cmd += ["--append-system-prompt", (
            "This directory persists across turns. Read SANDBOX.md. You can write files "
            "(notes.md, scripts). Run them with python3 / node / bash, then "
            "`bash harvis-check.sh`. Answer in Markdown with fenced code blocks."
        )]
    if claude_model:
        cmd += ["--model", claude_model]
    if launch_mode == "auto":
        # Phase D: an auto-escalated (NOT user-initiated) run is READ-ONLY — withhold the
        # write/exec tools from Claude's own agentic loop, mirroring the native lane's
        # offer-time withholding. Read/search tools (WebSearch, WebFetch, Read, Grep, Glob)
        # stay. NOTE: verify the exact --disallowedTools spelling against the connected
        # Claude Code CLI version; the tool NAMES are stable.
        cmd += ["--disallowedTools", "Bash", "Edit", "Write", "MultiEdit", "NotebookEdit",
                # The CAD tools obey the same rule. Reading a project or a build is fine;
                # creating a revision or taking a build slot is a write the user never
                # asked for, and it would land in their project history all the same.
                *_cad_write_tool_names()]

    yield root_ev("log", {"message": f"Connected to {label} ({claude_model or 'subscription'}) — workspace tools active…"})

    proc: asyncio.subprocess.Process | None = None
    final_text_parts: list[str] = []
    streamed_text = False
    tool_calls = 0
    timed_out = False
    stderr_buf: list[str] = []
    # The CLI's own verdict on the run, read off its `result` line. Kept separately from the
    # exit code because it carries WHY (an HTTP status, a message) where rc only carries THAT.
    cli_error: str = ""
    cli_error_status: int = 0

    async def _drain(p) -> None:
        try:
            async for raw in p.stderr:
                s = raw.decode("utf-8", "replace").rstrip()
                if s:
                    stderr_buf.append(s)
                    if len(stderr_buf) > 30:
                        del stderr_buf[: len(stderr_buf) - 30]
        except Exception:
            pass

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=_STREAM_LIMIT,
            )
        except Exception as exc:
            yield root_ev("error", {"message": f"Could not start {label}: {exc}",
                                    "fix_hint": f"Is the {container} sidecar running?"})
            return
        stderr_task = asyncio.create_task(_drain(proc))
        hard_deadline = time.monotonic() + _MAX_RUN_S
        idle_deadline = time.monotonic() + _IDLE_TIMEOUT_S
        while True:
            now = time.monotonic()
            hit_hard = hard_deadline <= idle_deadline
            remaining = (hard_deadline if hit_hard else idle_deadline) - now
            if remaining <= 0:
                timed_out = "max" if hit_hard else "idle"
                break
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                continue
            if not raw:
                break
            # The engine is alive: push the idle deadline out. The hard ceiling does not move.
            idle_deadline = time.monotonic() + _IDLE_TIMEOUT_S
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                yield root_ev("log", {"message": line[:400]})
                continue
            if obj.get("type") == "result" and obj.get("is_error"):
                cli_error = str(obj.get("result") or "").strip()
                try:
                    cli_error_status = int(obj.get("api_error_status") or 0)
                except Exception:
                    cli_error_status = 0
            try:
                for ev in _map_claude_line(obj, root_ev):
                    if ev.type == "tool_call":
                        tool_calls += 1
                    elif ev.type == "token":
                        text = str((ev.data or {}).get("content") or "")
                        if (ev.data or {}).get("final"):
                            final_text_parts = [text]
                            if streamed_text:
                                continue  # already shown live; don't render it a second time
                        else:
                            streamed_text = True
                            final_text_parts.append(text)
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
        if run_id:
            kill_run_by_marker(container, run_id)

    # Capture the files Claude wrote THIS RUN as artifacts BEFORE 'done' so the workspace
    # Artifacts tab auto-pops with a preview. Text files only, secret-named skipped, and
    # scoped by `-newer` to the baseline marker — without that scope the persistent per-user
    # sandbox hands back every file it has ever held. No baseline (the touch failed) means we
    # cannot tell this run's output from last week's, so capture nothing rather than guess.
    try:
        if not _mark_ok:
            raise _NoBaseline()
        lp = await asyncio.create_subprocess_exec(
            "docker", "exec", "-u", "1001", container, "sh", "-c",
            f"cd {workdir} 2>/dev/null && find . -type f -size -524288c "
            f"-newer ./{_RUN_MARK} 2>/dev/null | head -20",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(lp.communicate(), timeout=15)
        for rel in (r.strip().lstrip("./") for r in out.decode("utf-8", "replace").splitlines()):
            if not rel or rel == _RUN_MARK or _is_secret_artifact(rel):
                continue
            cp = await asyncio.create_subprocess_exec(
                "docker", "exec", "-u", "1001", container, "cat", f"{workdir}/{rel}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            cout, _ = await asyncio.wait_for(cp.communicate(), timeout=15)
            await _db_save_artifact(pool, parent_workspace_id, "file", path=rel,
                                    content=cout.decode("utf-8", "replace"))
    except _NoBaseline:
        pass
    except Exception as exc:
        logger.warning("claude chat workspace: artifact capture failed: %s", exc)

    if timed_out:
        yield root_ev("error", _timeout_event(label, timed_out))
        return

    summary = " ".join(p for p in final_text_parts if p).strip()

    # A failed CLI is an ERROR, not a `done` whose summary is the failure. Two real runs proved
    # how many ways this leaks through, so the gate is the exit code — the one signal that
    # doesn't lie — and never the stream's shape:
    #
    #   * sidecar absent: `docker exec` exits non-zero with EMPTY stdout, so the read loop ends
    #     on its first iteration, indistinguishable from a model with nothing to say. The old
    #     code then used stderr as a fallback summary, which is how the docker daemon's
    #     "No such container: harvis-claude-code" got rendered under a green tick.
    #   * bad credential: the CLI exits 1 but DOES print text — "Failed to authenticate.
    #     API Error: 401" — on a result line marked {"subtype":"success","is_error":true}.
    #     A guard that only fires when the output is empty sails straight past this one.
    #
    # Hence: rc != 0 fails the run, full stop. Any text produced is reported as partial rather
    # than dropped, and `cli_error` supplies the reason when the CLI named one.
    rc = proc.returncode if proc is not None else None
    if cli_error or rc not in (0, None):
        if _missing_sidecar(stderr_buf, container):
            yield root_ev("error", {
                "message": f"{label} isn't installed on this Harvis.",
                "fix_hint": _engine_install_hint(engine, container),
            })
        elif cli_error_status in (401, 403):
            yield root_ev("error", {
                "message": f"{label} rejected the credential: {cli_error[:300]}",
                "fix_hint": (
                    "Re-verify your Kimi Code Console key in Integrations — a Moonshot "
                    "platform key won't work here, it must be a Kimi Code membership key."
                    if is_kimi else
                    "Re-verify your Claude subscription or API key in Integrations."
                ),
            })
        else:
            detail = cli_error or (stderr_buf[-1] if stderr_buf else f"exit code {rc}")
            yield root_ev("error", {
                "message": f"{label} failed to run: {detail[:300]}",
                "fix_hint": f"Check the {container} sidecar's logs: `docker logs {container}`.",
                **({"partial_output": summary[:2000]} if summary else {}),
            })
        return

    summary = (summary[:2000] if summary else "") or f"{label} finished."
    yield root_ev("done", {"summary": summary})
