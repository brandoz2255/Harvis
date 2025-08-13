-- DEVELOPMENT ONLY: Database Reset Script
-- WARNING: This script DESTROYS ALL DATA - NEVER run in production!
-- 
-- This script is for development environment ONLY to reset the database
-- to a clean state. It will delete ALL user accounts and data.
--
-- Usage: docker exec -i pgsql-db psql -U pguser -d database -f /path/to/this/file
--
-- SAFETY CHECK: Only run this if you understand you will lose ALL DATA

-- Drop all tables and cascade to dependent objects (DESTRUCTIVE!)
DROP TABLE IF EXISTS vibe_executions CASCADE;
DROP TABLE IF EXISTS vibe_chat CASCADE;
DROP TABLE IF EXISTS vibe_files CASCADE;
DROP TABLE IF EXISTS vibe_sessions CASCADE;
DROP TABLE IF EXISTS user_api_keys CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- Drop functions if they exist
DROP FUNCTION IF EXISTS register_user(VARCHAR, VARCHAR, VARCHAR);
DROP FUNCTION IF EXISTS update_updated_at_column();
DROP FUNCTION IF EXISTS update_vibe_files_updated_at();

-- Now recreate everything using the safe db_setup.sql
-- Note: This assumes you'll run the main db_setup.sql after this script

\echo 'DEVELOPMENT DATABASE RESET COMPLETE'
\echo 'Now run the main db_setup.sql to recreate tables'
\echo 'WARNING: ALL USER DATA HAS BEEN DESTROYED'