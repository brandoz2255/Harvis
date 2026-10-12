"""Which kind of source an uploaded file is, and how to read it as text.

The upload route used to map only pdf/txt/md/doc/docx and fall back to TEXT for
everything else, so a PNG or an MP3 was opened as UTF-8 and failed with a decode
error. Images and audio now have their own types (the ingester OCRs and
captions the first, transcribes the second), HTML is recognised so its tags are
stripped, and an unknown extension is accepted only when the bytes really are
text.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from .models import SourceType

IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff"})
AUDIO_EXTS = frozenset({"mp3", "wav", "m4a", "ogg", "webm", "oga", "opus", "flac", "aac"})
HTML_EXTS = frozenset({"html", "htm", "xhtml"})
MARKDOWN_EXTS = frozenset({"md", "markdown"})
# Plain-text formats read as UTF-8 (csv/json/srt stay as written; they are text).
TEXT_EXTS = frozenset({
    "txt", "text", "log", "csv", "tsv", "json", "xml", "yaml", "yml", "srt", "vtt", "rst", "tex",
    "ini", "toml", "py", "js", "ts", "tsx", "jsx", "java", "c", "cpp", "h", "go", "rs", "sh", "sql",
})
TRANSCRIPT_EXTS = frozenset({"srt", "vtt"})

TYPE_MAP: dict[str, SourceType] = {
    "pdf": SourceType.PDF,
    "doc": SourceType.DOC,
    "docx": SourceType.DOC,
    **{e: SourceType.IMAGE for e in IMAGE_EXTS},
    **{e: SourceType.AUDIO for e in AUDIO_EXTS},
    **{e: SourceType.MARKDOWN for e in MARKDOWN_EXTS},
    **{e: SourceType.TEXT for e in TEXT_EXTS | HTML_EXTS},
}


class UnsupportedFile(ValueError):
    """The upload is not something a notebook can read. The message is for the user."""


def extension_of(filename: str) -> str:
    name = (filename or "").rsplit("/", 1)[-1]
    return name.lower().rsplit(".", 1)[-1] if "." in name else ""


def _is_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte character cut by the sniff window is not a binary file.
        if exc.start < len(head) - 4:
            return False
    return True


def classify_upload(filename: str, head: bytes = b"") -> Tuple[SourceType, str]:
    """``(source type, lowercase extension)`` for an upload, or raise UnsupportedFile."""
    ext = extension_of(filename)
    if ext in TYPE_MAP:
        return TYPE_MAP[ext], ext
    if _is_text(head[:4096]):
        return SourceType.TEXT, ext or "txt"
    shown = f".{ext}" if ext else "that file"
    raise UnsupportedFile(
        f"{shown} files are not supported. Use PDF, Word, text, Markdown, HTML, an image "
        "(PNG, JPG, WebP, GIF) or audio (MP3, WAV, M4A, OGG, WebM)."
    )


_HTML_START = re.compile(r"^\s*(<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>])", re.IGNORECASE)


def looks_like_html(text: str) -> bool:
    return bool(_HTML_START.match((text or "")[:600]))


def html_to_text(html: str) -> str:
    """Readable text from an HTML document: main content when there is one, no tags.

    trafilatura picks the article body out of page chrome; BeautifulSoup is the
    fallback for fragments and pages trafilatura finds nothing in. Both are already
    in requirements.
    """
    text = ""
    try:
        import trafilatura

        text = trafilatura.extract(html, include_tables=True, include_comments=False, no_fallback=False) or ""
    except Exception:
        text = ""
    if len(text.strip()) >= 50:
        return text.strip()
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return re.sub(r"<[^>]+>", " ", html).strip()
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "template", "svg"]):
        element.decompose()
    body = soup.find("main") or soup.find("article") or soup.find("body") or soup
    lines = (ln.strip() for ln in body.get_text(separator="\n").splitlines())
    return "\n".join(ln for ln in lines if ln)


def read_text_file(path: str) -> str:
    """Text from a file: UTF-8 (BOM tolerated), UTF-16 when it has a BOM, else Latin-1."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def sniff_ext(path: Optional[str]) -> str:
    return extension_of(path or "")
