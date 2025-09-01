# python_back_end/research/search/scoring.py
from __future__ import annotations
from typing import List
from ..core.types import Hit

SEARCH_DOMAINS = ("google.com", "bing.com", "yahoo.com", "duckduckgo.com", "search.brave.com")
LOW_VALUE_DOMAINS = ("pinterest.", "facebook.", "x.com", "twitter.com", "instagram.com")

TECH_HINTS = ("tutorial", "guide", "documentation", "api", "example", "implementation", "benchmark")

def score_hit(
    hit: Hit,
    queries: List[str],
    authority_domains: List[str],
    recency_markers: List[str],
) -> float:
    """
    Lightweight heuristic score combining:
    - keyword overlap (title/snippet)
    - authority domain boost
    - recency markers (year tokens)
    - domain penalties for low-value/SE homepages
    """
    title = (hit.title or "").lower()
    snippet = (hit.snippet or "").lower()
    url = (hit.url or "").lower()

    # penalties
    if any(d in url for d in SEARCH_DOMAINS):
        return 0.0
    penalty = 0.0
    if any(d in url for d in LOW_VALUE_DOMAINS):
        penalty += 0.1

    # keyword overlap
    q_words = set(" ".join(queries).lower().split())
    title_matches = sum(1 for w in q_words if w in title)
    snip_matches = sum(1 for w in q_words if w in snippet)
    overlap = 0.0
    if q_words:
        overlap = (title_matches / len(q_words)) * 0.6 + (snip_matches / len(q_words)) * 0.3

    # authority boost
    authority = 0.0
    if any(dom in url for dom in authority_domains):
        authority += 0.3

    # recency boost
    recency = 0.0
    if any(y in (title + " " + snippet) for y in recency_markers):
        recency += 0.15

    # technical hint
    tech = 0.0
    if any(tok in (title + " " + snippet) for tok in TECH_HINTS):
        tech += 0.1

    score = max(0.0, overlap + authority + recency + tech - penalty)
    # keep within [0, 1.2]
    return min(1.2, score)

