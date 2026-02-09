-- RVC Voice Models Table
-- Stores metadata for RVC character voice models

CREATE TABLE IF NOT EXISTS rvc_voice_models (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    category VARCHAR(50) DEFAULT 'custom',  -- cartoon, tv_show, celebrity, custom
    description TEXT,
    model_path VARCHAR(255) NOT NULL,
    index_path VARCHAR(255),
    pitch_shift INT DEFAULT 0,
    is_public BOOLEAN DEFAULT FALSE,
    is_cached BOOLEAN DEFAULT FALSE,
    sample_audio_path VARCHAR(255),  -- Preview audio sample
    last_used TIMESTAMP WITH TIME ZONE,
    usage_count INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_rvc_voice_models_user_id ON rvc_voice_models(user_id);
CREATE INDEX IF NOT EXISTS idx_rvc_voice_models_slug ON rvc_voice_models(slug);
CREATE INDEX IF NOT EXISTS idx_rvc_voice_models_category ON rvc_voice_models(category);
CREATE INDEX IF NOT EXISTS idx_rvc_voice_models_is_public ON rvc_voice_models(is_public);
CREATE INDEX IF NOT EXISTS idx_rvc_voice_models_is_cached ON rvc_voice_models(is_cached);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_rvc_voice_models_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_rvc_voice_models_updated_at ON rvc_voice_models;
CREATE TRIGGER trigger_update_rvc_voice_models_updated_at
    BEFORE UPDATE ON rvc_voice_models
    FOR EACH ROW
    EXECUTE FUNCTION update_rvc_voice_models_updated_at();

-- Comments for documentation
COMMENT ON TABLE rvc_voice_models IS 'Stores RVC voice model metadata for character voice conversion';
COMMENT ON COLUMN rvc_voice_models.slug IS 'URL-friendly unique identifier for the voice';
COMMENT ON COLUMN rvc_voice_models.category IS 'Voice category: cartoon, tv_show, celebrity, custom';
COMMENT ON COLUMN rvc_voice_models.model_path IS 'Path to .pth model file relative to RVC_MODELS_DIR';
COMMENT ON COLUMN rvc_voice_models.index_path IS 'Optional path to .index file for improved quality';
COMMENT ON COLUMN rvc_voice_models.pitch_shift IS 'Default pitch shift in semitones (-12 to +12)';
COMMENT ON COLUMN rvc_voice_models.is_cached IS 'Whether model should be pre-loaded into VRAM on startup';
COMMENT ON COLUMN rvc_voice_models.is_public IS 'Whether voice is available to all users';


