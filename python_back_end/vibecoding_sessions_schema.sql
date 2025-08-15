-- Vibecoding Sessions Database Schema
-- This schema manages vibecoding development sessions with container persistence

-- Table for vibecoding sessions
CREATE TABLE IF NOT EXISTS vibecoding_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(255) UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    project_name VARCHAR(255) NOT NULL DEFAULT 'Untitled Project',
    description TEXT,
    container_id VARCHAR(255) UNIQUE,
    volume_name VARCHAR(255) NOT NULL,
    container_status VARCHAR(50) DEFAULT 'stopped',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    project_config JSONB DEFAULT '{}'::jsonb
);

-- Table for session files (metadata and quick access)
CREATE TABLE IF NOT EXISTS vibecoding_session_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES vibecoding_sessions(id) ON DELETE CASCADE,
    file_path VARCHAR(512) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) DEFAULT 'text',
    file_size BIGINT DEFAULT 0,
    content_preview TEXT, -- First 500 chars for quick preview
    language VARCHAR(50), -- Programming language detected
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, file_path)
);

-- Table for session terminal history
CREATE TABLE IF NOT EXISTS vibecoding_terminal_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES vibecoding_sessions(id) ON DELETE CASCADE,
    command TEXT NOT NULL,
    output TEXT,
    exit_code INTEGER DEFAULT 0,
    working_directory VARCHAR(512) DEFAULT '/workspace',
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    execution_time_ms INTEGER DEFAULT 0
);

-- Table for session snapshots/checkpoints
CREATE TABLE IF NOT EXISTS vibecoding_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES vibecoding_sessions(id) ON DELETE CASCADE,
    snapshot_name VARCHAR(255) NOT NULL,
    description TEXT,
    file_count INTEGER DEFAULT 0,
    total_size BIGINT DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table for session sharing and collaboration
CREATE TABLE IF NOT EXISTS vibecoding_session_sharing (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES vibecoding_sessions(id) ON DELETE CASCADE,
    shared_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shared_with INTEGER REFERENCES users(id) ON DELETE CASCADE,
    share_token VARCHAR(255) UNIQUE, -- For anonymous sharing
    permissions JSONB DEFAULT '{"read": true, "write": false, "execute": false}'::jsonb,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_user_id ON vibecoding_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_session_id ON vibecoding_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_last_activity ON vibecoding_sessions(last_activity);
CREATE INDEX IF NOT EXISTS idx_vibecoding_sessions_is_active ON vibecoding_sessions(is_active);

CREATE INDEX IF NOT EXISTS idx_vibecoding_session_files_session_id ON vibecoding_session_files(session_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_session_files_file_path ON vibecoding_session_files(session_id, file_path);
CREATE INDEX IF NOT EXISTS idx_vibecoding_session_files_updated_at ON vibecoding_session_files(updated_at);

CREATE INDEX IF NOT EXISTS idx_vibecoding_terminal_history_session_id ON vibecoding_terminal_history(session_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_terminal_history_executed_at ON vibecoding_terminal_history(executed_at);

CREATE INDEX IF NOT EXISTS idx_vibecoding_snapshots_session_id ON vibecoding_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_snapshots_created_at ON vibecoding_snapshots(created_at);

CREATE INDEX IF NOT EXISTS idx_vibecoding_session_sharing_session_id ON vibecoding_session_sharing(session_id);
CREATE INDEX IF NOT EXISTS idx_vibecoding_session_sharing_share_token ON vibecoding_session_sharing(share_token);
CREATE INDEX IF NOT EXISTS idx_vibecoding_session_sharing_expires_at ON vibecoding_session_sharing(expires_at);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply the trigger to relevant tables
CREATE TRIGGER update_vibecoding_sessions_updated_at 
    BEFORE UPDATE ON vibecoding_sessions 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_vibecoding_session_files_updated_at 
    BEFORE UPDATE ON vibecoding_session_files 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- View for session overview with stats
CREATE OR REPLACE VIEW vibecoding_session_overview AS
SELECT 
    s.id,
    s.session_id,
    s.user_id,
    u.username,
    s.project_name,
    s.description,
    s.container_status,
    s.created_at,
    s.updated_at,
    s.last_activity,
    s.is_active,
    COALESCE(file_stats.file_count, 0) as file_count,
    COALESCE(file_stats.total_size, 0) as total_size,
    COALESCE(terminal_stats.command_count, 0) as command_count,
    CASE 
        WHEN s.last_activity > CURRENT_TIMESTAMP - INTERVAL '1 hour' THEN 'active'
        WHEN s.last_activity > CURRENT_TIMESTAMP - INTERVAL '1 day' THEN 'recent'
        ELSE 'inactive'
    END as activity_status
FROM vibecoding_sessions s
LEFT JOIN users u ON s.user_id = u.id
LEFT JOIN (
    SELECT 
        session_id,
        COUNT(*) as file_count,
        SUM(file_size) as total_size
    FROM vibecoding_session_files 
    GROUP BY session_id
) file_stats ON s.id = file_stats.session_id
LEFT JOIN (
    SELECT 
        session_id,
        COUNT(*) as command_count
    FROM vibecoding_terminal_history 
    WHERE executed_at > CURRENT_TIMESTAMP - INTERVAL '7 days'
    GROUP BY session_id
) terminal_stats ON s.id = terminal_stats.session_id;

-- Function to cleanup old inactive sessions
CREATE OR REPLACE FUNCTION cleanup_inactive_sessions(inactive_days INTEGER DEFAULT 7)
RETURNS INTEGER AS $$
DECLARE
    cleanup_count INTEGER;
BEGIN
    -- Mark sessions as inactive if no activity for specified days
    UPDATE vibecoding_sessions 
    SET is_active = false, container_status = 'cleanup'
    WHERE last_activity < CURRENT_TIMESTAMP - INTERVAL '1 day' * inactive_days
    AND is_active = true;
    
    GET DIAGNOSTICS cleanup_count = ROW_COUNT;
    
    -- Clean up old terminal history (keep last 1000 commands per session)
    DELETE FROM vibecoding_terminal_history 
    WHERE id NOT IN (
        SELECT id FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY session_id 
                ORDER BY executed_at DESC
            ) as rn
            FROM vibecoding_terminal_history
        ) ranked WHERE rn <= 1000
    );
    
    RETURN cleanup_count;
END;
$$ LANGUAGE plpgsql;

-- Insert some sample data for testing (optional)
/*
INSERT INTO vibecoding_sessions (session_id, user_id, project_name, description, volume_name) VALUES
('test-session-1', 1, 'My First Project', 'A simple Python project', 'vibecoding_test-session-1'),
('test-session-2', 1, 'Web API Project', 'FastAPI web application', 'vibecoding_test-session-2');
*/