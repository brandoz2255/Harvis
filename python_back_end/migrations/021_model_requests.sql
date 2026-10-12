-- 021: "request a model" queue. A signed-in user asks for a model; the admin
-- approves (then downloads it through the cookbook) or denies it.
--
-- One OPEN row per model (case-insensitive): a second person asking for the same
-- model is added to `requesters` instead of creating another row.
--
-- Idempotent: main.py applies it on every boot.

CREATE TABLE IF NOT EXISTS model_requests (
    id           SERIAL PRIMARY KEY,
    model        TEXT NOT NULL,
    note         TEXT,
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'approved', 'denied')),
    requested_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requesters   INTEGER[] NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at   TIMESTAMPTZ,
    decided_by   INTEGER,
    reason       TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS model_requests_one_open_per_model
    ON model_requests (lower(model)) WHERE status = 'open';

-- The per-user spam limits count a person's recent and open rows.
CREATE INDEX IF NOT EXISTS model_requests_by_user
    ON model_requests (requested_by, created_at DESC);

-- The "denied recently" check looks a model up by name.
CREATE INDEX IF NOT EXISTS model_requests_denied_by_model
    ON model_requests (lower(model), decided_at DESC) WHERE status = 'denied';
