from pydantic import BaseModel
from typing import List, Dict, Any
from ..registry import Tool, register
from ..vectordb_client import VectorDBClient

_vectordb_client: VectorDBClient | None = None


class GetSourceListInput(BaseModel):
    pass


class GetSourceListOutput(BaseModel):
    sources: Dict[str, Any]
    total_documents: int


async def get_source_list_handler(_: GetSourceListInput) -> dict:
    """List all available sources and their statistics."""
    global _vectordb_client

    if _vectordb_client is None:
        raise ValueError("VectorDB client not initialized")

    stats = await _vectordb_client.get_source_stats()

    # Format response with model info
    formatted = {
        "local_rag_corpus_code": {
            "embedding_model": "qwen3-embedding",
            "dimensions": 2560,
            "sources": [
                {"name": name, "count": count}
                for name, count in stats.get("local_rag_corpus_code", {}).items()
            ],
        },
        "local_rag_corpus_docs": {
            "embedding_model": "nomic-embed-text",
            "dimensions": 768,
            "sources": [
                {"name": name, "count": count}
                for name, count in stats.get("local_rag_corpus_docs", {}).items()
            ],
        },
    }

    total = sum(
        sum(s["count"] for s in coll["sources"])
        for coll in formatted.values()
        if "sources" in coll
    )

    return {"sources": formatted, "total_documents": total}


def register_get_source_list():
    register(
        Tool(
            name="get_source_list",
            input_model=GetSourceListInput,
            output_model=GetSourceListOutput,
            scope="rag.read",
            handler=get_source_list_handler,
            timeout_s=10,
        )
    )
