"""
Database initialization script for RAG vector tables.

Ensures both vector collections exist before RAG operations.
This prevents the "relation does not exist" errors during startup.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Collection configurations matching EMBEDDING_TIER_CONFIG in source_config.py
RAG_COLLECTIONS = {
    "local_rag_corpus_code": {"dimension": 4096, "tier": "high"},
    "local_rag_corpus_docs": {"dimension": 768, "tier": "standard"},
}


async def ensure_rag_tables_exist(db_pool) -> bool:
    """
    Ensure all RAG vector tables exist in the database.

    This function creates the necessary tables with correct vector types
    before any RAG operations are attempted, preventing "relation does not exist" errors.

    Args:
        db_pool: asyncpg connection pool

    Returns:
        True if all tables exist or were created successfully
    """
    if db_pool is None:
        logger.warning("No database pool provided, skipping table initialization")
        return False

    try:
        async with db_pool.acquire() as conn:
            # Ensure pgvector extension exists
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            logger.info("pgvector extension ready")

            for collection_name, config in RAG_COLLECTIONS.items():
                dimension = config["dimension"]

                # Determine vector type based on dimension
                # pgvector standard vector type limit is 2000
                # For larger embeddings, use halfvec (supports up to 4000)
                if dimension > 2000:
                    vector_type = f"halfvec({dimension})"
                    index_ops = "halfvec_cosine_ops"
                else:
                    vector_type = f"vector({dimension})"
                    index_ops = "vector_cosine_ops"

                # Check if table exists
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = $1
                    )
                """, collection_name)

                if not table_exists:
                    logger.info(f"Creating missing table: {collection_name} ({vector_type})")

                    # Create table with correct vector type
                    await conn.execute(f"""
                        CREATE TABLE IF NOT EXISTS {collection_name} (
                            id VARCHAR(64) PRIMARY KEY,
                            embedding {vector_type},
                            text TEXT NOT NULL,
                            metadata JSONB DEFAULT '{{}}'::jsonb,
                            source VARCHAR(128),
                            created_at TIMESTAMPTZ DEFAULT NOW(),
                            updated_at TIMESTAMPTZ DEFAULT NOW()
                        );
                    """)

                    # Create source index
                    await conn.execute(f"""
                        CREATE INDEX IF NOT EXISTS idx_{collection_name}_source
                        ON {collection_name}(source);
                    """)

                    # Create HNSW index for fast similarity search
                    # m=16: Number of connections per node (default 16)
                    # ef_construction=64: Size of dynamic candidate list for construction
                    await conn.execute(f"""
                        CREATE INDEX IF NOT EXISTS idx_{collection_name}_embedding
                        ON {collection_name} USING hnsw (embedding {index_ops})
                        WITH (m = 16, ef_construction = 64);
                    """)

                    logger.info(f"Created table and indexes for {collection_name}")
                else:
                    # Verify dimension matches
                    row = await conn.fetchrow(f"""
                        SELECT
                            CASE
                                WHEN format_type(a.atttypid, a.atttypmod) ~ 'vector\\(([0-9]+)\\)'
                                THEN (regexp_match(format_type(a.atttypid, a.atttypmod), 'vector\\(([0-9]+)\\)'))[1]::int
                                WHEN format_type(a.atttypid, a.atttypmod) ~ 'halfvec\\(([0-9]+)\\)'
                                THEN (regexp_match(format_type(a.atttypid, a.atttypmod), 'halfvec\\(([0-9]+)\\)'))[1]::int
                                ELSE NULL
                            END as dim,
                            t.typname as type_name
                        FROM pg_attribute a
                        JOIN pg_type t ON a.atttypid = t.oid
                        WHERE a.attrelid = '{collection_name}'::regclass
                        AND a.attname = 'embedding'
                    """)

                    existing_dim = row['dim'] if row else None
                    existing_type = row['type_name'] if row else None

                    if existing_dim == dimension:
                        logger.info(f"Table {collection_name} exists with correct dimension ({dimension})")
                    else:
                        logger.warning(
                            f"Table {collection_name} dimension mismatch: "
                            f"expected {dimension}, found {existing_dim} ({existing_type})"
                        )

            logger.info("All RAG tables verified/created successfully")
            return True

    except Exception as e:
        logger.error(f"Failed to ensure RAG tables exist: {e}")
        import traceback
        traceback.print_exc()
        return False


async def get_table_stats(db_pool) -> Dict[str, Dict[str, Any]]:
    """
    Get statistics for all RAG tables.

    Args:
        db_pool: asyncpg connection pool

    Returns:
        Dictionary mapping collection names to their stats
    """
    stats = {}

    if db_pool is None:
        return stats

    try:
        async with db_pool.acquire() as conn:
            for collection_name in RAG_COLLECTIONS.keys():
                try:
                    # Get row count
                    count = await conn.fetchval(f"""
                        SELECT COUNT(*) FROM {collection_name}
                    """)

                    # Get source breakdown
                    sources = await conn.fetch(f"""
                        SELECT source, COUNT(*) as count
                        FROM {collection_name}
                        GROUP BY source
                        ORDER BY count DESC
                    """)

                    stats[collection_name] = {
                        "total_rows": count,
                        "sources": {row['source']: row['count'] for row in sources}
                    }
                except Exception as e:
                    stats[collection_name] = {"error": str(e)}

    except Exception as e:
        logger.error(f"Failed to get table stats: {e}")

    return stats
