"""Readers for PowerPoint, Excel and ePub files, and OCR for scanned PDFs.

These sit beside ``extractors.py`` so each stays small. Everything raises
``IngestionError`` with a sentence the user can act on, like the other extractors.
No new dependency: python-pptx, openpyxl and pypdfium2 are already in
requirements-core.txt, ePub is a zip of XHTML, and OCR calls the tesseract CLI the
image reader already uses.
"""
from __future__ import annotations

import asyncio
import logging
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote

from .extractors import Extracted, IngestionError, _missing, join_pages
from .source_types import html_to_text

logger = logging.getLogger(__name__)

XLSX_MAX_ROWS = 2000
XLSX_MAX_COLS = 50
# Rows looked at, empty ones included, across the whole workbook. XLSX_MAX_ROWS only counts rows
# that hold something, so a sheet of endless blank rows would otherwise be scanned to the end.
XLSX_MAX_SCAN_ROWS = 200_000
# A zip that expands past this is refused rather than unpacked (zip bomb).
ZIP_MAX_UNCOMPRESSED = 300 * 1024 * 1024
ZIP_MAX_ENTRIES = 20000
EPUB_MAX_CHAPTER_BYTES = 5 * 1024 * 1024
EPUB_MAX_TOTAL_CHARS = 5_000_000  # text kept from one book; the rest is dropped with a notice
EPUB_MAX_PACKAGE_BYTES = 2 * 1024 * 1024  # container.xml and the OPF are read whole
# One XML part of a pptx or epub is parsed whole by its reader, so no single part may expand past this.
ZIP_MAX_XML_ENTRY = 50 * 1024 * 1024
OCR_DPI = 200
OCR_MAX_PIXELS = 6000  # longest side of a rendered page, so a poster-sized page cannot exhaust memory
OCR_PAGE_TIMEOUT_S = 90
_OCR_LANG = re.compile(r"^[A-Za-z_]{2,20}(\+[A-Za-z_]{2,20}){0,3}$")


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, "") or default)
    except ValueError:
        value = default
    return max(low, min(high, value))


def ocr_max_pages() -> int:
    return _env_int("NOTEBOOK_OCR_MAX_PAGES", 50, 1, 500)


def ocr_max_seconds() -> int:
    return _env_int("NOTEBOOK_OCR_MAX_SECONDS", 600, 10, 3600)


# --- OCR for scanned PDFs ----------------------------------------------------------


@dataclass
class OcrOutcome:
    texts: Dict[int, str] = field(default_factory=dict)
    attempted: int = 0
    skipped: int = 0
    timed_out: bool = False
    limit: int = 0

    def meta(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"ocr": True, "ocr_pages": self.attempted}
        if self.skipped:
            out["ocr_skipped_pages"] = self.skipped
            if self.timed_out:
                reason = f"OCR stopped after {ocr_max_seconds()} seconds"
            else:
                reason = f"OCR is limited to {self.limit} pages (NOTEBOOK_OCR_MAX_PAGES)"
            out["ingest_notice"] = f"{reason}; {self.skipped} scanned page(s) were not read."
        return out


def ocr_pdf_pages(path: str, page_numbers: Sequence[int]) -> OcrOutcome:
    """Render the given 1-based pages at ~200 dpi and read them with tesseract.

    Blocking: call it from a worker thread. Stops at the page cap or the time budget
    and reports what it skipped instead of pretending the whole file was read.
    """
    if not shutil.which("tesseract"):
        raise IngestionError(
            "This PDF has no selectable text, so it is probably a scan, and this server has no OCR engine "
            "(tesseract) installed. Ask the host to install it, or upload the pages as images."
        )
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise IngestionError(
            "This PDF is a scan and this server cannot render PDF pages for OCR (pypdfium2 is missing)."
        ) from exc

    limit = ocr_max_pages()
    todo = list(page_numbers)[:limit]
    outcome = OcrOutcome(skipped=len(page_numbers) - len(todo), limit=limit)
    deadline = time.monotonic() + ocr_max_seconds()
    lang = os.getenv("NOTEBOOK_OCR_LANG", "").strip()
    lang_args = ["-l", lang] if lang and _OCR_LANG.match(lang) else []

    try:
        doc = pdfium.PdfDocument(path)
    except Exception as exc:
        raise IngestionError(
            f"This PDF could not be rendered for OCR ({str(exc)[:100]}). It may be damaged or protected."
        ) from exc
    try:
        with tempfile.TemporaryDirectory(prefix="nb-ocr-") as work:
            for position, number in enumerate(todo):
                remaining = deadline - time.monotonic()
                if remaining < 5:
                    outcome.timed_out = True
                    outcome.skipped += len(todo) - position
                    break
                outcome.attempted += 1
                text = _ocr_one_page(doc, number, work, lang_args, min(OCR_PAGE_TIMEOUT_S, remaining))
                if text:
                    outcome.texts[number] = text
    finally:
        doc.close()
    return outcome


def _ocr_one_page(doc, number: int, work: str, lang_args: List[str], timeout: float) -> str:
    image_path = os.path.join(work, f"p{number}.png")
    try:
        page = doc[number - 1]
        try:
            width, height = page.get_size()
            scale = min(OCR_DPI / 72, OCR_MAX_PIXELS / max(width, height, 1))
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            try:
                image.save(image_path)
            finally:
                image.close()
        finally:
            page.close()
        run = subprocess.run(
            ["tesseract", image_path, "stdout", *lang_args], capture_output=True, text=True, timeout=timeout
        )
        return (run.stdout or "").strip()
    except subprocess.TimeoutExpired:
        logger.warning("OCR timed out on PDF page %s", number)
    except Exception as exc:
        logger.warning("OCR failed on PDF page %s: %s", number, exc)
    finally:
        try:
            os.unlink(image_path)
        except OSError:
            pass
    return ""


# --- zip containers ----------------------------------------------------------------


def _check_zip(path: str, *, parses_xml_whole: bool = False) -> None:
    """Refuse a zip that would expand too far. Reads only the directory, never the data.

    ``parses_xml_whole`` is for pptx and epub, whose readers load each XML part into memory;
    an xlsx sheet is streamed, so a big one is fine there.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise IngestionError("This file is damaged or is not the format its name says.") from exc
    too_big = len(infos) > ZIP_MAX_ENTRIES or sum(i.file_size for i in infos) > ZIP_MAX_UNCOMPRESSED
    if parses_xml_whole and not too_big:
        xml_ends = (".xml", ".rels", ".opf", ".xhtml", ".html", ".htm", ".ncx")
        too_big = any(i.file_size > ZIP_MAX_XML_ENTRY for i in infos if i.filename.lower().endswith(xml_ends))
    if too_big:
        raise IngestionError("This file expands to far more data than a notebook source can hold.")


# --- PowerPoint --------------------------------------------------------------------


def _shape_lines(shapes, title_shape) -> List[str]:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    lines: List[str] = []
    for shape in shapes:
        if title_shape is not None and shape.shape_id == title_shape.shape_id:
            continue
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            lines.extend(_shape_lines(shape.shapes, title_shape))
            continue
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
            continue
        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            text = shape.text_frame.text.strip()
            if text:
                lines.append(text)
    return lines


def _read_pptx(path: str) -> Extracted:
    from pptx import Presentation

    _check_zip(path, parses_xml_whole=True)
    prs = Presentation(path)
    pages: List[Tuple[int, str]] = []
    body_chars = 0
    for number, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        title = (title_shape.text_frame.text.strip() if title_shape is not None and title_shape.has_text_frame else "")
        lines = [f"Slide {number}" + (f": {title}" if title else "")]
        body = _shape_lines(slide.shapes, title_shape)
        lines.extend(body)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                body.append(notes)
                lines.append(f"Speaker notes: {notes}")
        body_chars += len(title) + sum(len(b) for b in body)
        pages.append((number, "\n".join(lines)))
    if body_chars < 10:
        raise IngestionError("No text was found in this presentation. Slides that are only pictures cannot be read.")
    return join_pages(pages, {"page_count": len(pages), "page_label": "slide"})


# --- Excel -------------------------------------------------------------------------


def _cell(value: Any) -> str:
    return "" if value is None else str(value).replace("\r", " ").replace("\n", " ").strip()


def _read_xlsx(path: str) -> Extracted:
    import openpyxl

    _check_zip(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts: List[str] = []
    truncated: List[str] = []
    cells = 0
    scanned = 0
    scan_capped = False
    try:
        for ws in wb.worksheets:
            if scan_capped:
                break
            lines = [f"Sheet: {ws.title}"]
            rows = 0
            for row in ws.iter_rows(values_only=True):
                scanned += 1
                if scanned > XLSX_MAX_SCAN_ROWS:
                    scan_capped = True
                    break
                if rows >= XLSX_MAX_ROWS:
                    truncated.append(ws.title)
                    break
                values = [_cell(v) for v in row[:XLSX_MAX_COLS]]
                while values and not values[-1]:
                    values.pop()
                if not values:
                    continue
                rows += 1
                cells += sum(1 for v in values if v)
                lines.append(" | ".join(values))
            if len(lines) > 1:
                parts.append("\n".join(lines))
    finally:
        wb.close()
    if not cells:
        raise IngestionError("No cell values were found in this spreadsheet.")
    meta: Dict[str, Any] = {"sheet_count": len(wb.worksheets)}
    notices: List[str] = []
    if truncated:
        notices.append(f"Only the first {XLSX_MAX_ROWS} rows of {', '.join(truncated)} were read.")
    if scan_capped:
        notices.append(f"Reading stopped after {XLSX_MAX_SCAN_ROWS} rows, blank ones included.")
    if notices:
        meta["ingest_notice"] = " ".join(notices)
    return Extracted("\n\n".join(parts), None, meta)


# --- ePub --------------------------------------------------------------------------


def _xml_root(data: bytes):
    try:
        from defusedxml import ElementTree as ET
    except ImportError:  # defusedxml is in requirements-core; stdlib does not resolve external entities
        from xml.etree import ElementTree as ET
    return ET.fromstring(data)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_package_file(zf: zipfile.ZipFile, member: str) -> bytes:
    """container.xml or the OPF, which are parsed whole, so a huge one is refused."""
    if zf.getinfo(member).file_size > EPUB_MAX_PACKAGE_BYTES:
        raise IngestionError("This ePub's table of contents is far larger than a real book's, so it was not read.")
    return zf.read(member)


def _read_epub(path: str) -> Extracted:
    _check_zip(path, parses_xml_whole=True)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        try:
            container = _xml_root(_read_package_file(zf, "META-INF/container.xml"))
            opf_path = next(
                el.attrib["full-path"] for el in container.iter() if _local(el.tag) == "rootfile" and "full-path" in el.attrib
            )
            opf = _xml_root(_read_package_file(zf, opf_path))
        except IngestionError:
            raise
        except (KeyError, StopIteration, Exception) as exc:
            raise IngestionError("This ePub could not be read: its table of contents is missing or damaged.") from exc

        manifest: Dict[str, Tuple[str, str, str]] = {}
        spine: List[str] = []
        title = ""
        for el in opf.iter():
            name = _local(el.tag)
            if name == "item" and "id" in el.attrib and "href" in el.attrib:
                manifest[el.attrib["id"]] = (
                    el.attrib["href"], el.attrib.get("media-type", ""), el.attrib.get("properties", "")
                )
            elif name == "itemref" and "idref" in el.attrib:
                spine.append(el.attrib["idref"])
            elif name == "title" and not title and (el.text or "").strip():
                title = el.text.strip()

        base = posixpath.dirname(opf_path)
        chapters: List[str] = []
        seen: set = set()  # a spine may list one file thousands of times; read each file once
        total_chars = 0
        text_capped = False
        for idref in spine:
            href, media, props = manifest.get(idref, ("", "", ""))
            if not href or "nav" in props.split() or "html" not in media:
                continue
            member = posixpath.normpath(posixpath.join(base, unquote(href.split("#", 1)[0])))
            if member.startswith("..") or member not in names or member in seen:
                continue
            seen.add(member)
            if zf.getinfo(member).file_size > EPUB_MAX_CHAPTER_BYTES:
                logger.warning("Skipped an oversized ePub chapter: %s", member)
                continue
            raw = zf.read(member).decode("utf-8", errors="replace")
            text = html_to_text(raw).strip()
            if text:
                chapters.append(text)
                total_chars += len(text)
                if total_chars >= EPUB_MAX_TOTAL_CHARS:
                    text_capped = True
                    break
    if sum(len(c) for c in chapters) < 10:
        raise IngestionError("No readable text was found in this ePub. It may be protected by DRM.")
    meta: Dict[str, Any] = {"chapter_count": len(chapters)}
    if title:
        meta["book_title"] = title[:200]
    if text_capped:
        meta["ingest_notice"] = f"Only the first {EPUB_MAX_TOTAL_CHARS:,} characters of this book were read."
    return Extracted("\n\n".join(chapters), None, meta)


# --- dispatch ----------------------------------------------------------------------

_READERS = {"pptx": _read_pptx, "xlsx": _read_xlsx, "xlsm": _read_xlsx, "epub": _read_epub}
_KIND = {"pptx": "presentation", "xlsx": "spreadsheet", "xlsm": "spreadsheet", "epub": "ePub"}
_MISSING_LIB = {"pptx": "python-pptx", "xlsx": "openpyxl", "xlsm": "openpyxl"}


async def extract_office(path: Optional[str], ext: str) -> Extracted:
    """Read a .pptx, .xlsx/.xlsm or .epub file."""
    if _missing(path):
        raise IngestionError("The uploaded file is no longer on the server. Remove this source and upload it again.")
    reader = _READERS.get(ext)
    if reader is None:
        raise IngestionError(f".{ext} files are not supported.")
    try:
        return await asyncio.to_thread(reader, path)
    except IngestionError:
        raise
    except ImportError as exc:
        raise IngestionError(f"Reading {_KIND[ext]}s is not installed on this server ({_MISSING_LIB.get(ext, ext)}).") from exc
    except Exception as exc:
        raise IngestionError(
            f"This {_KIND[ext]} could not be opened ({type(exc).__name__}: {str(exc)[:100]}). "
            "It may be damaged, password protected or saved in an old format."
        ) from exc
