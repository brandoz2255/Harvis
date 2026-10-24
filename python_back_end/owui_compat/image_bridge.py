"""OWUI-facade image-generation bridge.

When an OWUI chat-completion request asks for an image — either the explicit
``harvis_image_generate`` flag from the composer's "+ → Create Image" item, or a
conservative natural-language match ("generate an image of X", "draw a cat"; questions,
code/tech context and an explicit Agent/Orchestrate pick are never matched) — run the
VERIFIED v0 generation path (``image.harvis_image._run_generation``: provider
txt2img → binary artifact → 'artifact' trace event) as a background WORKSPACE
run and return the same ``<details type="workspace_run">`` marker SSE that
``workspace_bridge.maybe_handle_workspace`` emits. The existing WorkspaceRunCard
attaches to ``GET /api/workspace/stream/{id}`` and the Artifacts rail previews
the PNG — no new frontend plumbing.

Gating is HONEST and never hijacks a normal chat: flag off / provider not ready
→ BOTH triggers get a short plain-text SSE saying why (a matched image request
that silently reached a model made the model guess). Never raises — any other
failure on the NL path → ``None`` → normal chat.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from types import SimpleNamespace
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Conservative NL trigger: an explicit generate-verb within a SHORT gap of an
# image-noun ("generate an image of X", "can you make me an image of Y").
# Strict on purpose — "explain this image" / "search for pictures" must NOT
# match; a demonstrative/possessive in the gap ("make THIS picture bigger")
# means an EXISTING image; and the 12-char gap cap keeps unrelated objects out
# ("create a function for photo resize").
_IMAGE_NL_RE = re.compile(
    r"\b(generate|create|make|draw|paint|render)\b"
    r"(?:(?!\b(?:this|that|these|those|my|your|his|her|its|our|their|the|sure|it)\b).){0,12}?"
    r"\b(image|picture|photo|drawing|art|illustration|painting)\b",
    re.IGNORECASE | re.DOTALL,
)

# "draw a cat" names no image-noun, so it gets its own anchored trigger. The veto scans the
# first four words after the article, so "draw a network diagram", "draw a bar chart" and
# "draw an ascii art cat" keep reaching the model, as do "draw a conclusion" and "draw a box".
_DRAW_RE = re.compile(
    r"^\s*(?:please\s+)?draw\s+(?:me\s+)?(?:a|an)\s+"
    r"(?!(?:\S+\s+){0,3}?(?:conclusion|comparison|parallel|distinction|diagram|chart|graph|"
    r"flow\s*chart|flowchart|table|uml|mermaid|ascii|box|circle|square|rectangle|triangle|"
    r"polygon|grid|spiral|fractal|histogram|plot|heatmap|timeline|wireframe|mockup|layout|"
    r"line|border|blank|picture|image|photo|drawing|svg|canvas|curve|arrow|shape|pattern|"
    # idioms and extraction senses: "draw a card", "draw a breath", "draw a random sample"
    r"inference|inferences|sample|samples|lesson|lessons|card|cards|number|numbers|breath|"
    r"crowd|crowds|salary|wage|herring|bath|attention|random|raffle|lottery|ticket|"
    r"audience|customers|visitors|analogy|moral|check|cheque|winner|straw|bead|paycheck)\b)"
    r"\w+",
    re.IGNORECASE,
)
_DRAW_LEAD_RE = re.compile(r"^\s*(?:please\s+)?draw\s+(?:me\s+)?", re.IGNORECASE)
# "draw a X from/between/out of ..." is the extraction sense (a sample, a card, a number), and
# a long message is a sentence about drawing, not a picture request. Neither claims the image lane.
_DRAW_VETO_RE = re.compile(
    r"\b(?:from|between|among|amongst|out\s+of|at\s+random|randomly)\b|\bof\s+\d", re.IGNORECASE
)
_DRAW_MAX_WORDS = 20

# Subject lead-ins after the image-noun: "of a fox", "showing a fox", ": a fox".
_SUBJECT_LEAD_RE = re.compile(r"^\s*(?:(?:of|showing|depicting)\b|[:,\-])\s*", re.IGNORECASE)

# Explicit forced prefix the composer "+" → "Create image" button inserts:
# "🖼️ create image <description>". Deterministic — forces the image lane (no NL
# guessing); an optional leading image emoji is tolerated, and the remainder IS the prompt.
_EXPLICIT_PREFIX_RE = re.compile(
    r"^\s*(?:[\U0001F5BC\U0001F3A8\U0001F4F7\U0001F58C\U0001F4F8]️?\s*)?"
    # No \b after "image": the composer can drop the trailing space ("create imagea fox"),
    # so match the literal phrase and let the remainder (incl. a run-on first word) be the prompt.
    r"create\s+image[\s:>\-]*",
    re.IGNORECASE,
)


def _extract_prompt(message: str) -> str:
    """Strip the leading generate-command and keep the subject as the prompt:
    "generate an image of a red fox in snow" → "a red fox in snow". Falls back
    to the whole message when there's no match or no remaining subject."""
    msg = (message or "").strip()
    m = _IMAGE_NL_RE.search(msg)
    if not m:
        if _DRAW_RE.match(msg):
            return _DRAW_LEAD_RE.sub("", msg, count=1).strip() or msg
        return msg
    rest = msg[m.end():].strip()
    rest = _SUBJECT_LEAD_RE.sub("", rest, count=1).strip()
    return rest or msg


# A matched request now gets a hard notice instead of a model answer, so the loose verb+noun
# match alone is not enough: the noun must be followed by a subject ("image OF a fox"), and
# questions or code/tech context ("how do I make an image smaller in css", "create a photo
# gallery website") stay with the model.
_SUBJECT_GATE_RE = re.compile(r"\s*(?:(?:of|showing|depicting)\b|:)", re.IGNORECASE)
_QUESTION_LEAD_RE = re.compile(
    r"^\s*(?:how|what|why|which|where|when|who|explain|is|are|does|do|should|could\s+i|can\s+i|"
    r"tell\s+me|show\s+me\s+how|teach\s+me|walk\s+me\s+through|help\s+me\s+(?:learn|understand)|"
    r"i\s+(?:want|need|would\s+like|'d\s+like|wanna)\s+to\s+(?:learn|understand|know)|"
    r"i(?:'m|\s+am)\s+(?:trying|learning|curious)|(?:learn|guide|tutorial|instructions)\b)",
    re.IGNORECASE,
)
# A how-to or tutorial question phrased as an instruction ("tell me how to generate an image of a
# fox in stable diffusion") is about the technique, not a request to make the picture.
_HOWTO_RE = re.compile(
    r"\bhow\s+(?:to|do|can|could|would|should|does|did|about)\b|\b(?:tutorial|instructions|"
    r"step[- ]by[- ]step|steps\s+to|way\s+to|ways\s+to|learn\s+to|learn\s+how)\b",
    re.IGNORECASE,
)
_TECH_CONTEXT_RE = re.compile(
    r"\b(?:docker|dockerfile|kubernetes|k8s|container|containers|css|html|react|vue|angular|"
    r"website|webpage|web\s+page|app|apps|gallery|upload|thumbnail|thumbnails|frame|function|"
    r"script|code|python|javascript|typescript|flask|django|api|sql|database|schema|diagram|"
    r"chart|graph|flowchart|uml|mermaid|ascii|svg|homelab|network|architecture|pipeline|"
    r"library|package|npm|pip|css3|canvas|turtle|matplotlib|csv|dataset|spreadsheet|excel|json|"
    r"rows|deck|gimp|photoshop|illustrator|blender|inkscape|figma|canva)\b",
    re.IGNORECASE,
)


def _is_image_request(message: str) -> bool:
    """The strict natural-language image trigger: verb + image-noun + subject, or anchored
    'draw a X'. Questions and code/tech context never count."""
    if (
        not message
        or _QUESTION_LEAD_RE.match(message)
        or _HOWTO_RE.search(message)
        or _TECH_CONTEXT_RE.search(message)
    ):
        return False
    if _DRAW_RE.match(message):
        return not _DRAW_VETO_RE.search(message) and len(message.split()) <= _DRAW_MAX_WORDS
    return any(
        _SUBJECT_GATE_RE.match(message[m.end():]) for m in _IMAGE_NL_RE.finditer(message)
    )


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
    """Honest short assistant message (explicit trigger only) — flag off /
    provider not ready. Reuses the workspace bridge's OpenAI-chunk shape."""
    from .workspace_bridge import _openai_sse_lines

    return _sse_response(_openai_sse_lines(uuid.uuid4().hex[:8], text))


async def maybe_handle_image_generation(
    request: Request, owui_body: dict, user
) -> Optional[StreamingResponse]:
    """If this chat turn is an image request, launch a generation run and return
    the run-marker SSE. Otherwise return ``None`` (caller falls through — first
    to the workspace detector, then to a normal chat completion)."""
    try:
        return await _handle(request, owui_body, user)
    except Exception:
        logger.exception("owui image_bridge: interceptor failed; falling through")
        return None


async def _handle(request: Request, owui_body: dict, user) -> Optional[StreamingResponse]:
    from .workspace_bridge import (
        _last_user_message,
        _marker_content,
        _messages_to_history,
        _openai_sse_lines,
    )

    explicit = bool(owui_body.get("harvis_image_generate"))  # Trigger A: the + button
    history = _messages_to_history(owui_body)
    message = str(owui_body.get("harvis_image_prompt") or "").strip() or _last_user_message(history)
    if not message.strip():
        return None
    # Trigger A2 (the + button): an explicit "🖼️ create image <desc>" prefix. Deterministic —
    # forces the image lane (honest errors, not silent fallthrough) and IS the prompt verbatim.
    forced_prompt = None
    pref = _EXPLICIT_PREFIX_RE.match(message)
    if pref:
        forced_prompt = message[pref.end():].strip()
        if not forced_prompt:
            return None  # just the marker, no description yet — don't generate
        explicit = True
    if not explicit:  # Trigger B: strict NL match; an explicit Agent/Orchestrate pick is never taken
        mode = str(owui_body.get("harvis_mode") or "auto").strip().lower()
        if mode in ("agent", "orchestrate") or not _is_image_request(message):
            return None

    # Lazy imports — same idiom as workspace_bridge; keep the facade decoupled.
    try:
        from image.harvis_image import _image_gen_enabled, _run_generation
        from image.provider import GenSpec, resolve_provider
    except Exception:
        logger.exception("owui image_bridge: image module import failed")
        return _notice_sse("Image generation is unavailable on this deployment.") if explicit else None

    # GATING — honest for both triggers: say why and how to fix it, with no model call.
    if not _image_gen_enabled():
        return _notice_sse(
            "Image generation is disabled on this install, so I can't make that picture. "
            "To turn it on, set HARVIS_OWUI_IMAGE_GENERATION=true and run an image provider "
            "(A1111 or ComfyUI), then restart the backend."
        )
    provider = await resolve_provider()
    if provider.id == "none":
        reason = (await provider.readiness()).get("reason") or "no image provider ready"
        return _notice_sse(
            f"Image generation isn't ready, so I can't make that picture: {reason}. "
            "Start an image provider (A1111 or ComfyUI) and try again."
        )

    try:
        spec = GenSpec(prompt=(forced_prompt if forced_prompt is not None else _extract_prompt(message)))
    except ValueError as exc:
        return _notice_sse(f"Can't generate an image: {exc}") if explicit else None

    pool = getattr(request.app.state, "pg_pool", None)
    user_id = getattr(user, "id", None)
    if pool is None or user_id is None:
        return _notice_sse("Image generation is unavailable right now (no database).") if explicit else None

    try:
        from workspace.terminal_container import emit_terminal_event
        from workspace.workspace_router import (
            WorkspaceLiveBroadcaster,
            _db_complete_run,
            _db_create_run,
            _workspace_broadcasters,
            _workspace_tasks,
            _workspaces,
        )
    except Exception:
        logger.exception("owui image_bridge: workspace import failed")
        return _notice_sse("Image generation is unavailable right now.") if explicit else None

    run_id = f"img_{uuid.uuid4().hex[:12]}"
    session_id = owui_body.get("chat_id") or owui_body.get("session_id") or f"owui-{run_id}"
    task_brief = f"Image: {spec.prompt[:200]}"
    started_epoch = time.monotonic()

    # Register the run in memory so the card's /api/workspace/stream/{id} gets the
    # LIVE phase (broadcaster fan-out), not just DB replay. No OpenClaw session —
    # generation is a local provider call, so client is None (Stop still works:
    # cancel tolerates a failed client.cancel and cancels the asyncio task).
    _workspaces[run_id] = {
        "client": None,
        "status": "running",
        "task_brief": task_brief,
        "session_id": session_id,
        "chat_history": history,
        "user_id": user_id,
        "started_epoch": started_epoch,
        "agent_id": "image",
        "model_name": provider.id,
        "launch_mode": "user",
    }
    _workspace_broadcasters[run_id] = WorkspaceLiveBroadcaster()
    # FK: the run row must exist before any event lands (workspace_events FKs it).
    await _db_create_run(pool, run_id, user_id, session_id, task_brief, model_name=provider.id)

    async def _bg():
        ws = _workspaces.get(run_id) or {}
        try:
            await emit_terminal_event(
                pool, run_id, event_type="tool_call",
                payload={
                    "tool": "image.generate",
                    "args": {
                        "provider": provider.id,
                        "prompt": spec.prompt[:120],
                        "width": spec.width, "height": spec.height, "steps": spec.steps,
                    },
                },
            )
            # The VERIFIED v0 path: txt2img → binary artifact → 'artifact' event →
            # run completion ('completed', or 'error' + terminal 'error' event).
            # It never raises — read back the outcome it persisted.
            await _run_generation(pool, run_id, provider, spec, started_epoch)
            async with pool.acquire() as conn:
                status = await conn.fetchval(
                    "SELECT status FROM workspace_runs WHERE id = $1", run_id
                )
                artifact_id = await conn.fetchval(
                    """
                    SELECT id FROM workspace_artifacts
                    WHERE workspace_id = $1 AND artifact_type = 'file' AND content_bytes IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    run_id,
                )
            if status == "completed" and artifact_id:
                summary = (
                    "Generated your image.\n\n"
                    f"![generated](/api/workspace/artifact/{artifact_id}/raw)"
                )
                await emit_terminal_event(
                    pool, run_id, event_type="tool_result",
                    payload={"tool": "image.generate", "success": True,
                             "output": f"{spec.width}x{spec.height} PNG via {provider.id}"},
                )
                await emit_terminal_event(
                    pool, run_id, event_type="final_message",
                    payload={"run_id": run_id, "content": summary},
                )
                await emit_terminal_event(
                    pool, run_id, event_type="done",
                    payload={"run_id": run_id, "summary": summary},
                )
                ws["status"] = "done"
            else:
                # _run_generation already emitted the terminal 'error' event and
                # completed the run with the honest reason.
                ws["status"] = "error"
        except asyncio.CancelledError:
            ws["status"] = "cancelled"
            await emit_terminal_event(
                pool, run_id, event_type="cancelled",
                payload={"message": "Image generation cancelled."},
            )
            await _db_complete_run(
                pool, run_id, "cancelled", None, "cancelled by user",
                tool_calls=1, event_count=2, started_epoch=started_epoch,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("owui image_bridge: run %s failed", run_id)
            ws["status"] = "error"
            await emit_terminal_event(
                pool, run_id, event_type="error",
                payload={"run_id": run_id, "message": f"image generation failed: {exc}"},
            )
            await _db_complete_run(
                pool, run_id, "error", None, f"image generation failed: {exc}",
                tool_calls=1, event_count=2, started_epoch=started_epoch,
            )
        finally:
            broadcaster = _workspace_broadcasters.get(run_id)
            if broadcaster is not None:
                await broadcaster.put(None)  # sentinel: stream has ended
            _workspace_tasks.pop(run_id, None)

    _workspace_tasks[run_id] = asyncio.create_task(_bg(), name=f"workspace-{run_id}")
    logger.info(
        "owui image_bridge: launched %s (provider=%s explicit=%s)", run_id, provider.id, explicit
    )

    suggestion = SimpleNamespace(
        task_type="image_generation",
        task_type_label="Image generation",
        task_brief=spec.prompt,
    )
    return _sse_response(
        _openai_sse_lines(run_id, _marker_content(run_id, suggestion, engine="Image"))
    )
