import os
import logging
import asyncpg
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class VectorDBClient:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self._pool: Optional[asyncpg.Pool] = None

    async def initialize(self):
        """Initialize connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self.db_url,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )
            logger.info("VectorDB connection pool initialized")

    async def close(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("VectorDB connection pool closed")

    async def search(
        self,
        collection: str,
        embedding: List[float],
        top_k: int = 5,
        source_filter: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Simple vector similarity search.

        Args:
            collection: Table name (local_rag_corpus_code or local_rag_corpus_docs)
            embedding: Vector embedding as list of floats
            top_k: Number of results to return
            source_filter: Optional list of sources to filter by

        Returns:
            List of {text, source, similarity} dicts
        """
        if self._pool is None:
            await self.initialize()

        # Determine vector type based on collection
        is_code_collection = "code" in collection
        vector_type = "halfvec" if is_code_collection else "vector"

        # Build query
        query = f"""
            SELECT text, source,
                   1 - (embedding <=> $1::{vector_type}) as similarity
            FROM {collection}
        """
        params = [embedding, top_k]

        if source_filter:
            query += " WHERE source = ANY($2)"
            params.append(source_filter)

        query += f" ORDER BY embedding <=> $1::{vector_type} LIMIT $2"

        try:
            async with self._pool.acquire() as conn:
                # Convert embedding list to string format for pgvector
                embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                rows = await conn.fetch(query, embedding_str, top_k)
                return [
                    {
                        "text": row["text"],
                        "source": row["source"],
                        "similarity": float(row["similarity"]),
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            raise

    async def get_source_stats(self) -> Dict[str, Dict[str, int]]:
        """
        Get document counts per source for each collection.

        Returns:
            Dict mapping collection name to {source: count}
        """
        if self._pool is None:
            await self.initialize()

        collections = ["local_rag_corpus_code", "local_rag_corpus_docs"]
        stats = {}

        try:
            async with self._pool.acquire() as conn:
                for collection in collections:
                    rows = await conn.fetch(
                        f"SELECT source, COUNT(*) as count FROM {collection} GROUP BY source"
                    )
                    stats[collection] = {row["source"]: row["count"] for row in rows}
            return stats
        except Exception as e:
            logger.error(f"Failed to get source stats: {e}")
            return {}
