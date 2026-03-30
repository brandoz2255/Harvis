#!/bin/bash
set -e

# PostgreSQL initialization script for Harvis AI
# This runs ONCE when the database is first initialized (empty data directory)
# Safe to run multiple times - all operations are idempotent

echo "=== Harvis AI Database Initialization ==="
echo "Running as user: $POSTGRES_USER"
echo "Database: $POSTGRES_DB"
echo ""

# 1. Create pgvector extension (required for embeddings)
echo "[1/4] Creating pgvector extension..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    COMMENT ON EXTENSION vector IS 'Vector similarity search extension for embeddings';
EOSQL
echo "✓ pgvector extension created"

# 2. Create artifacts table schema
echo ""
echo "[2/4] Creating artifacts schema..."
if [ -f /docker-entrypoint-initdb.d/artifacts_schema.sql ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" < /docker-entrypoint-initdb.d/artifacts_schema.sql
    echo "✓ Artifacts schema created"
else
    echo "⚠ artifacts_schema.sql not found, skipping"
fi

# 3. Create artifact build jobs schema
echo ""
echo "[3/4] Creating artifact build jobs schema..."
if [ -f /docker-entrypoint-initdb.d/artifacts_build_jobs_schema.sql ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" < /docker-entrypoint-initdb.d/artifacts_build_jobs_schema.sql
    echo "✓ Build jobs schema created"
else
    echo "⚠ artifacts_build_jobs_schema.sql not found, skipping"
fi

# 4. Verify setup
echo ""
echo "[4/4] Verifying database setup..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 
        'Tables created:' as info,
        COUNT(*) as count 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    AND table_name IN ('artifacts', 'artifact_build_jobs');
    
    SELECT 
        'Extensions installed:' as info,
        extname as extension
    FROM pg_extension 
    WHERE extname = 'vector';
EOSQL

echo ""
echo "=== Database initialization complete ==="
echo "Your database is ready to use!"
