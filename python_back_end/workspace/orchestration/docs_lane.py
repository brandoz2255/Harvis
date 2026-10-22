"""The harvis-doc tools for native workspace runs.

A workspace run is a tool loop around a local model. It had no way to look up the document
format, check a draft, see its own slides or make the file; the pipeline lives in
:mod:`owui_compat.docs_tools` and is already offered to chat and to MCP sidecars. This module
is the loop's adapter: it offers the same five tools (``docs_guide``, ``docs_validate``,
``docs_preview``, ``docs_check``, ``docs_export``) and turns each result into the short plain
text a small model can act on.

The names are the unprefixed ones the MCP sidecar shows, so a model sees one vocabulary
everywhere. None of them is in ``TOOL_SCHEMA``, so ``dispatch_tool`` never sees them: the
runner routes them here first, the way it routes ``mcp__*`` tools to the connector runtime.

No heavy import happens at module load. ``tools.py`` imports the name tuple for lane
classification, and the document pipeline (python-pptx, the render client) is only wanted
once a run actually calls a docs tool.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Kept literal so tools.py can classify lanes without importing the pipeline; a test pins
# it to docs_tools.TOOL_NAMES.
DOCS_TOOL_NAMES: tuple[str, ...] = (
    "docs_guide", "docs_validate", "docs_export", "docs_preview", "docs_check",
)
# docs_export stores a file in the caller's own file store; the rest only read.
DOCS_WRITE_TOOLS: frozenset[str] = frozenset({"docs_export"})
DOCS_READ_TOOLS: frozenset[str] = frozenset(DOCS_TOOL_NAMES) - DOCS_WRITE_TOOLS

MAX_PAGE_CHARS = 1200      # per previewed page; the model needs the words, not the layout
MAX_ISSUES = 30
MAX_ERROR_CHARS = 600


def is_docs_tool(name: str) -> bool:
    return name in DOCS_TOOL_NAMES


def docs_tool_specs() -> list[dict]:
    """The five OpenAI function specs. Non-strict: strict mode makes every optional argument
    nullable, which small local models answer with ``null`` or a made-up value."""
    from owui_compat import docs_tools

    return docs_tools.openai_tools(strict=False)


def _problem_lines(payload: dict) -> list[str]:
    return [f"- {p}" for p in (payload.get("problems") or [])[:MAX_ISSUES]]


def _issue_lines(payload: dict) -> list[str]:
    out = []
    for it in (payload.get("issues") or [])[:MAX_ISSUES]:
        where = f" ({it['where']})" if it.get("where") else ""
        out.append(f"- {it.get('severity', 'issue')}{where}: {it.get('message', '')}")
    return out


def _compact(name: str, payload: dict, ok: bool) -> tuple[str, bool]:
    """``(text, ok)`` for one result. Never carries page images or base64 file bytes."""
    if not ok:
        return (f"ERROR: {str(payload.get('error') or f'{name} failed.')[:MAX_ERROR_CHARS]}", False)

    if name == "docs_guide":
        return (str(payload.get("guide") or ""), True)

    if name == "docs_validate":
        head = f"kind={payload.get('kind')} title={payload.get('title')!r} parts={payload.get('parts')}"
        if payload.get("ok"):
            return (f"VALID. {head}. No problems.", True)
        return ("\n".join([f"NOT VALID. {head}. Fix these, then validate again:", *_problem_lines(payload)]), True)

    if name == "docs_check":
        lines = _issue_lines(payload)
        render = "" if (payload.get("checked") or {}).get("render") else " (page render unavailable, code checks only)"
        if not lines:
            return (f"CHECK PASSED{render}. No findings.", True)
        verdict = "CHECK PASSED with notes" if payload.get("ok") else "CHECK FAILED"
        return ("\n".join([f"{verdict}{render}. Findings:", *lines]), True)

    if name == "docs_preview":
        pages = payload.get("pages") or []
        lines = [f"Rendered {payload.get('format')}: {payload.get('page_count')} page(s), "
                 f"showing {len(pages)}. Page text only; you cannot see the images."]
        for p in pages:
            text = " ".join(str(p.get("text") or "").split())[:MAX_PAGE_CHARS]
            lines.append(f"--- page {p.get('page')} ---\n{text or '(no text on this page)'}")
        return ("\n".join(lines), True)

    if name == "docs_export":
        url = payload.get("download_url")
        if not url:
            return (f"ERROR: built {payload.get('filename')} ({payload.get('bytes')} bytes) but it could not be "
                    "saved to the user's file store, so there is no download link. Do not tell the user it "
                    "was saved.", False)
        return (f"Saved {payload.get('filename')} ({payload.get('bytes')} bytes). "
                f"download_url: {url}", True)

    return (str(payload)[:MAX_ERROR_CHARS], True)


async def dispatch_docs_tool(name: str, args: dict, *, pool, user_id) -> tuple[str, bool]:
    """Run one docs tool for a workspace run. Returns ``(text, ok)`` and never raises."""
    try:
        from owui_compat import docs_tools

        ctx = docs_tools.DocsToolContext(pool=pool, user_id=user_id, source="workspace")
        payload, ok = await docs_tools.dispatch(name, args, ctx)
        return _compact(name, payload, ok)
    except Exception:
        logger.exception("docs lane: %s failed unexpectedly", name)
        return (f"ERROR: {name} failed unexpectedly.", False)
