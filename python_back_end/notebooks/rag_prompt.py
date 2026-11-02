"""The notebook answer prompt: system rules, numbered sources, prior turns, the question.

Shared by the non-streaming chat, the onb_compat session answer and any streaming route, so
they all send the model the same messages. Pure functions; nothing here talks to a model or
the database.
"""
from typing import Any, Dict, List, Optional, Tuple

from .chat_config import length_num_predict, normalize_config, render_style_block
from .language import language_clause
from .models import ChunkWithScore, Citation
from .rag_limits import fit_to_budget, rag_context_budget

SYSTEM_RULES = """You are a helpful research assistant analyzing a notebook's sources.
Your task is to answer questions based ONLY on the provided source materials.

Important guidelines:
1. ONLY use information from the provided sources - do not use external knowledge
2. If the information is not in the sources, say "I don't see information about that in your sources"
3. Cite sources using the bracketed source NUMBER exactly as shown in the context headers — e.g. [SOURCE 1] or [SOURCE 2] (you may add the paragraph, e.g. [SOURCE 1: Para 3]). Always cite by the SOURCE number, never by the title.
4. Be direct and concise in your answers
5. If multiple sources provide relevant information, synthesize them together
6. Quote relevant passages when appropriate using quotation marks

Remember: You are a research assistant helping the user understand their uploaded materials."""

CITE_REMINDER = "Answer from the sources above only, and cite them like [SOURCE 1]."


def _one_line(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def system_prompt_for(notebook: Any, config: Optional[Dict[str, Any]]) -> str:
    """The rules, then (after them, so they cannot be overridden) style, length and language."""
    cfg = normalize_config(config)
    parts = [SYSTEM_RULES]
    title = _one_line(getattr(notebook, "title", ""), 120)
    if title:
        parts.append(f"The notebook is titled: {title}")
    style = render_style_block(cfg["persona"], cfg["style"], cfg["length"])
    if style:
        parts.append(style)
    language = language_clause(cfg["output_language"])
    if language:
        parts.append(language)
    return "\n\n".join(parts)


def build_context(chunks: List[ChunkWithScore]) -> Tuple[str, List[Citation]]:
    """Numbered source text for the prompt, and the citations in the same order.

    Each passage header is counted against the budget and long passages are shortened
    evenly, so every citation number in the prompt still has its text instead of the last
    passages being cut off the end.
    """
    headers = []
    for chunk_with_score in chunks:
        metadata = chunk_with_score.chunk.metadata or {}
        page_info = ""
        if "page" in metadata:
            page_info = f", Page {metadata['page']}"
        elif "paragraphs" in metadata:
            page_info = f", Para {metadata['paragraphs'][0]+1}" if metadata['paragraphs'] else ""
        elif metadata.get("kind") == "summary":
            page_info = f", {metadata.get('section') or 'Summary'}"
        headers.append(f"{chunk_with_score.source_title or 'Unknown Source'}{page_info}")

    overhead = sum(len(f"\n--- SOURCE {i}: {h} ---\n\n---\n") for i, h in enumerate(headers, 1))
    bodies = fit_to_budget([c.chunk.content for c in chunks], rag_context_budget() - overhead)

    context_parts = []
    citations = []
    for i, (chunk_with_score, header, body) in enumerate(zip(chunks, headers, bodies), 1):
        chunk = chunk_with_score.chunk
        metadata = chunk.metadata or {}
        context_parts.append(f"""
--- SOURCE {i}: {header} ---
{body}
---
""")
        citations.append(Citation(
            source_id=chunk.source_id,
            source_title=chunk_with_score.source_title or "Unknown Source",
            chunk_id=chunk.id,
            page=metadata.get("page"),
            section=metadata.get("section"),
            quote=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
        ))
    return "\n".join(context_parts), citations


def build_prompt_parts(
    notebook: Any, chunks: List[ChunkWithScore], config: Optional[Dict[str, Any]] = None
) -> Tuple[str, str, List[Citation]]:
    """``(system prompt, numbered context text, citations)`` for these passages."""
    context_text, citations = build_context(chunks)
    return system_prompt_for(notebook, config), context_text, citations


def compose_messages(
    system_prompt: str, context: str, history: Optional[List[Dict[str, str]]], query: str
) -> List[Dict[str, str]]:
    """Chat messages: system (rules + sources), the prior turns, then the question."""
    system = f"{system_prompt}\n\nSOURCES:\n{context}" if context else system_prompt
    messages = [{"role": "system", "content": system}]
    for turn in history or []:
        role, content = turn.get("role"), turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": f"{query}\n\n{CITE_REMINDER}" if context else query})
    return messages


def build_messages(
    notebook: Any,
    chunks: List[ChunkWithScore],
    history: Optional[List[Dict[str, str]]],
    message: str,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Everything the model is sent for one grounded answer."""
    system_prompt, context, _ = build_prompt_parts(notebook, chunks, config)
    return compose_messages(system_prompt, context, history, message)


def num_predict_for(config: Optional[Dict[str, Any]]) -> Optional[int]:
    """Reply token cap implied by the configured length; None leaves the generator default."""
    return length_num_predict(normalize_config(config)["length"])
