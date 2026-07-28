"""Bridge OWUI chat-completions to Harvis's model_proxy, in-process.

The facade authenticates the user (JWT, via ``get_current_user``) and then hands
a cleaned OpenAI body to ``model_proxy.execute_chat_completion`` — reusing
Harvis's full model-routing brain (Moonshot/NVIDIA/Ollama selection, auto-model
resolution, tool-call rescue, SSE) WITHOUT the shared-gateway-token check that
the public ``/v1/chat/completions`` route enforces. model_proxy already emits
OpenAI ``chat.completion.chunk`` SSE, which is exactly what OWUI's stream parser
consumes — so the StreamingResponse passes straight through.

Attachments (S3): OWUI sends ``files: [...]`` alongside the messages. We resolve
each into the prompt here (text/code → a context block on the last user message;
images → an OpenAI ``image_url`` content-part for vision models) before handing
the body to model_proxy. No RAG/embeddings in v1 — raw content injection.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re

from .translate import owui_body_to_proxy

logger = logging.getLogger(__name__)

# Cap injected text so a giant attachment can't blow the context budget.
_MAX_TEXT_FILE_CHARS = 24_000


def _last_user_index(messages: list) -> int:
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], dict) and messages[i].get("role") == "user":
            return i
    return -1


def _as_content_list(content) -> list:
    """Normalise a message's content to the OpenAI content-part list form."""
    if isinstance(content, list):
        return content
    return [{"type": "text", "text": content or ""}]


def _content_to_text(content) -> str:
    """Flatten a message's content (str or content-part list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def _chat_transcript(chat_obj: dict, max_chars: int = _MAX_TEXT_FILE_CHARS) -> str:
    """Flatten a stored OWUI chat blob into a readable User/Assistant transcript."""
    msgs = (chat_obj or {}).get("messages")
    if not isinstance(msgs, list):
        return ""
    lines: list[str] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = m.get("role") or ""
        c = m.get("content")
        if isinstance(c, list):  # multimodal → keep the text parts
            c = " ".join(
                p.get("text", "")
                for p in c
                if isinstance(p, dict) and p.get("type") == "text"
            )
        c = str(c or "").strip()
        if not c:
            continue
        who = "User" if role == "user" else ("Assistant" if role == "assistant" else role or "—")
        lines.append(f"{who}: {c}")
    text = "\n\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…[truncated]"
    return text


async def _inject_files(request, owui_body: dict, user_id: int | None = None) -> None:
    """Resolve ``owui_body['files']`` into the last user message, in place.

    Handles uploaded files (text → context block, image → vision part) AND
    referenced chats (``type:"chat"`` — only id+metadata arrive, so we fetch the
    referenced chat's transcript and inject it as context). Never raises — a
    failure just means that attachment isn't injected (logged), not a 500.
    """
    files = owui_body.get("files")
    if not isinstance(files, list) or not files:
        return
    messages = owui_body.get("messages")
    if not isinstance(messages, list) or not messages:
        return
    idx = _last_user_index(messages)
    if idx < 0:
        return

    pool = getattr(request.app.state, "pg_pool", None)
    text_blocks: list[str] = []
    image_parts: list[dict] = []

    for f in files:
        if not isinstance(f, dict):
            continue
        try:
            ftype = f.get("type") or ""
            url = f.get("url") or ""
            fid = f.get("id") or (f.get("file") or {}).get("id")

            # Knowledge bases (type:"collection") are handled by _inject_knowledge
            # (RAG over the KB's vector chunks) — not as a raw file.
            if ftype == "collection":
                continue

            # 0) Referenced chat (type:"chat") — the body carries only id/title,
            # so resolve the chat and inject its transcript as context.
            if ftype == "chat" and fid and pool is not None and user_id is not None:
                from . import persistence

                ref = await persistence.get_chat(pool, user_id, fid)
                if ref:
                    transcript = _chat_transcript((ref or {}).get("chat") or {})
                    if transcript:
                        title = f.get("title") or f.get("name") or ref.get("title") or "Referenced chat"
                        text_blocks.append(f"### Referenced chat: {title}\n{transcript}")
                continue

            # 1) Inline image already carrying a data/remote URL — use as-is.
            if ftype == "image" and url:
                image_parts.append({"type": "image_url", "image_url": {"url": url}})
                continue

            # 2) Uploaded file referenced by id — resolve from owui_files.
            if fid and pool is not None:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT filename, path, content_type FROM owui_files WHERE id=$1",
                        fid,
                    )
                if not row or not os.path.exists(row["path"]):
                    continue
                ctype = (row["content_type"] or "").lower()
                # Audio/video are ingested by _inject_media (Whisper transcript) —
                # never decode their raw bytes as a "text file" (that injects garbage).
                if ctype.startswith(("audio/", "video/")):
                    continue
                with open(row["path"], "rb") as fh:
                    raw = fh.read()
                if ctype.startswith("image/"):
                    b64 = base64.b64encode(raw).decode("ascii")
                    image_parts.append(
                        {"type": "image_url", "image_url": {"url": f"data:{ctype};base64,{b64}"}}
                    )
                else:
                    try:
                        text = raw.decode("utf-8", errors="replace")
                    except Exception:
                        text = ""
                    if text.strip():
                        if len(text) > _MAX_TEXT_FILE_CHARS:
                            text = text[:_MAX_TEXT_FILE_CHARS] + "\n…[truncated]"
                        text_blocks.append(f"### Attached file: {row['filename']}\n{text}")
                continue

            # 3) Inline non-image file content carried in the body (rare).
            inline = f.get("content") or (f.get("file") or {}).get("content")
            name = f.get("name") or (f.get("file") or {}).get("filename") or "attachment"
            if isinstance(inline, str) and inline.strip():
                t = inline[:_MAX_TEXT_FILE_CHARS]
                text_blocks.append(f"### Attached file: {name}\n{t}")
        except Exception:
            logger.warning("owui_compat: file injection skipped one entry", exc_info=True)

    if not text_blocks and not image_parts:
        return

    msg = messages[idx]
    content = _as_content_list(msg.get("content"))
    if text_blocks:
        block = (
            "The user attached the following file(s). Use them as context for the request.\n\n"
            + "\n\n".join(text_blocks)
        )
        content.append({"type": "text", "text": block})
    content.extend(image_parts)
    msg["content"] = content
    logger.info(
        "owui_compat: injected %d text + %d image attachment(s) into the prompt",
        len(text_blocks), len(image_parts),
    )


# ── Media / link ingestion (Phase 1) ────────────────────────────────────────────
# Paste a link (article / PDF / YouTube) or drop an mp3/mp4, and the chat reads it:
# audio/video → existing Whisper transcript; http(s) links → the existing research
# extractor. Both injected as a context block on the last user message. Reuses
# what already exists — no new deps. Gated by HARVIS_CHAT_MEDIA_INGEST (default on).
_MEDIA_INGEST_ENABLED = os.getenv("HARVIS_CHAT_MEDIA_INGEST", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
_MAX_MEDIA_URLS = 3
_MAX_MEDIA_FILES = 3
_MAX_MEDIA_CHARS = 24_000
_URL_RE = re.compile(r"""https?://[^\s<>"')\]}]+""", re.IGNORECASE)
# Process-lifetime transcript cache so a re-sent attachment isn't re-transcribed
# every turn (Whisper is expensive on the 8GB box). Bounded; keyed by file id.
_transcript_cache: dict[str, str] = {}


def _extract_urls(text: str) -> list[str]:
    """Deduped http(s) URLs from the user's message, trailing punctuation stripped."""
    seen: list[str] = []
    for m in _URL_RE.findall(text or ""):
        u = m.rstrip(".,;:!?)]}\"'")
        if u and u not in seen:
            seen.append(u)
        if len(seen) >= _MAX_MEDIA_URLS:
            break
    return seen


def _whisper_text(res) -> str:
    """transcription.transcribe returns a dict ({'text': ...}); tolerate a str."""
    if isinstance(res, dict):
        return str(res.get("text") or "").strip()
    return str(res or "").strip()


async def _inject_media(request, owui_body: dict, user_id: int | None = None) -> None:
    """Ingest media the user shared into the last user message as context:
    audio/video attachments → Whisper transcript; http(s) links in the message →
    readable text (article/PDF/YouTube) via the research extractor. Every URL passes
    the SSRF guard first. Runs BEFORE _inject_files so the URL scan sees the original
    message. Never raises — a failed item is skipped (logged), not a 500."""
    if not _MEDIA_INGEST_ENABLED:
        return
    messages = owui_body.get("messages")
    if not isinstance(messages, list) or not messages:
        return
    idx = _last_user_index(messages)
    if idx < 0:
        return

    blocks: list[str] = []

    # 1) Audio/video attachments → Whisper transcript (ffmpeg decodes mp4/mov/webm).
    files = owui_body.get("files")
    if isinstance(files, list) and files:
        pool = getattr(request.app.state, "pg_pool", None)
        done = 0
        for f in files:
            if done >= _MAX_MEDIA_FILES:
                break
            if not isinstance(f, dict):
                continue
            fid = f.get("id") or (f.get("file") or {}).get("id")
            if not fid or pool is None:
                continue
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT filename, path, content_type FROM owui_files WHERE id=$1", fid
                    )
                if not row:
                    continue
                ctype = (row["content_type"] or "").lower()
                if not ctype.startswith(("audio/", "video/")):
                    continue
                if not row["path"] or not os.path.exists(row["path"]):
                    continue
                transcript = _transcript_cache.get(str(fid))
                if transcript is None:
                    from transcription import transcribe as transcribe_audio

                    res = await asyncio.to_thread(transcribe_audio, row["path"])
                    transcript = _whisper_text(res)
                    if len(transcript) > _MAX_MEDIA_CHARS:
                        transcript = transcript[:_MAX_MEDIA_CHARS] + "\n…[truncated]"
                    _transcript_cache[str(fid)] = transcript
                    if len(_transcript_cache) > 256:
                        _transcript_cache.pop(next(iter(_transcript_cache)))
                if transcript:
                    kind = "video" if ctype.startswith("video/") else "audio"
                    blocks.append(f"### Transcript of attached {kind} — {row['filename']}\n{transcript}")
                    done += 1
            except Exception:
                logger.warning("owui_compat: media transcription skipped one file", exc_info=True)

    # 2) http(s) links in the message → readable text (article / PDF / YouTube).
    urls = _extract_urls(_content_to_text(messages[idx].get("content")))
    if urls:
        for url in urls:
            # A URL in the user's message is a request to read it. When we can't,
            # say so in-band — a silent drop lets the model answer confidently
            # about content it never received (i.e. hallucinate), which reads to
            # the user as success. An honest marker lets the model caveat instead.
            try:
                from tools.openclaw_proxy import _validate_url

                try:
                    _validate_url(url)  # SSRF: reject private/localhost/non-http(s)
                except Exception:
                    logger.info("owui_compat: media ingest skipped blocked URL %s", url)
                    blocks.append(f"### Could not read {url}\n(blocked: address not permitted for fetching)")
                    continue
                from research.extract.router import extract_url

                doc = await asyncio.to_thread(extract_url, url)
                text = (getattr(doc, "text", "") or "").strip()
                if not (getattr(doc, "success", False) and text):
                    blocks.append(f"### Could not read {url}\n(the page could not be fetched or had no readable text)")
                    continue
                if len(text) > _MAX_MEDIA_CHARS:
                    text = text[:_MAX_MEDIA_CHARS] + "\n…[truncated]"
                title = (getattr(doc, "title", "") or "").strip()
                header = f"### Content from {url}" + (f" — {title}" if title else "")
                blocks.append(f"{header}\n{text}")
            except Exception:
                logger.warning("owui_compat: media ingest skipped one URL", exc_info=True)
                blocks.append(f"### Could not read {url}\n(fetch failed)")

    if not blocks:
        return
    msg = messages[idx]
    content = _as_content_list(msg.get("content"))
    content.append(
        {
            "type": "text",
            "text": "The user shared the media/link(s) below. Their transcribed/extracted "
            "content is provided as context — use it to answer.\n\n" + "\n\n".join(blocks),
        }
    )
    msg["content"] = content
    logger.info("owui_compat: injected %d media/link context block(s)", len(blocks))


async def _inject_knowledge(request, owui_body: dict, user_id: int | None = None) -> None:
    """K3 RAG: when the chat carries attached knowledge base(s) (OWUI sends them
    as ``{type:"collection", id}`` entries inside ``files``), embed the latest
    user message, vector-search each KB's chunks, and inject the top matches as a
    context block on the last user message. Never raises — a failure just means
    no KB context is injected (logged), not a 500.
    """
    files = owui_body.get("files")
    if not isinstance(files, list) or not files:
        return
    kb_ids = [
        f.get("id")
        for f in files
        if isinstance(f, dict) and f.get("type") == "collection" and f.get("id")
    ]
    if not kb_ids:
        return
    messages = owui_body.get("messages")
    if not isinstance(messages, list) or not messages:
        return
    idx = _last_user_index(messages)
    if idx < 0:
        return
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return
    query_text = _content_to_text(messages[idx].get("content"))
    if not query_text.strip():
        return
    try:
        from . import knowledge as kb

        blocks = await kb.retrieve_context(pool, kb_ids, query_text, user_id=user_id)
    except Exception:
        logger.warning("owui_compat: knowledge injection failed", exc_info=True)
        return
    if not blocks:
        return

    msg = messages[idx]
    content = _as_content_list(msg.get("content"))
    block = (
        "The user attached the following knowledge base(s). Use the retrieved "
        "context below to answer; cite the file path when relevant.\n\n"
        + "\n\n".join(blocks)
    )
    content.append({"type": "text", "text": block})
    msg["content"] = content
    logger.info(
        "owui_compat: injected %d knowledge block(s) from %d KB(s)", len(blocks), len(kb_ids)
    )


async def _inject_skills(request, owui_body: dict, user_id: int | None = None) -> None:
    """Inject the user's ENABLED Customize skills as a system message, so a skill
    created in Agent Studio → Customize actually shapes the agent's behaviour (the
    runtime half of the Skills builder). Bounded so many skills can't blow the
    context budget. Never raises. (MCP connections reaching the runtime remains a
    separate, deferred bridge.)
    """
    if user_id is None:
        return
    # Only skills EXPLICITLY attached to THIS chat (skill_ids) — NEVER all enabled
    # ones. Global always-on bled e.g. a "pirate" skill into every chat. skill_ids is
    # populated by the composer $-mention picker (and model-level attach); injection is
    # additionally AUDIT-GATED below — only a skill a human marked 'supported' in
    # Customize → Skills gets its body injected. Everything else gets an honest note.
    skill_ids = owui_body.get("skill_ids")
    if not isinstance(skill_ids, list) or not skill_ids:
        return
    messages = owui_body.get("messages")
    if not isinstance(messages, list):
        return
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return

    # THE fail-closed per-skill gate (capabilities ready + lane enabled + human
    # 'supported' verdict, else an honest 'unavailable' note) lives in
    # skills.gated_skill_blocks — SHARED with sub-agent runs (orchestrator), so
    # both paths get byte-identical governance. Chat supplies the capability
    # resolver (it has a request context to probe with).
    async def _ready_caps() -> set:
        from .capabilities import ready_capability_keys
        return await ready_capability_keys(request, int(user_id))

    try:
        from .skills import gated_skill_blocks

        blocks = await gated_skill_blocks(
            pool, int(user_id), skill_ids, ready_caps_resolver=_ready_caps
        )
    except Exception:
        logger.warning("owui_compat: skill gate failed — injecting nothing (fail-closed)", exc_info=True)
        return
    if not blocks:
        return
    messages.insert(
        0,
        {
            "role": "system",
            "content": "Active skills — apply these capabilities/instructions when relevant:\n\n"
            + "\n\n".join(blocks),
        },
    )
    logger.info("owui_compat: injected %d active skill(s) into the prompt", len(blocks))


async def _inject_project_instructions(request, owui_body: dict) -> None:
    """If the chat belongs to a Project (folder), prepend that project's custom
    instructions (folder.data.system_prompt) as a system message so they apply
    to the whole conversation — Claude-Projects style. ``chat_id`` rides in the
    OWUI body (stripped later by owui_body_to_proxy). Never raises.
    """
    chat_id = owui_body.get("chat_id")
    if not chat_id:
        return
    messages = owui_body.get("messages")
    if not isinstance(messages, list):
        return
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return
    try:
        from . import persistence

        instructions = await persistence.get_chat_folder_system_prompt(pool, chat_id)
    except Exception:
        logger.warning("owui_compat: project-instruction lookup failed", exc_info=True)
        return
    if not instructions:
        return
    messages.insert(
        0,
        {
            "role": "system",
            "content": "Project instructions (apply to this whole conversation):\n" + instructions,
        },
    )
    logger.info("owui_compat: injected project instructions (%d chars)", len(instructions))


# Authoring contract for the typed ```canvas panel (rendered by the OWUI frontend:
# CanvasRenderer.svelte inline in the message + auto-popped into the Artifacts
# rail). COMPACT + OPT-IN ("MAY") so ordinary chat behaviour is unchanged, and
# model-friendly enough for small local models to emit reliably.
_CANVAS_CONTRACT = (
    "Rich data panels: for data-heavy or analytical answers (metrics, tables, comparisons, "
    "breakdowns) you MAY add one fenced ```canvas code block containing ONLY valid JSON:\n"
    '{"title":"...","blocks":[\n'
    '{"kind":"stat","label":"Total errors","value":"15","delta":"-12%","tone":"good"},\n'
    '{"kind":"table","headers":["Service","Errors"],"rows":[["auth","12"],["chat","3"]]},\n'
    '{"kind":"chart","chartType":"bar","categories":["auth","chat"],'
    '"series":[{"name":"Errors","data":[12,3]}]},\n'
    '{"kind":"callout","tone":"warning","text":"auth error rate rising"},\n'
    '{"kind":"diff","language":"python","before":"x=1","after":"x=2"},\n'
    '{"kind":"heading","text":"..."},\n'
    '{"kind":"text","text":"..."}]}\n'
    "chartType: bar|line|pie. tone: info|good|warning|danger. "
    "Use plain markdown for simple replies; never wrap a whole answer in canvas."
)


def _inject_canvas_contract(owui_body: dict) -> None:
    """Teach the model the typed ```canvas block (stat/table/chart/callout/diff
    panels the OWUI frontend renders inline + in the Artifacts rail). Never
    raises; a body without a messages list is left untouched."""
    messages = owui_body.get("messages")
    if not isinstance(messages, list):
        return
    messages.insert(0, {"role": "system", "content": _CANVAS_CONTRACT})


# Sentinels that mean "no explicit model was chosen" — route these to the user's
# saved Integrations default model (Phase D). A real model name is left untouched.
_NO_MODEL_SENTINELS = {"", "auto", "default", "user-pref", "dynamic"}


async def _apply_default_model(request, owui_body: dict, user_id: int | None) -> None:
    """Phase D — backend run-time routing from the user's saved preference.

    When a request arrives WITHOUT an explicit model (empty / an auto sentinel),
    substitute the user's server-side `default_model` (Integrations preference,
    set via Phase C2). This is what makes a saved default actually drive routing
    for clients that don't pre-fill a model (raw API hitting the facade). Normal
    OWUI chat always sends an explicit model, so this is a no-op there. The direct
    OpenClaw/Discord path bypasses the facade, so its global `/model` pick still
    applies. Fail-soft: any error leaves the body untouched and model_proxy's own
    auto-resolution still runs."""
    try:
        if user_id is None:
            return
        m = (owui_body.get("model") or "").strip()
        if m.lower() not in _NO_MODEL_SENTINELS:
            return
        from .capabilities import _read_integrations

        pool = getattr(request.app.state, "pg_pool", None)
        _prefs, default_model = await _read_integrations(pool, int(user_id))
        if default_model:
            owui_body["model"] = default_model
    except Exception:
        pass


async def run_chat_completion(request, owui_body: dict, user_id: int | None = None):
    # Lazy import keeps this package free of import-time coupling to the
    # workspace package (avoids any chance of a circular import at load).
    from workspace.model_proxy import execute_chat_completion

    await _inject_media(request, owui_body, user_id=user_id)  # links/audio/video → context
    await _inject_files(request, owui_body, user_id=user_id)
    await _inject_knowledge(request, owui_body, user_id=user_id)
    # NOTE: skills are NOT auto-injected into every chat — that bled a globally-
    # enabled skill (e.g. "always answer like a pirate") into unrelated chats.
    # Skills now apply only when explicitly attached to a chat (kb_ids-style opt-in,
    # below) — never globally. See _inject_skills.
    await _inject_skills(request, owui_body, user_id=user_id)
    await _inject_project_instructions(request, owui_body)
    _inject_canvas_contract(owui_body)  # typed ```canvas panels (opt-in, compact)
    await _apply_default_model(request, owui_body, user_id)  # Phase D: pref → routing
    # NOTE: model choice is strictly SELECTION-BASED — the picked model is always used. An
    # auto-model-swap router was built + verified here (2026-07-10) and then removed at the
    # user's request; see docs/handoffs/2026-07-10-model-picker-effort-slider.md if revisited.
    # Phase F: cloud chat models (Claude/GPT) routed to the vendor with the user's OWN verified
    # credential — full context already injected above; never enters the native Ollama router.
    from .cloud_chat import is_cloud_chat_model, proxy_cloud_chat
    if is_cloud_chat_model(owui_body.get("model")):
        pool = getattr(request.app.state, "pg_pool", None)
        return await proxy_cloud_chat(owui_body, pool, user_id)
    # H2: Hermes Agent as a Chat "Agent Mode" — the request carries harvis_agent_mode='hermes'
    # (the user's picked model does NOT drive Hermes; its own runtime model does). The legacy
    # sentinel-model path is kept for back-compat. Routed to the real app's API server (sidecar),
    # never the native router. Uses the per-user resolved Hermes model.
    from .hermes_chat import is_hermes_chat_model, proxy_hermes_chat
    if (owui_body.get("harvis_agent_mode") == "hermes") or is_hermes_chat_model(owui_body.get("model")):
        pool = getattr(request.app.state, "pg_pool", None)
        return await proxy_hermes_chat(owui_body, pool, user_id)
    proxy_body = owui_body_to_proxy(owui_body)
    return await execute_chat_completion(request, proxy_body)
