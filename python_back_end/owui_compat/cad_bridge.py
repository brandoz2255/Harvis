"""OWUI-facade CAD bridge: an explicit "create cad" marker in chat starts a real
local CAD build and returns a ``<details type="cad_build">`` card marker.

**Explicit trigger only.** Unlike ``image_bridge``, there is no natural-language
detector here, and there deliberately still isn't one. What changed at Gate 7B is
what happens *after* the marker: a description that matches no registered recipe is
now designed into a CadIR document rather than refused. The marker stays required
because a detector would turn an ordinary sentence about brackets into a build, and
a build is a thing with a cost and a card, not a thing to guess at.

Gating is honest and never hijacks a normal chat: the marker is required, so a turn
that does not carry it returns ``None`` and falls through. When the marker IS there
and the lane is off, the user gets a short assistant message saying so — never a
silent fallthrough that looks like the request was ignored. When the marker is there
and generation fails, the message distinguishes "the lane is broken" from "I could
not design that", because those are different news and only one of them is worth
rephrasing for.

The card the marker renders carries only opaque ids. Measurements, status and
artifact links all come from ``GET /api/cad/builds/{bid}``, which is ownership-
checked; nothing in the chat token is trusted.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from . import cad_agent, cad_store, cad_tools, fab_cad

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


# "1x1", "2 x 4", "4×2", "2 by 4" — how a person states a brick's stud grid.
_STUD_GRID_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:[x×*]|by)\s*(\d{1,2})(?![\d.])", re.IGNORECASE)

# "10x10x10" is a box's three dimensions, not a stud grid. It has to be recognised
# separately rather than fenced off with a lookahead, because the tail of a triple is
# itself a valid-looking pair and the engine happily backtracks onto it.
_TRIPLE_RE = re.compile(
    r"(?<![\d.])\d{1,3}(?:\.\d+)?\s*[x×*]\s*\d{1,3}(?:\.\d+)?\s*[x×*]\s*\d",
    re.IGNORECASE)


def _recipe_params(recipe: str, text: str) -> dict:
    """The parameters the sentence stated, for a recipe that has somewhere to put them.

    Without this the recipe name was the *whole* reading of the sentence: "a 1x1
    studded brick" matched ``brick``, threw the rest away, and built the recipe's own
    4×2 default — which is exactly the near-miss :func:`_resolve_recipe`'s docstring
    says this lane exists not to have, arriving one step later instead. A user who
    stated a size and got a different one has no way to tell from the part.

    Only the stud grid is read, because it is the only thing a person says in the same
    breath as the recipe name and the only one with an unambiguous mapping. Everything
    else — pitch, wall thickness, height — stays a Parameters-tab edit rather than a
    guess. The engine clamps each value against the recipe's declared range, so an
    absurd grid is refused there rather than trusted here.
    """
    if recipe != "studded_brick_v1":
        return {}
    text = text or ""
    if _TRIPLE_RE.search(text):
        return {}
    m = _STUD_GRID_RE.search(text)
    if not m:
        return {}
    # Clamped, not dropped. A grid outside the recipe's range would otherwise fall back
    # to the 4×2 default, which is further from what was asked for than the nearest
    # buildable grid — and the clamped numbers go in the title, so the substitution is
    # something the user sees rather than something the part quietly is.
    x = max(1, min(16, int(m.group(1))))
    y = max(1, min(16, int(m.group(2))))
    return {"studs_x": x, "studs_y": y}


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
                    recipe: str, label: str | None = None,
                    job_id: str = "", session_id: str = "") -> str:
    """``<details type="cad_build">`` so OWUI's marked extension parses it into a
    token ``MarkdownTokens`` dispatches to ``CadResultCard``.

    Word-only attribute keys, because OWUI's ``parseAttributes`` regex captures
    ``\\w+`` only — and nothing that would be re-parsed as ``type`` and clobber the
    ``cad_build`` discriminator. Every value here is an id or a display label; the
    card fetches the build for anything that is a claim about geometry.

    ``jobid`` is the authoring lane's answer to a card that has to exist before the
    model has created anything. The other three ids are empty on that path and the
    card fills them in from the job stream; on the recipe path there is no job and
    they are known from the first byte, as they always were.

    ``sessionid`` (CS-1) is how the card in the source chat knows which room this
    request opened, so "Open" goes to the session rather than to a workspace overlay
    in a chat the part does not live in. Empty on the recipe path, which builds in
    place and opens no room.
    """
    esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    shown = label or _label(recipe)
    summary = (f"Designing {esc(shown)}…" if job_id
               else f"Building {esc(shown)} locally…")
    return (
        f'<details type="cad_build" buildid="{esc(build_id)}" '
        f'jobid="{esc(job_id)}" sessionid="{esc(session_id)}" '
        f'projectid="{esc(project_id)}" revisionid="{esc(revision_id)}" '
        f'recipe="{esc(recipe)}" recipelabel="{esc(shown)}">\n'
        f"<summary>{summary}\n"
        f"</details>\n"
    )


async def _open_cad_chat(pool, user_id: int, description: str,
                         title: str, model_id: str = "") -> Optional[str]:
    """Give this part a room of its own — the conversation half of a CAD session.

    A part is not a chat message. Making one takes many turns and produces a tree, a
    viewport, a code view and a history, none of which belongs interleaved with a
    conversation about something else. So the request moves into its own conversation
    and the original chat keeps a card pointing at it.

    The room is a real ``owui_chats`` row rather than a CAD-only invention, which is
    what lets everything else work unchanged: the queue keys on conversation id, this
    lane routes on chat id, and the room survives a restart because chats already do.
    The original request is seeded as its first message, so the room opens showing the
    reason it exists rather than empty.

    ``model_id`` is the lane that is about to author the part, recorded as the room's
    model. A room opened with no model on record is one the person cannot send a
    follow-up from — OWUI reads the chat's own ``models`` and does not fall back —
    and it would also misreport who authored the part.

    Returns the chat id, or ``None`` — and ``None`` is not fatal. The session is where
    the work is *shown*; the turn runs against the job either way. A failure here means
    the request behaves exactly as every CAD request did before sessions existed.
    """
    from . import persistence

    now = int(time.time())          # seconds, the unit OWUI stamps messages in
    msg_id = str(uuid.uuid4())
    models = [model_id] if model_id else []
    first = {
        "id": msg_id,
        "parentId": None,
        "childrenIds": [],
        "role": "user",
        "content": description[:8000],
        "timestamp": now,
        "models": models,
    }
    chat_obj = {
        "title": title,
        "models": models,
        "params": {},
        "history": {"messages": {msg_id: first}, "currentId": msg_id},
        "messages": [first],
        "tags": [],
        "files": [],
        # Read by the sidebar so a CAD room opens its workspace rather than a bare
        # chat. Advisory only — the route resolves the session by id server-side.
        "harvis_cad": True,
    }
    try:
        chat = await persistence.create_chat(pool, user_id, chat_obj)
    except Exception:
        logger.warning("cad_bridge: could not open a CAD conversation", exc_info=True)
        return None

    # OWUI's chat JSON carries its own id, and the id only exists after the insert.
    # Best-effort: a chat whose inner id is missing still loads by row id.
    try:
        await persistence.update_chat(pool, user_id, str(chat["id"]),
                                      {"id": str(chat["id"])})
    except Exception:
        logger.debug("cad_bridge: could not stamp the CAD chat id", exc_info=True)
    return str(chat["id"])


async def _seed_cad_card(pool, user_id: int, chat_id: str, content: str,
                         model_id: str = "") -> None:
    """Put the card that watches this turn *inside* the room, under the request.

    The room is where the part is made, and until now it opened showing the request
    and nothing else. Everything about the work — the timeline, the renders, the
    finished product and its exports — lived on the card in the chat the request came
    from, which is the one place the person is *not* while the studio is open. So the
    studio's own conversation was empty of the very work the studio was doing.

    It is the same marker the source chat gets, with one difference: no ``sessionid``.
    That attribute exists to send a reader to the room; a card already in the room has
    nowhere to send them.

    Best-effort. Without it the room still loads, the turn still runs, and the source
    chat's card is untouched — what is lost is the timeline in the room, which is worth
    a log line and not a failed turn.
    """
    from . import persistence

    try:
        chat = await persistence.get_chat(pool, user_id, chat_id)
        obj = (chat or {}).get("chat") or {}
        history = dict(obj.get("history") or {})
        messages = dict(history.get("messages") or {})
        parent = history.get("currentId")

        msg_id = str(uuid.uuid4())
        msg = {
            "id": msg_id,
            "parentId": parent,
            "childrenIds": [],
            "role": "assistant",
            "content": content,
            "model": model_id,
            "timestamp": int(time.time()),
            "done": True,
        }
        # OWUI walks the tree by `childrenIds`, and a message its parent does not
        # claim is a message the renderer never reaches.
        if parent and parent in messages:
            kids = list(messages[parent].get("childrenIds") or [])
            kids.append(msg_id)
            messages[parent] = {**messages[parent], "childrenIds": kids}
        messages[msg_id] = msg

        await persistence.update_chat(pool, user_id, chat_id, {
            "history": {"messages": messages, "currentId": msg_id},
            "messages": list(obj.get("messages") or []) + [msg],
        })
    except Exception:
        logger.warning("cad_bridge: could not seed the room's own CAD card",
                       exc_info=True)


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
    # A selection is the third way a turn can be meant for this lane, and it is as
    # deliberate as the marker: the user clicked a body in the workspace and the
    # composer has been showing "Editing: <that body>" ever since. It is only a
    # *claim* at this point — nothing has been verified — so if it turns out not to
    # resolve, the turn is handed back to normal chat below rather than built.
    claimed_by_selection = isinstance(owui_body.get("harvis_cad_selection"), dict)

    pool = getattr(request.app.state, "pg_pool", None)
    user_id = getattr(user, "id", None)
    conversation_id = owui_body.get("chat_id") or owui_body.get("session_id") or None

    # CS-1. The fourth way a turn belongs to this lane, and the quietest: it was typed
    # inside a CAD session. A session is a room with one part in it, so a message sent
    # there needs no marker — asking someone to re-type "create cad" in the room the
    # part already lives in would be asking them to prove what the URL already says.
    #
    # It is read from the database rather than believed from the body: the client sends
    # a chat id, and whether that chat is a CAD room is ours to answer.
    session = None
    if pool is not None and user_id is not None and conversation_id:
        try:
            session = await cad_store.session_for_conversation(
                pool, int(user_id), str(conversation_id))
        except Exception:
            logger.warning("cad_bridge: could not look up the CAD session",
                           exc_info=True)

    pref = _EXPLICIT_PREFIX_RE.match(message)
    if pref:
        explicit = True
        remainder = message[pref.end():].strip()
    elif explicit or claimed_by_selection or session:
        remainder = message.strip()
    else:
        return None  # no marker, no selection, no session — a normal chat turn

    if not fab_cad.cad_enabled():
        return _notice_sse(
            "Local CAD is disabled on this deployment "
            "(`HARVIS_ADAPTIVE_CAD_ENABLED` is off), so I can't build geometry here."
        )

    if not remainder:
        return _notice_sse(
            "Tell me which part to build and I'll make it locally — either by name "
            f"({_offer()}), or by describing the shape and its dimensions in "
            "millimetres. Either way you can adjust it in CAD Studio afterwards."
        )

    recipe = _resolve_recipe(remainder)
    if session:
        # Inside a session the part is already chosen. Matching "make it taller" to a
        # registered brick would build a different object under this room's name.
        recipe = None

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

    # UX-D §5. The browser may name a selection; it may not describe one. Everything
    # readable comes back from the store, so what the model is told about the part is
    # what the database says about it.
    selection = await _resolve_selection(owui_body, pool, user_id)
    if selection is None and claimed_by_selection and not explicit:
        # The chip was the only reason this turn came here, and it named nothing this
        # user owns in this revision — a stale selection left by a rebuild, or a
        # revision that moved on. Swallowing the message would lose what they typed
        # for a reason they cannot see, so it goes back to ordinary chat.
        return None
    if selection:
        # An edit of the part on screen. A registered recipe would be the wrong answer
        # here — "make this 5 mm wider" is a change to this project, not a request for a
        # different one, and matching it to a brick would quietly build the wrong thing.
        recipe = None

    document: dict | None = None
    generated: dict | None = None
    params: dict = {}
    # Set when this turn is a change to a part that already exists: the project it
    # belongs to and the revision the edit is based on. Everything downstream reads it
    # to decide between appending a revision and creating a project.
    edit_base: dict | None = None
    if recipe is None:
        # The selected model authors the part itself when it is a cloud model that can
        # call tools. `resolve_lane` answers only on a credential that really exists,
        # so `None` here means the user picked a local model and gets the local
        # generator — its own lane, not a downgrade it was not told about.
        selected = str(owui_body.get("model") or "")
        lane = await cad_agent.resolve_lane(selected, pool, user_id)
        if lane is not None:
            return await _native_lane(lane, remainder, pool, user_id, conversation_id,
                                      selection=selection, session=session)

        # `None` has two meanings and they are not interchangeable: a local tag, which
        # legitimately belongs to `cad_generate`, or a cloud model this user cannot
        # currently use. Until now both silently became the first, so a person who
        # picked Opus got a part authored by a 4B model and nothing on screen said so.
        # Refusing is the honest answer — the selected model is not a detail.
        blocked = await cad_agent.unavailable_reason(selected, pool, user_id)
        if blocked:
            return _notice_sse(blocked)

        # A selection, or a session with a part in it, means this turn is a change to
        # something that already exists rather than a request for a new part. Both used
        # to be refused here — the local generator only ever wrote a whole document from
        # a sentence, so an "edit" would have been a replacement wearing the same name.
        # It now has a path that reads the current revision and changes part of it, so
        # the refusal is narrowed to the one case that is still true: a project whose
        # revision holds no CadIR document to edit.
        edit_project = (selection or {}).get("project_id") or (
            (session or {}).get("project_id") if session else None)
        if edit_project:
            edit_base = await _edit_base(pool, str(edit_project), user_id)
            if edit_base is None:
                return _notice_sse(
                    _no_document_to_edit_text(selection, session, selected))

        local_model, missing = await _local_model(selected)
        if missing:
            return _notice_sse(
                f"**{selected}** isn't installed on any inference host, so it can't "
                "design this part. Pick an installed model, or pull that one on the "
                "host you want to use.")

        # No registered recipe matched, so design one. Until Gate 7 this branch said
        # "I don't have a recipe for that" and stopped; the sentence was true then and
        # is not now. What has NOT changed is what happens when generation fails —
        # the honest refusal is still the answer, it is just no longer the only one.
        instruction = _edit_instruction(remainder, selection) if edit_base else remainder
        generated = await _generate_document(
            instruction, local_model,
            base_document=(edit_base or {}).get("cadir"),
            base_spec=(edit_base or {}).get("design_spec"))
        if not generated or not generated.get("ok"):
            return _notice_sse(_generation_failure_text(generated, remainder))
        document = generated["document"]
        title = (edit_base or {}).get("title") or _generated_title(generated, remainder)
    else:
        params = _recipe_params(recipe, remainder)
        title = _label(recipe)
        if params:
            # In the title because it is the first thing the card says, and a grid the
            # sentence did not mean is then visible before the geometry finishes.
            title = f"{title} {params['studs_x']}×{params['studs_y']}"

    spec = {
        "design_spec": (generated or {}).get("design_spec")
                       or {"intent": remainder[:500], "units": "mm"},
        # A generated part is a CadIR document and is recorded as one. Storing it as a
        # recipe would make the revision claim provenance it does not have, and the
        # Versions tab would offer to rebuild something that was never registered.
        "source_kind": "recipe" if recipe else "cadir",
        "recipe_name": recipe,
        "cadir": document,
        # What the part was actually built with, not an empty map. A revision that
        # records `{}` cannot say which values produced its geometry, and the Source
        # tab renders a parameter list with nothing in it.
        "parameters": params,
        "created_by": "user" if recipe else "ai",
        "model_provider": None if recipe else "ollama",
        "model_name": None if recipe else (generated or {}).get("model"),
    }

    if edit_base:
        # An edit appends to the project that already exists. `created_by: "ai"` above
        # makes it a proposal (cad_store.is_proposal), so it is built, measured and
        # shown, but does not become the head until a person accepts it — the same
        # gate the cloud lanes' edits go through, for the same reason.
        try:
            revision = await cad_store.create_revision(
                pool, edit_base["project_id"], user_id, spec,
                base_revision_id=edit_base["revision_id"])
        except cad_store.StaleRevision:
            return _notice_sse(
                "The part changed while I was working on it, so I didn't apply that "
                "edit on top of an older version. Reload the workspace and ask again.")
        if not revision:
            return _notice_sse("Local CAD couldn't record that change.")
        project = {"id": edit_base["project_id"]}
    else:
        project = await cad_store.create_project(
            pool, user_id, title,
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
                       recipe or "", params, ["stl", "step", "glb"], document=document,
                       # Off the stored revision, not off `spec`: this is the chat
                       # lane, where the spec was extracted from the user's sentence
                       # before the model ran and the model never got a chance to edit
                       # it. Reading it back from the row is what makes the grade a
                       # verdict on what was actually recorded.
                       design_spec=revision.get("design_spec"),
                       revision_id=str(revision["id"])),
            name=f"cad-build-{build['id']}",
        )
        _running.add(task)
        task.add_done_callback(_running.discard)

    logger.info("owui cad_bridge: started build %s (%s project=%s)",
                build["id"], f"recipe={recipe}" if recipe else "generated", project["id"])

    return _sse_response(
        _openai_sse_lines(
            build["id"],
            _marker_content(build["id"], project["id"], revision["id"],
                            recipe or "cadir", label=title),
        )
    )


async def _resolve_selection(owui_body: dict, pool, user_id: int) -> dict | None:
    """The `harvis_cad_selection` field, turned into facts — or ``None``.

    The body carries three opaque ids and nothing else. Every readable word about the
    selection is fetched here (:func:`cad_store.resolve_selection`), so a page cannot
    tell a model that the user selected something they did not. A malformed, stale or
    cross-user selection resolves to ``None`` and the turn proceeds as an ordinary
    request — the alternative, failing the whole message because a chip went stale, would
    lose what the user actually typed.
    """
    raw = owui_body.get("harvis_cad_selection")
    if not isinstance(raw, dict):
        return None
    try:
        found = await cad_store.resolve_selection(
            pool, user_id,
            str(raw.get("project_id") or ""),
            str(raw.get("revision_id") or ""),
            str(raw.get("node_id") or ""),
        )
    except Exception:
        logger.warning("cad_bridge: selection could not be resolved", exc_info=True)
        return None
    if found is None:
        logger.info("cad_bridge: selection did not resolve for user %s; "
                    "treating the turn as unselected", user_id)
    return found


async def _edit_base(pool, project_id: str, user_id: int) -> dict | None:
    """The revision a local edit starts from, or ``None`` when there is nothing to edit.

    The newest revision, not the head: a proposal does not move the head, so editing
    from the head would silently discard the change the user is looking at and edit the
    one before it. ``create_revision`` accepts the tip as an honest base for exactly
    this reason.

    ``None`` means the project's newest revision carries no CadIR — a recipe-built part,
    whose geometry comes from registered Python and genuinely has no document for a model
    to change. That refusal is real and stays.
    """
    try:
        revisions = await cad_store.list_revisions(pool, project_id, user_id, limit=1)
    except Exception:
        logger.warning("cad_bridge: could not read revisions for %s", project_id,
                       exc_info=True)
        return None
    tip = revisions[0] if revisions else None
    if not tip or not isinstance(tip.get("cadir"), dict) or not tip["cadir"]:
        return None
    project = await cad_store.get_project(pool, project_id, user_id)
    return {
        "project_id": str(project_id),
        "revision_id": str(tip["id"]),
        "cadir": tip["cadir"],
        "design_spec": tip.get("design_spec") or {},
        "title": (project or {}).get("title"),
    }


def _edit_instruction(remainder: str, selection: dict | None) -> str:
    """What the user typed, plus the part they had selected when they typed it.

    The label and the operation id come from :func:`cad_store.resolve_selection`, which
    read them out of the build's own scene manifest — the page is never the source of
    a word the model sees about the selection.
    """
    if not selection:
        return remainder
    op = selection.get("cadir_operation_id")
    where = f"the {selection.get('label') or 'selected part'}"
    if op:
        where += f" (operation `{op}`)"
    return f"{remainder}\n\nThe user has {where} selected; the change is about that."


def _no_document_to_edit_text(selection: dict | None, session: dict | None,
                              selected: str) -> str:
    who = f"**{selected}**" if selected else "the local designer"
    part = ((selection or {}).get("label")
            or (session or {}).get("title") or "this part")
    return (
        f"I can't change **{part}** with {who}. This part was built from a registered "
        "recipe, so there is no CadIR document to edit — its shape comes from code, and "
        "the numbers in the Parameters panel are the only way to change it.\n\n"
        "The other option is a Claude or Kimi model, which can author a fresh CadIR "
        "version of the part and then edit that."
    )


async def _native_lane(lane, description: str, pool, user_id: int,
                       conversation_id, selection: dict | None = None,
                       session: dict | None = None) -> StreamingResponse:
    """Let the selected cloud model author the part through the CAD tools.

    Everything this lane creates goes through :func:`cad_tools.dispatch`, so it obeys
    the same ownership, quota and proposal rules as the MCP sidecars and the HTTP
    routes — this function contributes no store access of its own. The two things it
    does own are the *context* the model cannot forge (who is asking, what they
    actually said, and which provider really served the call) and the honesty of the
    ending: a lane that resolved and then failed is reported as itself. There is no
    quiet hand-off to :mod:`cad_generate`, because a user told a frontier model
    authored their part deserves that to be true. Moving the loop into a background
    task does not soften that — a silent substitution is *easier* to hide behind a
    progress card, not more acceptable, so the job's terminal event names the lane
    that failed exactly as this function used to.

    UX-0: this returns before the model has been asked anything. It used to ``await``
    the entire tool loop and emit the card afterwards, which meant nothing at all
    reached the browser for the twenty-plus seconds an authoring turn takes — no card,
    no project to open, no sign of life. The job row is minted first precisely because
    the model creates the project itself several seconds in, so there is no other id
    the card could have named.

    CS-1: a request that arrives from an ordinary chat opens its own room first, and
    the turn then runs *in that room* — the job is keyed on the new conversation, not
    the one the person typed in. That is what makes the follow-up they send inside the
    room queue behind this turn instead of racing it. The source chat keeps the card
    and the way back.
    """
    from . import cad_jobs

    source_conv = str(conversation_id) if conversation_id else None
    title = _generated_title({}, description)

    # An existing session means the message came from inside the room; anything else
    # opens one. Opening can fail, and if it does the turn still runs — in the chat it
    # came from, exactly as every turn did before sessions existed.
    cad_chat_id = None
    if session is None:
        cad_chat_id = await _open_cad_chat(
            pool, user_id, description, title,
            # `lane.model` is already the id the browser selected — provider-qualified
            # when the provider qualifies it. Re-prefixing it produced
            # `anthropic/anthropic/claude-opus-5`, a model no picker can match, so
            # the room opened with nothing selected.
            model_id=lane.model,
        )
    conv = (str(session["cad_conversation_id"]) if session
            else (cad_chat_id or source_conv))

    # UX-G. A second message while a turn is in flight used to start a second turn
    # against the same project, and two models proposing revisions over each other
    # leaves no way to say afterwards which one the user meant. It waits instead.
    #
    # Waiting rather than interrupting is the default on purpose: the running turn may
    # be seconds from a good revision, and throwing that away to act on a follow-up
    # the user probably meant as "and also…" costs them work they cannot get back.
    # Interrupting stays available and explicit — Stop the running turn, and the one
    # behind it starts immediately.
    active = None
    try:
        active = await cad_store.find_active_job(pool, user_id, conv)
    except Exception:
        logger.warning("cad_bridge: could not check for an in-flight turn",
                       exc_info=True)

    try:
        job = await cad_store.create_job(
            pool, user_id, description, conversation_id=conv,
            provider=lane.provider, model=lane.model, queued=bool(active),
        )
    except Exception:
        # No job row means no card to watch, and a turn whose only visible outcome is
        # a spinner is worse than an honest refusal.
        logger.warning("cad_bridge: could not open a CAD authoring job", exc_info=True)
        return _notice_sse(
            f"{lane.model} couldn't start authoring that (the job could not be "
            f"recorded).\n\nI can still build a registered part locally: {_offer()}."
        )

    # The room's record, written now that both ids exist. `job_id` is what carries the
    # project across the gap: the model has not created one yet, and the session binds
    # it on the next read (`cad_store._bind_project`).
    if session is None and cad_chat_id:
        try:
            session = await cad_store.create_session(
                pool, user_id, cad_conversation_id=cad_chat_id,
                source_conversation_id=source_conv, job_id=job["id"], title=title,
            )
        except Exception:
            logger.warning("cad_bridge: could not record the CAD session",
                           exc_info=True)

    # The room's copy of the card, written now that the job id exists — the room was
    # opened before there was a turn to point at. This is what puts the design activity
    # in the studio's conversation, directly under the request that started it.
    if cad_chat_id:
        await _seed_cad_card(
            pool, user_id, cad_chat_id,
            _marker_content("", "", "", "cadir", label=title, job_id=job["id"]),
            model_id=lane.model,   # already provider-qualified; see above
        )

    ctx = cad_tools.CadToolContext(
        pool=pool,
        user_id=user_id,
        conversation_id=conv,
        # The answer key is extracted from this, not from the model's `description`
        # argument — see `cad_tools._design_spec`.
        user_text=description,
        source="chat",
        model_provider=lane.provider,
        model_name=lane.model,
        # Resolved server-side, carried as facts. `cad_agent` turns these into the
        # brief; nothing downstream re-reads the client's version of either. The
        # session travels as an *id* rather than a snapshot because a queued turn can
        # start minutes after this line, by which time its project exists and its
        # newest revision has moved.
        extra={k: v for k, v in (
            ("selection", selection),
            ("cad_session_id", session["id"] if session else None),
        ) if v},
    )

    if active and conv:
        place = cad_jobs.enqueue(pool, job["id"], description, lane=lane, ctx=ctx,
                                 conversation_id=conv)
        logger.info("owui cad_bridge: %s/%s authoring job %s queued at %d behind %s",
                    lane.provider, lane.model, job["id"], place, active["id"])
        # The turn in front can finish between the check above and this line, and its
        # drain would then have found an empty queue. Re-asking is what stops the
        # follow-up waiting on something that has already ended; `drain` re-reads and
        # claims the row under a guard, so asking twice cannot start it twice.
        try:
            if not await cad_store.has_running_job(pool, user_id, conv):
                await cad_jobs.drain(pool, conv)
        except Exception:
            logger.warning("cad_bridge: could not drain the CAD queue", exc_info=True)
    else:
        cad_jobs.start_job(pool, job["id"], description, lane=lane, ctx=ctx,
                           conversation_id=conv)
        logger.info("owui cad_bridge: %s/%s authoring job %s started",
                    lane.provider, lane.model, job["id"])

    from .workspace_bridge import _openai_sse_lines

    return _sse_response(
        _openai_sse_lines(
            job["id"],
            _marker_content("", "", "", "cadir", label=title,
                            job_id=job["id"],
                            session_id=(session or {}).get("id", "")),
        )
    )


async def _local_model(selected: str) -> tuple[Optional[str], bool]:
    """The Ollama tag to design with, and whether the user's pick went missing.

    Returns ``(model, missing)``. ``missing`` is ``True`` only when the catalogue was
    readable and genuinely did not contain the selection — the one case where carrying
    on would mean designing with a model the user did not choose. The caller refuses
    instead, because "the model isn't there" is something to say, not to work around.

    This lane used to pass no model at all, so every part in chat was authored by
    ``HARVIS_CAD_MODEL`` no matter which model the user had selected. The revision
    recorded the substitute honestly, but nobody reads a revision to find out why the
    model they picked behaved like a different one.

    Not simply forwarding the name, though: :func:`cad_agent.resolve_lane` answers
    ``None`` for two unrelated reasons — a local tag, and a cloud model whose
    credential is missing — so a name arriving here is not proof Ollama can run it.
    Checking the catalogue keeps the choice when it is real, and falls back to the CAD
    default only when it is not. ``None`` from :func:`installed_models` means no host
    could be asked, and an unanswerable question is not grounds to override the user —
    the generate call then fails on its own terms, naming the real problem.

    The catalogue spans every inference host, not just the laptop. gemma4:12b lives
    only on the RTX 5080 rig, and a laptop-only check called the user's own selection
    uninstalled and quietly designed with something else.
    """
    selected = (selected or "").strip()
    if not selected:
        return None, False
    try:
        from . import cad_generate
    except Exception:
        return None, False
    tags = await cad_generate.installed_models()
    if tags is None or selected in tags:
        return selected or None, False
    logger.info("cad_bridge: %r is not installed on any inference host", selected)
    return None, True


async def _generate_document(description: str,
                             model: Optional[str] = None,
                             base_document: Optional[dict] = None,
                             base_spec: Optional[dict] = None) -> Optional[dict]:
    """Design a part from a description. Returns the generator's own result dict.

    With ``base_document`` the same call edits that document instead of designing a new
    part, and ``description`` is the change asked for rather than the whole brief.

    Returns ``None`` only when the generator could not run at all — no model, no
    validator, no engine. That is a different thing from a model that tried and
    failed, and the caller says a different sentence for each, because "the lane is
    broken" and "I couldn't design that" are not the same news.
    """
    try:
        from . import cad_generate
    except Exception:
        logger.exception("cad_bridge: cad_generate is unavailable")
        return None
    try:
        return await cad_generate.generate(description, model=model,
                                           base_document=base_document,
                                           base_spec=base_spec)
    except cad_generate.GenerateError as e:
        logger.warning("cad_bridge: generation could not run (%s)", e.code)
        return {"ok": False, "error_code": e.code, "message": e.message,
                "attempts": getattr(e, "attempts", None) or []}
    except Exception:
        logger.exception("cad_bridge: generation raised")
        return None


def _generation_failure_text(result: Optional[dict], description: str) -> str:
    """Say which of the two failures happened, and never pretend it was the other."""
    if result is None:
        return (
            "I couldn't design that — the local CAD generator isn't available on this "
            f"deployment. I can still build a registered part: {_offer()}."
        )
    code = result.get("error_code") or "generation_failed"
    if code == "model_missing":
        # Named, not generic: now that the lane honours the selected model, "the model
        # isn't installed" leaves the user guessing which one. The generator's own
        # message already carries the tag it tried.
        detail = str(result.get("message") or "").strip()
        return ("I couldn't design that — "
                + (detail or "the model this lane uses isn't installed")
                + f". I can still build a registered part: {_offer()}.")
    lane = {
        "model_missing": "the model this lane uses isn't installed",
        "engine_unreachable": "the CAD engine isn't reachable",
        "validate_unavailable": "the CAD engine is too old to validate a document",
        "queue_full": "the CAD engine is busy",
        "model_error": "the model backend returned an error",
    }.get(code)
    if lane:
        return (f"I couldn't design that — {lane}. "
                f"I can still build a registered part: {_offer()}.")

    tries = len(result.get("attempts") or []) or 1
    detail = str(result.get("message") or "").strip()
    return (
        f"I tried {tries} time{'s' if tries != 1 else ''} to design that and couldn't "
        "get a document the engine would accept"
        + (f" — the last problem was: {detail}" if detail else "")
        + ".\n\nIt helps to give every dimension in millimetres and to say how the "
        "features sit relative to each other. I can also build a registered part "
        f"right now: {_offer()}."
    )


def _generated_title(result: dict, description: str) -> str:
    """A short label for a part that has no recipe name to borrow one from."""
    intent = str(((result.get("design_spec") or {}).get("intent")) or "").strip()
    text = re.sub(r"\s+", " ", intent or description).strip()
    if len(text) > 60:
        text = text[:57].rstrip() + "..."
    return text or "Generated part"
