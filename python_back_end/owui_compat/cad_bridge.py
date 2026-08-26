"""OWUI-facade CAD bridge: an explicit "create cad" marker in chat starts a real
local CAD build and returns a ``<details type="cad_build">`` card marker.

**Explicit trigger only.** Unlike ``image_bridge``, there is no natural-language
detector here. The lane can only build the recipes the engine has registered, so a
detector would turn "design me a bracket" into a helmet hanger and call it an
answer. Prompt → geometry is Gate 7's problem and needs a CadIR to be honest about;
until then the only thing this bridge claims to understand is a recipe name.

Gating is honest and never hijacks a normal chat: the marker is required, so a turn
that does not carry it returns ``None`` and falls through. When the marker IS there
and the lane is off, or the recipe is unknown, the user gets a short assistant
message saying so — never a silent fallthrough that looks like the request was
ignored.

The card the marker renders carries only opaque ids. Measurements, status and
artifact links all come from ``GET /api/cad/builds/{bid}``, which is ownership-
checked; nothing in the chat token is trusted.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from . import cad_store, fab_cad

logger = logging.getLogger(__name__)

# The composer's "+ → Create → 3D / CAD" item inserts "🧊 create cad <recipe>".
# Same shape as image_bridge's prefix, and the same reason for no ``\b`` after
# "cad": the editor trims a trailing space, so "create cadbrick" must still parse.
_EXPLICIT_PREFIX_RE = re.compile(
    r"^\s*(?:[\U0001F9CA\U0001F4D0\U0001F9F1\U0001F5A8]️?\s*)?"
    r"create\s+cad[\s:>\-]*",
    re.IGNORECASE,
)

# Friendly names → registered recipe. The keys are what a person types; the values
# must exist in ``fab_cad.KNOWN_RECIPES`` (asserted at resolve time, so a recipe
# removed from the engine stops being offered instead of 400-ing later).
_RECIPE_ALIASES: dict[str, str] = {
    "helmet hanger": "helmet_hanger_v1",
    "helmet_hanger": "helmet_hanger_v1",
    "hanger": "helmet_hanger_v1",
    "helmet": "helmet_hanger_v1",
    "studded brick": "studded_brick_v1",
    "studded_brick": "studded_brick_v1",
    "brick": "studded_brick_v1",
    "block": "studded_brick_v1",
}

_RECIPE_LABELS: dict[str, str] = {
    "helmet_hanger_v1": "Helmet hanger",
    "studded_brick_v1": "Studded brick",
}


def _label(recipe: str) -> str:
    return _RECIPE_LABELS.get(recipe) or recipe.replace("_", " ")


def _available() -> list[str]:
    return [r for r in fab_cad.KNOWN_RECIPES]


def _offer() -> str:
    return ", ".join(f"**{_label(r)}**" for r in _available()) or "none"


def _resolve_recipe(text: str) -> Optional[str]:
    """Name-match only — no fuzzy scoring.

    A near-miss that silently picks the closest recipe is the failure this whole
    lane is trying not to have: the user would get a solid, look at it, and have no
    way to tell it was not what they asked for. No match returns ``None`` and the
    caller says what IS available.
    """
    norm = re.sub(r"[^a-z0-9 _]+", " ", (text or "").lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    if not norm:
        return None

    known = set(fab_cad.KNOWN_RECIPES)
    if norm in known:
        return norm

    # Longest alias first, so "studded brick" never loses to "brick".
    for alias in sorted(_RECIPE_ALIASES, key=len, reverse=True):
        target = _RECIPE_ALIASES[alias]
        if target not in known:
            continue
        if re.search(rf"(?:^|\s){re.escape(alias)}(?:\s|$)", norm):
            return target

    for recipe in known:
        if recipe in norm:
            return recipe
    return None


def _sse_response(lines: list[str]) -> StreamingResponse:
    async def _gen():
        for ln in lines:
            yield ln

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _notice_sse(text: str) -> StreamingResponse:
    """Short honest assistant message — the lane is off, the engine is down, or the
    recipe is not one this engine has."""
    from .workspace_bridge import _openai_sse_lines

    return _sse_response(_openai_sse_lines(uuid.uuid4().hex[:8], text))


def _marker_content(build_id: str, project_id: str, revision_id: str,
                    recipe: str) -> str:
    """``<details type="cad_build">`` so OWUI's marked extension parses it into a
    token ``MarkdownTokens`` dispatches to ``CadResultCard``.

    Word-only attribute keys, because OWUI's ``parseAttributes`` regex captures
    ``\\w+`` only — and nothing that would be re-parsed as ``type`` and clobber the
    ``cad_build`` discriminator. Every value here is an id or a display label; the
    card fetches the build for anything that is a claim about geometry.
    """
    esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    return (
        f'<details type="cad_build" buildid="{esc(build_id)}" '
        f'projectid="{esc(project_id)}" revisionid="{esc(revision_id)}" '
        f'recipe="{esc(recipe)}" recipelabel="{esc(_label(recipe))}">\n'
        f"<summary>Building {esc(_label(recipe))} locally…\n"
        f"</details>\n"
    )


async def maybe_handle_cad_build(
    request: Request, owui_body: dict, user
) -> Optional[StreamingResponse]:
    """If this turn carries the CAD marker, start a build and return its card
    marker. Otherwise return ``None`` and the caller falls through to the image
    bridge, the workspace bridge, and finally normal chat."""
    try:
        return await _handle(request, owui_body, user)
    except Exception:
        logger.exception("owui cad_bridge: interceptor failed; falling through")
        return None


async def _handle(request: Request, owui_body: dict, user) -> Optional[StreamingResponse]:
    from .workspace_bridge import _last_user_message, _messages_to_history, _openai_sse_lines

    history = _messages_to_history(owui_body)
    message = str(owui_body.get("harvis_cad_prompt") or "").strip() or _last_user_message(history)
    if not message.strip():
        return None

    explicit = bool(owui_body.get("harvis_cad_build"))
    pref = _EXPLICIT_PREFIX_RE.match(message)
    if pref:
        explicit = True
        remainder = message[pref.end():].strip()
    elif explicit:
        remainder = message.strip()
    else:
        return None  # no marker — this is a normal chat turn

    if not fab_cad.cad_enabled():
        return _notice_sse(
            "Local CAD is disabled on this deployment "
            "(`HARVIS_ADAPTIVE_CAD_ENABLED` is off), so I can't build geometry here."
        )

    if not remainder:
        return _notice_sse(
            f"Tell me which part to build and I'll make it locally. Available now: {_offer()}.\n\n"
            "Describing a new shape from scratch isn't supported yet — the local lane "
            "builds registered parametric recipes, and you can adjust their dimensions "
            "in CAD Studio afterwards."
        )

    recipe = _resolve_recipe(remainder)
    if recipe is None:
        return _notice_sse(
            f"I don't have a recipe for that. Available now: {_offer()}.\n\n"
            "The local CAD lane builds registered parametric recipes rather than "
            "generating new geometry from a description, so I'd rather say that than "
            "hand you the closest thing I happen to have."
        )

    pool = getattr(request.app.state, "pg_pool", None)
    user_id = getattr(user, "id", None)
    if pool is None or user_id is None:
        return _notice_sse("Local CAD is unavailable right now (no database).")
    user_id = int(user_id)

    # Quota before geometry, same as the revisions route: a build whose only possible
    # ending is a quota failure should not be started.
    try:
        await cad_store.check_quota(pool, user_id, None, 1)
    except cad_store.QuotaExceeded as e:
        return _notice_sse(f"Local CAD can't start that build: {e.message}")
    except Exception:
        logger.warning("cad_bridge: quota pre-check failed; continuing", exc_info=True)

    conversation_id = owui_body.get("chat_id") or owui_body.get("session_id") or None
    spec = {
        "design_spec": {"intent": remainder[:500], "units": "mm"},
        "source_kind": "recipe",
        "recipe_name": recipe,
        "parameters": {},
        "created_by": "user",
    }

    project = await cad_store.create_project(
        pool, user_id, _label(recipe),
        str(conversation_id) if conversation_id else None,
        revision=spec,
    )
    revision = project.get("revision")
    if not revision:
        return _notice_sse("Local CAD couldn't create that project.")

    build, created = await cad_store.create_build(pool, revision["id"], user_id, None)
    if not build:
        return _notice_sse("Local CAD couldn't start that build.")

    if created:
        from .cad_router import _run_build, _running

        task = asyncio.create_task(
            _run_build(pool, build["id"], user_id, project["id"],
                       recipe, {}, ["stl", "step", "glb"]),
            name=f"cad-build-{build['id']}",
        )
        _running.add(task)
        task.add_done_callback(_running.discard)

    logger.info("owui cad_bridge: started build %s (recipe=%s project=%s)",
                build["id"], recipe, project["id"])

    return _sse_response(
        _openai_sse_lines(
            build["id"],
            _marker_content(build["id"], project["id"], revision["id"], recipe),
        )
    )
