"""
GitHub Repository Import Router

Provides endpoints to list and clone GitHub repositories into session workspaces.
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, validator
import os
import re
import asyncio
import logging
import httpx
from typing import Optional, List

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibecode/repo", tags=["repo-import"])

class RepoImportRequest(BaseModel):
    session_id: str
    url: str
    branch: str = "main"
    dest: str = "/workspace"
    subdir: Optional[str] = None
    
    @validator('url')
    def validate_github_url(cls, v):
        """Validate that URL is a GitHub repository URL."""
        pattern = r'^https://github\.com/[\w-]+/[\w.-]+(\.git)?$'
        if not re.match(pattern, v):
            raise ValueError("URL must be a valid GitHub repository URL (https://github.com/owner/repo)")
        return v

class RepoImportResponse(BaseModel):
    ok: bool
    dest: str
    log: str

class Repository(BaseModel):
    id: int
    name: str
    full_name: str
    description: Optional[str]
    html_url: str
    clone_url: str
    default_branch: str
    private: bool
    updated_at: str
    language: Optional[str]
    stargazers_count: int

class RepoListResponse(BaseModel):
    repos: List[Repository]

@router.post("/import", response_model=RepoImportResponse)
async def import_repository(
    request_data: RepoImportRequest,
    request: Request
):
    """
    Clone a GitHub repository into the session's workspace.
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

    # Get GitHub token
    pool = getattr(request.app.state, 'pg_pool', None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT access_token FROM github_tokens WHERE user_id = $1",
            user_id
        )

    if not row:
        raise HTTPException(
            status_code=401,
            detail="GitHub not connected. Please connect your GitHub account first."
        )

    # Decrypt token
    from .auth_github import decrypt_token
    try:
        access_token = decrypt_token(row['access_token'])
    except Exception as e:
        logger.error(f"❌ Failed to decrypt token: {e}")
        raise HTTPException(status_code=500, detail="Failed to decrypt GitHub token")

    # Get container manager
    from .containers import container_manager

    # Determine clone destination
    repo_name = request_data.url.rstrip('/').rstrip('.git').split('/')[-1]
    if request_data.subdir:
        clone_dest = f"{request_data.dest}/{request_data.subdir}"
    else:
        clone_dest = f"{request_data.dest}/{repo_name}"

    # Get container for this session
    try:
        container = await container_manager.get_runner_container(request_data.session_id)
        if not container:
            container = await container_manager.get_container(request_data.session_id)
        if not container:
            raise HTTPException(status_code=404, detail="Session container not found")
    except Exception as e:
        logger.error(f"❌ Failed to get container: {e}")
        raise HTTPException(status_code=404, detail="Session container not found")

    # Check if destination already exists
    logger.info(f"🔍 Checking if {clone_dest} exists")
    check_result = container.exec_run(f"test -d {clone_dest}")
    if check_result.exit_code == 0:
        raise HTTPException(
            status_code=400,
            detail=f"Destination folder already exists: {clone_dest}"
        )

    # Pre-flight: Verify GitHub token is valid
    logger.info(f"🔍 Validating GitHub token")
    async with httpx.AsyncClient() as client:
        try:
            probe = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json"
                },
                timeout=5.0
            )
            if probe.status_code == 401:
                logger.error(f"❌ GitHub token is invalid or expired")
                raise HTTPException(
                    status_code=401,
                    detail="GitHub token invalid or expired. Please reconnect your GitHub account."
                )
            if probe.status_code == 403:
                logger.error(f"❌ GitHub token lacks required scope")
                raise HTTPException(
                    status_code=403,
                    detail="GitHub token lacks 'repo' scope for private repositories."
                )
            logger.info(f"✅ GitHub token is valid")
        except httpx.TimeoutException:
            logger.warning(f"⚠️ GitHub API timeout during token validation, continuing anyway")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"⚠️ Token validation failed: {e}, continuing anyway")

    # Ensure git is installed in the container
    logger.info(f"🔧 Checking if git is installed in container")
    git_check = container.exec_run("which git")
    if git_check.exit_code != 0:
        logger.info(f"📦 Installing git in container...")
        # Install git using apt-get (assuming Debian/Ubuntu based image)
        install_result = container.exec_run(
            "sh -c 'apt-get update -qq && apt-get install -y -qq git'",
            workdir="/workspace"
        )
        if install_result.exit_code != 0:
            logger.error(f"❌ Failed to install git in container")
            raise HTTPException(
                status_code=500,
                detail="Failed to install git in container"
            )
        logger.info(f"✅ Git installed successfully")

    # Build git clone command with proper authorization headers
    # CRITICAL: Use correct capitalization and configure BOTH domains
    # - Authorization: Bearer (not AUTHORIZATION: bearer)
    # - Configure both github.com and codeload.github.com (for redirects)
    auth_header = f"Authorization: Bearer {access_token}"

    git_clone_cmd = (
        f'git -c http.https://github.com/.extraheader="{auth_header}" '
        f'-c http.https://codeload.github.com/.extraheader="{auth_header}" '
        f'clone --depth 1 -b {request_data.branch} {request_data.url} {clone_dest}'
    )

    logger.info(f"🔄 Cloning repo into container {container.name}:{clone_dest}")

    try:
        # Execute git clone with timeout
        import time
        start_time = time.time()

        result = container.exec_run(
            git_clone_cmd,
            workdir="/workspace",
            demux=True
        )

        execution_time = int((time.time() - start_time) * 1000)

        # Decode output
        stdout_bytes, stderr_bytes = result.output
        stdout_str = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        combined_log = f"{stdout_str}\n{stderr_str}".strip()

        # Limit log to last 4000 characters
        if len(combined_log) > 4000:
            combined_log = "...\n" + combined_log[-4000:]

        if result.exit_code != 0:
            # Check if it's an auth error that might work for public repos
            if "could not read Username for 'https://github.com'" in combined_log:
                logger.info(f"🔄 Auth failed, retrying as public repository")
                # Retry without auth for public repos
                retry_cmd = f'git clone --depth 1 -b {request_data.branch} {request_data.url} {clone_dest}'
                retry_result = container.exec_run(retry_cmd, workdir="/workspace", demux=True)

                if retry_result.exit_code == 0:
                    logger.info(f"✅ Successfully cloned public repo")
                    return RepoImportResponse(
                        ok=True,
                        dest=clone_dest,
                        log="Successfully cloned public repository"
                    )

            # Remove any token from error log
            safe_log = combined_log.replace(access_token, "***TOKEN***")
            logger.error(f"❌ Git clone failed (exit {result.exit_code}): {safe_log}")

            # Provide helpful error messages
            if "Repository not found" in combined_log or "not found" in combined_log.lower():
                raise HTTPException(
                    status_code=404,
                    detail="Repository not found or no access. Check URL/branch or permissions."
                )
            elif "could not read Username" in combined_log:
                raise HTTPException(
                    status_code=401,
                    detail="Repository is private and credentials are missing. Reconnect GitHub."
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to clone repository. Check if URL and branch are correct."
                )

        logger.info(f"✅ Successfully cloned repo to {clone_dest} in {execution_time}ms")

        # Remove token from success log too
        safe_log = combined_log.replace(access_token, "***TOKEN***")

        return RepoImportResponse(
            ok=True,
            dest=clone_dest,
            log=safe_log
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error during clone: {e}")
        raise HTTPException(status_code=500, detail="Failed to clone repository")

@router.get("/list", response_model=RepoListResponse)
async def list_repositories(
    request: Request,
    page: int = 1,
    per_page: int = 30
):
    """
    List user's GitHub repositories.
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

    # Get GitHub token
    pool = getattr(request.app.state, 'pg_pool', None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT access_token FROM github_tokens WHERE user_id = $1",
            user_id
        )

    if not row:
        raise HTTPException(
            status_code=401,
            detail="GitHub not connected. Please connect your GitHub account first."
        )

    # Decrypt token
    from .auth_github import decrypt_token
    try:
        access_token = decrypt_token(row['access_token'])
    except Exception as e:
        logger.error(f"❌ Failed to decrypt token: {e}")
        raise HTTPException(status_code=500, detail="Failed to decrypt GitHub token")

    # Fetch repositories from GitHub API
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://api.github.com/user/repos",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json"
                },
                params={
                    "per_page": per_page,
                    "page": page,
                    "sort": "updated",
                    "affiliation": "owner,collaborator"
                },
                timeout=10.0
            )

            if response.status_code != 200:
                logger.error(f"❌ GitHub API error: {response.status_code}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Failed to fetch repositories from GitHub"
                )

            repos_data = response.json()

            # Transform to our model
            repos = []
            for repo in repos_data:
                repos.append(Repository(
                    id=repo['id'],
                    name=repo['name'],
                    full_name=repo['full_name'],
                    description=repo.get('description'),
                    html_url=repo['html_url'],
                    clone_url=repo['clone_url'],
                    default_branch=repo['default_branch'],
                    private=repo['private'],
                    updated_at=repo['updated_at'],
                    language=repo.get('language'),
                    stargazers_count=repo['stargazers_count']
                ))

            logger.info(f"✅ Listed {len(repos)} repositories for user {user_id}")
            return RepoListResponse(repos=repos)

        except httpx.TimeoutException:
            logger.error("❌ GitHub API timeout")
            raise HTTPException(status_code=504, detail="GitHub API timeout")
        except Exception as e:
            logger.error(f"❌ Error fetching repos: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch repositories")
