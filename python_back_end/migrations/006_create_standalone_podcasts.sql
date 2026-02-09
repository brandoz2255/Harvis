-- Migration: Create standalone_podcasts table for Open Notebook podcast generation
-- Date: 2026-01-28
-- Note: This table stores podcasts independently, supporting Open Notebook string IDs

-- Standalone Podcasts - for Open Notebook integration (no FK to notebooks table)
CREATE TABLE IF NOT EXISTS standalone_podcasts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id TEXT NOT NULL,  -- Open Notebook ID (e.g., "notebook:xyz")
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'completed', 'error', 'script_only')),
    style TEXT DEFAULT 'conversational',
    speakers INTEGER DEFAULT 2,
    duration_minutes INTEGER DEFAULT 10,
    audio_path TEXT,
    audio_url TEXT,
    transcript JSONB DEFAULT '[]'::jsonb,
    outline TEXT,
    error_message TEXT,
    duration_seconds INTEGER,
    source_ids TEXT[] DEFAULT '{}',  -- Open Notebook source IDs (e.g., "source:abc")
    note_ids TEXT[] DEFAULT '{}',    -- Open Notebook note IDs (e.g., "note:xyz")
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for podcast lookups
CREATE INDEX IF NOT EXISTS idx_standalone_podcasts_notebook_id ON standalone_podcasts(notebook_id);
CREATE INDEX IF NOT EXISTS idx_standalone_podcasts_user_id ON standalone_podcasts(user_id);
CREATE INDEX IF NOT EXISTS idx_standalone_podcasts_status ON standalone_podcasts(status);
CREATE INDEX IF NOT EXISTS idx_standalone_podcasts_created_at ON standalone_podcasts(created_at DESC);




