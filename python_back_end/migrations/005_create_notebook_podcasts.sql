-- Migration: Create notebook_podcasts table for podcast generation feature
-- Date: 2026-01-14

-- Notebook Podcasts - generated podcast episodes
CREATE TABLE IF NOT EXISTS notebook_podcasts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'completed', 'error')),
    style TEXT DEFAULT 'conversational' CHECK (style IN ('conversational', 'interview', 'educational', 'debate', 'storytelling')),
    speakers INTEGER DEFAULT 2,
    duration_minutes INTEGER DEFAULT 10,
    audio_path TEXT,
    transcript JSONB DEFAULT '[]'::jsonb,
    outline TEXT,
    error_message TEXT,
    duration_seconds INTEGER,
    source_ids UUID[] DEFAULT '{}',  -- Track which sources were used
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for podcast lookups
CREATE INDEX IF NOT EXISTS idx_notebook_podcasts_notebook_id ON notebook_podcasts(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebook_podcasts_user_id ON notebook_podcasts(user_id);
CREATE INDEX IF NOT EXISTS idx_notebook_podcasts_status ON notebook_podcasts(status);
CREATE INDEX IF NOT EXISTS idx_notebook_podcasts_created_at ON notebook_podcasts(created_at DESC);

-- Podcast Speaker Profiles - custom speaker profiles for podcasts (optional, for future enhancement)
CREATE TABLE IF NOT EXISTS podcast_speaker_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'Speaker',
    personality TEXT,
    voice_id TEXT,
    voice_provider TEXT DEFAULT 'chatterbox',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_podcast_speaker_profiles_user_id ON podcast_speaker_profiles(user_id);

-- Add trigger for updated_at on speaker profiles
CREATE OR REPLACE FUNCTION update_podcast_speaker_profile_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_podcast_speaker_profile_updated_at ON podcast_speaker_profiles;
CREATE TRIGGER trigger_podcast_speaker_profile_updated_at
    BEFORE UPDATE ON podcast_speaker_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_podcast_speaker_profile_updated_at();








