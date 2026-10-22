"""Export a ``harvis-doc`` block as a file: pptx, docx, xlsx, pdf, csv or md.

``export_doc`` is what the route calls; the ``to_*`` functions take the block
body and return the file's bytes. Every refusal is an ``ExportError`` whose text
is safe to show the person (the route returns it as the 400 detail).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote
from typing import Callable, Optional

from .docs_blocks import inline_runs, plain_text
from .docs_parse import ParsedDoc, parse_harvis_doc

MAX_SOURCE_BYTES = 1_000_000

# What each kind of document can be downloaded as, primary format first.
FORMATS = {
    "deck": ("pptx", "pdf"),
    "doc": ("docx", "pdf", "md"),
    "pdf": ("pdf", "docx"),
    "sheet": ("xlsx", "csv"),
}
MEDIA_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "csv": "text/csv; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


class ExportError(ValueError):
    """The document cannot be exported as asked."""


@dataclass
class ExportedFile:
    data: bytes
    media_type: str
    filename: str


_SLUG_CHARS = 60
_SLUG_BYTES = 150                       # file systems cap a name at 255 bytes; leave room for the extension
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


# Default_Ignorable_Code_Point characters that are not format characters (those already become hyphens): Hangul
# fillers, the combining grapheme joiner, Khmer inherent vowels, Mongolian and standard variation selectors.
_INVISIBLE = re.compile("[\u034f\u115f\u1160\u17b4\u17b5\u180b-\u180d\u180f\u3164\ufe00-\ufe0f\uffa0\U000e0100-\U000e01ef]")


def slugify(title: str) -> str:
    """A file name stem from the title: letters, digits and marks of any script, joined by hyphens.

    Everything else (separators, control and format characters, quotes, punctuation) becomes a hyphen, which is
    what keeps the name safe on Windows and macOS as well as Linux. Invisible letters and marks are dropped, so
    a title made only of them is "document" and not a name nobody can see."""
    text = _INVISIBLE.sub("", unicodedata.normalize("NFKC", title or "").lower())
    slug = re.sub(r"-+", "-", "".join(c if unicodedata.category(c)[0] in "LNM" else "-" for c in text)).strip("-")
    slug = slug[:_SLUG_CHARS]
    while len(slug.encode("utf-8")) > _SLUG_BYTES:
        slug = slug[:-1]
    slug = unicodedata.normalize("NFC", slug).strip("-")
    if slug in _RESERVED:                # "con.pdf" cannot be created on Windows
        slug += "-file"
    return slug or "document"


def content_disposition(filename: str) -> str:
    """An attachment header that carries the real name (RFC 5987) beside an ASCII fallback for old clients."""
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_stem).strip("-.")
    ascii_ext = re.sub(r"[^A-Za-z0-9]", "", ext)
    fallback = (ascii_stem or "document") + (f".{ascii_ext}" if ascii_ext else "")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _title(doc: ParsedDoc, title: Optional[str]) -> str:
    # A title can carry markdown (**bold**); the file's title is the words.
    return plain_text(inline_runs((title or doc.title or "").strip())) or "Untitled"


def parse_for_export(source: str, fmt: str) -> ParsedDoc:
    """Parse and check the document fits the format. Raises ExportError."""
    if not isinstance(source, str) or not source.strip():
        raise ExportError("The document is empty.")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ExportError("The document is larger than 1 MB.")
    if fmt not in MEDIA_TYPES:
        raise ExportError(f"Unknown format '{fmt}'. Use one of: {', '.join(MEDIA_TYPES)}.")
    doc = parse_harvis_doc(source)
    if not doc.header_complete:
        raise ExportError("The document header is not finished, so it cannot be exported yet.")
    if fmt not in FORMATS[doc.kind]:
        raise ExportError(f"A {doc.kind} cannot be exported as {fmt}. Use {' or '.join(FORMATS[doc.kind])}.")
    if doc.kind == "sheet":
        if not any(s.rows for s in doc.sheets):
            raise ExportError("The spreadsheet has no table to export.")
    elif not any(s.title or s.body for s in doc.sections):
        raise ExportError("The document has no content to export.")
    return doc


def _markdown(doc: ParsedDoc, title: str) -> str:
    parts = [f"# {title}"]
    for s in doc.sections:
        if s.title:
            parts.append(f"## {s.title}")
        if s.body:
            parts.append(s.body)
    return "\n\n".join(parts) + "\n"


def _builders() -> dict[str, Callable[[ParsedDoc, str], bytes]]:
    # Imported on first use: python-pptx, python-docx, openpyxl and weasyprint are heavy.
    from .docs_docx import build_docx
    from .docs_pdf import build_pdf
    from .docs_pptx import build_pptx
    from .docs_xlsx import build_csv, build_xlsx

    return {
        "pptx": build_pptx,
        "docx": build_docx,
        "xlsx": lambda doc, _title: build_xlsx(doc),
        "pdf": build_pdf,
        "csv": lambda doc, _title: build_csv(next(s for s in doc.sheets if s.rows)),
        "md": lambda doc, title: _markdown(doc, title).encode("utf-8"),
    }


def export_doc(source: str, fmt: str, title: Optional[str] = None) -> ExportedFile:
    fmt = (fmt or "").strip().lower()
    doc = parse_for_export(source, fmt)
    name = _title(doc, title)
    return ExportedFile(_builders()[fmt](doc, name), MEDIA_TYPES[fmt], f"{slugify(name)}.{fmt}")


def _to(fmt: str) -> Callable[[str, Optional[str]], bytes]:
    def convert(source: str, title: Optional[str] = None) -> bytes:
        return export_doc(source, fmt, title).data
    convert.__name__ = f"to_{fmt}"
    return convert


to_pptx = _to("pptx")
to_docx = _to("docx")
to_xlsx = _to("xlsx")
to_pdf = _to("pdf")
to_csv = _to("csv")
to_md = _to("md")
