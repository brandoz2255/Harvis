-- Phase 7 — per-user SOUL.md text content.
-- Separate table (not a column on users) because SOUL.md can be large
-- and we want clean DELETE-on-cascade semantics + a dedicated updated_at.

CREATE TABLE IF NOT EXISTS user_soul (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    content     TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
