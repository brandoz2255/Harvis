"""
Database Migration for MCP Plugin System

Run this SQL to add the necessary tables for MCP plugins and OpenClaw integration.
"""

MIGRATION_SQL = """
-- ============================================================================
-- MCP Plugin System - Database Migration
-- ============================================================================

-- MCP Servers registry
CREATE TABLE IF NOT EXISTS mcp_servers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    host VARCHAR(255) NOT NULL,
    port INTEGER,
    transport VARCHAR(20) DEFAULT 'stdio',
    config JSONB DEFAULT '{}',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, name)
);

-- MCP Tools from servers
CREATE TABLE IF NOT EXISTS mcp_tools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID REFERENCES mcp_servers(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    parameters JSONB NOT NULL DEFAULT '{}',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(server_id, name)
);

-- OpenClaw VM instances
CREATE TABLE IF NOT EXISTS openclaw_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    vm_type VARCHAR(20) DEFAULT 'virtualbox',
    vm_config JSONB DEFAULT '{}',
    bridge_token VARCHAR(255) UNIQUE,
    bridge_url VARCHAR(500),
    status VARCHAR(20) DEFAULT 'offline',
    last_connected_at TIMESTAMP WITH TIME ZONE,
    vm_ip VARCHAR(50),
    vm_port INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- OpenClaw tasks
CREATE TABLE IF NOT EXISTS openclaw_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID REFERENCES openclaw_instances(id) ON DELETE CASCADE,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    steps JSONB DEFAULT '[]',
    current_step INTEGER DEFAULT 0,
    result TEXT,
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    policy_profile VARCHAR(50) DEFAULT 'default',
    max_runtime_minutes INTEGER DEFAULT 30
);

-- OpenClaw events (for real-time streaming)
CREATE TABLE IF NOT EXISTS openclaw_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES openclaw_tasks(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Screenshots
CREATE TABLE IF NOT EXISTS screenshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES openclaw_tasks(id) ON DELETE CASCADE,
    job_id UUID REFERENCES openclaw_tasks(id) ON DELETE SET NULL,
    step_index INTEGER,
    caption TEXT,
    storage_path TEXT NOT NULL,
    thumbnail_path TEXT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    taken_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Approval gates
CREATE TABLE IF NOT EXISTS approval_gates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id VARCHAR(255) UNIQUE NOT NULL,
    job_id UUID NOT NULL,
    task_id UUID REFERENCES openclaw_tasks(id) ON DELETE CASCADE,
    tool_name VARCHAR(255) NOT NULL,
    tool_call_id VARCHAR(255) NOT NULL,
    action_description TEXT NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    parameters JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'pending',
    approved BOOLEAN,
    response_reason TEXT,
    responded_at TIMESTAMP WITH TIME ZONE,
    responded_by VARCHAR(100),
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    timeout_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_mcp_servers_user_id ON mcp_servers(user_id);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_server_id ON mcp_tools(server_id);
CREATE INDEX IF NOT EXISTS idx_openclaw_instances_user_id ON openclaw_instances(user_id);
CREATE INDEX IF NOT EXISTS idx_openclaw_tasks_instance_id ON openclaw_tasks(instance_id);
CREATE INDEX IF NOT EXISTS idx_openclaw_tasks_session_id ON openclaw_tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_openclaw_tasks_user_id ON openclaw_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_openclaw_events_task_id ON openclaw_events(task_id);
CREATE INDEX IF NOT EXISTS idx_openclaw_events_created_at ON openclaw_events(created_at);
CREATE INDEX IF NOT EXISTS idx_screenshots_task_id ON screenshots(task_id);
CREATE INDEX IF NOT EXISTS idx_approval_gates_task_id ON approval_gates(task_id);
CREATE INDEX IF NOT EXISTS idx_approval_gates_status ON approval_gates(status);

-- ============================================================================
-- Chat Messages Enhancement (Optional - add if not exists)
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'chat_messages' AND column_name = 'tool_calls'
    ) THEN
        ALTER TABLE chat_messages ADD COLUMN tool_calls JSONB DEFAULT NULL;
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'chat_messages' AND column_name = 'tool_results'
    ) THEN
        ALTER TABLE chat_messages ADD COLUMN tool_results JSONB DEFAULT NULL;
    END IF;
END $$;

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE mcp_servers IS 'Registry of MCP (Model Context Protocol) servers';
COMMENT ON TABLE mcp_tools IS 'Tools available from registered MCP servers';
COMMENT ON TABLE openclaw_instances IS 'OpenClaw VM instances for browser automation';
COMMENT ON TABLE openclaw_tasks IS 'Automation tasks executed by OpenClaw';
COMMENT ON TABLE openclaw_events IS 'Event stream for real-time task updates';
COMMENT ON TABLE screenshots IS 'Screenshot metadata for task recordings';
COMMENT ON TABLE approval_gates IS 'Approval requests for sensitive actions';
"""

if __name__ == "__main__":
    print(MIGRATION_SQL)
