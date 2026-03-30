from pydantic import BaseModel
from typing import List, Dict, Any
from ..registry import Tool, register
from ..vectordb_client import VectorDBClient
from ..embedding_client import EmbeddingClient

_vectordb_client: VectorDBClient | None = None
_embedding_client: EmbeddingClient | None = None


class SearchAllInput(BaseModel):
    query: str
    top_k: int = 5


class SearchAllOutput(BaseModel):
    results: List[Dict[str, Any]]


async def search_all_handler(inp: SearchAllInput) -> dict:
    """Cross-collection search (both code and docs)."""
    global _embedding_client, _vectordb_client

    if _embedding_client is None or _vectordb_client is None:
        raise ValueError("Clients not initialized")

    # Generate embeddings for both models
    code_embedding = await _embedding_client.generate(inp.query, "qwen3-embedding")
    docs_embedding = await _embedding_client.generate(inp.query, "nomic-embed-text")

    # Search both collections
    code_results = await _vectordb_client.search(
        "local_rag_corpus_code", code_embedding, inp.top_k // 2 + 1
    )
    docs_results = await _vectordb_client.search(
        "local_rag_corpus_docs", docs_embedding, inp.top_k // 2 + 1
    )

    # Merge and sort by similarity
    all_results = code_results + docs_results
    all_results.sort(key=lambda x: x["similarity"], reverse=True)

    # Return top_k results
    return {"results": all_results[: inp.top_k]}


def register_search_all():
    register(
        Tool(
            name="search_all",
            input_model=SearchAllInput,
            output_model=SearchAllOutput,
            scope="rag.read",
            handler=search_all_handler,
            timeout_s=30,
        )
    )
