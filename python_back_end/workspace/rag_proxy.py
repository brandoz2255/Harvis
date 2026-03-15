"""
RAG search proxy for OpenClaw workspace agents.

OpenClaw agents call this to search the Harvis vector database without
needing direct database access.

Security model:
  - Verifies OPENCLAW_GATEWAY_TOKEN on every request (only OpenClaw can call this).
  - Read-only: no writes to the vector database.
  - Returns text chunks and metadata; no raw embeddings exposed.

Endpoints:
  POST /rag/search   — semantic search across code or docs corpus
  GET  /rag/health   — check embedding models and DB connectivity

Note on indexing:
  local_rag_corpus_code uses halfvec(2560). pgvector 0.8.0 limits ANN indexes
  (both hnsw and ivfflat) to 4000 dimensions, so an HNSW index can be added
  after rebuild completes. At 2 241 rows sequential scan is fast enough (~10-30 ms).
  local_rag_corpus_docs uses vector(768) and has an HNSW index already.
"""

import logging
import os
from typing import List, Optional

import aiohttp
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBED_NOMIC_URL = os.getenv("EMBED_NOMIC_URL", OLLAMA_URL)   # port 8081, nomic-embed-text (llama.cpp)
EMBED_QW3_URL = os.getenv("EMBED_QW3_URL", OLLAMA_URL)        # port 8082, Qwen3-Embedding-4B (llama.cpp)
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_RERANK_URL = "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking"

# Model config keyed by context_type
_CORPUS_CONFIG = {
    "code": {
        "table": "local_rag_corpus_code",
        "model": "qwen3-embedding",
        "embed_url": None,  # resolved at runtime from EMBED_QW3_URL
        "dims": 2560,
        "cast": "halfvec",
        "ops": "<=>",   # cosine distance
    },
    "docs": {
        "table": "local_rag_corpus_docs",
        "model": "nomic-embed-text",
        "embed_url": None,  # resolved at runtime from EMBED_NOMIC_URL
        "dims": 768,
        "cast": "vector",
        "ops": "<=>",
    },
}

rag_proxy_router = APIRouter(prefix="/rag", tags=["rag-proxy"])


def _verify_openclaw_token(authorization: Optional[str]) -> None:
    if not OPENCLAW_GATEWAY_TOKEN:
        return  # dev mode
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):]
    if token != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid proxy token")


_EMBED_URL_MAP = {
    "qwen3-embedding": EMBED_QW3_URL,
    "nomic-embed-text": EMBED_NOMIC_URL,
}


async def _embed(query: str, model: str) -> List[float]:
    """Call the appropriate embedding server and return the vector.

    llama.cpp servers (ports 8081/8082) use OpenAI-compatible /v1/embeddings.
    Falls back to Ollama /api/embeddings if no dedicated URL is configured.
    """
    if len(query) > 8000:
        query = query[:8000]

    embed_url = _EMBED_URL_MAP.get(model, OLLAMA_URL)
    use_llamacpp = embed_url != OLLAMA_URL

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        if use_llamacpp:
            # llama.cpp OpenAI-compatible endpoint
            async with session.post(
                f"{embed_url}/v1/embeddings",
                json={"input": query},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise HTTPException(
                        status_code=502,
                        detail=f"llama.cpp embedding error ({resp.status}): {text[:200]}",
                    )
                data = await resp.json()
                vec = data.get("data", [{}])[0].get("embedding")
        else:
            # Ollama endpoint
            async with session.post(
                f"{embed_url}/api/embeddings",
                json={"model": model, "prompt": query},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise HTTPException(
                        status_code=502,
                        detail=f"Ollama embedding error ({resp.status}): {text[:200]}",
                    )
                data = await resp.json()
                vec = data.get("embedding")

    if not vec:
        raise HTTPException(status_code=502, detail="Embedding server returned empty vector")
    return vec


# ─── Request / response models ──────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    context_type: str = "code"   # "code" | "docs"
    top_k: int = 5
    score_threshold: float = 0.3
    rerank: bool = False          # set True to apply NVIDIA reranker after vector search

    @field_validator("context_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in _CORPUS_CONFIG:
            raise ValueError(f"context_type must be one of {list(_CORPUS_CONFIG)}")
        return v

    @field_validator("top_k")
    @classmethod
    def clamp_k(cls, v: int) -> int:
        return max(1, min(v, 20))

    @field_validator("query")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query cannot be empty")
        return v.strip()


class SearchResult(BaseModel):
    id: str
    text: str
    source: Optional[str]
    metadata: dict
    score: float


class SearchResponse(BaseModel):
    query: str
    context_type: str
    results: List[SearchResult]
    total: int
    reranked: bool = False


# ─── Reranker ────────────────────────────────────────────────────────────────

async def _rerank_results(query: str, results: List[SearchResult], api_key: str) -> List[SearchResult]:
    """Re-score results using NVIDIA nv-rerank-qa-mistral-4b:1.

    Falls back to original order (with a warning) if the API key is missing or the call fails.
    """
    payload = {
        "model": "nv-rerank-qa-mistral-4b:1",
        "query": {"text": query},
        "passages": [{"text": r.text[:2000]} for r in results],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.post(NVIDIA_RERANK_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"NVIDIA reranker error ({resp.status}): {text[:200]}")
            data = await resp.json()
    rankings = data.get("rankings", [])
    if not rankings:
        return results
    # rankings is a list of {"index": int, "logit": float} sorted by score
    # We re-sort our results list by the reranker's logit score (descending)
    indexed = {r["index"]: r.get("logit", 0.0) for r in rankings}
    return sorted(results, key=lambda r_: indexed.get(results.index(r_), 0.0), reverse=True)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@rag_proxy_router.post("/search", response_model=SearchResponse)
async def rag_search(
    req: SearchRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """
    Semantic search over the Harvis vector database.

    context_type "code"  → searches local_rag_corpus_code  (qwen3:embedding4b, halfvec 2560)
    context_type "docs"  → searches local_rag_corpus_docs  (nomic-embed-text, vector 768)
    """
    _verify_openclaw_token(authorization)

    cfg = _CORPUS_CONFIG[req.context_type]
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database pool not available")

    # Generate embedding
    try:
        vec = await _embed(req.query, cfg["model"])
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("rag_proxy: embedding failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Embedding error: {exc}")

    # Validate dimensions before hitting pgvector — wrong dims cause cryptic DB errors
    expected_dim = cfg["dims"]
    if len(vec) != expected_dim:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "embedding_dim_mismatch",
                "expected": expected_dim,
                "got": len(vec),
                "model": cfg["model"],
                "hint": "Ollama returned wrong dims — model may have fallen back to HuggingFace",
            },
        )

    # Format as pgvector literal
    vec_str = "[" + ",".join(str(x) for x in vec) + "]"
    table = cfg["table"]
    cast = cfg["cast"]

    sql = f"""
        SELECT
            id,
            text,
            source,
            metadata,
            1 - (embedding <=> $1::{cast}) AS score
        FROM {table}
        WHERE 1 - (embedding <=> $1::{cast}) >= $2
        ORDER BY embedding <=> $1::{cast}
        LIMIT $3
    """

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, vec_str, req.score_threshold, req.top_k)
    except Exception as exc:
        logger.error("rag_proxy: db search failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Database error: {exc}")

    results = [
        SearchResult(
            id=row["id"],
            text=row["text"],
            source=row["source"],
            metadata=dict(row["metadata"]) if row["metadata"] else {},
            score=float(row["score"]),
        )
        for row in rows
    ]

    logger.info(
        "rag_proxy: search context_type=%s query=%r top_k=%d returned=%d",
        req.context_type, req.query[:60], req.top_k, len(results),
    )

    reranked = False
    if req.rerank and results:
        if not NVIDIA_API_KEY:
            logger.warning("rag_proxy: rerank requested but NVIDIA_API_KEY not set, skipping")
        else:
            try:
                results = await _rerank_results(req.query, results, NVIDIA_API_KEY)
                reranked = True
                logger.info("rag_proxy: reranked %d results", len(results))
            except Exception as exc:
                logger.warning("rag_proxy: reranker failed, using original order: %s", exc)

    return SearchResponse(
        query=req.query,
        context_type=req.context_type,
        results=results,
        total=len(results),
        reranked=reranked,
    )


@rag_proxy_router.get("/health")
async def rag_health(
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """Check DB connectivity and embedding model availability."""
    _verify_openclaw_token(authorization)

    ollama_url = OLLAMA_URL

    # Check DB and row counts
    pool = getattr(request.app.state, "pg_pool", None)
    db_ok = False
    counts = {}
    if pool:
        try:
            async with pool.acquire() as conn:
                for ct, cfg in _CORPUS_CONFIG.items():
                    n = await conn.fetchval(f"SELECT COUNT(*) FROM {cfg['table']}")
                    counts[ct] = n
            db_ok = True
        except Exception as exc:
            logger.warning("rag_proxy health: db error: %s", exc)

    # Check embedding server availability (llama.cpp /health, or Ollama /api/tags fallback)
    models_status: dict = {}
    async with aiohttp.ClientSession() as session:
        for ctx, cfg in _CORPUS_CONFIG.items():
            model = cfg["model"]
            embed_url = _EMBED_URL_MAP.get(model, OLLAMA_URL)
            try:
                if embed_url != OLLAMA_URL:
                    # llama.cpp server — check /health
                    async with session.get(
                        f"{embed_url}/health",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as r:
                        available = r.status == 200
                else:
                    # Ollama fallback — check /api/tags
                    async with session.get(
                        f"{embed_url}/api/tags",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as r:
                        tags_data = await r.json()
                        pulled = {m["name"] for m in tags_data.get("models", [])}
                        available = model in pulled or any(
                            model.split(":")[0] == t.split(":")[0] for t in pulled
                        )
                models_status[ctx] = {"name": model, "url": embed_url, "available": available}
            except Exception as exc:
                logger.warning("rag_proxy health: embed check failed for %s: %s", ctx, exc)
                models_status[ctx] = {"name": model, "url": embed_url, "available": False}

    all_models_ok = all(v["available"] for v in models_status.values())

    return {
        "ok": db_ok and all_models_ok,
        "corpus_counts": counts,
        "models": models_status,
    }
