-- Artifact Build Jobs Schema for Harvis AI
-- Tracks build and execution of website/app artifacts in isolated executor pods
-- 
-- This schema extends the artifacts table with build job tracking for
-- isolated code execution on separate Kubernetes nodes

-- Build jobs table for tracking website/app builds
CREATE TABLE IF NOT EXISTS artifact_build_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    
    -- Job status tracking
    status VARCHAR(20) NOT NULL CHECK (status IN (
        'queued', 'building', 'running', 'failed', 'stopped', 'cleanup'
    )) DEFAULT 'queued',
    
    -- Build configuration
    node_version VARCHAR(20) DEFAULT '18',
    build_command TEXT DEFAULT 'npm install && npm run build',
    start_command TEXT DEFAULT 'npm start',
    framework VARCHAR(50) DEFAULT 'nextjs',
    
    -- Runtime configuration
    port INTEGER,                    -- Assigned port for this app
    preview_url TEXT,                -- Full URL to access the app
    
    -- Kubernetes info
    pod_name VARCHAR(255),           -- Kubernetes pod name
    namespace VARCHAR(255),          -- Kubernetes namespace
    node_name VARCHAR(255),          -- Node where pod is running
    
    -- Resource limits
    memory_limit VARCHAR(20) DEFAULT '1Gi',
    cpu_limit VARCHAR(20) DEFAULT '1000m',
    
    -- Timestamps
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    built_at TIMESTAMP WITH TIME ZONE,
    running_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    last_health_check TIMESTAMP WITH TIME ZONE,
    
    -- Error tracking
    build_logs TEXT,                 -- Full build output
    error_message TEXT,
    
    -- Cleanup
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP + INTERVAL '24 hours',
    
    -- Concurrency control (only one running job per artifact)
    CONSTRAINT unique_running_artifact UNIQUE (artifact_id, status)
    DEFERRABLE INITIALLY DEFERRED
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_build_jobs_artifact_id ON artifact_build_jobs(artifact_id);
CREATE INDEX IF NOT EXISTS idx_build_jobs_status ON artifact_build_jobs(status);
CREATE INDEX IF NOT EXISTS idx_build_jobs_queued_at ON artifact_build_jobs(queued_at);
CREATE INDEX IF NOT EXISTS idx_build_jobs_expires_at ON artifact_build_jobs(expires_at);
CREATE INDEX IF NOT EXISTS idx_build_jobs_pod_name ON artifact_build_jobs(pod_name);

-- Partial index for queued jobs (for queue processing)
CREATE INDEX IF NOT EXISTS idx_build_jobs_queued 
ON artifact_build_jobs(queued_at) 
WHERE status = 'queued';

-- Partial index for running jobs (for health checks)
CREATE INDEX IF NOT EXISTS idx_build_jobs_running 
ON artifact_build_jobs(last_health_check) 
WHERE status = 'running';

-- Function to update artifact status when build job changes
CREATE OR REPLACE FUNCTION update_artifact_build_status()
RETURNS TRIGGER AS $$
BEGIN
    -- Update artifact status based on build job status
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

-- Trigger for build status updates
DROP TRIGGER IF EXISTS trigger_build_status_update ON artifact_build_jobs;
CREATE TRIGGER trigger_build_status_update
    AFTER INSERT OR UPDATE OF status ON artifact_build_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_artifact_build_status();

-- Function to clean up expired build jobs
CREATE OR REPLACE FUNCTION cleanup_expired_build_jobs()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Delete expired jobs that are stopped or failed
    DELETE FROM artifact_build_jobs
    WHERE expires_at IS NOT NULL
    AND expires_at < CURRENT_TIMESTAMP
    AND status IN ('stopped', 'failed', 'cleanup');

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Function to stop old running jobs (for auto-cleanup)
CREATE OR REPLACE FUNCTION stop_old_running_jobs(max_age_hours INTEGER DEFAULT 24)
RETURNS INTEGER AS $$
DECLARE
    stopped_count INTEGER;
BEGIN
    UPDATE artifact_build_jobs
    SET status = 'stopped',
        completed_at = CURRENT_TIMESTAMP,
        error_message = COALESCE(error_message, '') || ' [Auto-stopped after ' || max_age_hours || ' hours]'
    WHERE status = 'running'
    AND running_at < CURRENT_TIMESTAMP - (max_age_hours || ' hours')::INTERVAL;

    GET DIAGNOSTICS stopped_count = ROW_COUNT;
    RETURN stopped_count;
END;
$$ LANGUAGE plpgsql;

-- View for build job statistics
CREATE OR REPLACE VIEW artifact_build_stats AS
SELECT
    status,
    framework,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (COALESCE(completed_at, CURRENT_TIMESTAMP) - queued_at))/60) as avg_duration_minutes,
    DATE_TRUNC('hour', queued_at) as hour_bucket
FROM artifact_build_jobs
GROUP BY status, framework, DATE_TRUNC('hour', queued_at)
ORDER BY hour_bucket DESC, status;

-- View for active/running jobs (for monitoring)
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
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - j.queued_at))/60 as minutes_in_queue,
    CASE 
        WHEN j.running_at IS NOT NULL THEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - j.running_at))/60
        ELSE NULL
    END as minutes_running
FROM artifact_build_jobs j
JOIN artifacts a ON j.artifact_id = a.id
WHERE j.status IN ('queued', 'building', 'running')
ORDER BY j.queued_at;

-- Comments for documentation
COMMENT ON TABLE artifact_build_jobs IS 'Tracks build and execution jobs for website/app artifacts';
COMMENT ON COLUMN artifact_build_jobs.artifact_id IS 'Reference to the artifact being built';
COMMENT ON COLUMN artifact_build_jobs.status IS 'Current status: queued, building, running, failed, stopped, cleanup';
COMMENT ON COLUMN artifact_build_jobs.port IS 'Port assigned to the running app';
COMMENT ON COLUMN artifact_build_jobs.preview_url IS 'URL to access the running app';
COMMENT ON COLUMN artifact_build_jobs.pod_name IS 'Kubernetes pod name for this build';
COMMENT ON COLUMN artifact_build_jobs.expires_at IS 'Auto-cleanup time (default 24 hours)';
