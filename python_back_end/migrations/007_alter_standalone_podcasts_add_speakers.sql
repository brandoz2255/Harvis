-- Migration: Add speaker_profiles and script columns to standalone_podcasts
-- Date: 2026-01-28

ALTER TABLE standalone_podcasts
    ADD COLUMN IF NOT EXISTS speaker_profiles JSONB DEFAULT '[]'::jsonb;

ALTER TABLE standalone_podcasts
    ADD COLUMN IF NOT EXISTS script JSONB;





