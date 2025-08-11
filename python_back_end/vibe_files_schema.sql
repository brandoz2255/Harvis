-- Vibe Files Database Schema
-- This creates the table structure for persistent file storage

CREATE TABLE IF NOT EXISTS vibe_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('file', 'folder')),
    content TEXT,
    language VARCHAR(50) DEFAULT 'plaintext',
    path TEXT NOT NULL,
    parent_id UUID REFERENCES vibe_files(id) ON DELETE CASCADE,
    session_id VARCHAR(255) NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_vibe_files_session_user ON vibe_files(session_id, user_id);
CREATE INDEX IF NOT EXISTS idx_vibe_files_parent ON vibe_files(parent_id);
CREATE INDEX IF NOT EXISTS idx_vibe_files_type ON vibe_files(type);

-- Create a trigger to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_vibe_files_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_vibe_files_updated_at
    BEFORE UPDATE ON vibe_files
    FOR EACH ROW
    EXECUTE FUNCTION update_vibe_files_updated_at();