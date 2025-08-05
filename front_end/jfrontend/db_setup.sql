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

-- Create user_api_keys table for storing encrypted API keys per user
CREATE TABLE user_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_name VARCHAR(50) NOT NULL, -- e.g., 'ollama', 'gemini', 'openai', 'anthropic'
    api_key_encrypted TEXT NOT NULL, -- Encrypted API key
    api_url VARCHAR(500), -- Optional: custom API URL (e.g., for Ollama local instances)
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, provider_name) -- One API key per provider per user
);

-- Create index for faster lookups
CREATE INDEX idx_user_api_keys_user_id ON user_api_keys(user_id);
CREATE INDEX idx_user_api_keys_provider ON user_api_keys(provider_name);

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at
CREATE TRIGGER update_user_api_keys_updated_at 
    BEFORE UPDATE ON user_api_keys 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
