-- VibeCode IDE Database Schema
-- This schema manages VibeCode development sessions with container persistence

-- Table for vibe sessions
CREATE TABLE IF NOT EXISTS vibecoding_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(255) UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    container_id VARCHAR(255),
    volume_name VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'stopped',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Indexes for vibecoding_sessions
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_user ON vibecoding_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_status ON vibecoding_sessions(status);

-- Table for user preferences
CREATE TABLE IF NOT EXISTS user_prefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL UNIQUE,
    theme VARCHAR(20) DEFAULT 'dark',
    left_panel_width INTEGER DEFAULT 280,
    right_panel_width INTEGER DEFAULT 384,
    terminal_height INTEGER DEFAULT 200,
    default_model VARCHAR(100) DEFAULT 'mistral',
    font_size INTEGER DEFAULT 14,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_user_prefs FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Index for user_prefs
CREATE INDEX IF NOT EXISTS idx_user_prefs_user ON user_prefs(user_id);

-- Trigger function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers to tables.
-- DROP-then-CREATE, because a bare CREATE TRIGGER errors with "already exists"
-- on the second run. This file is applied at every boot now, so it has to be
-- re-runnable; the same DROP IF EXISTS pattern migrations 010-015 already use.
DROP TRIGGER IF EXISTS update_vibecoding_sessions_updated_at ON vibecoding_sessions;
CREATE TRIGGER update_vibecoding_sessions_updated_at 
    BEFORE UPDATE ON vibecoding_sessions 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_user_prefs_updated_at ON user_prefs;
CREATE TRIGGER update_user_prefs_updated_at 
    BEFORE UPDATE ON user_prefs 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
