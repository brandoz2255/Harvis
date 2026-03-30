from pydantic import BaseModel
from typing import List, Dict, Any
from ..registry import Tool, register
from ..vectordb_client import VectorDBClient
from ..embedding_client import EmbeddingClient

_vectordb_client: VectorDBClient | None = None
_embedding_client: EmbeddingClient | None = None


class SearchCyberInput(BaseModel):
    query: str
    top_k: int = 5
    sources: List[str] | None = None


class SearchCyberOutput(BaseModel):
    results: List[Dict[str, Any]]


async def search_cyber_handler(inp: SearchCyberInput) -> dict:
    """Search cyber security documentation (768-dim nomic)."""
    global _embedding_client, _vectordb_client

    if _embedding_client is None or _vectordb_client is None:
        raise ValueError("Clients not initialized")

    embedding = await _embedding_client.generate(inp.query, "nomic-embed-text")

    source_filter = inp.sources if inp.sources else None
    results = await _vectordb_client.search(
        "local_rag_corpus_docs", embedding, inp.top_k, source_filter
    )

    return {"results": results}


def register_search_cyber():
    register(
        Tool(
            name="search_cyber",
            input_model=SearchCyberInput,
            output_model=SearchCyberOutput,
            scope="rag.read",
            handler=search_cyber_handler,
            timeout_s=30,
        )
    )
