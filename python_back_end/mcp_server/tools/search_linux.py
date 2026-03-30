from pydantic import BaseModel
from typing import List, Dict, Any
from ..registry import Tool, register
from ..vectordb_client import VectorDBClient
from ..embedding_client import EmbeddingClient

_vectordb_client: VectorDBClient | None = None
_embedding_client: EmbeddingClient | None = None


class SearchLinuxInput(BaseModel):
    query: str
    top_k: int = 5


class SearchLinuxOutput(BaseModel):
    results: List[Dict[str, Any]]


async def search_linux_handler(inp: SearchLinuxInput) -> dict:
    """Search Linux commands and system administration docs."""
    global _embedding_client, _vectordb_client

    if _embedding_client is None or _vectordb_client is None:
        raise ValueError("Clients not initialized")

    embedding = await _embedding_client.generate(inp.query, "nomic-embed-text")

    # Focus on Linux documentation sources
    linux_sources = ["redhat_docs", "arch_linux_docs"]
    results = await _vectordb_client.search(
        "local_rag_corpus_docs", embedding, inp.top_k, linux_sources
    )

    return {"results": results}


def register_search_linux():
    register(
        Tool(
            name="search_linux",
            input_model=SearchLinuxInput,
            output_model=SearchLinuxOutput,
            scope="rag.read",
            handler=search_linux_handler,
            timeout_s=30,
        )
    )
