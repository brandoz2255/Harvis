-- DANGER: This script previously contained DROP TABLE commands that destroy all user data!
-- The DROP TABLE commands have been removed to prevent accidental data loss.
-- For development reset, use the dev-setup scripts instead.

-- WARNING: Only run this in a clean/new database environment
-- This script will NOT recreate tables if they already exist (safe for production)

-- Create the users table with the correct schema (safe - only if not exists)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL, -- This is where the hashed password will be stored
    avatar VARCHAR(255), -- Optional: for user profile images
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create or replace the register_user function
CREATE OR REPLACE FUNCTION register_user(p_username VARCHAR, p_email VARCHAR, p_password_hash VARCHAR)
RETURNS BOOLEAN AS $$
BEGIN
    -- Check if username or email already exists
    IF EXISTS (SELECT 1 FROM users WHERE username = p_username OR email = p_email) THEN
        RETURN FALSE; -- User already exists
    END IF;

    INSERT INTO users (username, email, password) VALUES (p_username, p_email, p_password_hash);
    RETURN TRUE;
EXCEPTION WHEN unique_violation THEN
    -- This handles a race condition if another transaction inserts the same user
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- Create user_api_keys table for storing encrypted API keys per user
CREATE TABLE IF NOT EXISTS user_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_name VARCHAR(50) NOT NULL, -- e.g., 'ollama', 'gemini', 'openai', 'anthropic'
    api_key_encrypted TEXT NOT NULL, -- Encrypted API key
    api_url VARCHAR(500), -- Optional: custom API URL (e.g., for Ollama local instances)
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, provider_name) -- One API key per provider per user
);

-- Create index for faster lookups
CREATE INDEX idx_user_api_keys_user_id ON user_api_keys(user_id);
CREATE INDEX idx_user_api_keys_provider ON user_api_keys(provider_name);

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at
CREATE TRIGGER update_user_api_keys_updated_at
    BEFORE UPDATE ON user_api_keys
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create user_ollama_settings table for per-user Ollama configuration
CREATE TABLE IF NOT EXISTS user_ollama_settings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cloud_url VARCHAR(500), -- Cloud Ollama URL (e.g., https://cloud-ollama.com/ollama)
    local_url VARCHAR(500), -- Local Ollama URL (e.g., http://ollama:11434)
    api_key_encrypted TEXT, -- Encrypted API key for cloud Ollama
    preferred_endpoint VARCHAR(20) DEFAULT 'auto' CHECK (preferred_endpoint IN ('cloud', 'local', 'auto')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id) -- One Ollama configuration per user
);

-- Create index for faster lookups
CREATE INDEX idx_user_ollama_settings_user_id ON user_ollama_settings(user_id);

-- Trigger to automatically update updated_at
CREATE TRIGGER update_user_ollama_settings_updated_at
    BEFORE UPDATE ON user_ollama_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Vibe Coding Sessions
CREATE TABLE IF NOT EXISTS vibe_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);

-- File Tree Structure (nested folders/files)
CREATE TABLE IF NOT EXISTS vibe_files (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES vibe_sessions(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES vibe_files(id),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(10) CHECK (type IN ('file', 'folder')),
    content TEXT, -- null for folders
    language VARCHAR(50),
    path TEXT NOT NULL, -- full path for quick access
    size INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Chat History for Vibe Coding
CREATE TABLE IF NOT EXISTS vibe_chat (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES vibe_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    type VARCHAR(20) DEFAULT 'text',
    reasoning TEXT, -- for reasoning models
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Code Execution History
CREATE TABLE IF NOT EXISTS vibe_executions (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES vibe_sessions(id) ON DELETE CASCADE,
    command TEXT NOT NULL,
    output TEXT,
    exit_code INTEGER,
    execution_time INTEGER, -- milliseconds
    language VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX idx_vibe_sessions_user_id ON vibe_sessions(user_id);
CREATE INDEX idx_vibe_files_session_id ON vibe_files(session_id);
CREATE INDEX idx_vibe_files_parent_id ON vibe_files(parent_id);
CREATE INDEX idx_vibe_chat_session_id ON vibe_chat(session_id);
CREATE INDEX idx_vibe_executions_session_id ON vibe_executions(session_id);

-- Triggers for updated_at timestamps
CREATE TRIGGER update_vibe_sessions_updated_at 
    BEFORE UPDATE ON vibe_sessions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_vibe_files_updated_at 
    BEFORE UPDATE ON vibe_files 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- GitHub OAuth Tokens (encrypted)
CREATE TABLE IF NOT EXISTS github_tokens (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_github_tokens_user_id ON github_tokens(user_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- NotebookLM Feature Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Enable pgvector extension for embeddings (safe - only if not exists)
CREATE EXTENSION IF NOT EXISTS vector;

-- Notebooks - main container for sources, notes, and chat
CREATE TABLE IF NOT EXISTS notebooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for user lookups
CREATE INDEX IF NOT EXISTS idx_notebooks_user_id ON notebooks(user_id);
CREATE INDEX IF NOT EXISTS idx_notebooks_user_active ON notebooks(user_id, is_active);

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_notebooks_updated_at ON notebooks;
CREATE TRIGGER update_notebooks_updated_at
    BEFORE UPDATE ON notebooks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Notebook Sources - PDFs, text, URLs, etc.
CREATE TABLE IF NOT EXISTS notebook_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('pdf', 'text', 'url', 'markdown', 'doc', 'transcript', 'audio')),
    title TEXT,
    storage_path TEXT, -- path to raw file or URL
    original_filename TEXT, -- original uploaded filename
    content_text TEXT, -- extracted text content
    metadata JSONB DEFAULT '{}', -- page count, mime type, etc.
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'ready', 'error')),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for source lookups
CREATE INDEX IF NOT EXISTS idx_notebook_sources_notebook_id ON notebook_sources(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebook_sources_status ON notebook_sources(status);

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_notebook_sources_updated_at ON notebook_sources;
CREATE TRIGGER update_notebook_sources_updated_at
    BEFORE UPDATE ON notebook_sources
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Notebook Chunks - text chunks with embeddings for RAG
CREATE TABLE IF NOT EXISTS notebook_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES notebook_sources(id) ON DELETE CASCADE,
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(4096), -- Support for various models: codellama=4096, nomic-embed-text=768
    metadata JSONB DEFAULT '{}', -- page number, section, heading, etc.
    chunk_index INTEGER, -- order within the source
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for chunk lookups and vector search
CREATE INDEX IF NOT EXISTS idx_notebook_chunks_source_id ON notebook_chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_notebook_chunks_notebook_id ON notebook_chunks(notebook_id);

-- IVFFlat index for fast approximate nearest neighbor search
-- Note: This index should be created after some data is in the table for optimal performance
-- CREATE INDEX IF NOT EXISTS idx_notebook_chunks_embedding ON notebook_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Notebook Notes - user notes and AI-generated summaries
CREATE TABLE IF NOT EXISTS notebook_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('user_note', 'ai_note', 'summary', 'highlight')),
    title TEXT,
    content TEXT NOT NULL,
    source_meta JSONB DEFAULT '{}', -- citations, source references
    is_pinned BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for notes lookups
CREATE INDEX IF NOT EXISTS idx_notebook_notes_notebook_id ON notebook_notes(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebook_notes_user_id ON notebook_notes(user_id);
CREATE INDEX IF NOT EXISTS idx_notebook_notes_type ON notebook_notes(type);

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_notebook_notes_updated_at ON notebook_notes;
CREATE TRIGGER update_notebook_notes_updated_at
    BEFORE UPDATE ON notebook_notes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Notebook Chat Messages - per-notebook chat history
CREATE TABLE IF NOT EXISTS notebook_chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    reasoning TEXT, -- for reasoning models
    citations JSONB DEFAULT '[]', -- source citations
    model_used TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for chat lookups
CREATE INDEX IF NOT EXISTS idx_notebook_chat_messages_notebook_id ON notebook_chat_messages(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebook_chat_messages_user_id ON notebook_chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_notebook_chat_messages_created_at ON notebook_chat_messages(created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Open Notebook Integration Tables
-- ═══════════════════════════════════════════════════════════════════════════════

-- Notebook Transformations - AI transformations applied to sources/notes
CREATE TABLE IF NOT EXISTS notebook_transformations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    source_id UUID REFERENCES notebook_sources(id) ON DELETE SET NULL,
    note_id UUID REFERENCES notebook_notes(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    transformation_type TEXT NOT NULL CHECK (transformation_type IN (
        'summarize', 'key_points', 'questions', 'outline', 
        'simplify', 'critique', 'action_items', 'custom'
    )),
    original_content TEXT NOT NULL,
    transformed_content TEXT NOT NULL,
    model_used TEXT,
    custom_prompt TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for transformation lookups
CREATE INDEX IF NOT EXISTS idx_notebook_transformations_notebook_id ON notebook_transformations(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebook_transformations_user_id ON notebook_transformations(user_id);
CREATE INDEX IF NOT EXISTS idx_notebook_transformations_source_id ON notebook_transformations(source_id);
CREATE INDEX IF NOT EXISTS idx_notebook_transformations_type ON notebook_transformations(transformation_type);

-- Notebook Podcasts - generated podcast episodes
CREATE TABLE IF NOT EXISTS notebook_podcasts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'completed', 'error')),
    style TEXT DEFAULT 'conversational' CHECK (style IN (
        'conversational', 'interview', 'educational', 'debate', 'storytelling'
    )),
    speakers INTEGER DEFAULT 2,
    duration_minutes INTEGER DEFAULT 10,
    audio_path TEXT,
    transcript JSONB DEFAULT '[]', -- Array of {speaker, dialogue} objects
    outline TEXT, -- Generated outline
    error_message TEXT,
    duration_seconds INTEGER, -- Actual duration after generation
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for podcast lookups
CREATE INDEX IF NOT EXISTS idx_notebook_podcasts_notebook_id ON notebook_podcasts(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebook_podcasts_user_id ON notebook_podcasts(user_id);
CREATE INDEX IF NOT EXISTS idx_notebook_podcasts_status ON notebook_podcasts(status);

-- Podcast Speaker Profiles - custom speaker profiles for podcasts
CREATE TABLE IF NOT EXISTS podcast_speaker_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'Speaker',
    personality TEXT,
    voice_id TEXT, -- For TTS provider voice selection
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for speaker profile lookups
CREATE INDEX IF NOT EXISTS idx_podcast_speaker_profiles_user_id ON podcast_speaker_profiles(user_id);

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_podcast_speaker_profiles_updated_at ON podcast_speaker_profiles;
CREATE TRIGGER update_podcast_speaker_profiles_updated_at
    BEFORE UPDATE ON podcast_speaker_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add youtube to source types (ALTER if table exists)
DO $$
BEGIN
    -- Try to add youtube to the source type check constraint
    ALTER TABLE notebook_sources DROP CONSTRAINT IF EXISTS notebook_sources_type_check;
    ALTER TABLE notebook_sources ADD CONSTRAINT notebook_sources_type_check 
        CHECK (type IN ('pdf', 'text', 'url', 'markdown', 'doc', 'transcript', 'audio', 'youtube', 'image'));
EXCEPTION
    WHEN OTHERS THEN
        -- Constraint might already exist with correct values
        NULL;
END $$;
