# Guide: Optimizing Your n8n Automation System with pgvector and Local Models

This guide provides a comprehensive walkthrough for optimizing your n8n automation generation system by integrating `pgvector` as the vector database. It builds upon your existing Python codebase and the previous optimization guide, incorporating best practices for `pgvector` to enhance performance with local models.

## Part 1: Switching from ChromaDB to pgvector

Your current system uses `ChromaDB`. Migrating to `pgvector` will allow you to keep your vector embeddings alongside your other relational data, which can simplify your architecture and enable powerful hybrid queries.

### 1.1. Database Setup

First, ensure you have PostgreSQL installed with the `pgvector` extension enabled.

```sql
-- Run this in your PostgreSQL database
CREATE EXTENSION IF NOT EXISTS vector;
```

Next, create a table to store your n8n automations and their embeddings.

```sql
CREATE TABLE n8n_automations (
    id SERIAL PRIMARY KEY,
    automation_id VARCHAR(255) UNIQUE,
    name TEXT,
    trigger_type VARCHAR(255),
    node_count INTEGER,
    complexity_score INTEGER,
    categories JSONB,
    has_webhook BOOLEAN,
    has_database BOOLEAN,
    has_api_calls BOOLEAN,
    workflow_pattern VARCHAR(255),
    searchable_text TEXT,
    full_json JSONB,
    embedding vector(384) -- IMPORTANT: The dimension (384) must match your embedding model
);
```

### 1.2. Code Adaptation: The New `N8NVectorStore`

You will need to replace your `N8NVectorStore` class with one that interacts with PostgreSQL. Here is a template using the `psycopg2` library.

**New `requirements.txt` entry:**
```
psycopg2-binary
```

**Updated `N8NVectorStore` for `pgvector`:**

```python
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
import numpy as np

class N8NVectorStore:
    """Optimized vector store for n8n automations using pgvector"""

    def __init__(self, db_conn_string: str, embedding_model: str = "all-MiniLM-L6-v2"):
        self.conn = psycopg2.connect(db_conn_string)
        register_vector(self.conn)
        self.embedder = SentenceTransformer(embedding_model)
        logger.info(f"Initialized vector store with pgvector and {embedding_model}")

    def add_automation(self, automation: Dict[str, Any]) -> str:
        """Add automation to pgvector store"""
        try:
            metadata = self.extract_automation_features(automation)
            searchable_text = self.create_searchable_text(automation, metadata)

            # **CRITICAL: Normalize the embedding**
            embedding = self.embedder.encode(searchable_text)
            normalized_embedding = embedding / np.linalg.norm(embedding)

            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO n8n_automations (
                        automation_id, name, trigger_type, node_count, complexity_score,
                        categories, has_webhook, has_database, has_api_calls,
                        workflow_pattern, searchable_text, full_json, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (automation_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        full_json = EXCLUDED.full_json,
                        embedding = EXCLUDED.embedding;
                    """,
                    (
                        metadata.automation_id, metadata.name, metadata.trigger_type,
                        metadata.node_count, metadata.complexity_score, json.dumps(metadata.categories),
                        metadata.has_webhook, metadata.has_database, metadata.has_api_calls,
                        metadata.workflow_pattern, searchable_text, json.dumps(automation), normalized_embedding
                    )
                )
            self.conn.commit()
            logger.info(f"Added/updated automation: {metadata.name}")
            return metadata.automation_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error adding automation: {e}")
            raise

    def search_automations(self, query: str, n_results: int = 3, similarity_threshold: float = 0.7, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search for relevant automations with filtering"""
        try:
            query_embedding = self.embedder.encode(query)
            query_normalized = query_embedding / np.linalg.norm(query_embedding)

            sql_query = "SELECT id, name, full_json, 1 - (embedding <=> %s) AS similarity FROM n8n_automations"
            params = [query_normalized]

            where_clauses = []
            if filters:
                for key, value in filters.items():
                    where_clauses.append(f"{key} = %s")
                    params.append(value)

            if where_clauses:
                sql_query += " WHERE " + " AND ".join(where_clauses)

            # Use the cosine distance operator `<=>`
            sql_query += " ORDER BY embedding <=> %s LIMIT %s"
            params.extend([query_normalized, n_results])

            with self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(sql_query, tuple(params))
                results = cur.fetchall()

            # Filter by similarity threshold
            filtered_results = [dict(row) for row in results if row['similarity'] >= similarity_threshold]
            return filtered_results

        except Exception as e:
            logger.error(f"Error searching automations: {e}")
            return []

    # Keep your `extract_automation_features`, `_categorize_automation`,
    # `_determine_workflow_pattern`, and `create_searchable_text` methods as they are.
```

## Part 2: Advanced pgvector Optimization

To get the best performance, you **must** create an index on the `embedding` column.

### 2.1. Choosing Your Index: HNSW vs. IVFFlat

-   **HNSW (Hierarchical Navigable Small World):** **Recommended for most use cases.** It's faster for queries and better for data that changes often. It uses more memory and is slower to build, but the query performance is worth it.
-   **IVFFlat (Inverted File with Flat Compression):** A good choice if you are memory-constrained or if your data is static. It's faster to build and uses less memory, but query speed can be slower than HNSW.

### 2.2. Creating an HNSW Index (Recommended)

Since you are dealing with a dynamic system, HNSW is the better choice.

```sql
-- Create an HNSW index on the embedding column
-- This uses cosine distance, which is ideal for normalized embeddings
CREATE INDEX ON n8n_automations USING hnsw (embedding vector_cosine_ops);
```

### 2.3. Tuning Your Index

You can tune the index at creation time and at query time.

-   **`m`**: Max connections per layer (default 16).
-   **`ef_construction`**: Size of the candidate list during index build (default 64).
-   **`hnsw.ef_search`**: Query-time parameter for search candidate list size (default 40). Higher is more accurate but slower.

```sql
-- Example of tuning at query time
SET hnsw.ef_search = 100;
SELECT ... -- your query here
RESET hnsw.ef_search;
```

### 2.4. The Importance of `VACUUM ANALYZE`

After you have loaded your data and created your index, run `VACUUM ANALYZE` to update PostgreSQL's statistics, which is crucial for the query planner.

```sql
VACUUM ANALYZE n8n_automations;
```

## Part 3: Hybrid Search - The Superpower of pgvector

Your `search_automations` function already has basic filtering. `pgvector` allows you to combine this metadata filtering with vector search seamlessly and efficiently.

**Example:** Find automations that are "conditional" and semantically similar to a user's request.

```python
# In your search_automations function
filters = {'workflow_pattern': 'conditional'}
# The generated SQL will automatically include the WHERE clause
# before the vector search, making it very efficient.
```

## Part 4: Putting It All Together - Recommended Workflow

1.  **Setup PostgreSQL:** Install PostgreSQL and enable the `pgvector` extension.
2.  **Update `requirements.txt`:** Add `psycopg2-binary`.
3.  **Replace `N8NVectorStore`:** Update your Python code with the new `pgvector`-based class.
4.  **Load Your Data:** Run a script to load your 2500 n8n automations into the new `n8n_automations` table.
5.  **Create Index:** After loading the data, create the HNSW index on the `embedding` column.
6.  **Analyze:** Run `VACUUM ANALYZE n8n_automations;`.
7.  **Test:** Run your application and test the search functionality. Experiment with the `hnsw.ef_search` parameter to find the right balance of speed and accuracy for your local model.

By following this guide, you will have a robust, high-performance n8n automation generation system that leverages the power and flexibility of `pgvector` and is optimized for your local models.
