-- Add user_id scoping to RVC voice models
-- Allows per-user voice model libraries

-- Ensure user_id column exists (might already from 008)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rvc_voice_models' 
        AND column_name = 'user_id'
    ) THEN
        ALTER TABLE rvc_voice_models 
        ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;

-- Add source column to track where the model came from
ALTER TABLE rvc_voice_models 
ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'upload';
-- source values: 'upload', 'voice-models.com', 'huggingface', 'custom'

-- Add source_url column to track the original download URL
ALTER TABLE rvc_voice_models 
ADD COLUMN IF NOT EXISTS source_url TEXT;

-- Update index for user-specific queries
DROP INDEX IF EXISTS idx_rvc_voice_models_user_slug;
CREATE UNIQUE INDEX IF NOT EXISTS idx_rvc_voice_models_user_slug 
ON rvc_voice_models(user_id, slug) 
WHERE user_id IS NOT NULL;

-- Index for fetching user's voices
CREATE INDEX IF NOT EXISTS idx_rvc_voice_models_user_created 
ON rvc_voice_models(user_id, created_at DESC) 
WHERE user_id IS NOT NULL;

-- Comments
COMMENT ON COLUMN rvc_voice_models.source IS 'Source of the model: upload, voice-models.com, huggingface, custom';
COMMENT ON COLUMN rvc_voice_models.source_url IS 'Original download URL if imported from external source';


