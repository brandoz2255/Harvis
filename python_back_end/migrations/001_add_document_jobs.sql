-- Migration: Add async job system with pg-boss compatibility
-- Run this in your PostgreSQL database

-- =====================================================
-- Document Jobs Table (for tracking document generation jobs)
-- =====================================================
CREATE TABLE IF NOT EXISTS document_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
    message_id INTEGER REFERENCES chat_messages(id) ON DELETE SET NULL,
    job_type VARCHAR(50) NOT NULL,  -- 'spreadsheet', 'document', 'pdf', 'presentation', 'code', 'research'
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed', 'cancelled'
    
    -- Input data
    payload JSONB NOT NULL DEFAULT '{}',  -- { code: "...", title: "...", language: "...", etc. }
    
    -- Output data
    result JSONB DEFAULT NULL,  -- { artifact_id: "...", download_url: "...", file_path: "...", error: "..." }
    
    -- Metadata
    priority INTEGER DEFAULT 0,  -- Higher = processed first
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Expiration (cleanup old jobs)
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP + INTERVAL '7 days')
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_document_jobs_user_id ON document_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_document_jobs_status ON document_jobs(status);
CREATE INDEX IF NOT EXISTS idx_document_jobs_session_id ON document_jobs(session_id);
CREATE INDEX IF NOT EXISTS idx_document_jobs_message_id ON document_jobs(message_id);
CREATE INDEX IF NOT EXISTS idx_document_jobs_created_at ON document_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_document_jobs_expires_at ON document_jobs(expires_at) WHERE expires_at IS NOT NULL;

-- Partial index for active jobs (fast lookup)
CREATE INDEX IF NOT EXISTS idx_document_jobs_active ON document_jobs(user_id, status) 
    WHERE status IN ('pending', 'processing');

-- =====================================================
-- pg-boss Schema (auto-created by pg-boss, but we document it)
-- =====================================================
-- pg-boss will create these tables automatically:
-- - boss.job (main job queue)
-- - boss.archive (completed jobs)
-- - boss.schedule (scheduled jobs)
-- - boss.subscription (pub/sub subscriptions)
-- - boss.version (schema version)

-- =====================================================
-- Notification Trigger for Real-time Updates
-- =====================================================
CREATE OR REPLACE FUNCTION notify_job_status_change()
RETURNS TRIGGER AS $$
BEGIN
    -- Only notify on status changes
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
        
        -- Also notify on user channel for sidebar updates
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
-- Cleanup Function (run via cron/pg_cron)
-- =====================================================
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
-- Job Statistics View
-- =====================================================
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
-- Comments for documentation
-- =====================================================
COMMENT ON TABLE document_jobs IS 'Tracks async document/code generation jobs';
COMMENT ON COLUMN document_jobs.payload IS 'Input data: code, title, configuration';
COMMENT ON COLUMN document_jobs.result IS 'Output data: artifact_id, download_url, or error';
COMMENT ON COLUMN document_jobs.job_type IS 'Type: spreadsheet, document, pdf, presentation, code, research';

-- =====================================================
-- Example queries
-- =====================================================
-- Get active jobs for user:
-- SELECT * FROM document_jobs WHERE user_id = ? AND status IN ('pending', 'processing') ORDER BY created_at DESC;

-- Get recent completed jobs:
-- SELECT * FROM document_jobs WHERE user_id = ? AND status = 'completed' ORDER BY completed_at DESC LIMIT 10;

-- Update job status:
-- UPDATE document_jobs SET status = 'processing', started_at = NOW() WHERE id = ?;

-- Complete job:
-- UPDATE document_jobs SET status = 'completed', result = '{"artifact_id": "..."}', completed_at = NOW() WHERE id = ?;
