# python_back_end/research/search/providers/tavily.py
from __future__ import annotations
from typing import List
import logging

from ...core.types import Hit
from ...config.settings import get_settings

logger = logging.getLogger(__name__)

class TavilyProvider:
    """
    Tavily provider. Uses the official client if available, else falls back to HTTP.
    If no API key is configured, returns empty and the aggregator will rely on others.
    """

    def __init__(self, settings=None):
        self.cfg = settings or get_settings()
        self.api_key = self.cfg.tavily_api_key

    def search(
        self,
        queries: List[str],
        max_results: int = 10,
        region: str = None,
        safesearch: str = None,
    ) -> List[Hit]:
        if not self.api_key:
            logger.info("Tavily API key missing; skipping TavilyProvider")
            return []

        hits: List[Hit] = []
        for q in queries:
            try:
                # Preferred: official client
                try:
                    import tavily
                    client = tavily.TavilyClient(api_key=self.api_key)
                    resp = client.search(q, max_results=max_results)
                    results = resp.get("results", [])
                except Exception as e:
                    # Fallback to HTTP if client not present
                    logger.debug(f"Tavily client not available/failed ({e}); trying HTTP")
                    import requests
                    r = requests.post(
                        "https://api.tavily.com/search",
                        json={"api_key": self.api_key, "query": q, "max_results": max_results},
                        timeout=15,
                    )
                    r.raise_for_status()
                    results = r.json().get("results", [])

                for r in results:
                    url = r.get("url") or ""
                    title = r.get("title") or ""
                    body = r.get("content") or ""
                    if not url:
                        continue
                    hits.append(Hit(
                        title=title,
                        url=url,
                        snippet=body,
                        score=0.0,
                        source="tavily"
                    ))
            except Exception as e:
                logger.warning(f"Tavily search failed for '{q}': {e}")
                continue

        return hits

