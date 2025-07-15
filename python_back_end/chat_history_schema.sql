-- Chat History Database Schema for Jarvis AI
-- Run this SQL to create the necessary tables for chat history functionality

-- Drop tables if they exist (for clean setup)
DROP TABLE IF EXISTS chat_messages CASCADE;
DROP TABLE IF EXISTS chat_sessions CASCADE;

-- Chat sessions table to manage conversation sessions
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL DEFAULT 'New Chat',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_message_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    message_count INTEGER DEFAULT 0,
    model_used VARCHAR(100),
    is_active BOOLEAN DEFAULT true
);

-- Chat messages table to store individual messages
CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    reasoning TEXT NULL, -- For reasoning models thinking process
    model_used VARCHAR(100),
    input_type VARCHAR(20) DEFAULT 'text' CHECK (input_type IN ('text', 'voice', 'screen')),
    metadata JSONB DEFAULT '{}', -- Store additional metadata (timestamps, search results, etc.)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX idx_chat_sessions_user_updated ON chat_sessions(user_id, updated_at DESC);
CREATE INDEX idx_chat_sessions_active ON chat_sessions(user_id, is_active, updated_at DESC);

CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX idx_chat_messages_user_id ON chat_messages(user_id);
CREATE INDEX idx_chat_messages_session_created ON chat_messages(session_id, created_at ASC);
CREATE INDEX idx_chat_messages_role ON chat_messages(role);

-- Function to update session's updated_at and last_message_at when messages are added
CREATE OR REPLACE FUNCTION update_session_on_message_insert()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE chat_sessions 
    SET 
        updated_at = NEW.created_at,
        last_message_at = NEW.created_at,
        message_count = message_count + 1,
        model_used = COALESCE(NEW.model_used, model_used)
    WHERE id = NEW.session_id;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update session when messages are added
CREATE TRIGGER trigger_update_session_on_message_insert
    AFTER INSERT ON chat_messages
    FOR EACH ROW
    EXECUTE FUNCTION update_session_on_message_insert();

-- Function to auto-generate session title based on first user message
CREATE OR REPLACE FUNCTION auto_generate_session_title()
RETURNS TRIGGER AS $$
BEGIN
    -- Only update title for first user message if title is still default
    IF NEW.role = 'user' AND 
       (SELECT title FROM chat_sessions WHERE id = NEW.session_id) = 'New Chat' AND
       (SELECT COUNT(*) FROM chat_messages WHERE session_id = NEW.session_id AND role = 'user') = 1 THEN
        
        UPDATE chat_sessions 
        SET title = CASE 
            WHEN LENGTH(NEW.content) > 50 
            THEN LEFT(NEW.content, 47) || '...'
            ELSE NEW.content
        END
        WHERE id = NEW.session_id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-generate session titles
CREATE TRIGGER trigger_auto_generate_session_title
    AFTER INSERT ON chat_messages
    FOR EACH ROW
    EXECUTE FUNCTION auto_generate_session_title();

-- Sample data for testing (optional - remove in production)
-- INSERT INTO chat_sessions (user_id, title) VALUES (1, 'Sample Chat Session');

-- Grant permissions (adjust user as needed)
-- GRANT ALL PRIVILEGES ON chat_sessions TO your_app_user;
-- GRANT ALL PRIVILEGES ON chat_messages TO your_app_user;
-- GRANT USAGE, SELECT ON SEQUENCE chat_messages_id_seq TO your_app_user;