# python_back_end/research/config/settings.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------- Feature Flags ----------
ENABLE_TRAFILATURA = True          # robust HTML extraction
ENABLE_YOUTUBE = True              # transcript extraction when possible
ENABLE_PDF = True                  # PDF text + page mapping
ENABLE_BM25 = True                 # fast lexical rerank
ENABLE_CROSS_RERANK = False        # plug a cross-encoder later
ENABLE_QUOTE_BACKS = True          # enforce quote-backed citations
ENABLE_REQUESTS_CACHE = True       # cache HTTP GETs to speed up repeated runs

DEFAULT_USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
 
# ---------- Providers / Keys ----------
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY") or ""
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY") or "key"

# Optional extra providers you may add later
BING_API_KEY = os.getenv("BING_API_KEY") or ""
SERPAPI_KEY = os.getenv("SERPAPI_KEY") or ""

# ---------- Model Policy ----------
@dataclass
class ModelPolicy:
    # stage → model name
    planner: str = os.getenv("LLM_PLANNER_MODEL", "mistral")
    mapper: str = os.getenv("LLM_MAP_MODEL", "mistral")
    reducer: str = os.getenv("LLM_REDUCE_MODEL", "mistral")
    verifier: str = os.getenv("LLM_VERIFY_MODEL", "mistral")

# ---------- Budgets per depth ----------
@dataclass
class DepthBudget:
    max_providers: int
    max_hits: int            # total search hits to keep (after dedupe)
    max_extract: int         # how many URLs to fully extract
    max_chunks: int          # how many chunks to pass to map stage
    max_map_tokens: int      # rough cap per map call
    max_reduce_tokens: int   # rough cap for reduce call
    request_timeout_s: int

DEFAULT_BUDGETS: Dict[str, DepthBudget] = {
    "quick": DepthBudget(
        max_providers=1, max_hits=6, max_extract=4, max_chunks=12,
        max_map_tokens=800, max_reduce_tokens=1200, request_timeout_s=15
    ),
    "standard": DepthBudget(
        max_providers=2, max_hits=12, max_extract=8, max_chunks=24,
        max_map_tokens=1200, max_reduce_tokens=2000, request_timeout_s=20
    ),
    "deep": DepthBudget(
        max_providers=3, max_hits=20, max_extract=14, max_chunks=40,
        max_map_tokens=1600, max_reduce_tokens=2600, request_timeout_s=30
    ),
}
# ---------- HTTP / Networking ----------
REQUESTS_TIMEOUT_S = int(os.getenv("REQUESTS_TIMEOUT_S", "15"))
REQUESTS_RETRIES = int(os.getenv("REQUESTS_RETRIES", "2"))
REQUESTS_CACHE_NAME = os.getenv("REQUESTS_CACHE_NAME", "requests_cache")
REQUESTS_CACHE_EXPIRY_S = int(os.getenv("REQUESTS_CACHE_EXPIRY_S", "7200"))

# ---------- Search preferences ----------
DEFAULT_REGION = os.getenv("SEARCH_REGION", "us-en")
DEFAULT_SAFESEARCH = os.getenv("SEARCH_SAFESEARCH", "moderate")

# Authority and recency boosts (lightweight scoring hints)
AUTHORITY_DOMAINS = [
    "github.com", "arxiv.org", "openai.com", "huggingface.co",
    "pytorch.org", "tensorflow.org", "scikit-learn.org",
    "docs.python.org", "nvidia.com", "microsoft.com", "research.google",
    "deepmind.com", "anthropic.com"
]
RECENT_YEARS = ["2025", "2024", "2023"]

# ---------- Root Config ----------
@dataclass
class Settings:
    # endpoints
    cloud_ollama_url: str = os.getenv("CLOUD_OLLAMA_URL", "https://coyotegpt.ngrok.app/ollama")
    local_ollama_url: str = os.getenv("OLLAMA_URL", "http://ollama:11434")  # Use OLLAMA_URL for consistency with main chat

    # keys
    ollama_api_key: str = OLLAMA_API_KEY
    tavily_api_key: str = TAVILY_API_KEY

    # policies
    model_policy: ModelPolicy = field(default_factory=ModelPolicy)
    budgets: Dict[str, DepthBudget] = field(default_factory=lambda: DEFAULT_BUDGETS)

    # features
    enable_trafilatura: bool = ENABLE_TRAFILATURA
    enable_youtube: bool = ENABLE_YOUTUBE
    enable_pdf: bool = ENABLE_PDF
    enable_bm25: bool = ENABLE_BM25
    enable_cross_rerank: bool = ENABLE_CROSS_RERANK
    enable_quote_backs: bool = ENABLE_QUOTE_BACKS
    enable_requests_cache: bool = ENABLE_REQUESTS_CACHE

    # http/search
    user_agent: str = DEFAULT_USER_AGENT
    requests_timeout_s: int = REQUESTS_TIMEOUT_S
    requests_retries: int = REQUESTS_RETRIES
    requests_cache_name: str = REQUESTS_CACHE_NAME
    requests_cache_expiry_s: int = REQUESTS_CACHE_EXPIRY_S
    search_region: str = DEFAULT_REGION
    safesearch: str = DEFAULT_SAFESEARCH

    authority_domains: List[str] = field(default_factory=lambda: AUTHORITY_DOMAINS)
    recency_markers: List[str] = field(default_factory=lambda: RECENT_YEARS)

def get_settings() -> Settings:
    """
    Factory so callers can do:
        from research.config.settings import get_settings
        cfg = get_settings()
    """
    return Settings()