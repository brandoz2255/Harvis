# Development Database Setup Scripts

⚠️ **WARNING: These scripts are for DEVELOPMENT ONLY and will DESTROY data!**

## Files in this directory:

### `db_reset_dev_only.sql`
- **DESTRUCTIVE**: Drops all tables and data
- **Use case**: Reset development database to clean state
- **NEVER run in production**

## Usage:

### To reset development database:
```bash
# DANGER: This deletes all data!
docker exec -i pgsql-db psql -U pguser -d database < dev-setup/db_reset_dev_only.sql

# Then recreate tables:
docker exec -i pgsql-db psql -U pguser -d database < front_end/jfrontend/db_setup.sql
```

### Create a test user after reset:
```bash
# Use the signup endpoint to create test users
curl -X POST http://localhost:9000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","email":"test@example.com","password":"password123"}'
```

## Production Safety:

- **NEVER** run `db_reset_dev_only.sql` in production
- The main `db_setup.sql` is now safe (uses `IF NOT EXISTS`)
- Always backup production database before any schema changes
- Use proper database migrations for production updates