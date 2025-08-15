-- Database optimizations for authentication and chat history performance

-- 1. Users table optimizations
-- Add indexes for faster user lookups during authentication
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_id_active ON users(id) WHERE id IS NOT NULL;

-- 2. Chat sessions table optimizations
-- Add composite indexes for faster session queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_sessions_user_active 
ON chat_sessions(user_id, is_active, last_message_at DESC) 
WHERE is_active = TRUE;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_sessions_user_updated 
ON chat_sessions(user_id, updated_at DESC) 
WHERE is_active = TRUE;

-- 3. Chat messages table optimizations
-- Add indexes for faster message retrieval
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_messages_session_created 
ON chat_messages(session_id, created_at ASC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_messages_user_session 
ON chat_messages(user_id, session_id, created_at ASC);

-- 4. Connection and query optimizations
-- Set optimal PostgreSQL settings for authentication workload
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
ALTER SYSTEM SET default_statistics_target = 100;
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET effective_io_concurrency = 200;

-- Reload configuration
SELECT pg_reload_conf();

-- 5. Analyze tables to update statistics
ANALYZE users;
ANALYZE chat_sessions;
ANALYZE chat_messages;

-- 6. Vacuum for better performance
VACUUM ANALYZE users;
VACUUM ANALYZE chat_sessions;
VACUUM ANALYZE chat_messages;