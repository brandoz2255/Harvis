"""
GitHub OAuth Authentication Router

Provides OAuth flow for GitHub integration with encrypted token storage.
Refactored for backend-centric flow with cookie-based state management.
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import os
import httpx
import secrets
import base64
import json
from typing import Optional
from cryptography.fernet import Fernet
import logging
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Use /api/vibecode/github prefix to match what's registered in GitHub OAuth App
router = APIRouter(prefix="/api/vibecode/github", tags=["github-oauth"])

# Environment variables
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
# Default to localhost:9000 as that's what the browser sees
OAUTH_REDIRECT_BASE = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:9000")
GITHUB_OAUTH_SCOPE = os.getenv("GITHUB_OAUTH_SCOPE", "repo")
FERNET_KEY = os.getenv("FERNET_KEY")

# Only include redirect_uri in authorize URL if explicitly enabled
# By default, GitHub uses the callback URL registered in the OAuth App
FORCE_REDIRECT_URI = os.getenv("GITHUB_FORCE_REDIRECT_URI", "false").lower() == "true"

# Constants
STATE_COOKIE = "gh_oauth_state"
STATE_MAX_AGE = 600  # 10 minutes
CALLBACK_PATH = "/api/vibecode/github/callback"
REDIRECT_URI = f"{OAUTH_REDIRECT_BASE}{CALLBACK_PATH}"

# Initialize Fernet cipher
if FERNET_KEY:
    try:
        cipher_suite = Fernet(FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY)
    except Exception as e:
        logger.error(f"❌ Failed to initialize Fernet cipher: {e}")
        cipher_suite = None
else:
    logger.warning("⚠️ FERNET_KEY not set - GitHub OAuth will not work")
    cipher_suite = None

def encrypt_token(token: str) -> str:
    """Encrypt a GitHub access token using Fernet encryption."""
    if not cipher_suite:
        raise HTTPException(status_code=500, detail="Encryption not configured")
    return cipher_suite.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a GitHub access token."""
    if not cipher_suite:
        raise HTTPException(status_code=500, detail="Encryption not configured")
    try:
        return cipher_suite.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        logger.error(f"❌ Token decryption failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to decrypt token")

def _mk_state(next_path: str = "/") -> str:
    """Create a secure state string containing a nonce and next path."""
    raw = {"nonce": secrets.token_urlsafe(16), "next": next_path}
    return base64.urlsafe_b64encode(json.dumps(raw).encode()).decode()

def _parse_state(state: str) -> Optional[dict]:
    """Parse and validate the state string."""
    try:
        j = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        if "nonce" not in j:
            return None
        return j
    except Exception:
        return None

class GitHubStatusResponse(BaseModel):
    connected: bool
    login: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None

class DisconnectResponse(BaseModel):
    ok: bool

class OAuthStartResponse(BaseModel):
    redirect: str

@router.get("/start", response_model=OAuthStartResponse)
async def github_oauth_start(request: Request):
    """
    Start GitHub OAuth flow by generating authorization URL.
    Returns JSON with redirect URL (frontend handles navigation).
    By default, omits redirect_uri to use the OAuth App's registered callback.
    Set GITHUB_FORCE_REDIRECT_URI=true to include redirect_uri explicitly.
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")
    
    # Generate CSRF state token
    state = _mk_state("/ide")  # Default redirect to IDE after OAuth
    
    # Build GitHub authorization URL parameters
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "scope": GITHUB_OAUTH_SCOPE,
        "state": state,
        "allow_signup": "true",
    }
    
    # Only include redirect_uri if explicitly enabled
    # When omitted, GitHub uses the callback URL registered in the OAuth App
    if FORCE_REDIRECT_URI:
        params["redirect_uri"] = REDIRECT_URI
        logger.info(f"🔐 Using explicit redirect_uri: {REDIRECT_URI}")
    else:
        logger.info(f"🔐 Omitting redirect_uri (using OAuth App's registered callback)")
    
    # Build authorize URL
    authorize_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    
    logger.info(f"🔐 GitHub OAuth started (state: {state[:16]}...)")
    
    return OAuthStartResponse(redirect=authorize_url)

@router.get("/login")
async def github_login(next: str = "/"):
    """
    Legacy endpoint - redirects to /start for backward compatibility.
    Start GitHub OAuth flow.
    Redirects user to GitHub authorization page.
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

    state = _mk_state(next)

    # IMPORTANT: Use the legacy redirect_uri to match GitHub OAuth App registration
    legacy_redirect_uri = f"{OAUTH_REDIRECT_BASE}/api/auth/vibecode/github/callback"

    # Build GitHub authorization URL parameters
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "scope": GITHUB_OAUTH_SCOPE,
        "state": state,
        "allow_signup": "true",
        "redirect_uri": legacy_redirect_uri,  # Always include for legacy endpoint
    }

    url = "https://github.com/login/oauth/authorize?" + urlencode(params)

    logger.info(f"🔐 Starting GitHub OAuth redirect to: {url}")
    logger.info(f"🔐 Using redirect_uri: {legacy_redirect_uri}")

    resp = RedirectResponse(url)
    # Set httpOnly cookie for state validation (CSRF protection)
    resp.set_cookie(
        key=STATE_COOKIE,
        value=state,
        max_age=STATE_MAX_AGE,
        httponly=True,
        secure=False, # Set to True if using HTTPS
        path="/"
    )
    return resp

@router.get("/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None
):
    """
    Handle GitHub OAuth callback.
    Exchanges code for token, encrypts it, and stores it in DB.
    """
    return await _handle_github_callback(request, code, state)

# Also register at /api/auth/vibecode/github/callback for backward compatibility
# (in case GitHub OAuth App has the wrong callback URL registered)
auth_router = APIRouter(prefix="/api/auth/vibecode/github", tags=["github-oauth"])

@auth_router.get("/callback")
async def github_callback_legacy(
    request: Request,
    code: str | None = None,
    state: str | None = None
):
    """
    Legacy callback endpoint for GitHub OAuth.
    Handles callbacks from OAuth Apps registered with /api/auth/vibecode/github/callback.
    """
    # Use the legacy redirect_uri for token exchange to match what GitHub sent
    legacy_redirect_uri = f"{OAUTH_REDIRECT_BASE}/api/auth/vibecode/github/callback"
    return await _handle_github_callback(request, code, state, legacy_redirect_uri)

async def _handle_github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    redirect_uri_override: str | None = None
):
    """
    Handle GitHub OAuth callback.
    Exchanges code for token, encrypts it, and stores it in DB.
    
    Args:
        redirect_uri_override: Use this redirect_uri for token exchange if provided
                              (to match what GitHub actually sent)
    """
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")
    
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # Validate state against cookie
    cookie_state = request.cookies.get(STATE_COOKIE)
    if not cookie_state or cookie_state != state:
        logger.warning("❌ Invalid state cookie in OAuth callback")
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Parse state to get next path
    st = _parse_state(state)
    next_path = st.get("next", "/ide") if st else "/ide"
    
    # Use override if provided, otherwise use default
    token_exchange_redirect_uri = redirect_uri_override or REDIRECT_URI
    
    # Exchange code for access token
    # Always include redirect_uri in token exchange (required by GitHub)
    # Must match exactly what GitHub sent in the callback
    async with httpx.AsyncClient(headers={"Accept": "application/json"}) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": token_exchange_redirect_uri,  # Must match callback URL
            },
            timeout=20.0,
        )
    
    if token_resp.status_code != 200:
        logger.error(f"❌ GitHub token exchange failed: {token_resp.status_code}")
        raise HTTPException(status_code=401, detail="Token exchange failed")
        
    data = token_resp.json()
    access_token = data.get("access_token")
    if not access_token:
        logger.error(f"❌ No access token in response: {data}")
        raise HTTPException(status_code=401, detail="Failed to obtain access token")

    # Encrypt token
    encrypted_token = encrypt_token(access_token)
    
    # Get user ID from JWT
    from jose import jwt
    SECRET_KEY = os.getenv("JWT_SECRET", "key")
    ALGORITHM = "HS256"
    
    token = request.cookies.get("access_token")
    if not token:
        # If no session, we can't store the token associated with a user
        # In a real app, we might want to handle login here, but for now we require existing session
        logger.error("❌ No VibeCode session found during callback")
        return RedirectResponse(url=f"{OAUTH_REDIRECT_BASE}?error=no_session")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception as e:
        logger.error(f"❌ Failed to decode JWT: {e}")
        return RedirectResponse(url=f"{OAUTH_REDIRECT_BASE}?error=invalid_session")

    # Store in database
    pool = getattr(request.app.state, 'pg_pool', None)
    if not pool:
        logger.error("❌ Database pool not available")
        return RedirectResponse(url=f"{OAUTH_REDIRECT_BASE}?error=db_error")
    
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO github_tokens (user_id, access_token)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET access_token = $2, created_at = NOW()
            """,
            user_id,
            encrypted_token
        )
    
    logger.info(f"✅ GitHub token stored for user {user_id}")
    
    # Redirect back to app
    # Append a query param so frontend knows to refresh status
    separator = "&" if "?" in next_path else "?"
    final_redirect = f"{next_path}{separator}github_connected=true"
    
    resp = RedirectResponse(url=final_redirect)
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp

@router.get("/status", response_model=GitHubStatusResponse)
async def github_status(request: Request):
    """
    Check if user has connected GitHub account and return user info.
    Requires authentication via JWT cookie.
    """
    # Extract user ID from JWT token
    from jose import jwt
    SECRET_KEY = os.getenv("JWT_SECRET", "key")
    ALGORITHM = "HS256"
    
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    pool = getattr(request.app.state, 'pg_pool', None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")
    
    # Check if token exists
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT access_token FROM github_tokens WHERE user_id = $1",
            user_id
        )
    
    if not row:
        return GitHubStatusResponse(connected=False)
    
    # Decrypt token and fetch user info from GitHub
    try:
        access_token = decrypt_token(row['access_token'])
    except Exception:
        return GitHubStatusResponse(connected=False)
    
    # Fetch GitHub user info
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json"
            },
            timeout=10.0
        )
    
    if response.status_code != 200:
        return GitHubStatusResponse(connected=False)
    
    user_data = response.json()
    return GitHubStatusResponse(
        connected=True,
        login=user_data.get("login"),
        name=user_data.get("name"),
        avatar_url=user_data.get("avatar_url")
    )

@router.post("/disconnect", response_model=DisconnectResponse)
async def github_disconnect(request: Request):
    """
    Disconnect GitHub account by deleting stored token.
    Requires authentication via JWT cookie.
    """
    # Extract user ID from JWT token
    from jose import jwt
    SECRET_KEY = os.getenv("JWT_SECRET", "key")
    ALGORITHM = "HS256"
    
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    pool = getattr(request.app.state, 'pg_pool', None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")
    
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM github_tokens WHERE user_id = $1",
            user_id
        )
    
    logger.info(f"✅ GitHub disconnected for user {user_id}")
    return DisconnectResponse(ok=True)
