"""
Vector Database Adapter for RAG Corpus

Provides interface for storing and searching embeddings in PostgreSQL with pgvector.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class VectorRecord:
    """Record to store in the vector database."""
    id: str
    embedding: List[float]
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Result from vector search."""
    id: str
    text: str
    metadata: Dict[str, Any]
    score: float  # Similarity score (higher is better)


class VectorDBAdapter:
    """
    Adapter for pgvector operations.
    
    Stores embeddings in PostgreSQL with pgvector extension.
    Uses asyncpg for async database operations.
    """
    
    def __init__(
        self,
        db_pool,
        collection_name: str = "local_rag_corpus",
        embedding_dimension: int = None  # Auto-detect from first embedding
    ):
        """
        Initialize the vector database adapter.
        
        Args:
            db_pool: asyncpg connection pool
            collection_name: Name for the vector table
            embedding_dimension: Dimension of embeddings (auto-detected if None)
        """
        self.db_pool = db_pool
        self.table_name = collection_name
        self.embedding_dimension = embedding_dimension
        self._initialized = False
    
    async def initialize(self, embedding_dimension: int = None, recreate_if_mismatch: bool = False) -> None:
        """Initialize the database table and indexes."""
        # Update dimension if provided
        if embedding_dimension:
            self.embedding_dimension = embedding_dimension

        if not self.embedding_dimension:
            # If no dimension set yet, we can't initialize table creation,
            # but we can check if table exists to set our dimension
            if not self._initialized:
                # Try to learn dimension from existing table
                 async with self.db_pool.acquire() as conn:
                    existing_dim = await conn.fetchval(f"""
                        SELECT atttypmod
                        FROM pg_attribute
                        WHERE attrelid = '{self.table_name}'::regclass
                        AND attname = 'embedding'
                    """)
                    if existing_dim:
                        self.embedding_dimension = existing_dim
                        self._initialized = True
                        logger.info(f"Discovered existing vector table: {self.table_name} (dimension: {self.embedding_dimension})")
            return

        async with self.db_pool.acquire() as conn:
            try:
                # Ensure pgvector extension exists
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

                # Check if table exists first
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = $1
                    )
                """, self.table_name)

                row = None
                if table_exists:
                    # Get current dimension/type using a reliable method
                    row = await conn.fetchrow(f"""
                        SELECT
                            CASE
                                WHEN format_type(a.atttypid, a.atttypmod) ~ 'vector\\(([0-9]+)\\)'
                                THEN (regexp_match(format_type(a.atttypid, a.atttypmod), 'vector\\(([0-9]+)\\)'))[1]::int
                                WHEN format_type(a.atttypid, a.atttypmod) ~ 'halfvec\\(([0-9]+)\\)'
                                THEN (regexp_match(format_type(a.atttypid, a.atttypmod), 'halfvec\\(([0-9]+)\\)'))[1]::int
                                ELSE NULL
                            END as dim,
                            t.typname
                        FROM pg_attribute a
                        JOIN pg_type t ON a.atttypid = t.oid
                        WHERE a.attrelid = '{self.table_name}'::regclass
                        AND a.attname = 'embedding'
                    """)
                
                existing_dim = row['dim'] if row else None
                existing_type = row['typname'] if row else None

                logger.info(f"Existing table dimension: {existing_dim}, type: {existing_type}, requested: {self.embedding_dimension}")
                
                # Determine target type
                target_type_name = "halfvec" if self.embedding_dimension > 2000 else "vector"
                
                if existing_dim is not None:
                    # Table exists - check if dimension AND type match
                    # Note: atttypmod might include header overhead, but usually matches for vector
                    
                    type_mismatch = existing_type != target_type_name
                    dim_mismatch = existing_dim != self.embedding_dimension
                    
                    if dim_mismatch or type_mismatch:
                        if recreate_if_mismatch:
                            reason = []
                            if dim_mismatch: reason.append(f"dimension {existing_dim}->{self.embedding_dimension}")
                            if type_mismatch: reason.append(f"type {existing_type}->{target_type_name}")

                            logger.warning(f"Vector table mismatch ({', '.join(reason)}). Recreating table...")
                            await conn.execute(f"DROP TABLE IF EXISTS {self.table_name};")
                            logger.info(f"Dropped table {self.table_name}, will recreate with dimension {self.embedding_dimension}")
                        else:
                            logger.warning(
                                f"Vector table mismatch (Dim: {existing_dim}, Type: {existing_type}) vs (Dim: {self.embedding_dimension}, Type: {target_type_name}). "
                                f"Preserving existing data. To overwrite, explicit update is required."
                            )
                            self.embedding_dimension = existing_dim
                            self._initialized = True
                            return
                    else:
                        # Exact match
                        self._initialized = True
                        return
                
                # Determine vector type based on dimension limit (2000)
                # pgvector standard vector type limit is 2000.
                # For larger embeddings (like Qwen 2560), we must use halfvec (limits up to 4000)
                if self.embedding_dimension > 2000:
                    vector_type = f"halfvec({self.embedding_dimension})"
                    index_ops = "halfvec_cosine_ops"
                    logger.info(f"Using halfvec type for high-dimensional vectors ({self.embedding_dimension} > 2000)")
                else:
                    vector_type = f"vector({self.embedding_dimension})"
                    index_ops = "vector_cosine_ops"

                # Create table with correct vector type
                await conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id VARCHAR(64) PRIMARY KEY,
                        embedding {vector_type},
                        text TEXT NOT NULL,
                        metadata JSONB DEFAULT '{{}}',
                        source VARCHAR(128),
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """)
                
                # Create indexes
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_source 
                    ON {self.table_name}(source);
                """)
                
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_embedding 
                    ON {self.table_name} USING hnsw (embedding {index_ops});
                """)
                
                self._initialized = True
                logger.info(f"Initialized vector table: {self.table_name} (dimension: {self.embedding_dimension})")
                
            except Exception as e:
                # Table might not exist yet, that's OK
                if "does not exist" in str(e):
                    # Create table fresh with correct vector type
                    if self.embedding_dimension > 2000:
                        vector_type = f"halfvec({self.embedding_dimension})"
                    else:
                        vector_type = f"vector({self.embedding_dimension})"

                    await conn.execute(f"""
                        CREATE TABLE IF NOT EXISTS {self.table_name} (
                            id VARCHAR(64) PRIMARY KEY,
                            embedding {vector_type},
                            text TEXT NOT NULL,
                            metadata JSONB DEFAULT '{{}}',
                            source VARCHAR(128),
                            created_at TIMESTAMPTZ DEFAULT NOW(),
                            updated_at TIMESTAMPTZ DEFAULT NOW()
                        );
                    """)
                    self._initialized = True
                    logger.info(f"Created fresh vector table: {self.table_name} with {vector_type}")
                else:
                    logger.error(f"Failed to initialize vector table: {e}")
                    raise
    
    async def upsert_vectors(self, records: List[VectorRecord]) -> int:
        """
        Upsert records into the vector database.
        
        Args:
            records: List of records to upsert
            
        Returns:
            Number of records upserted
        """
        if not records:
            return 0
        
        # Auto-detect dimension from first embedding
        first_embedding = records[0].embedding
        embedding_dim = len(first_embedding)
        
        # Initialize with detected dimension
        # Allow recreation because we are writing new data with known dimension
        await self.initialize(embedding_dimension=embedding_dim, recreate_if_mismatch=True)
        
        upserted = 0
        
        # Determine vector cast type
        vector_cast = "halfvec" if embedding_dim > 2000 else "vector"
        
        async with self.db_pool.acquire() as conn:
            for record in records:
                try:
                    # Extract source from metadata
                    source = record.metadata.get("source", "unknown")
                    
                    # Convert embedding to pgvector format
                    embedding_str = "[" + ",".join(str(x) for x in record.embedding) + "]"
                    
                    # Use EXCLUDED.embedding for conflict update which automatically handles the type
                    await conn.execute(
                        f"""
                        INSERT INTO {self.table_name} 
                        (id, embedding, text, metadata, source, updated_at)
                        VALUES ($1, $2::{vector_cast}, $3, $4::jsonb, $5, NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            text = EXCLUDED.text,
                            metadata = EXCLUDED.metadata,
                            source = EXCLUDED.source,
                            updated_at = NOW()
                        """,
                        record.id,
                        embedding_str,
                        record.text,
                        json.dumps(record.metadata),
                        source
                    )
                    upserted += 1
                    
                except Exception as e:
                    logger.error(f"Error upserting record {record.id}: {e}")
        
        logger.info(f"Upserted {upserted} records to {self.table_name}")
        return upserted
    
    async def search(
        self,
        query_embedding: List[float],
        k: int = 5,
        sources: Optional[List[str]] = None,
        score_threshold: float = 0.0
    ) -> List[SearchResult]:
        """
        Search for similar vectors.
        
        Args:
            query_embedding: Query embedding vector
            k: Number of results to return
            sources: Optional list of sources to filter by
            score_threshold: Minimum similarity score
            
        Returns:
            List of search results
        """
        await self.initialize()
        
        results = []
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        
        async with self.db_pool.acquire() as conn:
            try:
                # Build query based on filters
                if sources:
                    sql = f"""
                    SELECT 
                        id,
                        text,
                        metadata,
                        1 - (embedding <=> $1::vector) AS similarity
                    FROM {self.table_name}
                    WHERE source = ANY($2)
                    AND 1 - (embedding <=> $1::vector) >= $3
                    ORDER BY embedding <=> $1::vector 
                    LIMIT $4
                    """
                    rows = await conn.fetch(sql, embedding_str, sources, score_threshold, k)
                else:
                    sql = f"""
                    SELECT 
                        id,
                        text,
                        metadata,
                        1 - (embedding <=> $1::vector) AS similarity
                    FROM {self.table_name}
                    WHERE 1 - (embedding <=> $1::vector) >= $2
                    ORDER BY embedding <=> $1::vector 
                    LIMIT $3
                    """
                    rows = await conn.fetch(sql, embedding_str, score_threshold, k)
                
                for row in rows:
                    metadata = row['metadata']
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    results.append(SearchResult(
                        id=row['id'],
                        text=row['text'],
                        metadata=metadata,
                        score=float(row['similarity'])
                    ))
                    
            except Exception as e:
                logger.error(f"Search error: {e}")
        
        return results
    
    async def delete_by_source(self, source: str) -> int:
        """
        Delete all records for a source.
        
        Args:
            source: Source to delete
            
        Returns:
            Number of records deleted
        """
        await self.initialize()
        
        async with self.db_pool.acquire() as conn:
            try:
                result = await conn.execute(
                    f"DELETE FROM {self.table_name} WHERE source = $1",
                    source
                )
                # asyncpg returns "DELETE N" string
                deleted = int(result.split()[-1]) if result else 0
                
                logger.info(f"Deleted {deleted} records from source {source}")
                return deleted
                
            except Exception as e:
                logger.error(f"Delete error: {e}")
                return 0
    
    async def delete_by_id(self, record_id: str) -> bool:
        """
        Delete a specific record.
        
        Args:
            record_id: ID of record to delete
            
        Returns:
            True if deleted, False otherwise
        """
        await self.initialize()
        
        async with self.db_pool.acquire() as conn:
            try:
                result = await conn.execute(
                    f"DELETE FROM {self.table_name} WHERE id = $1",
                    record_id
                )
                deleted = int(result.split()[-1]) if result else 0
                return deleted > 0
                
            except Exception as e:
                logger.error(f"Delete error: {e}")
                return False
    
    async def get_source_stats(self) -> Dict[str, int]:
        """
        Get document counts per source.
        
        Returns:
            Dictionary mapping source to count
        """
        await self.initialize()
        
        stats = {}
        
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    f"""
                    SELECT source, COUNT(*) as count
                    FROM {self.table_name}
                    GROUP BY source
                    """
                )
                
                for row in rows:
                    stats[row['source']] = row['count']
                    
            except Exception as e:
                logger.error(f"Stats error: {e}")
        
        return stats
    
    async def get_total_count(self) -> int:
        """Get total number of records."""
        await self.initialize()
        
        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow(f"SELECT COUNT(*) FROM {self.table_name}")
                return row[0] if row else 0
            except Exception as e:
                logger.error(f"Count error: {e}")
                return 0
    
    async def clear_all(self) -> int:
        """
        Delete all records.
        
        Returns:
            Number of records deleted
        """
        await self.initialize()
        
        async with self.db_pool.acquire() as conn:
            try:
                result = await conn.execute(f"DELETE FROM {self.table_name}")
                deleted = int(result.split()[-1]) if result else 0
                
                logger.info(f"Cleared {deleted} records from {self.table_name}")
                return deleted
                
            except Exception as e:
                logger.error(f"Clear error: {e}")
                return 0
    
    async def health_check(self) -> dict:
        """
        Check health of the vector database.
        
        Returns:
            Health status dict
        """
        try:
            async with self.db_pool.acquire() as conn:
                # Check if table exists
                table_exists = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = $1
                    )
                    """,
                    self.table_name
                )
                
                if table_exists:
                    count = await conn.fetchval(f"SELECT COUNT(*) FROM {self.table_name}")
                else:
                    count = 0
                
                return {
                    "status": "healthy",
                    "table_name": self.table_name,
                    "table_exists": table_exists,
                    "record_count": count,
                    "embedding_dimension": self.embedding_dimension,
                }
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }



class LocalRAGRetriever:
    """
    Retriever that combines local RAG with the existing chat pipeline.

    Provides context from the local corpus for LLM queries.
    """

    def __init__(
        self,
        vectordb_adapter: VectorDBAdapter,
        embedding_adapter,  # EmbeddingAdapter
        default_k: int = 5,
        score_threshold: float = 0.5
    ):
        """
        Initialize the retriever.

        Args:
            vectordb_adapter: Vector database adapter
            embedding_adapter: Embedding adapter for queries
            default_k: Default number of results
            score_threshold: Minimum similarity score
        """
        self.vectordb = vectordb_adapter
        self.embedder = embedding_adapter
        self.default_k = default_k
        self.score_threshold = score_threshold

    async def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        sources: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """
        Retrieve relevant context for a query.

        Args:
            query: User query
            k: Number of results (uses default if None)
            sources: Optional source filter

        Returns:
            List of search results
        """
        # Generate query embedding
        query_embedding = await self.embedder.embed_text(query)

        # Search vector database
        results = await self.vectordb.search(
            query_embedding=query_embedding,
            k=k or self.default_k,
            sources=sources,
            score_threshold=self.score_threshold
        )

        return results

    async def get_context_string(
        self,
        query: str,
        k: Optional[int] = None,
        sources: Optional[List[str]] = None,
        max_length: int = 4000
    ) -> str:
        """
        Get formatted context string for LLM prompt.

        Args:
            query: User query
            k: Number of results
            sources: Optional source filter
            max_length: Maximum total context length

        Returns:
            Formatted context string
        """
        results = await self.retrieve(query, k, sources)

        if not results:
            return ""

        context_parts = []
        total_length = 0

        for result in results:
            # Format each result
            source = result.metadata.get("source", "unknown")
            title = result.metadata.get("title", "")
            url = result.metadata.get("url", "")

            header = f"[{source}]"
            if title:
                header += f" {title}"
            if url:
                header += f"\nSource: {url}"

            context = f"{header}\n{result.text}\n"

            # Check length
            if total_length + len(context) > max_length:
                # Truncate this result
                remaining = max_length - total_length
                if remaining > 200:  # Only include if meaningful
                    context = context[:remaining] + "..."
                    context_parts.append(context)
                break

            context_parts.append(context)
            total_length += len(context)

        return "\n---\n".join(context_parts)


class MultiCollectionRetriever:
    """
    Retriever that searches across multiple collections with different embedding models.

    Handles the complexity of different embedding dimensions by:
    1. Mapping sources to their appropriate collection/embedding model
    2. Querying relevant collections with the correct embeddings
    3. Merging and ranking results
    """

    def __init__(
        self,
        vectordb_adapters: Dict[str, VectorDBAdapter],  # collection_name -> adapter
        embedding_adapters: Dict[str, Any],  # model_name -> adapter
        source_to_model: Dict[str, str],  # source -> model_name
        model_to_collection: Dict[str, str],  # model_name -> collection_name
        default_k: int = 5,
        score_threshold: float = 0.5
    ):
        """
        Initialize multi-collection retriever.

        Args:
            vectordb_adapters: Map of collection names to VectorDB adapters
            embedding_adapters: Map of model names to embedding adapters
            source_to_model: Map of source types to embedding model names
            model_to_collection: Map of model names to collection names
            default_k: Default number of results per collection
            score_threshold: Minimum similarity score
        """
        self.vectordb_adapters = vectordb_adapters
        self.embedding_adapters = embedding_adapters
        self.source_to_model = source_to_model
        self.model_to_collection = model_to_collection
        self.default_k = default_k
        self.score_threshold = score_threshold

    def _get_collections_for_sources(self, sources: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """
        Determine which collections to query based on source filters.

        Returns:
            Dict mapping collection_name -> list of sources to filter by
        """
        collections = {}

        if sources:
            # Group sources by their collection
            for source in sources:
                model = self.source_to_model.get(source)
                if model:
                    collection = self.model_to_collection.get(model)
                    if collection:
                        if collection not in collections:
                            collections[collection] = []
                        collections[collection].append(source)
        else:
            # Search all collections (no source filter)
            for collection in self.vectordb_adapters.keys():
                collections[collection] = None  # None means no filter

        return collections

    def _get_model_for_collection(self, collection: str) -> Optional[str]:
        """Get embedding model name for a collection."""
        for model, coll in self.model_to_collection.items():
            if coll == collection:
                return model
        return None

    async def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        sources: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """
        Retrieve relevant context from all applicable collections.

        Args:
            query: User query
            k: Total number of results desired
            sources: Optional source filter

        Returns:
            List of search results, merged and sorted by score
        """
        k = k or self.default_k
        collections_to_query = self._get_collections_for_sources(sources)

        if not collections_to_query:
            return []

        all_results = []

        # Query each collection with appropriate embedding
        for collection_name, source_filter in collections_to_query.items():
            adapter = self.vectordb_adapters.get(collection_name)
            if not adapter:
                continue

            model_name = self._get_model_for_collection(collection_name)
            embedder = self.embedding_adapters.get(model_name)
            if not embedder:
                continue

            try:
                # Generate query embedding with this model
                query_embedding = await embedder.embed_text(query)

                # Search this collection
                results = await adapter.search(
                    query_embedding=query_embedding,
                    k=k,  # Get k from each collection
                    sources=source_filter,
                    score_threshold=self.score_threshold
                )

                all_results.extend(results)

            except Exception as e:
                logger.warning(f"Error searching collection {collection_name}: {e}")

        # Sort all results by score (descending) and take top k
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:k]

    async def get_context_string(
        self,
        query: str,
        k: Optional[int] = None,
        sources: Optional[List[str]] = None,
        max_length: int = 4000
    ) -> str:
        """
        Get formatted context string for LLM prompt.

        Args:
            query: User query
            k: Number of results
            sources: Optional source filter
            max_length: Maximum total context length

        Returns:
            Formatted context string
        """
        results = await self.retrieve(query, k, sources)

        if not results:
            return ""

        context_parts = []
        total_length = 0

        for result in results:
            source = result.metadata.get("source", "unknown")
            title = result.metadata.get("title", "")
            url = result.metadata.get("url", "")

            header = f"[{source}]"
            if title:
                header += f" {title}"
            if url:
                header += f"\nSource: {url}"

            context = f"{header}\n{result.text}\n"

            if total_length + len(context) > max_length:
                remaining = max_length - total_length
                if remaining > 200:
                    context = context[:remaining] + "..."
                    context_parts.append(context)
                break

            context_parts.append(context)
            total_length += len(context)

        return "\n---\n".join(context_parts)
