-- Workspace tables for Harvis Workspace + OpenClaw integration
-- Safe to run multiple times (IF NOT EXISTS on everything)

CREATE TABLE IF NOT EXISTS workspace_runs (
    id            TEXT PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    session_id    TEXT NOT NULL,
    task_brief    TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMPTZ,
    duration_ms   INTEGER,
    event_count   INTEGER DEFAULT 0,
    tool_calls    INTEGER DEFAULT 0,
    final_summary TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_workspace_runs_user
    ON workspace_runs(user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS workspace_events (
    id            SERIAL PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspace_runs(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    event_type    TEXT NOT NULL,
    payload       JSONB DEFAULT '{}',
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workspace_events_ws
    ON workspace_events(workspace_id, seq ASC);

CREATE TABLE IF NOT EXISTS proxy_usage_log (
    id         SERIAL PRIMARY KEY,
    model      TEXT NOT NULL,
    tokens_in  INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd   NUMERIC(12, 8) DEFAULT 0,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proxy_usage_ts
    ON proxy_usage_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_proxy_usage_model
    ON proxy_usage_log(model, ts DESC);
