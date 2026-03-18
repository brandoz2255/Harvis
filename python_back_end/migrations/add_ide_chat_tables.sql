-- Migration: Add IDE Chat Tables
-- Purpose: Create separate chat sessions and messages for IDE Assistant
-- Date: 2025-10-30

-- IDE Chat Sessions (separate from home chat)
CREATE TABLE IF NOT EXISTS ide_chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    vibe_session_id UUID NOT NULL, -- links to vibecode session
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_ide_chat_sessions_user_id ON ide_chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_ide_chat_sessions_vibe_session_id ON ide_chat_sessions(vibe_session_id);

-- IDE Chat Messages (stores IDE assistant history)
CREATE TABLE IF NOT EXISTS ide_chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_session_id UUID NOT NULL REFERENCES ide_chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    attachments JSONB DEFAULT '[]'::jsonb, -- file paths/metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster message retrieval
CREATE INDEX IF NOT EXISTS idx_ide_chat_messages_chat_session_id ON ide_chat_messages(chat_session_id);
CREATE INDEX IF NOT EXISTS idx_ide_chat_messages_created_at ON ide_chat_messages(created_at);

-- Update trigger for ide_chat_sessions
CREATE OR REPLACE FUNCTION update_ide_chat_sessions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ide_chat_sessions_updated_at
    BEFORE UPDATE ON ide_chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_ide_chat_sessions_updated_at();


