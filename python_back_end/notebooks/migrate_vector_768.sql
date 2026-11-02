-- OPT-IN migration. Nothing in the backend runs this file; apply it by hand.
--
-- Narrows notebook_chunks.embedding from vector(4096) to vector(768) and adds an HNSW
-- cosine index (an index cannot be built on a 4096-wide vector column; the limit is 2000).
--
--   Before: ./database-backup/backup.sh   (this rewrites the table under an exclusive lock)
--   Run:    psql -v ON_ERROR_STOP=1 -f notebooks/migrate_vector_768.sql
--   Needs:  pgvector >= 0.7 (subvector, vector_norm). Safe to run twice.
--
-- What it does, in one transaction:
--   1. Rows that are not really 768-wide get embedding = NULL so they can be re-embedded.
--      Real width is embedding_dim when recorded; otherwise it is inferred from the zero
--      padding (anything non-zero past 768 is wider, an all-zero tail of the 768 is
--      narrower). Their sources are flagged metadata.needs_reembed = true; no chunk and
--      no source status is deleted or changed.
--   2. Re-types the column to vector(768), keeping the first 768 values of the rest.
--   3. Records embedding_dim = 768 on every row that still has a vector.
--   4. Creates idx_notebook_chunks_embedding_hnsw (vector_cosine_ops).
--
-- Do NOT apply this until the same release also makes the writers 768-wide
-- (notebooks/ingestion.py TARGET_DIM and the query-embedding padding). Against a
-- vector(768) column a 4096-wide insert or query fails.

BEGIN;

DO $$
DECLARE
    current_type TEXT;
BEGIN
    SELECT format_type(a.atttypid, a.atttypmod) INTO current_type
      FROM pg_attribute a
     WHERE a.attrelid = 'notebook_chunks'::regclass
       AND a.attname = 'embedding'
       AND NOT a.attisdropped;

    IF current_type IS NULL THEN
        RAISE EXCEPTION 'notebook_chunks.embedding not found';
    END IF;

    IF current_type = 'vector(768)' THEN
        RAISE NOTICE 'embedding is already vector(768); skipping the re-type';
    ELSIF current_type = 'vector(4096)' THEN
        -- Step 1: null out rows that are not genuinely 768-wide.
        UPDATE notebook_chunks
           SET embedding = NULL
         WHERE embedding IS NOT NULL
           AND (
                 (embedding_dim IS NOT NULL AND embedding_dim <> 768)
              OR (embedding_dim IS NULL AND (
                     vector_norm(subvector(embedding, 769, 3328)) <> 0
                  OR vector_norm(subvector(embedding, 737, 32)) = 0
                 ))
           );

        UPDATE notebook_sources
           SET metadata = metadata || '{"needs_reembed": true}'::jsonb
         WHERE id IN (SELECT DISTINCT source_id FROM notebook_chunks WHERE embedding IS NULL);

        -- Step 2: truncate the zero padding and re-type.
        ALTER TABLE notebook_chunks
            ALTER COLUMN embedding TYPE vector(768)
            USING subvector(embedding, 1, 768)::vector(768);
    ELSE
        RAISE EXCEPTION 'unexpected embedding type %, refusing to touch it', current_type;
    END IF;
END $$;

-- Step 3
UPDATE notebook_chunks SET embedding_dim = 768
 WHERE embedding IS NOT NULL AND embedding_dim IS DISTINCT FROM 768;

-- Step 4
CREATE INDEX IF NOT EXISTS idx_notebook_chunks_embedding_hnsw
    ON notebook_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMIT;
