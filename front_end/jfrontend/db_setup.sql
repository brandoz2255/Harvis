-- Drop the existing users table if it exists, to ensure a clean slate
DROP TABLE IF EXISTS users CASCADE;

-- Create the users table with the correct schema
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL, -- This is where the hashed password will be stored
    avatar VARCHAR(255), -- Optional: for user profile images
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create or replace the register_user function
CREATE OR REPLACE FUNCTION register_user(p_username VARCHAR, p_email VARCHAR, p_password_hash VARCHAR)
RETURNS BOOLEAN AS $$
BEGIN
    -- Check if username or email already exists
    IF EXISTS (SELECT 1 FROM users WHERE username = p_username OR email = p_email) THEN
        RETURN FALSE; -- User already exists
    END IF;

    INSERT INTO users (username, email, password) VALUES (p_username, p_email, p_password_hash);
    RETURN TRUE;
EXCEPTION WHEN unique_violation THEN
    -- This handles a race condition if another transaction inserts the same user
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;
