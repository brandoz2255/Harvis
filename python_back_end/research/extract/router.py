# python_back_end/research/extract/router.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import concurrent.futures as futures
import logging
import mimetypes
import os

import requests

from ..config.settings import get_settings
from ..core.utils import retry

from .html_trafilatura import extract_html
from .pdf import extract_pdf
from .youtube import extract_youtube

logger = logging.getLogger(__name__)

# Optional HTTP cache (requests-cache)
try:
    import requests_cache  # type: ignore
except Exception:  # pragma: no cover
    requests_cache = None

@dataclass
class ExtractedDoc:
    url: str
    title: str
    text: str
    language: Optional[str]
    meta: Dict[str, Any]
    success: bool

# ---- Helpers ----

def _head_content_type(url: str, timeout_s: int, user_agent: str) -> Optional[str]:
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout_s, headers={"User-Agent": user_agent})
        if r.ok:
            ct = r.headers.get("Content-Type", "")
            return ct.split(";")[0].strip().lower() if ct else None
    except Exception as e:
        logger.debug(f"HEAD failed for {url}: {e}")
    return None

def _guess_content_type(url: str) -> Optional[str]:
    # Guess from extension
    mt, _ = mimetypes.guess_type(url)
    return mt

def _is_youtube(url: str) -> bool:
    return any(h in url for h in ("youtube.com", "youtu.be"))

# ---- ExtractionRouter Class ----

class ExtractionRouter:
    """
    Router class for content extraction from various sources.
    
    Provides a unified interface for extracting content from URLs,
    automatically routing to the appropriate extractor based on content type.
    """
    
    def __init__(self, settings=None):
        self.settings = settings
    
    def extract_url(self, url: str) -> ExtractedDoc:
        """Extract content from a single URL"""
        return extract_url(url, self.settings)
    
    def extract_many(self, urls: List[str], max_workers: int = 4) -> List[ExtractedDoc]:
        """Extract content from multiple URLs in parallel"""
        return extract_many(urls, max_workers, self.settings)

# ---- Public API ----

def extract_url(url: str, settings=None) -> ExtractedDoc:
    """
    Main entry: choose best extractor for the URL.
    """
    cfg = settings or get_settings()

    # Setup caching once
    if cfg.enable_requests_cache and requests_cache and not getattr(extract_url, "_cache_installed", False):
        try:
            requests_cache.install_cache(
                cache_name=cfg.requests_cache_name,
                expire_after=cfg.requests_cache_expiry_s
            )
            extract_url._cache_installed = True  # type: ignore[attr-defined]
        except Exception as e:
            logger.debug(f"requests-cache install failed: {e}")

    content_type = _head_content_type(url, timeout_s=cfg.requests_timeout_s, user_agent=cfg.user_agent) \
                   or _guess_content_type(url) \
                   or ""

    # Route by type
    if _is_youtube(url) and cfg.enable_youtube:
        data = extract_youtube(url, timeout_s=cfg.requests_timeout_s)
    elif (content_type.endswith("pdf") or url.lower().endswith(".pdf")) and cfg.enable_pdf:
        data = extract_pdf(url, user_agent=cfg.user_agent, timeout_s=cfg.requests_timeout_s)
    else:
        # HTML by default
        data = extract_html(url, html=None, user_agent=cfg.user_agent, timeout_s=cfg.requests_timeout_s)

    return ExtractedDoc(
        url=data.get("url", url),
        title=data.get("title", "") or "",
        text=data.get("text", "") or "",
        language=data.get("language"),
        meta=data.get("meta", {}),
        success=bool(data.get("success")),
    )

def extract_many(urls: List[str], max_workers: int = 4, settings=None) -> List[ExtractedDoc]:
    """
    Parallel extractor convenience.
    """
    cfg = settings or get_settings()
    out: List[ExtractedDoc] = []
    with futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda u: extract_url(u, settings=cfg), urls))
        out.extend(results)
    return out

