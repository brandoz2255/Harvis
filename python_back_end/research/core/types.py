# python_back_end/research/core/types.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class Hit:
    """
    A single search hit from a provider (DuckDuckGo, Tavily, etc).
    """
    title: str
    url: str
    snippet: str
    score: float
    source: str   # provider name e.g. "ddg", "tavily", "bing"

@dataclass
class DocChunk:
    """
    A chunk of extracted document text, ready for LLM input.
    """
    url: str
    title: str
    text: str
    start: int
    end: int
    meta: Dict[str, str]   # e.g., {"page": "3"} for PDFs

@dataclass
class Quote:
    """
    A short exact span pulled from a document, used for grounded citations.
    """
    url: str
    title: str
    quote: str
    location: str  # fragment anchor, or "p. 3" for PDFs

@dataclass
class ResearchArtifacts:
    """
    Bundle of all intermediate data in a research run.
    Useful for debugging or for MCP streaming.
    """
    queries: List[str]
    hits: List[Hit]
    chunks: List[DocChunk]
    quotes: List[Quote]

