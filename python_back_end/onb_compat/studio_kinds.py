"""Studio kinds that are exported as files: data tables (CSV) and slide decks (PPTX).

Pure functions, no web stack. ``studio_generate`` registers the schemas and prompts here
with its structured kinds, ``studio_routes`` serves the downloads, and the tests call the
normalisers and builders directly.

A data table is stored as ``{title, columns[str], rows[{cells[str], source}]}``: the source
column is kept apart from the cells so the viewer can style it and the CSV can put it last.
A slide deck is stored as ``{title, slides[{title, bullets[str], notes, source}]}``. That
outline is the artifact; the PPTX is rebuilt from it on every download, so an edited or
revised outline is exported as it stands.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_COLUMNS = 12
MAX_ROWS = 60
MAX_CELL_CHARS = 400
MAX_SLIDES = 20
MAX_BULLETS = 7
MAX_BULLET_CHARS = 220
MAX_INSTRUCTION_CHARS = 2000
SOURCE_COLUMN_NAMES = {"source", "sources", "citation", "citations", "reference", "references"}

# Kinds that need the onb_notebook_artifacts kind CHECK widened (see the migration file).
NEW_KINDS = ("data_table", "slides")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

DATA_TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"cells": {"type": "array", "items": {"type": "string"}}, "source": {"type": "string"}},
                "required": ["cells"],
            },
        },
    },
    "required": ["columns", "rows"],
}

SLIDES_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["title", "bullets"],
            },
        },
    },
    "required": ["title", "slides"],
}

DATA_TABLE_PROMPT = (
    "Turn the following content into one data table that compares or lists the important items in "
    "it. Return ONLY a JSON object exactly like "
    '{"title":"what the table shows","columns":["Item","Attribute 1","Attribute 2"],'
    '"rows":[{"cells":["value","value","value"],"source":"title of the source it came from"}]}. '
    "Use 3-6 columns, the first column names the item, and 6-30 rows. Every row has exactly one cell "
    "per column; write a short value, or an empty string when the content does not say. The "
    '"source" of a row is the title that follows "=== SOURCE:" in the content. No prose, no Markdown, '
    "no code fences. Use ONLY the content; do not invent values.\n\n{content}"
)

SLIDES_PROMPT = (
    "Create a slide deck outline from the following content. Return ONLY a JSON object exactly like "
    '{"title":"deck title","slides":[{"title":"slide title","bullets":["short point","short point"],'
    '"notes":"what the presenter says","source":"title of the source it came from"}]}. '
    "Write 6-10 slides that follow the logic of the content: what it is, the main ideas one per slide, "
    "and a final slide of takeaways. Each slide has 3-5 bullets of under 20 words. Notes are 1-3 "
    'sentences. The "source" is the title that follows "=== SOURCE:" in the content, or an empty '
    "string. No prose, no Markdown, no code fences. Use ONLY the content; do not invent facts.\n\n{content}"
)


def clean_text(value: Any, limit: int) -> str:
    """One line of text with control characters removed (they are illegal in XML) and a length cap."""
    text = _CONTROL.sub(" ", str(value if value is not None else ""))
    return " ".join(text.split())[:limit]


def clean_instruction(raw: Any) -> str:
    """A user-written instruction for a generator: text only, no control characters, capped."""
    if not isinstance(raw, str):
        return ""
    text = _CONTROL.sub(" ", raw).replace("{content}", "").strip()
    return text[:MAX_INSTRUCTION_CHARS]


def apply_instruction(prompt: str, instruction: str) -> str:
    """Put the user's instruction in front of the ``{content}`` slot of a prompt template.

    The sources stay the only allowed facts; the instruction decides focus, audience and layout.
    """
    if not instruction:
        return prompt
    block = (
        "The user also wrote this instruction. Follow it; where it conflicts with the default layout "
        "above, the instruction wins. It does not allow facts that are not in the content.\n"
        f"USER INSTRUCTION: {instruction}\n\n"
    )
    if "{content}" in prompt:
        return prompt.replace("{content}", block + "{content}", 1)
    return f"{prompt}\n\n{block}"


def _source_of(item: Dict[str, Any]) -> str:
    raw = item.get("source") or item.get("citation") or item.get("sources") or item.get("reference") or ""
    if isinstance(raw, list):
        raw = "; ".join(str(r) for r in raw if r)
    return clean_text(raw, 200)


def normalize_data_table(data: Any) -> Dict[str, Any]:
    """``{title, columns, rows:[{cells, source}]}``, or ``{}`` when the reply holds no usable table.

    Tolerant of the shapes small models return: columns as objects, rows as bare lists or as
    objects keyed by column name, and a Source column inside the table instead of beside it.
    """
    if not isinstance(data, dict):
        return {}
    raw_cols = data.get("columns") or data.get("headers") or data.get("header") or []
    if not isinstance(raw_cols, list):
        return {}
    columns: List[str] = []
    for col in raw_cols[:MAX_COLUMNS]:
        if isinstance(col, dict):
            col = col.get("name") or col.get("title") or col.get("label") or ""
        name = clean_text(col, 80)
        if name:
            columns.append(name)
    raw_rows = data.get("rows") or data.get("data") or []
    if len(columns) < 2 or not isinstance(raw_rows, list):
        return {}

    src_idx = next((i for i, c in enumerate(columns) if c.casefold() in SOURCE_COLUMN_NAMES), None)
    rows: List[Dict[str, Any]] = []
    for item in raw_rows[:MAX_ROWS]:
        source = ""
        if isinstance(item, dict) and isinstance(item.get("cells"), list):
            cells = list(item["cells"])
            source = _source_of(item)
        elif isinstance(item, dict):
            cells = [item.get(c, "") for c in columns]
            source = _source_of(item)
        elif isinstance(item, list):
            cells = list(item)
        else:
            continue
        cells = [clean_text(c if not isinstance(c, (list, dict)) else "", MAX_CELL_CHARS) for c in cells]
        cells = (cells + [""] * len(columns))[: len(columns)]
        if src_idx is not None:
            source = source or cells[src_idx]
            cells.pop(src_idx)
        if not any(cells):
            continue
        rows.append({"cells": cells, "source": source})
    if not rows:
        return {}
    if src_idx is not None:
        columns.pop(src_idx)
    if len(columns) < 1:
        return {}
    title = clean_text(data.get("title") or data.get("name") or "", 140)
    return {"title": title or "Data table", "columns": columns, "rows": rows}


def normalize_slides(data: Any) -> Dict[str, Any]:
    """``{title, slides:[{title, bullets, notes, source}]}``, or ``{}`` when no slide is usable."""
    if not isinstance(data, dict):
        return {}
    raw = data.get("slides") or data.get("outline") or data.get("sections") or []
    if not isinstance(raw, list):
        return {}
    slides: List[Dict[str, Any]] = []
    for item in raw[:MAX_SLIDES]:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title") or item.get("heading") or item.get("name") or "", 140)
        bullets_raw = item.get("bullets") or item.get("points") or item.get("content") or []
        if isinstance(bullets_raw, str):
            bullets_raw = [b for b in re.split(r"\n+|(?<=[.!?])\s+", bullets_raw) if b.strip()]
        if not isinstance(bullets_raw, list):
            bullets_raw = []
        bullets = [b for b in (clean_text(str(x).lstrip("-*• "), MAX_BULLET_CHARS) for x in bullets_raw) if b]
        if not title or not bullets:
            continue
        slides.append({
            "title": title,
            "bullets": bullets[:MAX_BULLETS],
            "notes": clean_text(item.get("notes") or item.get("speaker_notes") or "", 1200),
            "source": _source_of(item),
        })
    if not slides:
        return {}
    title = clean_text(data.get("title") or data.get("name") or "", 140)
    return {"title": title or slides[0]["title"], "slides": slides}


def _defuse(cell: str) -> str:
    """A spreadsheet runs a cell that starts with = + - or @ as a formula; source text is untrusted."""
    return "'" + cell if cell.startswith(_FORMULA_START) else cell


def table_to_csv(content: Dict[str, Any]) -> bytes:
    """The table as UTF-8 CSV (with a BOM so Excel reads accents), Source as the last column."""
    columns = [str(c) for c in content.get("columns") or []]
    rows = [r for r in content.get("rows") or [] if isinstance(r, dict)]
    with_source = any(r.get("source") for r in rows)
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([_defuse(c) for c in columns] + (["Source"] if with_source else []))
    for row in rows:
        cells = [str(c) for c in row.get("cells") or []]
        cells = (cells + [""] * len(columns))[: len(columns)]
        writer.writerow([_defuse(c) for c in cells] + ([_defuse(str(row.get("source") or ""))] if with_source else []))
    return ("﻿" + buf.getvalue()).encode("utf-8")


def safe_filename(title: Any, fallback: str, extension: str) -> str:
    """An ASCII file name for Content-Disposition."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(title or "")).strip("._-")[:60]
    return f"{stem or fallback}.{extension}"


def slides_to_pptx(content: Dict[str, Any]) -> bytes:
    """Render a slide outline to a 16:9 PPTX. Raises ``ValueError`` for an outline with no slides."""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    slides = [s for s in content.get("slides") or [] if isinstance(s, dict) and s.get("title")]
    if not slides:
        raise ValueError("The deck has no slides.")
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    left, width = Inches(0.8), Inches(11.7)

    deck_title = clean_text(content.get("title") or slides[0]["title"], 140)
    cover = prs.slides.add_slide(prs.slide_layouts[0])
    cover.shapes.title.text = deck_title
    cover.shapes.title.left, cover.shapes.title.width = left, width
    cover.shapes.title.top, cover.shapes.title.height = Inches(2.3), Inches(1.8)
    subtitle = cover.placeholders[1]
    subtitle.text = f"{len(slides)} slides"
    subtitle.left, subtitle.width = left, width
    subtitle.top, subtitle.height = Inches(4.3), Inches(1.0)

    for spec in slides[:MAX_SLIDES]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = clean_text(spec["title"], 140)
        slide.shapes.title.left, slide.shapes.title.width = left, width
        slide.shapes.title.top, slide.shapes.title.height = Inches(0.4), Inches(1.2)
        body = slide.placeholders[1]
        body.left, body.width = left, width
        body.top, body.height = Inches(1.8), Inches(5.0)
        bullets = [clean_text(b, MAX_BULLET_CHARS) for b in spec.get("bullets") or [] if b][:MAX_BULLETS] or [""]
        chars = sum(len(b) for b in bullets)
        size = Pt(26) if chars < 300 else Pt(22) if chars < 520 else Pt(18)
        frame = body.text_frame
        frame.word_wrap = True
        for i, text in enumerate(bullets):
            para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
            para.text = text
            for run in para.runs:
                run.font.size = size
        notes = clean_text(spec.get("notes") or "", 1200)
        source = clean_text(spec.get("source") or "", 200)
        if source:
            notes = f"{notes}\n\nSource: {source}".strip()
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


_MIGRATION = os.path.join(os.path.dirname(__file__), "..", "notebooks", "migrations", "2026_10_30_studio_kinds.sql")
_migrated = False


async def ensure_kind_constraints(pool: Any) -> None:
    """Apply the additive CHECK widening once per process, so a data table or deck can be saved.

    The migration only widens constraints and is idempotent. A failure is logged and left to
    surface as the database's own error when the artifact is saved.
    """
    global _migrated
    if _migrated or pool is None:
        return
    try:
        with open(_MIGRATION, "r", encoding="utf-8") as fh:
            sql = fh.read()
        async with pool.acquire() as conn:
            await conn.execute(sql)
        _migrated = True
    except Exception as exc:  # noqa: BLE001 - never block generation on a migration problem
        logger.warning("studio kinds migration did not apply: %s", exc)
