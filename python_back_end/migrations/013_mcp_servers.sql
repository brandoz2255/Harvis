-- Phase 5 — per-user MCP server configs + OAuth token storage.
-- Replaces Hermes's ~/.hermes/mcp-tokens/*.json file pattern with a
-- multi-tenant Postgres-backed equivalent. Schemas are payload-agnostic
-- (jsonb) so we don't pin the MCP Python SDK shape into our schema.

CREATE TABLE IF NOT EXISTS mcp_servers (
    id            BIGSERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_name   TEXT NOT NULL,
    transport     TEXT NOT NULL,                 -- 'stdio' | 'sse' | 'streamable-http'
    url           TEXT,                          -- HTTP transports
    command       TEXT,                          -- stdio transports
    args          JSONB NOT NULL DEFAULT '[]'::jsonb,
    env           JSONB NOT NULL DEFAULT '{}'::jsonb,
    auth_method   TEXT NOT NULL DEFAULT 'none',  -- 'none' | 'oauth'
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, server_name)
);

CREATE INDEX IF NOT EXISTS idx_mcp_servers_user
    ON mcp_servers(user_id);


CREATE TABLE IF NOT EXISTS mcp_oauth_tokens (
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_name       TEXT NOT NULL,
    tokens_json       JSONB,                      -- OAuthToken-shaped payload (SDK-agnostic)
    client_info_json  JSONB,                      -- OAuthClientInformationFull-shaped payload
    expires_at        TIMESTAMPTZ,                -- absolute expiry — survives process restart
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, server_name)
);

CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_expires
    ON mcp_oauth_tokens(expires_at)
    WHERE expires_at IS NOT NULL;
