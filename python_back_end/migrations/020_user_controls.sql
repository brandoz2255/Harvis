-- 020: what the instance admin can set per person (Settings ▸ People), and the
-- per-day message count those limits are checked against.
--
-- No row means no limits. Admins are never limited (the code skips them), so
-- the admin cannot lock themselves out from this page.
--
-- Idempotent: main.py applies it on every boot.

CREATE TABLE IF NOT EXISTS harvis_user_controls (
    user_id             INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    -- Turned off: every request with this person's sign-in is refused and they
    -- cannot sign in again until the admin turns them back on.
    blocked             BOOLEAN NOT NULL DEFAULT FALSE,
    -- Chat messages per day (server date). NULL = no limit, 0 = no chatting.
    daily_message_limit INTEGER CHECK (daily_message_limit IS NULL OR daily_message_limit >= 0),
    -- Models on this server they may chat with. NULL = any.
    allowed_models      TEXT[],
    updated_by          INTEGER,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS harvis_usage_daily (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day       DATE NOT NULL DEFAULT CURRENT_DATE,
    messages  INTEGER NOT NULL DEFAULT 0,
    last_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, day)
);
