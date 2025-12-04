# GitHub OAuth Setup Guide

This guide explains how to set up GitHub OAuth integration for the VibeCode IDE.

## Prerequisites

1. A GitHub account
2. A GitHub OAuth App created at https://github.com/settings/developers

## Step 1: Create GitHub OAuth App

1. Go to https://github.com/settings/developers
2. Click "New OAuth App"
3. Fill in the form:
   - **Application name**: VibeCode IDE (or your preferred name)
   - **Homepage URL**: `http://localhost:9000`
   - **Authorization callback URL**: `http://localhost:9000/api/vibecode/github/callback`
4. Click "Register application"
5. Copy the **Client ID** and generate a **Client Secret**

## Step 2: Configure Environment Variables

Add the following to your `python_back_end/.env` file:

```bash
# GitHub OAuth Configuration
GITHUB_CLIENT_ID=Ov23lixCUt5rv6HNxDPa
GITHUB_CLIENT_SECRET=<NEW_GENERATED_SECRET>  # ⚠️ Rotate this - old one was exposed
OAUTH_REDIRECT_BASE=http://localhost:9000
GITHUB_OAUTH_SCOPE=repo

# By default, redirect_uri is omitted from authorize URL (uses OAuth App's registered callback)
# Set to "true" to explicitly include redirect_uri in authorize URL
# Only enable if you need to override the OAuth App's callback URL
GITHUB_FORCE_REDIRECT_URI=false

# Generate a Fernet key for token encryption
# Run: python3 python_back_end/generate_fernet_key.py
FERNET_KEY=<generated-key-here>
```

### Important: Rotate Your Client Secret

Since the client secret was exposed, you must:
1. Go to your GitHub OAuth App settings
2. Click "Generate a new client secret"
3. Update `GITHUB_CLIENT_SECRET` in your `.env` file
4. Restart the backend

### Generate FERNET_KEY

Run the helper script to generate a secure encryption key:

```bash
cd python_back_end
python3 generate_fernet_key.py
```

Copy the generated key and add it to your `.env` file.

## Step 3: Run Database Migration

The `github_tokens` table needs to be created. Run the migration:

```bash
# Option 1: Using the migration runner script
docker exec -it backend python run_migrations.py

# Option 2: Direct SQL execution
docker exec -i pgsql-db psql -U pguser -d database < python_back_end/migrations/004_create_github_tokens.sql
```

## Step 4: Restart Services

After updating environment variables, restart the backend:

```bash
docker compose restart backend
```

## Step 5: Verify Setup

1. Start your development server
2. Navigate to the IDE page (`http://localhost:9000/ide`)
3. Look for the "Connect GitHub" button in the header
4. Click it and complete the OAuth flow
5. After authorization, you should see your GitHub username and avatar in the header

## Testing

### Test OAuth Flow

```bash
# Check if OAuth start endpoint works (returns JSON with redirect URL)
curl -s http://localhost:9000/api/vibecode/github/start \
  -H "Cookie: access_token=<your-jwt-token>"
# Expected: {"redirect":"https://github.com/login/oauth/authorize?client_id=...&scope=repo&state=...&allow_signup=true"}
# NOTE: No redirect_uri present unless GITHUB_FORCE_REDIRECT_URI=true

# Verify callback route is reachable
curl -i http://localhost:9000/api/vibecode/github/callback
# Expected: 405 Method Not Allowed or 400 Bad Request (proves route exists)

# Check GitHub connection status
curl -s http://localhost:9000/api/vibecode/github/status \
  -H "Cookie: access_token=<your-jwt-token>"
```

### Test Repository Import

```bash
curl -X POST http://localhost:9000/api/vibecode/repo/import \
  -H "Content-Type: application/json" \
  -H "Cookie: access_token=<your-jwt-token>" \
  -d '{
    "session_id": "<your-session-id>",
    "url": "https://github.com/octocat/Hello-World",
    "branch": "main"
  }'
```

## Features

### GitHub Status Widget

- Located in the IDE header (top right)
- Shows "Connect GitHub" button when not connected
- Shows GitHub username, avatar, and "Sign out" button when connected

### Import Repository Button

- Located in the file explorer toolbar (next to refresh button)
- Opens a modal to import a GitHub repository
- Fields:
  - Repository URL (required)
  - Branch (default: main)
  - Folder Name (optional - defaults to repository name)
- Automatically refreshes the file explorer after successful import

## Security Notes

- **Never commit** `GITHUB_CLIENT_SECRET` or `FERNET_KEY` to version control
- Tokens are encrypted using Fernet before storage
- All API endpoints require JWT authentication
- Tokens are never logged or exposed in error messages

## Troubleshooting

### "GitHub OAuth not configured"

- Check that `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are set in `.env`
- Restart the backend container after updating `.env`

### "Encryption not configured"

- Check that `FERNET_KEY` is set in `.env`
- Generate a new key using `generate_fernet_key.py` if needed
- Restart the backend container

### "Database not available"

- Ensure PostgreSQL container is running: `docker ps | grep pgsql-db`
- Check database connection in backend logs

### "Invalid state parameter"

- This is a CSRF protection error
- Clear browser cookies and try again
- Ensure you're using the same browser session

### "The redirect_uri is not associated with this application"

- **Root cause**: Mismatch between OAuth App's callback URL and what's sent in authorize request
- **Fix**: 
  1. Verify OAuth App callback URL is exactly: `http://localhost:9000/api/vibecode/github/callback`
  2. Set `GITHUB_FORCE_REDIRECT_URI=false` (default) to omit redirect_uri from authorize URL
  3. GitHub will use the OAuth App's registered callback automatically
  4. If you must include redirect_uri, ensure it matches EXACTLY (no trailing slash, same scheme/host/port)

### Repository import fails

- Verify GitHub connection status first
- Check that the repository URL is correct
- Ensure the branch exists
- Check container logs for detailed error messages

## Production Deployment

For production:

1. Update `OAUTH_REDIRECT_BASE` to your production URL
2. Update GitHub OAuth App callback URL to match
3. Use secure, randomly generated secrets
4. Enable HTTPS
5. Consider using Redis for OAuth state storage (currently in-memory)

## Files Modified

### Backend
- `python_back_end/vibecoding/auth_github.py` - OAuth endpoints
- `python_back_end/vibecoding/repo_import.py` - Repository import endpoint
- `python_back_end/migrations/004_create_github_tokens.sql` - Database schema
- `python_back_end/main.py` - Router registration (already done)

### Frontend
- `front_end/jfrontend/components/GitHubStatus.tsx` - Status widget
- `front_end/jfrontend/components/ImportRepoButton.tsx` - Import button
- `front_end/jfrontend/app/ide/page.tsx` - Header integration
- `front_end/jfrontend/components/MonacoVibeFileTree.tsx` - Explorer toolbar integration

