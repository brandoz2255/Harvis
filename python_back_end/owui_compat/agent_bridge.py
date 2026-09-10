"""Teammates in the chat model picker.

A teammate shows up in the model list as ``agent:<uuid>``. Picking it and
sending a message does not run a chat completion — it starts a coordinated
agent run and returns a run-card marker, exactly like the workspace bridge
does, but carrying the teammate's identity so the card can draw its head and
its own panel.

Two entry points:

``agent_model_entries(pool, user_id)``
    the model-picker rows, appended by ``_owui_models``.

``maybe_handle_agent(request, owui_body, user)``
    first link in the ``/api/chat/completions`` chain. Returns ``None`` for
    every request that is not addressed to a teammate, so an install with no
    teammates behaves exactly as before.
"""

from __future__ import annotations

import html
import json
import logging
import time
import urllib.parse
from typing import Optional

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

MODEL_PREFIX = "agent:"
_DEFAULT_TINT = "#7c5cff"

# The mascot heads, as tiny inline SVGs. Drawn from the validated ``tint`` only —
# there is no user-supplied string anywhere in the markup, so the data URI can
# never carry anything but a colour this process chose.
_MASCOT_SHAPES = {
    "claw": (
        '<path d="M18 44c0-14 10-26 22-26s22 12 22 26c0 4-2 6-5 6-4 0-5-3-6-7'
        '-1-5-5-8-11-8s-10 3-11 8c-1 4-2 7-6 7-3 0-5-2-5-6z" fill="{tint}"/>'
        '<circle cx="30" cy="38" r="4" fill="#0b0b12"/>'
        '<circle cx="50" cy="38" r="4" fill="#0b0b12"/>'
    ),
    "bolt": '<path d="M44 8 22 44h14l-4 28 26-38H43z" fill="{tint}"/>',
    "orb": (
        '<circle cx="40" cy="40" r="26" fill="{tint}"/>'
        '<circle cx="32" cy="32" r="8" fill="#ffffff" opacity="0.35"/>'
    ),
    "spark": (
        '<path d="M40 10 46 34 70 40 46 46 40 70 34 46 10 40 34 34z" fill="{tint}"/>'
    ),
}


def _avatar_data_uri(avatar: dict | None) -> str:
    """A self-contained SVG head for the picker and the roster.

    Not an upload and not a remote URL: the mascot is one of a fixed set and the
    tint is a validated ``#rrggbb``, so nothing a user typed reaches the markup.
    """
    avatar = avatar or {}
    mascot = str(avatar.get("mascot") or "claw").lower()
    tint = str(avatar.get("tint") or _DEFAULT_TINT).lower()
    if not (len(tint) == 7 and tint[0] == "#" and all(c in "0123456789abcdef" for c in tint[1:])):
        tint = _DEFAULT_TINT
    shape = _MASCOT_SHAPES.get(mascot, _MASCOT_SHAPES["claw"]).format(tint=tint)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="80" height="80">'
        '<rect width="80" height="80" rx="18" fill="#12121a"/>' + shape + "</svg>"
    )
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg, safe="")


def model_id_for(agent_id: str) -> str:
    return f"{MODEL_PREFIX}{agent_id}"


def parse_model_id(model_id: str) -> Optional[str]:
    """The agent uuid inside ``agent:<uuid>``, or None when it is another model."""
    if not model_id or not str(model_id).startswith(MODEL_PREFIX):
        return None
    return str(model_id)[len(MODEL_PREFIX):].strip() or None


def agent_model_entry(agent: dict) -> dict:
    """One OWUI model row for a teammate."""
    title = (agent.get("title") or "").strip()
    job = (agent.get("job") or "").strip()
    described = title or job or "A Harvis teammate with its own workspace."
    return {
        "id": model_id_for(agent["id"]),
        "name": agent.get("name") or "Teammate",
        "object": "model",
        "owned_by": "harvis-agent",
        "info": {
            "meta": {
                "description": described,
                "profile_image_url": _avatar_data_uri(agent.get("avatar")),
                "capabilities": {},
            }
        },
    }


async def agent_model_entries(pool, user_id) -> list[dict]:
    """Picker rows for this user's enabled teammates. Never raises."""
    if pool is None or user_id is None:
        return []
    try:
        from plugins.agents.store import list_teammates

        agents = await list_teammates(pool, int(user_id), enabled_only=True)
    except Exception:
        logger.debug("agent_bridge: teammate model list unavailable", exc_info=True)
        return []
    return [agent_model_entry(a) for a in agents]


# ── the chat turn ────────────────────────────────────────────────────────────


def _messages_to_history(owui_body: dict) -> list[dict]:
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
            return (m.get("content") or "").strip()
    return ""


def marker_content(
    workspace_id: str,
    agent: dict,
    *,
    goal: str = "",
    override: bool = False,
) -> str:
    """The ``<details type="workspace_run">`` block the run card mounts.

    Same discriminator as every other run card, plus ``agentid``/``agentname``
    so the card knows to draw the teammate panel. OWUI's attribute parser only
    captures ``\\w+`` keys, so every key here is word-only.
    """
    name = html.escape(agent.get("name") or "Teammate", quote=True)
    brief = html.escape((goal or "")[:240], quote=True)
    tint = str((agent.get("avatar") or {}).get("tint") or _DEFAULT_TINT)
    if not (len(tint) == 7 and tint[0] == "#"):
        tint = _DEFAULT_TINT
    mascot = html.escape(str((agent.get("avatar") or {}).get("mascot") or "claw"), quote=True)
    return (
        f'<details type="workspace_run" workspaceid="{workspace_id}" '
        f'agentid="{html.escape(str(agent["id"]), quote=True)}" agentname="{name}" '
        f'agentmascot="{mascot}" agenttint="{html.escape(tint, quote=True)}" '
        f'tasktype="agent" tasklabel="{name}" taskbrief="{brief}" '
        f'engine="{name}" launchmode="{"Override" if override else "Agent"}">\n'
        f"<summary>{name} is working…</summary>\n"
        f"</details>\n"
    )


def _sse(workspace_id: str, content: str) -> list[str]:
    cid = f"chatcmpl-agent-{workspace_id}"
    base = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "harvis-agent",
    }
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    lines.append("data: [DONE]\n\n")
    return lines


def _stream(lines: list[str]) -> StreamingResponse:
    async def _gen():
        for ln in lines:
            yield ln

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _plain(workspace_id: str, text: str) -> StreamingResponse:
    return _stream(_sse(workspace_id, text))


async def maybe_handle_agent(request, owui_body: dict, user):
    """Claim the turn when the picked model is a teammate; otherwise None.

    Returning None is the common case and must stay cheap: one prefix check on
    the model id, before any database work.
    """
    agent_id = parse_model_id(owui_body.get("model") or "")
    if not agent_id:
        return None

    pool = getattr(request.app.state, "pg_pool", None)
    user_id = getattr(user, "id", None)
    if pool is None or user_id is None:
        return _plain("none", "Teammates need the database, which is not available right now.")

    try:
        from plugins.agents.store import get_agent

        agent = await get_agent(pool, int(user_id), agent_id)
    except Exception:
        logger.exception("agent_bridge: lookup failed for %s", agent_id)
        agent = None

    if agent is None or not agent.get("enabled", True):
        # Do NOT fall through: a plain completion with model "agent:<uuid>" would
        # fail somewhere far from here with an unreadable error.
        return _plain(
            "none",
            "That teammate is gone or switched off. Pick another model, or turn it "
            "back on from the Agents page.",
        )

    history = _messages_to_history(owui_body)
    goal = _last_user_message(history)
    if not goal:
        return _plain("none", f"{agent.get('name') or 'Your teammate'} is ready. What should it work on?")

    try:
        from plugins.agents.intake import create_agent_run

        launch = await create_agent_run(
            request=request,
            user_id=int(user_id),
            agent=agent,
            goal=goal,
            # None means "read the override out of the wording"; the roster's
            # explicit toggle is the only thing that overrides that reading.
            override=None,
            chat_history=history[:-1],
            session_id=owui_body.get("chat_id") or None,
            # The model the user last picked in plain chat; "auto" teammates run on it.
            last_pick=str(owui_body.get("harvis_last_model") or ""),
        )
    except Exception:
        logger.exception("agent_bridge: launch failed for agent %s", agent_id)
        return _plain("none", "That run could not start. The workspace service may be down.")

    workspace_id = launch["workspace_id"]
    logger.info(
        "agent_bridge: launched %s for teammate %s (override=%s, model=%r via %s)",
        workspace_id, agent_id, launch.get("override"),
        launch.get("model"), launch.get("model_source"),
    )
    return _stream(
        _sse(
            workspace_id,
            marker_content(
                workspace_id, agent, goal=goal, override=bool(launch.get("override"))
            ),
        )
    )
