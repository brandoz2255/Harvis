-- Migration: Update vector dimension from 1024 to 4096
-- This is required because codellama produces 4096-dimensional embeddings
-- Run this migration against your PostgreSQL database

-- Step 1: Drop the existing chunks (they need to be regenerated with new embeddings)
-- WARNING: This will delete all existing embeddings. Sources will need to be re-ingested.
TRUNCATE TABLE notebook_chunks;

-- Step 2: Alter the column to use 4096 dimensions
ALTER TABLE notebook_chunks 
ALTER COLUMN embedding TYPE vector(4096);

-- Step 3: Update any sources that were previously processed to 'pending' so they get re-ingested
UPDATE notebook_sources 
SET status = 'pending', error_message = NULL 
WHERE status IN ('ready', 'error');

-- Verify the change
SELECT column_name, udt_name 
FROM information_schema.columns 
WHERE table_name = 'notebook_chunks' AND column_name = 'embedding';

