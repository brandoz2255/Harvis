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
    brief: str = "",
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
    # What the run ACTUALLY executes (`resolved_brief`), not the detector's paraphrase.
    # The paraphrase comes from an LLM reading the last ten turns, and those turns carry
    # earlier cards with their own `taskbrief=` attribute — so a stale brief re-fed itself
    # every turn. A card read "Compare the Fable GPT 5.x Sol benchmarks" while the user had
    # asked for a tree and the agent was, correctly, drawing a tree.
    brief = html.escape((brief or suggestion.task_brief or "")[:240], quote=True)
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


# Human label for each dispatch lane (agent_id) — what the run card's engine chip shows.
# Keyed by the SAME agent_id that selects the event stream in workspace_router, so the chip
# can never claim an engine that isn't the one running. Unknown ids fall back to the id
# itself rather than silently reading "OpenClaw".
_ENGINE_LABELS = {
    "main": "OpenClaw",
    "agent-native": "Harvis Agent",
    "orchestrated": "Orchestrator",
    "claude": "Claude",
    "kimi": "Kimi",
    "kimi-code": "Kimi Code",
    "nvidia-kimi": "NVIDIA Kimi",
    "cloud-ollama": "Cloud Ollama",
    "gpt-oss": "GPT-OSS",
    "local": "Local",
}


def _resolve_engine(mode: str, model_id: str) -> tuple[str, str]:
    """``(agent_id, engine_label)`` for this turn.

    ONE resolution drives both the dispatch lane and the card chip. They used to be two
    independent ternaries, which is how a Moonshot/Kimi pick ended up dispatching to the
    OpenClaw tool-loop *and* labelling itself "OpenClaw" — the model the user chose was
    never consulted. Adding an engine now means adding one row here, not editing two
    parallel conditionals that can drift apart.
    """
    if mode == "orchestrate":
        agent_id = "orchestrated"
    elif model_id.startswith("anthropic/"):
        agent_id = "claude"  # cloud Claude drives its OWN tool-loop (claude -p)
    elif model_id.startswith("kimi-code/"):
        # Kimi Code SUBSCRIPTION → the Claude Code sidecar with ANTHROPIC_BASE_URL repointed.
        # Deliberately checked BEFORE the moonshot/ prefix: this is a different product on a
        # different credential and a different bill, and collapsing the two would silently
        # spend pay-as-you-go balance when the user picked their membership allowance.
        agent_id = "kimi-code"
    elif model_id.startswith("moonshot/"):
        agent_id = "kimi"  # → stream_kimi_workspace (the original Harvis workspace engine)
    else:
        # Everything else — local Ollama tags and the per-user cloud providers (groq,
        # cerebras, gemini, nvidia, mistral, OpenAI) — runs on Harvis's OWN tool-loop.
        # That is the only lane offering Agent Reach, so "Agent" means the same thing
        # here as it does on a CLI engine. This used to default to "main" (OpenClaw),
        # which has no reach tools; HARVIS_OWUI_WORKSPACE_AGENT=main restores that.
        agent_id = os.getenv("HARVIS_OWUI_WORKSPACE_AGENT", "agent-native")
    return agent_id, _ENGINE_LABELS.get(agent_id, agent_id)


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


# ── Reach intent: information the model CANNOT have ──────────────────────────
# `_LIVE_TOOL_RE` above is deliberately loose because it only ever *suppresses* a
# launch on a paid cloud model — a false positive there costs nothing. It is far
# too loose to *cause* a launch: "write a web scraper" and "parse this price
# column" would both send a code question to the slow tool lane.
#
# These two patterns are the tight version, and each one names a request the
# model provably cannot answer from training data:
#   1. an explicit fetch/search imperative ("search the web for…", "read this page"),
#   2. a question about right-now (latest / today / current price).
# Anything else stays in plain chat, where it was already being answered fine.
#
# A bare pasted URL is deliberately NOT a trigger. chat_completion._inject_media
# already fetches http(s) links through the research extractor and injects the
# page as context, inline and immediately — diverting those to a workspace run
# would trade a fast inline answer for a slow one behind a run card, to reach the
# same page.
_REACH_IMPERATIVE_RE = re.compile(
    r"(search\s+(the\s+)?(web|internet|online)|web\s?search|google\s+(it|for|this)|"
    r"look\s+(it|this|that)?\s*up\s+(online|on\s+the\s+web)|browse\s+to\b|"
    r"(read|open|check|visit|fetch|pull\s+up)\s+(this|that|the)\s+"
    r"(page|url|link|site|article|repo|readme|feed|video|transcript)|"
    r"summari[sz]e\s+(this|that|the)\s+"
    r"(page|url|link|site|article|repo|readme|feed|video|transcript))",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_FRESHNESS_RE = re.compile(
    r"\b(latest|current(ly)?|today'?s?|right\s+now|as\s+of\s+(today|now)|"
    r"this\s+(week|month|year)|newest|up[-\s]to[-\s]date|breaking\s+news)\b",
    re.IGNORECASE,
)
# An information request does not have to be shaped like a question. "give me current
# details on gpt oss 20b" scored 0 here while asking for exactly the thing the weights
# cannot supply — it went to a sandbox run, which answered from memory and named the
# wrong model. The imperative openers below are the same ask in the imperative mood;
# the freshness word is still required, so "give me a function that sorts a list"
# stays out.
_QUESTION_RE = re.compile(
    r"(\?|^\s*(what|who|when|where|which|how\s+(many|much)|is|are|does|did|has|have)\b"
    r"|\b(give|tell|show|get|find|fetch)\s+me\b"
    r"|^\s*(list|find|look\s+up)\b)",
    re.IGNORECASE,
)


# Verbs that ask for something to EXIST when the turn is done — a file, a report, a
# patch, a running command. Those belong in a workspace even when the same turn also
# needs live information, because chat_reach can only read and answer.
_ARTIFACT_VERB_RE = re.compile(
    r"\b(build|write|create|make|generate|implement|code|refactor|fix|patch|edit|"
    r"install|deploy|run|execute|test|compile|scaffold|migrate|rename|delete|"
    r"add\s+(a|an|the)\b|save|export|draft)\b",
    re.IGNORECASE,
)


def _answer_only_reach(message: str, suggestion) -> bool:
    """True when the turn is a live-information *question* with nothing to produce.

    The detector scores "is this a multi-step build task" and it rated
    "give me current details on gpt oss 20b" at 0.90 — high enough to auto-launch a
    sandbox run, which then answered from stale weights and named the wrong model.
    A question with no artifact verb has nothing for a sandbox to do: chat_reach
    reaches the same pages in a couple of seconds with no run card. Deliberately
    narrow — anything that asks for a file, a patch, or a command stays on the
    workspace path, as does a forced agent/orchestrate turn (handled by the caller).
    """
    if (getattr(suggestion, "task_type", None) or "") != "research":
        return False
    if not _needs_reach(message):
        return False
    return not _ARTIFACT_VERB_RE.search(message or "")


def _needs_reach(message: str) -> bool:
    """True when the turn asks for information only a live fetch can supply."""
    m = (message or "").strip()
    if not m:
        return False
    if _REACH_IMPERATIVE_RE.search(m):
        return True
    return bool(_FRESHNESS_RE.search(m) and _QUESTION_RE.search(m))


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
    if m.startswith(("anthropic/", "openai/", "moonshot/")):
        return  # cloud models don't run via OpenClaw→Ollama — the 'claude'/'kimi' lanes handle
                # them. moonshot/* especially: writing a cloud id into openclaw_llm_config makes
                # model_proxy try to resolve it as an OLLAMA TAG, fail, and silently fall back to
                # a local model — the same trap documented for hermes-agent below.
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
    # Moonshot/Kimi facade ids are provider-prefixed (``moonshot/kimi-k3`` …) exactly like the
    # other cloud providers — see cloud_chat._MOONSHOT_MODELS. Prefix-matching (not an id list)
    # keeps new K-versions routing correctly without touching this file.
    _is_moonshot = _model_id.startswith("moonshot/")

    # OpenAI/GPT used to be forced back to plain chat here, because the only lane the
    # else-branch could reach was OpenClaw (an Ollama-backed loop a cloud model can't
    # drive). The "agent-native" lane changed that: it POSTs OpenAI Chat Completions
    # with Harvis's tool schema, using this user's OWN key (see
    # orchestration/provider_route.py), so GPT now runs the same tool-loop as every
    # other API-key provider. A missing key fails the run by name instead of silently
    # answering as a local model.
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
            # The detector scores "is this a multi-step BUILD task", so it rates a plain
            # question low no matter how un-answerable that question is from training
            # data. "What's the latest release of X?" scored 0.2 and got answered from
            # a stale weight file, with the tools that could have fetched it sitting
            # right there. Needing information the model cannot have is its own launch
            # reason — see _needs_reach for the (deliberately narrow) definition.
            if not _needs_reach(message):
                return None
            # …but plain chat can now answer these itself: chat_reach runs the same
            # two read-only tools inline, in a couple of seconds, with no run card
            # and no sandbox. When it is on it owns the turn, because launching a
            # workspace to answer "what's the latest X?" is the slower way to reach
            # the identical page. This branch is the fallback for HARVIS_CHAT_REACH=0.
            from .chat_reach import chat_reach_enabled

            if chat_reach_enabled():
                logger.info("owui workspace_bridge: reach intent → chat_reach owns it")
                return None
            suggestion = WorkspaceSuggestion({
                "should_suggest": True,
                "confidence": 1.0,
                "task_type": "research",
                "task_brief": message[:500],
                "reason": "Needs live information the model cannot have.",
            })
            logger.info("owui workspace_bridge: reach intent → auto workspace launch")
        # A high detector score is not a reason to run a sandbox for a question. The
        # detector rates research tasks highly and has no opinion about whether the
        # answer needs anything built, so a pure "give me current details on X" was
        # taking the slow lane and answering from memory anyway.
        elif _answer_only_reach(message, suggestion):
            from .chat_reach import chat_reach_enabled

            if chat_reach_enabled():
                logger.info(
                    "owui workspace_bridge: answer-only research (conf=%.2f) → chat_reach owns it",
                    suggestion.confidence,
                )
                return None
        # Cloud models are paid per token and slower on the tool lane, so they take it
        # ONLY for genuine tool tasks (web search, current info, code execution); simple
        # generation stays in fast plain chat where the artifact preview auto-opens.
        # Forced agent/orchestrate (above) always runs it.
        if _is_openai and not _needs_live_tools(suggestion, message):
            logger.info("owui workspace_bridge: OpenAI simple task → plain chat")
            return None
        # Kimi/Moonshot is a paid cloud engine like Claude — same rule, so simple generation
        # doesn't burn Moonshot tokens on the slow tool lane when fast chat would do.
        if _is_moonshot and not _needs_live_tools(suggestion, message):
            logger.info("owui workspace_bridge: Kimi simple task → plain chat")
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

    # Lane + chip label from one resolution (see _resolve_engine) — the picked model
    # decides BOTH, so the card can't advertise an engine the run isn't using.
    _agent_id, _engine_label = _resolve_engine(mode, _model_id)
    logger.info(
        "owui workspace_bridge: model=%r → agent_id=%r engine=%r (mode=%s)",
        _model_id, _agent_id, _engine_label, mode,
    )

    launch_kwargs = dict(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=resolved_brief,
        chat_history=history,
        # Resolved above from the picked model. Default "agent-native" → the native
        # SubAgentRunner, the only lane that offers Agent Reach. Override per-deploy
        # via HARVIS_OWUI_WORKSPACE_AGENT ("main" = the old OpenClaw loop, "local" …).
        agent_id=_agent_id,
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

    lines = _openai_sse_lines(
        workspace_id,
        _marker_content(
            workspace_id, suggestion, needs_approval=needs_approval,
            mode=mode, engine=_engine_label, brief=resolved_brief,
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
