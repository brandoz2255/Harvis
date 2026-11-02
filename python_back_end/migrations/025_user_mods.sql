-- 025: per-user mods (plugins/mods).
--
-- One row per version of a mod a person has installed. The server computes
-- `hash` from the manifest and resources it stores (plugins/mods/manifest.py);
-- a client-sent hash is never trusted.
--
-- status
--   draft   — installed, never approved for this hash. Agent proposals land here.
--   on      — approved and running. At most one version per (user, name).
--   off     — switched off by the person, or replaced by a newer approved version.
--   broken  — the mod crashed or never started; switched off until approved again.
--
-- approved_hash is the hash the person saw on the approval card. A version only
-- runs while approved_hash = hash, so a changed byte means a new row and a new ask.
--
-- source: who installed it — 'user' (pasted or uploaded), 'agent' (proposed by
-- Harvis through the mods_propose tool; it can never approve).
--
-- Idempotent: main.py applies it on every boot.

CREATE TABLE IF NOT EXISTS user_mods (
    id            BIGSERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    version       TEXT NOT NULL,
    hash          TEXT NOT NULL,
    tiers         TEXT[] NOT NULL,
    manifest      JSONB NOT NULL,
    resources     JSONB NOT NULL DEFAULT '{}'::jsonb,
    source        TEXT NOT NULL DEFAULT 'user',
    status        TEXT NOT NULL DEFAULT 'draft',
    status_reason TEXT,
    approved_hash TEXT,
    approved_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name, hash)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_mods_status_check') THEN
        ALTER TABLE user_mods ADD CONSTRAINT user_mods_status_check
            CHECK (status IN ('draft', 'on', 'off', 'broken'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_mods_source_check') THEN
        ALTER TABLE user_mods ADD CONSTRAINT user_mods_source_check
            CHECK (source IN ('user', 'agent'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS user_mods_one_on_idx ON user_mods (user_id, name) WHERE status = 'on';
CREATE INDEX IF NOT EXISTS user_mods_user_idx ON user_mods (user_id, name, created_at DESC);
