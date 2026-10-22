-- 023: account approval (the waiting room).
--
-- account_status
--   active   — can use Harvis. Every existing account, and every new one unless
--              approval is on (HARVIS_SIGNUP_APPROVAL; on by default for a shared server).
--   pending  — signed up, waiting for the host's approval. Can sign in, but every
--              request except the waiting-room ones is refused
--              (plugins/people/approval.py, plugins/people/gate.py).
-- Rejected sign-ups are deleted, so there is no "rejected" row to keep.
--
-- note_to_host: what the person wrote on the sign-up form ("Jane from CSE 4800").
--
-- Idempotent: main.py applies it on every boot.

ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status    TEXT NOT NULL DEFAULT 'active';
ALTER TABLE users ADD COLUMN IF NOT EXISTS note_to_host      TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_account_status_check'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_account_status_check
            CHECK (account_status IN ('active', 'pending'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS users_pending_idx ON users (created_at) WHERE account_status = 'pending';
