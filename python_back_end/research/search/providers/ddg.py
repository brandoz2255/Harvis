# python_back_end/research/search/providers/ddg.py
from __future__ import annotations
from typing import List
import logging
import time

from ddgs import DDGS

from ...core.types import Hit
from ...config.settings import get_settings

logger = logging.getLogger(__name__)

class DDGProvider:
    """
    DuckDuckGo (ddgs) provider.
    """

    def __init__(self, settings=None):
        self.cfg = settings or get_settings()

    def search(
        self,
        queries: List[str],
        max_results: int = 10,
        region: str = None,
        safesearch: str = None,
    ) -> List[Hit]:
        region = region or self.cfg.search_region
        safesearch = safesearch or self.cfg.safesearch

        out: List[Hit] = []
        with DDGS() as ddg:
            for q in queries:
                # small delay to avoid rate limiting
                time.sleep(0.35)
                try:
                    results = list(ddg.text(
                        q,
                        max_results=max_results,
                        backend="api",
                        region=region,
                        safesearch=safesearch
                    ))
                except Exception as e:
                    logger.warning(f"DDG search failed for '{q}': {e}")
                    continue

                for r in results:
                    url = r.get("href") or r.get("link") or ""
                    title = r.get("title") or ""
                    body = r.get("body") or ""
                    if not url:
                        continue
                    out.append(Hit(
                        title=title,
                        url=url,
                        snippet=body,
                        score=0.0,
                        source="ddg"
                    ))
        return out

