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

import base64
import json
import logging
import os

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
    # ones. Global always-on bled e.g. a "pirate" skill into every chat. No UI
    # populates skill_ids yet, so nothing injects until per-chat skill attach lands.
    skill_ids = owui_body.get("skill_ids")
    if not isinstance(skill_ids, list) or not skill_ids:
        return
    messages = owui_body.get("messages")
    if not isinstance(messages, list):
        return
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, content FROM owui_skills WHERE user_id=$1 "
                "AND id = ANY($2::text[]) AND enabled=TRUE",
                int(user_id), [str(s) for s in skill_ids],
            )
    except Exception:
        return
    blocks: list[str] = []
    used = 0
    for r in rows:
        c = (r["content"] or "").strip()
        body = f"### {r['name']}\n{c}" if c else f"### {r['name']}"
        if used + len(body) > 6000 and blocks:
            break
        blocks.append(body)
        used += len(body)
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

    await _inject_files(request, owui_body, user_id=user_id)
    await _inject_knowledge(request, owui_body, user_id=user_id)
    # NOTE: skills are NOT auto-injected into every chat — that bled a globally-
    # enabled skill (e.g. "always answer like a pirate") into unrelated chats.
    # Skills now apply only when explicitly attached to a chat (kb_ids-style opt-in,
    # below) — never globally. See _inject_skills.
    await _inject_skills(request, owui_body, user_id=user_id)
    await _inject_project_instructions(request, owui_body)
    await _apply_default_model(request, owui_body, user_id)  # Phase D: pref → routing
    # Phase F: cloud chat models (Claude/GPT) routed to the vendor with the user's OWN verified
    # credential — full context already injected above; never enters the native Ollama router.
    from .cloud_chat import is_cloud_chat_model, proxy_cloud_chat
    if is_cloud_chat_model(owui_body.get("model")):
        pool = getattr(request.app.state, "pg_pool", None)
        return await proxy_cloud_chat(owui_body, pool, user_id)
    # Phase E4B: the Hermes-Agent chat model is the real app's OpenAI-compatible API server
    # (a separate sidecar) — proxy it straight through, never entering the native router.
    from .hermes_chat import is_hermes_chat_model, proxy_hermes_chat
    if is_hermes_chat_model(owui_body.get("model")):
        return await proxy_hermes_chat(owui_body)
    proxy_body = owui_body_to_proxy(owui_body)
    return await execute_chat_completion(request, proxy_body)
