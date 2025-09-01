# python_back_end/research/search/aggregator.py
from __future__ import annotations
from typing import List, Iterable, Optional, Tuple
import logging
from dataclasses import dataclass

from ..config.settings import get_settings
from ..core.types import Hit
from ..core.utils import canonicalize_url
from .providers.ddg import DDGProvider
from .providers.tavily import TavilyProvider
from .scoring import score_hit

logger = logging.getLogger(__name__)

@dataclass
class ProviderSpec:
    name: str
    weight: float = 1.0   # you can change provider influence later


class SearchAggregator:
    """
    Aggregates results from multiple search providers, canonicalizes/dedupes,
    scores and truncates per depth budgets.
    """

    def __init__(
        self,
        providers: Optional[List[ProviderSpec]] = None,
        settings=None,
    ):
        self.cfg = settings or get_settings()

        # Default provider mix (bounded by budget later)
        if providers is None:
            providers = []
            # DDG is always present
            providers.append(ProviderSpec("ddg", weight=1.0))
            # Include Tavily if a key exists
            if self.cfg.tavily_api_key:
                providers.append(ProviderSpec("tavily", weight=1.0))
        self.providers = providers

        # instances cache
        self._provider_clients = {}

    # ---- public API ----

    def search(
        self,
        queries: List[str],
        depth: str = "standard",
        region: Optional[str] = None,
        safesearch: Optional[str] = None,
    ) -> List[Hit]:
        """
        Run queries across providers, merge, dedupe, re-score, and return top-N hits.
        """
        budget = self.cfg.budgets.get(depth, self.cfg.budgets["standard"])
        max_providers = min(budget.max_providers, len(self.providers))

        chosen = self.providers[:max_providers]
        logger.info(f"Search using providers: {[p.name for p in chosen]} with depth={depth}")

        all_hits: List[Hit] = []
        for spec in chosen:
            prov = self._get_provider(spec.name)
            try:
                hits = prov.search(
                    queries=queries,
                    max_results=budget.max_hits * 2,  # collect more; we'll dedupe
                    region=region or self.cfg.search_region,
                    safesearch=safesearch or self.cfg.safesearch,
                )
                # mark provider weight in score later
                for h in hits:
                    h.score = max(0.0, h.score) + (0.02 * spec.weight)
                all_hits.extend(hits)
            except Exception as e:
                logger.warning(f"Provider {spec.name} failed: {e}")

        logger.info(f"Aggregator collected {len(all_hits)} raw hits")

        deduped = self._dedupe_hits(all_hits)
        logger.info(f"After dedupe: {len(deduped)} hits")

        rescored = self._score_hits(deduped, queries)
        topn = sorted(rescored, key=lambda h: h.score, reverse=True)[:budget.max_hits]
        return topn

    # ---- internals ----

    def _get_provider(self, name: str):
        if name in self._provider_clients:
            return self._provider_clients[name]

        if name == "ddg":
            client = DDGProvider(settings=self.cfg)
        elif name == "tavily":
            client = TavilyProvider(settings=self.cfg)
        else:
            raise ValueError(f"Unknown provider: {name}")

        self._provider_clients[name] = client
        return client

    def _dedupe_hits(self, hits: Iterable[Hit]) -> List[Hit]:
        seen = {}
        uniq: List[Hit] = []

        for h in hits:
            key = canonicalize_url(h.url)
            if not key:
                continue

            # If already seen, keep the one with higher score and longer snippet
            if key in seen:
                prev_idx = seen[key]
                prev = uniq[prev_idx]
                better = h if _is_better(h, prev) else prev
                uniq[prev_idx] = better
            else:
                seen[key] = len(uniq)
                uniq.append(h)

        return uniq

    def _score_hits(self, hits: Iterable[Hit], queries: List[str]) -> List[Hit]:
        out: List[Hit] = []
        for h in hits:
            s = score_hit(h, queries, authority_domains=self.cfg.authority_domains, recency_markers=self.cfg.recency_markers)
            h.score = s
            out.append(h)
        return out


def _is_better(a: Hit, b: Hit) -> bool:
    """
    Prefer higher score and richer snippet; break ties using provider source.
    """
    if a.score != b.score:
        return a.score > b.score
    if len(a.snippet) != len(b.snippet):
        return len(a.snippet) > len(b.snippet)

    # small deterministic tiebreaker
    return a.source < b.source

