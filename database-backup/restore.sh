#!/bin/bash
# Database Restore Script for Harvis AI Project
# Restores database from a backup file

set -e  # Exit on any error

# Configuration
CONTAINER_NAME="pgsql-db"
DB_NAME="database"
DB_USER="pguser"
BACKUP_DIR="./database-backup/backups"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to show usage
show_usage() {
    echo "Usage: $0 [backup_file]"
    echo ""
    echo "If no backup file specified, will list available backups"
    echo ""
    echo "Examples:"
    echo "  $0                                    # List available backups"
    echo "  $0 harvis_backup_20250113_143022.sql # Restore specific backup"
    echo "  $0 latest                             # Restore latest backup"
}

# Check if container is running
check_container() {
    if ! docker ps | grep -q "$CONTAINER_NAME"; then
        echo -e "${RED}Error: Container $CONTAINER_NAME is not running${NC}"
        exit 1
    fi
}

# List available backups
list_backups() {
    echo -e "${BLUE}Available backups in $BACKUP_DIR:${NC}"
    if [ -d "$BACKUP_DIR" ] && [ "$(ls -A $BACKUP_DIR/harvis_backup_*.sql 2>/dev/null)" ]; then
        ls -lt "$BACKUP_DIR"/harvis_backup_*.sql | while read -r line; do
            filename=$(echo "$line" | awk '{print $9}' | xargs basename)
            size=$(echo "$line" | awk '{print $5}')
            date=$(echo "$line" | awk '{print $6, $7, $8}')
            echo "  $filename (${size} bytes, $date)"
        done
        echo ""
        echo "Use: $0 <filename> to restore a specific backup"
        echo "Use: $0 latest to restore the most recent backup"
    else
        echo "  No backups found."
        echo "  Run ./database-backup/backup.sh to create a backup first."
    fi
}

# Get latest backup file
get_latest_backup() {
    ls -t "$BACKUP_DIR"/harvis_backup_*.sql 2>/dev/null | head -n1 || echo ""
}

# Main script
if [ $# -eq 0 ]; then
    list_backups
    exit 0
fi

if [ "$1" = "help" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_usage
    exit 0
fi

check_container

# Determine backup file to restore
if [ "$1" = "latest" ]; then
    BACKUP_FILE=$(get_latest_backup)
    if [ -z "$BACKUP_FILE" ]; then
        echo -e "${RED}No backup files found${NC}"
        exit 1
    fi
    echo "Using latest backup: $(basename "$BACKUP_FILE")"
else
    if [[ "$1" == /* ]]; then
        # Absolute path provided
        BACKUP_FILE="$1"
    else
        # Relative path or just filename
        if [ -f "$1" ]; then
            BACKUP_FILE="$1"
        else
            BACKUP_FILE="$BACKUP_DIR/$1"
        fi
    fi
fi

# Verify backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}Error: Backup file not found: $BACKUP_FILE${NC}"
    echo ""
    list_backups
    exit 1
fi

# Show warning and ask for confirmation
echo -e "${YELLOW}WARNING: This will REPLACE all data in the database!${NC}"
echo "Backup file: $BACKUP_FILE"
echo "Database: $DB_NAME"
echo "Container: $CONTAINER_NAME"
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo -e "${YELLOW}Starting database restore...${NC}"

# Create a backup before restore (safety measure)
SAFETY_BACKUP="./database-backup/backups/pre_restore_safety_$(date +"%Y%m%d_%H%M%S").sql"
echo "Creating safety backup before restore..."
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" > "$SAFETY_BACKUP"
echo "Safety backup saved: $SAFETY_BACKUP"

# Restore the database
echo "Restoring from backup file..."
docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" "$DB_NAME" < "$BACKUP_FILE"

echo -e "${GREEN}✓ Database restore completed successfully!${NC}"

# Verify restore by checking tables
echo "Verifying restore - checking table counts:"
docker exec "$CONTAINER_NAME" psql -U "$DB_USER" "$DB_NAME" -c "
SELECT 
    schemaname,
    tablename,
    n_tup_ins as row_count
FROM pg_stat_user_tables 
ORDER BY schemaname, tablename;
"

echo -e "${GREEN}Database restore verification completed!${NC}"