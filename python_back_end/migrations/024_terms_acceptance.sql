-- 024: which house rules each account accepted at sign-up (plugins/people/terms.py).
--
-- terms_version      — terms.VERSION the person ticked, or NULL when nothing was
--                      asked (the host's own account, a laptop, accounts made
--                      before this migration).
-- terms_accepted_at  — when they ticked it.
--
-- Idempotent: main.py applies it on every boot.

ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version     TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;
