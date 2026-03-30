from pydantic import BaseModel
from typing import List, Dict, Any
from ..registry import Tool, register
from ..vectordb_client import VectorDBClient
from ..embedding_client import EmbeddingClient

# Global clients (initialized by app.py)
_vectordb_client: VectorDBClient | None = None
_embedding_client: EmbeddingClient | None = None


class SearchCodeInput(BaseModel):
    query: str
    top_k: int = 5
    sources: List[str] | None = None


class SearchCodeOutput(BaseModel):
    results: List[Dict[str, Any]]


async def search_code_handler(inp: SearchCodeInput) -> dict:
    """Search code embeddings (2560-dim Qwen3)."""
    global _embedding_client, _vectordb_client

    if _embedding_client is None or _vectordb_client is None:
        raise ValueError("Clients not initialized")

    # Generate embedding
    embedding = await _embedding_client.generate(inp.query, "qwen3-embedding")

    # Search vector DB
    source_filter = inp.sources if inp.sources else None
    results = await _vectordb_client.search(
        "local_rag_corpus_code", embedding, inp.top_k, source_filter
    )

    return {"results": results}


def register_search_code():
    register(
        Tool(
            name="search_code",
            input_model=SearchCodeInput,
            output_model=SearchCodeOutput,
            scope="rag.read",
            handler=search_code_handler,
            timeout_s=30,
        )
    )
