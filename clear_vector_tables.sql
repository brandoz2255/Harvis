-- SQL Script to Clear Old Vector Tables for RAG Corpus
-- Run this after updating embedding model dimensions from 2560 to 4096
-- This clears old 2560-dim tables so new 4096-dim tables can be created

-- WARNING: This will delete ALL existing RAG corpus embeddings!
-- Backup your data before running if needed.

BEGIN;

-- Step 1: Clear all records from existing vector tables
DELETE FROM local_rag_corpus_docs WHERE 1=1;
DELETE FROM local_rag_corpus WHERE 1=1;

-- Step 2: Drop old vector tables with wrong dimensions
DROP TABLE IF EXISTS local_rag_corpus_docs;
DROP TABLE IF EXISTS local_rag_corpus;

-- Step 3: Verify tables are gone (optional check)
-- Uncomment the following lines to verify deletion:
-- SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'local_rag_corpus%';

COMMIT;

-- After running this script:
-- 1. Restart the backend service
-- 2. Trigger fresh RAG updates from the UI
-- 3. New tables will be created with 4096 dimensions automatically
