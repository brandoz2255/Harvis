-- Artifacts Database Schema for Harvis AI
-- Enables LLM to generate documents (Excel, DOCX, PDF, PPTX) and interactive websites

-- Create artifacts table (safe - won't drop existing tables)
CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id INTEGER REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Artifact metadata
    artifact_type VARCHAR(50) NOT NULL CHECK (artifact_type IN (
        'spreadsheet', 'document', 'pdf', 'presentation', 'website', 'app', 'code'
    )),
    title VARCHAR(255) NOT NULL,
    description TEXT,

    -- Content storage
    content JSONB NOT NULL DEFAULT '{}',  -- JSON manifest for generation or stored website code
    file_path VARCHAR(500),               -- For generated document files: /data/artifacts/file.xlsx
    file_size BIGINT,                     -- File size in bytes
    mime_type VARCHAR(100),

    -- Website/app specific
    framework VARCHAR(50),                -- 'react', 'nextjs', 'vanilla', etc.
    dependencies JSONB DEFAULT '{}',      -- npm packages needed for website artifacts

    -- Status tracking
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN (
        'pending', 'generating', 'ready', 'failed', 'expired'
    )),
    error_message TEXT,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE   -- For cleanup of generated files
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_artifacts_message_id ON artifacts(message_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_session_id ON artifacts(session_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_user_id ON artifacts(user_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_created_at ON artifacts(created_at DESC);

-- Function to update artifact's updated_at timestamp
CREATE OR REPLACE FUNCTION update_artifact_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for updated_at (drop first if exists to avoid conflicts)
DROP TRIGGER IF EXISTS trigger_artifact_updated_at ON artifacts;
CREATE TRIGGER trigger_artifact_updated_at
    BEFORE UPDATE ON artifacts
    FOR EACH ROW
    EXECUTE FUNCTION update_artifact_updated_at();

-- Function to clean up expired artifacts (call periodically)
CREATE OR REPLACE FUNCTION cleanup_expired_artifacts()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM artifacts
    WHERE expires_at IS NOT NULL
    AND expires_at < CURRENT_TIMESTAMP
    AND status = 'ready';

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- View for artifact statistics (useful for monitoring)
CREATE OR REPLACE VIEW artifact_stats AS
SELECT
    artifact_type,
    status,
    COUNT(*) as count,
    SUM(file_size) as total_size_bytes,
    DATE_TRUNC('day', created_at) as created_date
FROM artifacts
GROUP BY artifact_type, status, DATE_TRUNC('day', created_at)
ORDER BY created_date DESC, artifact_type;

-- Comments for documentation
COMMENT ON TABLE artifacts IS 'Stores AI-generated artifacts (documents, websites, code)';
COMMENT ON COLUMN artifacts.content IS 'JSON manifest for document generation or website source code';
COMMENT ON COLUMN artifacts.file_path IS 'Path to generated file in /data/artifacts volume';
COMMENT ON COLUMN artifacts.framework IS 'Framework for website/app artifacts (react, nextjs, etc.)';
COMMENT ON COLUMN artifacts.dependencies IS 'NPM dependencies for website artifacts';
