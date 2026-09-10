-- 017: the columns Settings → Account has always claimed to edit.
--
-- The Account pane posts name, profile_image_url, bio, gender and date_of_birth
-- to POST /api/v1/auths/update/profile. Three of those had no column at all, the
-- route did not exist, and `avatar` was VARCHAR(255) — smaller than any of the
-- data-URI images that pane produces from a cropped upload. So the form rendered
-- five inputs, none of which could persist anything.
--
-- `name` is a NEW column rather than a reuse of `username`. `username` is UNIQUE
-- and is the login identity; letting a display name write to it would mean two
-- people cannot both call themselves "Dave", and a rename would silently change
-- what you sign in with. NULL here means "never set" and the API falls back to
-- `username`, so every existing row keeps the name it already shows.
--
-- Idempotent: safe to re-run on every boot.

ALTER TABLE users ADD COLUMN IF NOT EXISTS name          TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio           TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS gender        TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS date_of_birth DATE;

-- Widen avatar only if it is still the narrow varchar. Guarded so a re-run does
-- not take an unnecessary ACCESS EXCLUSIVE lock on the users table.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users'
          AND column_name = 'avatar'
          AND data_type = 'character varying'
    ) THEN
        ALTER TABLE users ALTER COLUMN avatar TYPE TEXT;
    END IF;
END
$$;
