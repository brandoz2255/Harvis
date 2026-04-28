-- Phase 1A — messaging plugin schema
-- Per-user platform identity links + audit trail for inbound/outbound traffic.

CREATE TABLE IF NOT EXISTS messaging_platforms (
    id                   SERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform             TEXT NOT NULL,
    identifier           TEXT NOT NULL,
    sender_display_name  TEXT,
    enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    config               JSONB NOT NULL DEFAULT '{}',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- (platform, identifier) is the natural key the dispatcher resolves on.
CREATE UNIQUE INDEX IF NOT EXISTS uq_messaging_platforms_platform_identifier
    ON messaging_platforms(platform, identifier);

CREATE INDEX IF NOT EXISTS idx_messaging_platforms_user
    ON messaging_platforms(user_id);


CREATE TABLE IF NOT EXISTS messaging_audit (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    platform    TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
    chat_id     TEXT NOT NULL,
    thread_id   TEXT,
    sender_id   TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    text        TEXT,
    status      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messaging_audit_ts
    ON messaging_audit(ts DESC);

CREATE INDEX IF NOT EXISTS idx_messaging_audit_user_ts
    ON messaging_audit(user_id, ts DESC);

CREATE INDEX IF NOT EXISTS idx_messaging_audit_platform_chat
    ON messaging_audit(platform, chat_id, ts DESC);
