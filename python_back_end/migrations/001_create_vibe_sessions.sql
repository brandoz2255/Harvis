-- Migration: Ensure vibecoding_sessions table has required columns
-- This migration ensures the vibecoding_sessions table has all required columns for VibeCode IDE

-- Add deleted_at column if it doesn't exist (for soft deletes)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'vibecoding_sessions' AND column_name = 'deleted_at'
    ) THEN
        ALTER TABLE vibecoding_sessions ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE;
    END IF;
END $$;

-- Ensure session_id column exists and is unique
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE table_name = 'vibecoding_sessions' 
        AND constraint_type = 'UNIQUE' 
        AND constraint_name = 'vibecoding_sessions_session_id_key'
    ) THEN
        -- Add unique constraint if it doesn't exist
        ALTER TABLE vibecoding_sessions ADD CONSTRAINT vibecoding_sessions_session_id_key UNIQUE (session_id);
    END IF;
END $$;

-- Create indexes if they don't exist
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_user ON vibecoding_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_status ON vibecoding_sessions(status);
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_session_id ON vibecoding_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_deleted_at ON vibecoding_sessions(deleted_at) WHERE deleted_at IS NULL;

-- Ensure last_activity column exists
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'vibecoding_sessions' AND column_name = 'last_activity'
    ) THEN
        ALTER TABLE vibecoding_sessions ADD COLUMN last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW();
    END IF;
END $$;

-- Update existing rows to have last_activity if NULL
UPDATE vibecoding_sessions SET last_activity = updated_at WHERE last_activity IS NULL;

-- Trigger function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_vibecoding_sessions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to vibecoding_sessions table
DROP TRIGGER IF EXISTS update_vibecoding_sessions_updated_at_trigger ON vibecoding_sessions;
CREATE TRIGGER update_vibecoding_sessions_updated_at_trigger
    BEFORE UPDATE ON vibecoding_sessions 
    FOR EACH ROW EXECUTE FUNCTION update_vibecoding_sessions_updated_at();

-- Comments for documentation
COMMENT ON TABLE vibecoding_sessions IS 'Stores VibeCode IDE development sessions with container persistence';
COMMENT ON COLUMN vibecoding_sessions.session_id IS 'Unique session identifier used in API calls';
COMMENT ON COLUMN vibecoding_sessions.container_id IS 'Docker container ID for this session';
COMMENT ON COLUMN vibecoding_sessions.volume_name IS 'Docker volume name for persistent workspace storage';
COMMENT ON COLUMN vibecoding_sessions.status IS 'Session status: running, stopped, suspended, error';
COMMENT ON COLUMN vibecoding_sessions.deleted_at IS 'Soft delete timestamp - NULL means active';
