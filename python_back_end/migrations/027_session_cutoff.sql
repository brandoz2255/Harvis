-- 027: server-side sign-out. users.tokens_valid_after is the moment before which
-- no sign-in for that account counts (auth_optimized.revoked compares it with the
-- token's `iat`).
--
-- NULL means nothing has ever been ended, so every token minted before this
-- migration keeps working until it expires. It is set by:
--   * a password change, by whichever code path makes it (trigger below, so a
--     route that forgets cannot leave old sign-ins alive);
--   * turning an account off (trigger on harvis_user_controls, so an admin who
--     turns it back on later does not revive a token stolen in between);
--   * "sign out everywhere" (POST /api/auth/signout-all).
--
-- Idempotent: main.py applies it on every boot.

ALTER TABLE users ADD COLUMN IF NOT EXISTS tokens_valid_after TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION harvis_users_password_cutoff() RETURNS trigger AS $$
BEGIN
    IF NEW.password IS DISTINCT FROM OLD.password THEN
        NEW.tokens_valid_after := clock_timestamp();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS harvis_users_password_cutoff ON users;
CREATE TRIGGER harvis_users_password_cutoff
    BEFORE UPDATE OF password ON users
    FOR EACH ROW EXECUTE FUNCTION harvis_users_password_cutoff();

CREATE OR REPLACE FUNCTION harvis_controls_block_cutoff() RETURNS trigger AS $$
BEGIN
    IF NEW.blocked AND (TG_OP = 'INSERT' OR NOT COALESCE(OLD.blocked, FALSE)) THEN
        UPDATE users SET tokens_valid_after = clock_timestamp() WHERE id = NEW.user_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS harvis_controls_block_cutoff ON harvis_user_controls;
CREATE TRIGGER harvis_controls_block_cutoff
    AFTER INSERT OR UPDATE OF blocked ON harvis_user_controls
    FOR EACH ROW EXECUTE FUNCTION harvis_controls_block_cutoff();
