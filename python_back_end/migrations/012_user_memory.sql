-- Phase 4 — per-user memory store (built-in MemoryProvider backend).
-- Real semantic providers (pgvector, honcho, holographic) ship as plugins
-- that implement the same MemoryProvider ABC and have their own schema.

CREATE TABLE IF NOT EXISTS harvis_user_memory (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual',
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_harvis_user_memory_user_created
    ON harvis_user_memory(user_id, created_at DESC);

-- The builtin provider uses plain ILIKE for recall; performance is fine
-- below ~10k entries per user. Mature providers (pgvector, holographic,
-- honcho) ship their own schema and indexes via their own migrations.
