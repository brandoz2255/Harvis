-- Phase 6 — per-user cron jobs.
-- Replaces Hermes's ~/.hermes/cron/jobs.json file with multi-tenant
-- Postgres rows. Scheduler runtime (tick loop) is separate; this is the
-- persistence layer.

CREATE TABLE IF NOT EXISTS cron_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    schedule_type   TEXT NOT NULL,            -- 'cron' | 'interval' | 'once'
    schedule_expr   TEXT NOT NULL,            -- cron string, "30m", or ISO datetime
    prompt          TEXT NOT NULL,
    delivery        TEXT,                     -- e.g. 'discord:<channel_id>', 'slack:<channel>', 'internal'
    status          TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | running | paused | completed | error
    next_run_at     TIMESTAMPTZ,
    last_run_at     TIMESTAMPTZ,
    run_count       INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Filter index — the scheduler's hot path is "find me jobs due now".
CREATE INDEX IF NOT EXISTS idx_cron_jobs_due
    ON cron_jobs(next_run_at)
    WHERE status = 'scheduled' AND next_run_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cron_jobs_user
    ON cron_jobs(user_id, created_at DESC);
