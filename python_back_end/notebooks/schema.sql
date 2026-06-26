-- Notebook schema (idempotent). Extracted from the canonical db_setup.sql
-- so the backend can self-create these on startup (the tables were never
-- applied on this deploy). All CREATE TABLE/INDEX are IF NOT EXISTS.
CREATE EXTENSION IF NOT EXISTS vector;

-- updated_at trigger fn (idempotent) — the triggers below depend on it; define
-- it here so this schema is self-contained even if db_setup's copy never ran.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';


CREATE TABLE IF NOT EXISTS notebooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    emoji TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Additive: emoji column for notebooks that predate it (idempotent)
ALTER TABLE notebooks ADD COLUMN IF NOT EXISTS emoji TEXT;

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

-- User-defined transformation DEFINITIONS (open-notebook "Transformations" tab).
-- Built-in transformations are code-defined in onb_compat; this stores the custom
-- ones a user creates in the UI. Distinct from notebook_transformations (which holds
-- the RESULTS of applying a transformation to a source = open-notebook "insights").
CREATE TABLE IF NOT EXISTS notebook_transformation_defs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    title TEXT,
    description TEXT,
    prompt TEXT NOT NULL,
    apply_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notebook_transformation_defs_user ON notebook_transformation_defs(user_id);

-- Indexes for transformation lookups
CREATE INDEX IF NOT EXISTS idx_notebook_transformations_notebook_id ON notebook_transformations(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebook_transformations_user_id ON notebook_transformations(user_id);
CREATE INDEX IF NOT EXISTS idx_notebook_transformations_source_id ON notebook_transformations(source_id);
CREATE INDEX IF NOT EXISTS idx_notebook_transformations_type ON notebook_transformations(transformation_type);

-- Notebook Studio artifacts (onb_compat) — generated, REVIEWABLE study artifacts
-- (quiz / flashcards / study_guide) produced by the per-notebook Studio rail.
-- Persisted so the rail can LOG them and the user can reopen + review later.
-- Podcasts live in standalone_podcasts (also notebook-scoped via its TEXT notebook_id)
-- and are merged into the same log at read time.
CREATE TABLE IF NOT EXISTS onb_notebook_artifacts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('quiz', 'flashcards', 'study_guide')),
    title       TEXT,
    format      TEXT NOT NULL DEFAULT 'json',   -- 'json' (quiz/flashcards) | 'markdown' (study_guide)
    content     JSONB NOT NULL,                  -- {questions:[…]} | {cards:[…]} | {markdown:"…"}
    model_used  TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_onb_artifacts_notebook ON onb_notebook_artifacts(notebook_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_onb_artifacts_user ON onb_notebook_artifacts(user_id);

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

-- ─── open-notebook chat sessions (onb_compat) ──────────────────────────────────
-- The vendored open-notebook UI has multiple chat sessions per notebook (Harvis's
-- native chat did not). Dedicated tables so the native notebook_chat_messages path
-- is untouched.
CREATE TABLE IF NOT EXISTS notebook_chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    title TEXT,
    model_override TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_onb_sessions_nb ON notebook_chat_sessions(notebook_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS notebook_chat_session_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES notebook_chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,            -- 'human' | 'ai'
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_onb_session_msgs ON notebook_chat_session_messages(session_id, created_at);
-- Per-assistant-message citations: [{source_id, title, snippet, locator}] so the
-- chat UI can show a hover preview + scroll-to/highlight the cited passage.
ALTER TABLE notebook_chat_session_messages ADD COLUMN IF NOT EXISTS citations JSONB DEFAULT '[]';
