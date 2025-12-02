-- Migration: Update user_prefs table for VibeCode IDE preferences
-- This migration updates the user_prefs table to support VibeCode IDE preferences

-- Create user_prefs table if it doesn't exist
CREATE TABLE IF NOT EXISTS user_prefs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    theme TEXT DEFAULT 'dark',
    editor_font_size INTEGER DEFAULT 14,
    layout_config JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add new columns if they don't exist
DO $$
BEGIN
    -- Add left_panel_width column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_prefs' AND column_name = 'left_panel_width'
    ) THEN
        ALTER TABLE user_prefs ADD COLUMN left_panel_width INTEGER DEFAULT 280;
    END IF;
    
    -- Add right_panel_width column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_prefs' AND column_name = 'right_panel_width'
    ) THEN
        ALTER TABLE user_prefs ADD COLUMN right_panel_width INTEGER DEFAULT 384;
    END IF;
    
    -- Add terminal_height column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_prefs' AND column_name = 'terminal_height'
    ) THEN
        ALTER TABLE user_prefs ADD COLUMN terminal_height INTEGER DEFAULT 200;
    END IF;
    
    -- Add default_model column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_prefs' AND column_name = 'default_model'
    ) THEN
        ALTER TABLE user_prefs ADD COLUMN default_model VARCHAR(100) DEFAULT 'mistral';
    END IF;
    
    -- Add font_size column (alias for editor_font_size)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_prefs' AND column_name = 'font_size'
    ) THEN
        ALTER TABLE user_prefs ADD COLUMN font_size INTEGER DEFAULT 14;
        -- Copy existing editor_font_size values to font_size
        UPDATE user_prefs SET font_size = editor_font_size WHERE font_size IS NULL;
    END IF;
END $$;

-- Create index on user_id for fast lookups
CREATE INDEX IF NOT EXISTS idx_user_prefs_user_id ON user_prefs(user_id);

-- Add unique constraint if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE table_name = 'user_prefs' 
        AND constraint_type = 'UNIQUE' 
        AND constraint_name = 'unique_user_prefs'
    ) THEN
        ALTER TABLE user_prefs ADD CONSTRAINT unique_user_prefs UNIQUE (user_id);
    END IF;
END $$;

-- Trigger function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_user_prefs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to user_prefs table
DROP TRIGGER IF EXISTS update_user_prefs_updated_at_trigger ON user_prefs;
CREATE TRIGGER update_user_prefs_updated_at_trigger
    BEFORE UPDATE ON user_prefs 
    FOR EACH ROW EXECUTE FUNCTION update_user_prefs_updated_at();

-- Comments for documentation
COMMENT ON TABLE user_prefs IS 'Stores user preferences for VibeCode IDE (theme, layout, etc.)';
COMMENT ON COLUMN user_prefs.user_id IS 'Foreign key to users table';
COMMENT ON COLUMN user_prefs.theme IS 'UI theme: light or dark';
COMMENT ON COLUMN user_prefs.left_panel_width IS 'Width of left file explorer panel in pixels';
COMMENT ON COLUMN user_prefs.right_panel_width IS 'Width of right tabs panel in pixels';
COMMENT ON COLUMN user_prefs.terminal_height IS 'Height of terminal panel in pixels';
COMMENT ON COLUMN user_prefs.default_model IS 'Default AI model selection';
COMMENT ON COLUMN user_prefs.font_size IS 'Editor and terminal font size';
