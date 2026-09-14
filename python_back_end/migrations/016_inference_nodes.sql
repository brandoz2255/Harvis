-- 016: inference nodes registered through the admin API.
-- Env-configured nodes (HARVIS_INFERENCE_NODES) never land here; this table is the
-- operator-editable half of plugins/inference_nodes. The token column holds a Fernet
-- ciphertext (same key derivation as openclaw_llm_config), never the bearer token.
CREATE TABLE IF NOT EXISTS inference_nodes (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    base_url        TEXT NOT NULL,
    dialect         TEXT NOT NULL DEFAULT 'openai',
    label           TEXT NOT NULL DEFAULT '',
    hardware        TEXT NOT NULL DEFAULT '',
    token_encrypted TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    priority        INTEGER NOT NULL DEFAULT 100,
    created_by      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
