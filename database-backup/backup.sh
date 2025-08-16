#!/bin/bash
# Database Backup Script for Harvis AI Project
# Creates timestamped backups of the PostgreSQL database

set -e  # Exit on any error

# Configuration
CONTAINER_NAME="pgsql-db"
DB_NAME="database"
DB_USER="pguser"
BACKUP_DIR="./database-backup/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="harvis_backup_${TIMESTAMP}.sql"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting database backup...${NC}"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Check if container is running
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo -e "${RED}Error: Container $CONTAINER_NAME is not running${NC}"
    exit 1
fi

# Create backup (exclude problematic extensions)
echo "Creating backup: $BACKUP_FILE"
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" \
    --exclude-table=langchain_pg_embedding \
    --exclude-table=langchain_pg_collection > "$BACKUP_DIR/$BACKUP_FILE"

# Verify backup file was created and has content
if [ -s "$BACKUP_DIR/$BACKUP_FILE" ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_FILE" | cut -f1)
    echo -e "${GREEN}✓ Backup completed successfully${NC}"
    echo "  File: $BACKUP_DIR/$BACKUP_FILE"
    echo "  Size: $BACKUP_SIZE"
    
    # Show table count in backup for verification
    echo "Backup contains data for these tables:"
    grep "COPY.*FROM stdin" "$BACKUP_DIR/$BACKUP_FILE" | sed 's/COPY \([^ ]*\).*/  - \1/' || echo "  - No table data found"
    
else
    echo -e "${RED}Error: Backup file is empty or was not created${NC}"
    exit 1
fi

# Keep only last 10 backups (cleanup old ones)
echo "Cleaning up old backups (keeping last 10)..."
cd "$BACKUP_DIR"
ls -t harvis_backup_*.sql | tail -n +11 | xargs -r rm
cd - > /dev/null

echo -e "${GREEN}Database backup completed successfully!${NC}"