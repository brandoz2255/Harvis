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


async def _inject_files(request, owui_body: dict) -> None:
    """Resolve ``owui_body['files']`` into the last user message, in place.

    Never raises — attachment resolution must not break a chat turn. A failure
    just means the file isn't injected (logged), not a 500.
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


async def run_chat_completion(request, owui_body: dict):
    # Lazy import keeps this package free of import-time coupling to the
    # workspace package (avoids any chance of a circular import at load).
    from workspace.model_proxy import execute_chat_completion

    await _inject_files(request, owui_body)
    proxy_body = owui_body_to_proxy(owui_body)
    return await execute_chat_completion(request, proxy_body)
