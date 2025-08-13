# Database Backup and Restore

This directory contains scripts for backing up and restoring the PostgreSQL database.

## 🚨 **IMPORTANT: Always backup before making changes!**

## Scripts:

### `backup.sh`
Creates a timestamped backup of the entire database.
```bash
./database-backup/backup.sh
```

**Features:**
- Automatic timestamping: `harvis_backup_20250113_143022.sql`
- Backup verification (checks file size and content)
- Automatic cleanup (keeps last 10 backups)
- Color-coded output for easy reading

### `restore.sh`
Restores database from a backup file.

```bash
# List available backups
./database-backup/restore.sh

# Restore specific backup
./database-backup/restore.sh harvis_backup_20250113_143022.sql

# Restore latest backup
./database-backup/restore.sh latest
```

**Safety Features:**
- Creates safety backup before restore
- Confirmation prompt before destructive operations
- Verification of restored data
- Clear warnings about data loss

## Usage Examples:

### Create a backup before making changes:
```bash
./database-backup/backup.sh
```

### Restore if something goes wrong:
```bash
# See what backups are available
./database-backup/restore.sh

# Restore the latest one
./database-backup/restore.sh latest
```

### Regular backup workflow:
```bash
# Before any database changes
./database-backup/backup.sh

# Make your changes...

# If something goes wrong, restore
./database-backup/restore.sh latest
```

## Backup Storage:

- Backups are stored in `./database-backup/backups/`
- Files are named: `harvis_backup_YYYYMMDD_HHMMSS.sql`
- Automatic cleanup keeps the 10 most recent backups
- Each backup is a complete PostgreSQL dump

## Security Notes:

- Backup files contain all user data including password hashes
- Store backups securely
- Don't commit backup files to version control
- Consider encrypting backup files for production use

## Production Recommendations:

1. **Automated Backups**: Set up cron jobs for regular backups
2. **Off-site Storage**: Copy backups to remote storage (AWS S3, etc.)
3. **Retention Policy**: Keep daily backups for 30 days, weekly for 6 months
4. **Testing**: Regularly test restore procedures
5. **Monitoring**: Alert if backups fail or become too large/small