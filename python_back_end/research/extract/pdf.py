# python_back_end/research/extract/pdf.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
import io
import logging
import requests

logger = logging.getLogger(__name__)

# We prefer pypdf (formerly PyPDF2)
try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None

@dataclass
class PageSpan:
    page: int
    start: int
    end: int

def _download_pdf_bytes(url: str, user_agent: str, timeout_s: int) -> bytes:
    r = requests.get(url, timeout=timeout_s, headers={"User-Agent": user_agent})
    r.raise_for_status()
    return r.content

def extract_pdf(url: str, user_agent: str, timeout_s: int) -> Dict[str, Any]:
    """
    Extract text from a PDF and build a page map (list of spans with absolute char offsets).
    """
    try:
        if not PdfReader:
            raise RuntimeError("pypdf not installed (pip install pypdf)")

        raw = _download_pdf_bytes(url, user_agent=user_agent, timeout_s=timeout_s)
        reader = PdfReader(io.BytesIO(raw))

        texts: List[str] = []
        page_spans: List[PageSpan] = []
        cursor = 0

        for idx, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
            except Exception as e:
                logger.debug(f"pypdf page {idx} extract_text failed: {e}")
                t = ""
            start = cursor
            texts.append(t)
            cursor += len(t)
            page_spans.append(PageSpan(page=idx + 1, start=start, end=cursor))

        title = ""
        try:
            meta = reader.metadata or {}
            title = (meta.get("/Title") or "").strip()
        except Exception:
            pass

        full_text = "".join(texts)
        meta_out: Dict[str, Any] = {
            "pages": len(reader.pages),
            "page_spans": [ps.__dict__ for ps in page_spans],
        }

        return {
            "url": url,
            "title": title,
            "text": full_text,
            "language": None,
            "meta": meta_out,
            "success": bool(full_text),
        }
    except Exception as e:
        logger.warning(f"PDF extraction failed for {url}: {e}")
        return {
            "url": url,
            "title": "",
            "text": "",
            "language": None,
            "meta": {"error": str(e)},
            "success": False,
        }

