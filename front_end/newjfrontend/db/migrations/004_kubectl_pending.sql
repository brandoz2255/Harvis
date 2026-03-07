-- Migration 004: kubectl_pending_commands
-- Audit log for kubectl write commands that required human approval.
-- The in-memory approval gate in kubectl_proxy.py handles the live blocking;
-- this table provides a durable audit trail of every approve/reject decision.

CREATE TABLE IF NOT EXISTS kubectl_pending_commands (
    id              TEXT PRIMARY KEY,               -- 8-char hex approval_id
    command         TEXT        NOT NULL,
    namespace       TEXT,
    timeout_s       INTEGER     NOT NULL DEFAULT 30,
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    resolved_by_id  INTEGER     REFERENCES users(id) ON DELETE SET NULL,
    stdout          TEXT,                           -- populated after approved + executed
    stderr          TEXT,
    exit_code       INTEGER,
    duration_ms     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_kubectl_pending_status
    ON kubectl_pending_commands (status, requested_at DESC);
