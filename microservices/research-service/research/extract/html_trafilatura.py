from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

import  requests

logger = logging.getLogger(__name__)

try:
    import trafilatura
except Exception:
    trafilatura = None 

try:
    from readablity import Document 
except Exception:
    Document = None 

@dataclass
class HtmlExtractionResult:
    title: str
    test: str 
    language: Optional[str]
    meta: Dict[str, Any]

def fetch_html(url: str, user_agent: str, timeout_s: int) -> str :
    r = requests.get(url, timeout=timeout_s, headers={"User-Agent": user_agent})
    r.raise_for_status()
    return r.text  



def _trafilatura_extract(html: str) -> HtmlExtractionResult:
    # Use trafilatura’s bare_extraction for metadata/title if available
    title = ""
    lang = None
    meta: Dict[str, Any] = {}
    text = ""

    if trafilatura:
        try:
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                include_formatting=False,
                favor_precision=True,
            ) or ""
        except Exception as e:
            logger.debug(f"trafilatura.extract failed: {e}")

        try:
            bare = trafilatura.bare_extraction(html) or {}
            title = bare.get("title") or title
            lang = bare.get("language")
        except Exception as e:
            logger.debug(f"trafilatura.bare_extraction failed: {e}")

    return HtmlExtractionResult(title=title or "", text=text or "", language=lang, meta=meta)

def readablity_fallback(html: str) -> HtmlExtractionResult:
    if not  Document:
        return HtmlExtractionResult(title="", test="", language=None, meta={})
    try:
        doc = Document(html)
        title = (doc.short_title() or "").strip()
        content_html = doc.summary() or ""
        import re
        text = re.sub(r"<[^>]+>", " ", content_html)
        text = " ".join(text.split())
        return HtmlExtractionResult(title=title, text=text, language=None, meta={"engine":"readablity"})
    except Exception as e:
        logger.debug(f"readablity_fallback failed: {e}")
        return HtmlExtractionResult(title=" ", text=" ", language=None, meta={})

def extract_html(url: str, html: Optional[str], user_agent: str, timeout_s: int) -> Dict[str, Any]:
    """
    Extract title & clean text from HTML using trafilatura, falling back to readability.
    Returns a dict that upper layers convert into ExtractedDoc.
    """
    try:
        if html is None:
            html = fetch_html(url, user_agent=user_agent, timeout_s=timeout_s)

        res = _trafilatura_extract(html)
        if not res.text:
            res = _readability_fallback(html)

        return {
            "url": url,
            "title": res.title,
            "text": res.text,
            "language": res.language,
            "meta": res.meta,
            "success": bool(res.text),
        }
    except Exception as e:
        logger.warning(f"HTML extraction failed for {url}: {e}")
        return {
            "url": url,
            "title": "",
            "text": "",
            "language": None,
            "meta": {"error": str(e)},
            "success": False,
        }


