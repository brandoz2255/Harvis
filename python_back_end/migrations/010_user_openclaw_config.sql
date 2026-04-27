-- Per-user OpenClaw configuration for BYO mode.
-- Users with no row in this table default to the bundled OpenClaw.
-- Users with a row and mode='byo' route their sessions to their own OpenClaw instance.

CREATE TABLE IF NOT EXISTS user_openclaw_config (
    user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    mode               VARCHAR(10) NOT NULL DEFAULT 'bundled'
                       CHECK (mode IN ('bundled', 'byo')),
    byo_url            TEXT,
    byo_token_encrypted TEXT,
    byo_verified_at    TIMESTAMPTZ,
    byo_last_error     TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_openclaw_config_mode
    ON user_openclaw_config(mode);

-- Trigger to auto-update updated_at on row changes
CREATE OR REPLACE FUNCTION update_user_openclaw_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_user_openclaw_config_updated_at
    ON user_openclaw_config;
CREATE TRIGGER trigger_user_openclaw_config_updated_at
    BEFORE UPDATE ON user_openclaw_config
    FOR EACH ROW EXECUTE FUNCTION update_user_openclaw_config_updated_at();
