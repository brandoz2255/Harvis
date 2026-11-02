-- 026: a messaging identity can be linked to more than one Harvis user.
--
-- Until now (platform, identifier) was unique across the whole table, so one
-- person could belong to one Harvis user only, and a sender paired to user A who
-- messaged user B's bot was answered as A. Each user's own bot now resolves
-- senders from that user's rows alone (plugins/messaging/dispatcher.py).
--
-- house
--   TRUE   — the link belongs to the host's shared bot (env-configured adapters,
--            the Discord workspace bot). At most one user per (platform, identifier).
--   FALSE  — the link only applies to the owner's own bot. Any number of users
--            may link the same identity.
-- Every row that exists when this runs keeps working with the house bot, except
-- the ones a user approved on their own bot: a row whose identity sits in that
-- user's saved pairing.approved list while the user has the platform enabled in
-- their own messaging settings becomes an own-bot row. Rows written afterwards
-- are own-bot unless the code says otherwise.
--
-- One-way once two users share an identity: the old unique index on
-- (platform, identifier) cannot come back, and code from before this migration
-- resolves a sender across all rows. Roll back only after reducing the table to
-- one row per (platform, identifier).
--
-- Idempotent: main.py applies it on every boot. The column is added, and the
-- reconcile runs, only in the guard's first pass, so a re-run cannot turn
-- own-bot rows back into house rows or flip rows a user later made house.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'messaging_platforms' AND column_name = 'house'
    ) THEN
        ALTER TABLE messaging_platforms ADD COLUMN house BOOLEAN NOT NULL DEFAULT TRUE;
        IF to_regclass('owui_user_settings') IS NOT NULL THEN
            UPDATE messaging_platforms m SET house = FALSE
            FROM owui_user_settings s
            WHERE s.user_id = m.user_id
              AND s.settings->'hermes_ui'->'messaging'->m.platform->>'enabled' = 'true'
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(CASE WHEN jsonb_typeof(s.settings->'hermes_ui'->'pairing'->'approved') = 'array'
                                                 THEN s.settings->'hermes_ui'->'pairing'->'approved'
                                                 ELSE '[]'::jsonb END) a
                  WHERE a->>'platform' = m.platform AND a->>'user_id' = m.identifier);
        END IF;
    END IF;
END $$;

ALTER TABLE messaging_platforms ALTER COLUMN house SET DEFAULT FALSE;

DROP INDEX IF EXISTS uq_messaging_platforms_platform_identifier;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_messaging_platforms_user_platform_identifier') THEN
        ALTER TABLE messaging_platforms ADD CONSTRAINT uq_messaging_platforms_user_platform_identifier
            UNIQUE (user_id, platform, identifier);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_messaging_platforms_house_identity
    ON messaging_platforms (platform, identifier) WHERE house;
