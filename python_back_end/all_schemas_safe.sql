-- Combined Safe Schema for Harvis AI
-- This file is idempotent - safe to run multiple times
-- Creates all required tables without dropping existing data

-- =====================================================
-- 1. CHAT SESSIONS AND MESSAGES (required by artifacts/document_jobs)
-- =====================================================

-- Chat sessions table
CREATE TABLE IF NOT EXISTS chat_sessions (
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

-- Chat messages table
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    reasoning TEXT NULL,
    model_used VARCHAR(100),
    input_type VARCHAR(20) DEFAULT 'text' CHECK (input_type IN ('text', 'voice', 'screen')),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for chat tables
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated ON chat_sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_active ON chat_sessions(user_id, is_active, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created ON chat_messages(session_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_role ON chat_messages(role);

-- Function to update session on message insert
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

-- Trigger for session updates
DROP TRIGGER IF EXISTS trigger_update_session_on_message_insert ON chat_messages;
CREATE TRIGGER trigger_update_session_on_message_insert
    AFTER INSERT ON chat_messages
    FOR EACH ROW
    EXECUTE FUNCTION update_session_on_message_insert();

-- =====================================================
-- 2. ARTIFACTS TABLE (for generated documents/websites)
-- =====================================================

CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id INTEGER REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    artifact_type VARCHAR(50) NOT NULL CHECK (artifact_type IN (
        'spreadsheet', 'document', 'pdf', 'presentation', 'website', 'app', 'code'
    )),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    content JSONB NOT NULL DEFAULT '{}',
    file_path VARCHAR(500),
    file_size BIGINT,
    mime_type VARCHAR(100),
    framework VARCHAR(50),
    dependencies JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN (
        'pending', 'generating', 'ready', 'failed', 'expired'
    )),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for artifacts
CREATE INDEX IF NOT EXISTS idx_artifacts_message_id ON artifacts(message_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_session_id ON artifacts(session_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_user_id ON artifacts(user_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_created_at ON artifacts(created_at DESC);

-- Function to update artifact timestamp
CREATE OR REPLACE FUNCTION update_artifact_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_artifact_updated_at ON artifacts;
CREATE TRIGGER trigger_artifact_updated_at
    BEFORE UPDATE ON artifacts
    FOR EACH ROW
    EXECUTE FUNCTION update_artifact_updated_at();

-- =====================================================
-- 3. ARTIFACT BUILD JOBS (for website/app execution tracking)
-- =====================================================

CREATE TABLE IF NOT EXISTS artifact_build_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL CHECK (status IN (
        'queued', 'building', 'running', 'failed', 'stopped', 'cleanup'
    )) DEFAULT 'queued',
    node_version VARCHAR(20) DEFAULT '18',
    build_command TEXT DEFAULT 'npm install && npm run build',
    start_command TEXT DEFAULT 'npm start',
    framework VARCHAR(50) DEFAULT 'nextjs',
    port INTEGER,
    preview_url TEXT,
    pod_name VARCHAR(255),
    namespace VARCHAR(255),
    node_name VARCHAR(255),
    memory_limit VARCHAR(20) DEFAULT '1Gi',
    cpu_limit VARCHAR(20) DEFAULT '1000m',
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    built_at TIMESTAMP WITH TIME ZONE,
    running_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    last_health_check TIMESTAMP WITH TIME ZONE,
    build_logs TEXT,
    error_message TEXT,
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP + INTERVAL '24 hours'
);

-- Indexes for build jobs
CREATE INDEX IF NOT EXISTS idx_build_jobs_artifact_id ON artifact_build_jobs(artifact_id);
CREATE INDEX IF NOT EXISTS idx_build_jobs_status ON artifact_build_jobs(status);
CREATE INDEX IF NOT EXISTS idx_build_jobs_queued_at ON artifact_build_jobs(queued_at);
CREATE INDEX IF NOT EXISTS idx_build_jobs_expires_at ON artifact_build_jobs(expires_at);
CREATE INDEX IF NOT EXISTS idx_build_jobs_pod_name ON artifact_build_jobs(pod_name);
CREATE INDEX IF NOT EXISTS idx_build_jobs_queued ON artifact_build_jobs(queued_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_build_jobs_running ON artifact_build_jobs(last_health_check) WHERE status = 'running';

-- Function to update artifact status when build job changes
CREATE OR REPLACE FUNCTION update_artifact_build_status()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IN ('queued', 'building') THEN
        UPDATE artifacts SET status = 'generating' WHERE id = NEW.artifact_id;
    ELSIF NEW.status = 'running' THEN
        UPDATE artifacts SET status = 'ready' WHERE id = NEW.artifact_id;
    ELSIF NEW.status = 'failed' THEN
        UPDATE artifacts SET status = 'failed', error_message = NEW.error_message WHERE id = NEW.artifact_id;
    ELSIF NEW.status = 'stopped' THEN
        UPDATE artifacts SET status = 'expired' WHERE id = NEW.artifact_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_build_status_update ON artifact_build_jobs;
CREATE TRIGGER trigger_build_status_update
    AFTER INSERT OR UPDATE OF status ON artifact_build_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_artifact_build_status();

-- =====================================================
-- 4. DOCUMENT JOBS (pg-boss async job tracking)
-- =====================================================

CREATE TABLE IF NOT EXISTS document_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
    message_id INTEGER REFERENCES chat_messages(id) ON DELETE SET NULL,
    job_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    payload JSONB NOT NULL DEFAULT '{}',
    result JSONB DEFAULT NULL,
    priority INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP + INTERVAL '7 days')
);

-- Indexes for document jobs
CREATE INDEX IF NOT EXISTS idx_document_jobs_user_id ON document_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_document_jobs_status ON document_jobs(status);
CREATE INDEX IF NOT EXISTS idx_document_jobs_session_id ON document_jobs(session_id);
CREATE INDEX IF NOT EXISTS idx_document_jobs_message_id ON document_jobs(message_id);
CREATE INDEX IF NOT EXISTS idx_document_jobs_created_at ON document_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_document_jobs_expires_at ON document_jobs(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_document_jobs_active ON document_jobs(user_id, status) WHERE status IN ('pending', 'processing');

-- Notification trigger for real-time job status updates
CREATE OR REPLACE FUNCTION notify_job_status_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        PERFORM pg_notify(
            'job_status_' || NEW.id::text,
            json_build_object(
                'job_id', NEW.id,
                'status', NEW.status,
                'result', NEW.result,
                'updated_at', NEW.updated_at
            )::text
        );
        PERFORM pg_notify(
            'user_jobs_' || NEW.user_id::text,
            json_build_object(
                'job_id', NEW.id,
                'job_type', NEW.job_type,
                'status', NEW.status,
                'session_id', NEW.session_id
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS document_jobs_status_trigger ON document_jobs;
CREATE TRIGGER document_jobs_status_trigger
    AFTER UPDATE ON document_jobs
    FOR EACH ROW
    EXECUTE FUNCTION notify_job_status_change();

-- =====================================================
-- 5. UTILITY FUNCTIONS
-- =====================================================

-- Cleanup expired artifacts
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

-- Cleanup expired build jobs
CREATE OR REPLACE FUNCTION cleanup_expired_build_jobs()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM artifact_build_jobs
    WHERE expires_at IS NOT NULL
    AND expires_at < CURRENT_TIMESTAMP
    AND status IN ('stopped', 'failed', 'cleanup');
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Cleanup old document jobs
CREATE OR REPLACE FUNCTION cleanup_old_document_jobs()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM document_jobs
    WHERE expires_at < CURRENT_TIMESTAMP
       OR (status IN ('completed', 'failed', 'cancelled')
           AND completed_at < CURRENT_TIMESTAMP - INTERVAL '7 days');
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 6. VIEWS FOR MONITORING
-- =====================================================

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

CREATE OR REPLACE VIEW artifact_active_builds AS
SELECT
    j.id as job_id,
    j.artifact_id,
    a.title as artifact_title,
    a.artifact_type,
    j.status,
    j.framework,
    j.port,
    j.preview_url,
    j.pod_name,
    j.node_name,
    j.queued_at,
    j.started_at,
    j.built_at,
    j.running_at,
    j.expires_at,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - j.queued_at))/60 as minutes_in_queue
FROM artifact_build_jobs j
JOIN artifacts a ON j.artifact_id = a.id
WHERE j.status IN ('queued', 'building', 'running')
ORDER BY j.queued_at;

CREATE OR REPLACE VIEW document_job_stats AS
SELECT
    user_id,
    job_type,
    status,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration_seconds
FROM document_jobs
GROUP BY user_id, job_type, status;

-- =====================================================
-- Done! All tables created safely.
-- =====================================================
