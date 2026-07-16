"""OWUI-facade workspace bridge.

When an OWUI chat-completion request looks like a multi-step *workspace task*,
launch a Harvis workspace run and return a short OpenAI-SSE stream whose only
content is a ``<details type="workspace_run" data-workspace-id="…">`` marker.
The OWUI frontend renders that marker as a live ``WorkspaceRunCard`` which then
attaches to ``GET /api/workspace/stream/{id}`` for the actual run.

This mirrors the native ``/api/chat`` auto-launch (``main.py`` + ``chat_bridge.py``)
but emits a *marker* instead of streaming the whole run inline — so the run is
owned by the card / right-rail, not by the chat-completion request (which returns
immediately). No new backend plumbing: it reuses ``_start_workspace`` etc.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import time
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Parity with the native /api/chat auto-launch threshold (main.py ~2920).
_AUTO_LAUNCH_CONFIDENCE = 0.8

# ── Opt-in run-level approval gate (P1.5, default OFF) ───────────────────────
# When HARVIS_OWUI_APPROVALS is on, a detected workspace task is NOT launched
# immediately — its launch kwargs are parked here and the run-card shows
# Approve/Deny. POST /api/owui/workspace/{id}/approve launches it; /deny discards.
# When OFF (default) runs launch immediately, exactly as before — zero change to
# the working flow. In-memory by design (single uvicorn worker); a pending run
# lost to a restart simply can't be approved (the card shows it unavailable).
_PENDING_RUNS: dict[str, dict] = {}


def _approvals_enabled() -> bool:
    return os.getenv("HARVIS_OWUI_APPROVALS", "false").strip().lower() in ("1", "true", "yes", "on")


def _messages_to_history(owui_body: dict) -> list[dict]:
    """OWUI sends OpenAI-style messages; the detector wants ``[{role, content}]``
    with plain-string content (flatten multimodal parts to their text)."""
    out: list[dict] = []
    for m in owui_body.get("messages") or []:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        if role and content:
            out.append({"role": role, "content": str(content)})
    return out


def _last_user_message(history: list[dict]) -> str:
    for m in reversed(history):
        if m.get("role") == "user":
            return m.get("content", "") or ""
    return ""


def _marker_content(
    workspace_id: str,
    suggestion,
    needs_approval: bool = False,
    *,
    mode: str = "auto",
    engine: str = "OpenClaw",
) -> str:
    """Newline-fenced ``<details type="workspace_run">`` block so OWUI's marked
    extension parses it into a token the WorkspaceRunCard renders.

    NOTE: OWUI's ``parseAttributes`` regex only captures ``\\w+`` attribute keys
    (no hyphens), so we use word-only keys — and NOT ``data-task-type`` (would be
    parsed as ``type`` and clobber the ``workspace_run`` discriminator).

    ``engine`` + ``launchmode`` surface on the card chip immediately (before the
    stream confirms the executor), so the user sees e.g. "OpenClaw · Auto"."""
    label = html.escape(suggestion.task_type_label or "Workspace task", quote=True)
    ttype = html.escape(suggestion.task_type or "", quote=True)
    brief = html.escape((suggestion.task_brief or "")[:240], quote=True)
    approval_attr = ' needsapproval="1"' if needs_approval else ""
    mode_label = {"auto": "Auto", "agent": "Agent", "orchestrate": "Orchestrate"}.get(
        (mode or "auto").lower(), "Auto"
    )
    eng = html.escape(engine or "OpenClaw", quote=True)
    return (
        f'<details type="workspace_run" workspaceid="{workspace_id}" '
        f'tasktype="{ttype}" tasklabel="{label}" taskbrief="{brief}" '
        f'engine="{eng}" launchmode="{mode_label}"{approval_attr}>\n'
        f"<summary>Working in a Harvis Workspace…</summary>\n"
        f"</details>\n"
    )


def _openai_sse_lines(workspace_id: str, content: str) -> list[str]:
    """A minimal OpenAI chat.completion.chunk sequence carrying ``content`` then
    ``[DONE]`` — exactly what OWUI's createOpenAITextStream parser expects."""
    cid = f"chatcmpl-ws-{workspace_id}"
    created = int(time.time())
    base = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "harvis-workspace",
    }
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    lines.append("data: [DONE]\n\n")
    return lines


# Models that aren't a concrete pick — never sync these (they ARE the auto-route).
_MODEL_SENTINELS = {"", "auto", "default", "user-pref", "dynamic", "harvis-workspace"}

# A cloud model only takes the (slower) workspace lane for tasks that genuinely need live
# tools — web search, current info, fetching, code execution. Simple generation a model can
# do from its own knowledge stays in fast plain chat.
_LIVE_TOOL_RE = re.compile(
    r"\b(search|google|look\s?up|browse|web|internet|online|current|latest|news|today|"
    r"recent|weather|stock|price|fetch|download|scrape|crawl|run\s+(the\s+)?(code|tests?)|execute)\b",
    re.IGNORECASE,
)


def _needs_live_tools(suggestion, message: str) -> bool:
    if (getattr(suggestion, "task_type", "") or "") in ("research", "multi_step"):
        return True
    return bool(_LIVE_TOOL_RE.search(message or ""))


async def _sync_workspace_model(pool, model_name: str) -> None:
    """Make the OpenClaw workspace follow the model picked in the OWUI dropdown.

    Points the active ``openclaw_llm_config`` row at ``model_name`` so model_proxy's
    ``auto`` resolution serves it; ``_resolve_route`` then auto-discovers the node
    (laptop vs rig) and falls back if it's unreachable. Without this, the workspace
    ignored the dropdown and always used the static DB config.

    NOTE: the active config is a single global row (``WHERE is_active=TRUE``), so this
    is effectively the same lever as Discord's ``set-model`` — the web-UI selection
    becomes the shared workspace model. Best-effort: a failure leaves the prior model.
    """
    if pool is None:
        return
    m = (model_name or "").strip()
    if m.lower() in _MODEL_SENTINELS:
        return
    if m.startswith(("anthropic/", "openai/")):
        return  # cloud models don't run via OpenClaw→Ollama — the 'claude' lane handles them
    if m == "hermes-agent":
        return  # Hermes Agent is a remote-proxied engine (its own OpenAI-compatible API server,
                # local or BYO external), NOT an Ollama tag. Syncing it into the OpenClaw→Ollama
                # config makes model_proxy fail to resolve it and silently fall back to qwen3.5 on
                # the OpenClaw engine. The Chat lane (proxy_hermes_chat) routes it directly.
    base = os.getenv("OLLAMA_URL", "http://ollama:11434")
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE openclaw_llm_config SET model_id=$1, provider_url=$2, updated_at=NOW() "
                "WHERE is_active = TRUE AND (model_id IS DISTINCT FROM $1 OR provider_url IS DISTINCT FROM $2)",
                m, base,
            )
        logger.info("owui workspace_bridge: workspace model synced to UI pick → %s", m)
    except Exception:
        logger.warning("owui workspace_bridge: model sync failed for %r", m, exc_info=True)


async def maybe_handle_workspace(
    request: Request, owui_body: dict, user
) -> Optional[StreamingResponse]:
    """If this chat turn is a workspace task, launch the run and return an SSE
    carrying the run marker. Otherwise return ``None`` (caller falls through to a
    normal chat completion). Never raises — any failure → ``None`` → normal chat.
    """
    history = _messages_to_history(owui_body)
    message = _last_user_message(history)
    if not message.strip():
        return None

    # Manual mode override — the Auto/Chat/Agent/Orchestrate pill next to Send:
    #   'chat'        → never launch a workspace (fast direct answer)
    #   'agent'       → always launch the workspace tool-loop for this message
    #   'orchestrate' → always launch the P5 multi-agent orchestrator (agent_id="orchestrated")
    #   'auto'/absent → fall through to the auto-detector (default)
    mode = str(owui_body.get("harvis_mode") or "auto").strip().lower()
    if mode == "chat":
        return None  # user forced fast chat
    # Launch-path signal: explicit pill picks (agent/orchestrate) are user-initiated;
    # 'auto'/absent goes through the auto-detector. Auto-detected launches run with
    # heavy tools withheld (no Tier-3 capability token — see below).
    launch_mode = "user" if mode in ("agent", "orchestrate") else "auto"

    _model_id = str(owui_body.get("model") or "")
    _is_anthropic = _model_id.startswith("anthropic/")
    _is_openai = _model_id.startswith("openai/")

    # FIX 5: OpenAI/GPT cloud models have no workspace tool lane. If the user FORCES
    # agent/orchestrate on one, launching the native/OpenClaw loop would run on a model
    # it can't drive — fall back to plain chat honestly (the auto path already returns
    # None for _is_openai below). Cloud Claude keeps the lane (it has a workspace bridge).
    if mode in ("agent", "orchestrate") and _is_openai:
        logger.info(
            "owui workspace_bridge: %s mode requested on an OpenAI model (no workspace lane) → plain chat",
            mode,
        )
        return None

    # Lazy imports — keep the package free of import-time coupling to workspace/.
    try:
        from workspace.task_detector import detect_workspace_task, WorkspaceSuggestion
        from workspace.workspace_router import (
            _start_workspace,
            _db_enable_interactive,
            _db_create_run,
            _resolve_task_brief,
        )
    except Exception:
        logger.exception("owui workspace_bridge: import failed; skipping detection")
        return None

    if mode in ("agent", "orchestrate"):
        # User forced agent/orchestrate — skip detection, force a workspace.
        suggestion = WorkspaceSuggestion({
            "should_suggest": True,
            "confidence": 1.0,
            "task_type": "multi_step",
            "task_brief": message[:500],
            "reason": f"{mode} mode forced by user.",
        })
        logger.info("owui workspace_bridge: %s mode forced for this message", mode)
    else:
        try:
            suggestion = await detect_workspace_task(history)
        except Exception:
            logger.exception("owui workspace_bridge: detect_workspace_task failed")
            return None
        if not (suggestion.should_suggest and suggestion.confidence >= _AUTO_LAUNCH_CONFIDENCE):
            return None
        # Cloud models: GPT has no workspace lane yet → plain chat. Cloud Claude takes the
        # (slower, tool-driving) workspace lane ONLY for genuine tool tasks (web search,
        # current info, code execution); simple generation stays in fast plain chat where
        # the artifact preview auto-opens. Forced agent/orchestrate (above) always runs it.
        if _is_openai:
            return None
        if _is_anthropic and not _needs_live_tools(suggestion, message):
            logger.info("owui workspace_bridge: cloud Claude simple task → plain chat")
            return None

    pool = getattr(request.app.state, "pg_pool", None)
    user_id = getattr(user, "id", None)
    if pool is None or user_id is None:
        return None

    message = _last_user_message(history)
    workspace_id = uuid.uuid4().hex[:8]
    session_id = owui_body.get("chat_id") or owui_body.get("session_id") or f"owui-{workspace_id}"
    model_name = owui_body.get("model") or ""
    # Workspace follows the UI model: point the active OpenClaw config at whatever
    # model the chat dropdown selected, so the workspace runs on it (model_proxy's
    # `auto` path resolves to it; the node is auto-discovered downstream). Previously
    # the workspace ignored the dropdown and used the static config.
    await _sync_workspace_model(pool, model_name)
    # Use the RAW user message as the brief — it carries the literal challenge
    # data (hashes, ciphertext, encoded blobs) that the hash/decode/crypto skill
    # detection in openclaw_client needs to fire its CodeAct flow. The detector's
    # `suggestion.task_brief` paraphrases that away ("Find the MD5 hash values…"),
    # which silently disables cracking for CTF tasks (model narrates instead).
    resolved_brief = _resolve_task_brief(message, history)
    started_epoch = time.monotonic()

    interactive_context = None
    if launch_mode == "user":
        try:
            cap = await _db_enable_interactive(
                pool, workspace_id=workspace_id, user_id=user_id, ttl_seconds=3600
            )
            interactive_context = {"workspace_id": workspace_id, "capability_token": cap}
        except Exception:
            logger.warning("owui workspace_bridge: enable_interactive failed for %s", workspace_id)
    else:
        # Auto-detected launch: withhold the Tier-3 capability token. Without a
        # workspace_web_caps row, every /api/tools/browser/* call 403s in
        # _require_interactive, and openclaw_client never injects the browser
        # credentials hint — the run is restricted to base tools.
        logger.info(
            "owui workspace_bridge: auto launch %s — Tier-3 interactive withheld",
            workspace_id,
        )

    launch_kwargs = dict(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=resolved_brief,
        chat_history=history,
        # Route web-UI workspace tasks through OpenClaw's tool-loop by default. agent_id
        # NOT in {local,kimi,nvidia-kimi,cloud-ollama,gpt-oss} → the `else` branch in
        # workspace_router → client.stream (which actually has tools). Override per-deploy
        # via HARVIS_OWUI_WORKSPACE_AGENT (e.g. "local" for the tool-less direct model).
        # 'orchestrate' mode → the P5 multi-agent orchestrator; otherwise the default
        # OpenClaw tool-loop agent (override via HARVIS_OWUI_WORKSPACE_AGENT).
        agent_id=(
            "orchestrated" if mode == "orchestrate"
            else "claude" if _is_anthropic   # cloud Claude drives its OWN tool-loop (claude -p)
            else os.getenv("HARVIS_OWUI_WORKSPACE_AGENT", "main")
        ),
        user_id=user_id,
        model_name=model_name,
        live_web=True,
        parallel=True,
        # Orchestrate "uniform model" toggle: force every sub-agent onto the
        # chat-selected model instead of per-role profile models. Default off
        # (heterogeneous). Only meaningful when agent_id == "orchestrated".
        uniform_model=bool(owui_body.get("harvis_orchestrate_uniform")),
        # Attached repo (clone-local "attached" isolation): a read-only bind-mounted
        # repo path the user picked. Each sub-agent runs in a `git clone --local` of
        # it and produces a real `git diff` vs HEAD. Only meaningful when orchestrated.
        repo_path=(owui_body.get("harvis_repo_path") or None),
        interactive_context=interactive_context,
        # "user" (explicit agent/orchestrate pill) vs "auto" (auto-detected).
        # Auto runs carry no Tier-3 token and get heavy tools withheld downstream.
        launch_mode=launch_mode,
    )

    needs_approval = _approvals_enabled()
    if needs_approval:
        # Opt-in gate: park the run; the card asks Approve/Deny before it launches.
        _PENDING_RUNS[workspace_id] = {
            "kwargs": launch_kwargs,
            "user_id": user_id,
            "session_id": session_id,
            "task_brief": resolved_brief,
        }
        logger.info(
            "owui workspace_bridge: %s awaiting approval (conf=%.2f type=%s)",
            workspace_id, suggestion.confidence, suggestion.task_type,
        )
    else:
        try:
            await _start_workspace(pool=pool, started_epoch=started_epoch, **launch_kwargs)
            await _db_create_run(pool, workspace_id, user_id, session_id, resolved_brief)
        except Exception:
            logger.exception("owui workspace_bridge: launch failed for %s", workspace_id)
            return None
        logger.info(
            "owui workspace_bridge: launched %s (conf=%.2f type=%s)",
            workspace_id, suggestion.confidence, suggestion.task_type,
        )

    _engine_label = (
        "Orchestrator" if mode == "orchestrate"
        else "Claude" if _is_anthropic
        else "OpenClaw"
    )
    lines = _openai_sse_lines(
        workspace_id,
        _marker_content(
            workspace_id, suggestion, needs_approval=needs_approval,
            mode=mode, engine=_engine_label,
        ),
    )

    async def _gen():
        for ln in lines:
            yield ln

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def resolve_workspace_approval(request: Request, workspace_id: str, approved: bool) -> dict:
    """Resolve a parked (opt-in) workspace run: launch it on approve, discard on
    deny. Returns a small JSON status the run-card uses to switch to streaming or
    show 'cancelled'. Safe no-op if the workspace isn't pending (already resolved,
    or lost to a restart)."""
    pending = _PENDING_RUNS.pop(workspace_id, None)
    if pending is None:
        return {"ok": False, "status": "not_pending"}
    if not approved:
        logger.info("owui workspace_bridge: %s denied", workspace_id)
        return {"ok": True, "status": "denied"}

    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"ok": False, "status": "no_pool"}
    try:
        from workspace.workspace_router import _start_workspace, _db_create_run

        await _start_workspace(pool=pool, started_epoch=time.monotonic(), **pending["kwargs"])
        await _db_create_run(
            pool, workspace_id, pending["user_id"], pending["session_id"], pending["task_brief"]
        )
    except Exception:
        logger.exception("owui workspace_bridge: approve-launch failed for %s", workspace_id)
        return {"ok": False, "status": "launch_failed"}
    logger.info("owui workspace_bridge: %s approved + launched", workspace_id)
    return {"ok": True, "status": "approved"}
