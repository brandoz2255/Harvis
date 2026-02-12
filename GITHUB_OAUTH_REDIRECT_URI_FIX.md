# GitHub OAuth redirect_uri Mismatch Fix

## Problem

GitHub OAuth was failing with "The redirect_uri is not associated with this application" because the `redirect_uri` parameter in the authorize URL didn't match exactly what was registered in the GitHub OAuth App.

## Solution

Updated the backend to **omit `redirect_uri` by default** from the authorize URL. When omitted, GitHub automatically uses the callback URL registered in the OAuth App, eliminating mismatch errors.

### Changes Made

1. **Added `/start` endpoint** that returns JSON with redirect URL (frontend handles navigation)
2. **Made `redirect_uri` optional** - only included if `GITHUB_FORCE_REDIRECT_URI=true`
3. **Updated `/login` endpoint** to also respect the `FORCE_REDIRECT_URI` setting
4. **Added environment variable** `GITHUB_FORCE_REDIRECT_URI` (default: `false`)

### Configuration

**Default behavior (recommended):**
```bash
GITHUB_FORCE_REDIRECT_URI=false  # Omit redirect_uri, use OAuth App's registered callback
```

**Explicit redirect_uri (only if needed):**
```bash
GITHUB_FORCE_REDIRECT_URI=true   # Include redirect_uri in authorize URL
```

When `FORCE_REDIRECT_URI=true`, ensure:
- OAuth App callback URL = `http://localhost:9000/api/vibecode/github/callback`
- Backend `REDIRECT_URI` = `http://localhost:9000/api/vibecode/github/callback`
- **EXACT match** (no trailing slash, same scheme/host/port)

### OAuth App Settings

1. Go to https://github.com/settings/developers
2. Select your OAuth App
3. Set **Authorization callback URL** to exactly:
   ```
   http://localhost:9000/api/vibecode/github/callback
   ```
4. **No trailing slash**, use `http://` (not `https://`) for localhost

### Testing

```bash
# Test /start endpoint (should NOT include redirect_uri by default)
curl -s http://localhost:9000/api/vibecode/github/start \
  -H "Cookie: access_token=<token>"
# Expected: {"redirect":"https://github.com/login/oauth/authorize?client_id=...&scope=repo&state=...&allow_signup=true"}

# Verify callback route exists
curl -i http://localhost:9000/api/vibecode/github/callback
# Expected: 405 or 400 (proves route is reachable)
```

### Files Modified

- `python_back_end/vibecoding/auth_github.py`:
  - Added `FORCE_REDIRECT_URI` environment variable check
  - Added `/start` endpoint with optional `redirect_uri`
  - Updated `/login` endpoint to respect `FORCE_REDIRECT_URI`
  - Improved logging for debugging

### Security Note

⚠️ **Rotate your GitHub Client Secret** - the old one was exposed publicly. Generate a new one in your OAuth App settings and update `GITHUB_CLIENT_SECRET` in your `.env` file.

## Status

✅ Fixed - OAuth flow now works reliably without redirect_uri mismatches

