"""
Workspace Repo Manager — GitHub repo clone/sync/push for OpenClaw workspace.

Security: GitHub tokens NEVER enter the OpenClaw container. All authenticated
git operations happen in this backend module. OpenClaw only reads/writes files
on the shared volume.

Endpoints:
  POST /api/workspace/clone-repo    — Clone a GitHub repo into the shared volume
  POST /api/workspace/sync-repo     — Pull latest changes for a cloned repo
  POST /api/workspace/push-changes  — Commit + push changes back to GitHub
  GET  /api/workspace/repos         — List repos cloned into the workspace
  GET  /api/workspace/user-repos    — List user's GitHub repos (for picker UI)
  DELETE /api/workspace/repos/{id}  — Remove a cloned repo
"""

import asyncio
import logging
import os
import shutil
import subprocess
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized

logger = logging.getLogger(__name__)

repo_manager_router = APIRouter(prefix="/api/workspace", tags=["workspace-repos"])

# Path inside the backend container where the shared volume is mounted
PROJECTS_DIR = os.getenv("OPENCLAW_PROJECTS_DIR", "/data/openclaw-projects")

# Corresponding path inside the OpenClaw container (for display / agent instructions)
OPENCLAW_PROJECTS_PATH = "/home/node/projects"


# ── Pydantic Models ──────────────────────────────────────────────────────────

class CloneRepoRequest(BaseModel):
    owner: str
    repo: str
    branch: str = "main"

class SyncRepoRequest(BaseModel):
    owner: str
    repo: str

class PushChangesRequest(BaseModel):
    owner: str
    repo: str
    branch: str
    commit_message: str
    create_pr: bool = False
    pr_title: Optional[str] = None
    pr_body: Optional[str] = None

class RepoInfo(BaseModel):
    id: Optional[int] = None
    owner: str
    repo: str
    branch: str
    local_path: str
    openclaw_path: str
    last_synced: Optional[str] = None

class RepoListResponse(BaseModel):
    repos: list[RepoInfo]

class GitHubRepoItem(BaseModel):
    full_name: str
    owner: str
    name: str
    default_branch: str
    private: bool
    description: Optional[str] = None
    html_url: str


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_github_token(pool, user_id: int) -> str:
    """Fetch and decrypt the user's GitHub OAuth token from the DB."""
    from vibecoding.auth_github import decrypt_token

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT access_token FROM github_tokens WHERE user_id = $1",
            user_id,
        )
    if not row:
        raise HTTPException(status_code=400, detail="GitHub not connected. Please connect your GitHub account first.")

    return decrypt_token(row["access_token"])


def _user_id(user) -> int:
    if isinstance(user, dict):
        return int(user.get("id") or user.get("user_id"))
    return int(getattr(user, "id"))


async def _ensure_workspace_repos_table(pool):
    """Create workspace_repos table if it doesn't exist (idempotent)."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_repos (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                owner VARCHAR(255) NOT NULL,
                repo VARCHAR(255) NOT NULL,
                branch VARCHAR(255) DEFAULT 'main',
                local_path VARCHAR(500) NOT NULL,
                last_synced TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, owner, repo)
            );
        """)


def _repo_dir(owner: str, repo: str) -> str:
    """Return the absolute path on the backend's filesystem for a repo."""
    # Sanitize to prevent path traversal
    safe_owner = owner.replace("/", "").replace("..", "")
    safe_repo = repo.replace("/", "").replace("..", "")
    return os.path.join(PROJECTS_DIR, safe_owner, safe_repo)


def _openclaw_repo_path(owner: str, repo: str) -> str:
    """Return the path as seen from inside the OpenClaw container."""
    return f"{OPENCLAW_PROJECTS_PATH}/{owner}/{repo}"


async def _run_git(cmd: list[str], cwd: str, env: Optional[dict] = None) -> tuple[int, str, str]:
    """Run a git command async and return (returncode, stdout, stderr)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    # Prevent interactive prompts
    full_env["GIT_TERMINAL_PROMPT"] = "0"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=full_env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


# ── Endpoints ────────────────────────────────────────────────────────────────

@repo_manager_router.post("/clone-repo", response_model=RepoInfo)
async def clone_repo(req: CloneRepoRequest, request: Request, user=Depends(get_current_user_optimized)):
    """Clone a GitHub repo into the OpenClaw shared workspace volume."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    await _ensure_workspace_repos_table(pool)

    # Get user's GitHub token (never sent to OpenClaw)
    uid = _user_id(user)
    gh_token = await _get_github_token(pool, uid)

    repo_path = _repo_dir(req.owner, req.repo)

    # Check if already cloned
    if os.path.isdir(os.path.join(repo_path, ".git")):
        # Already exists — just pull
        logger.info("Repo %s/%s already cloned, pulling latest", req.owner, req.repo)
        clone_url = f"https://x-access-token:{gh_token}@github.com/{req.owner}/{req.repo}.git"
        rc, out, err = await _run_git(
            ["git", "remote", "set-url", "origin", clone_url], cwd=repo_path
        )
        rc, out, err = await _run_git(
            ["git", "pull", "origin", req.branch], cwd=repo_path
        )
        if rc != 0:
            logger.warning("git pull failed: %s", err[:500])
    else:
        # Fresh clone
        os.makedirs(os.path.dirname(repo_path), exist_ok=True)
        clone_url = f"https://x-access-token:{gh_token}@github.com/{req.owner}/{req.repo}.git"

        logger.info("Cloning %s/%s branch=%s into %s", req.owner, req.repo, req.branch, repo_path)
        rc, out, err = await _run_git(
            ["git", "clone", "--branch", req.branch, "--single-branch", "--depth", "50", clone_url, repo_path],
            cwd=PROJECTS_DIR,
        )
        if rc != 0:
            logger.error("git clone failed: %s", err[:500])
            raise HTTPException(status_code=500, detail=f"Clone failed: {err[:200]}")

    # Clear the token from the remote URL after clone (security)
    safe_url = f"https://github.com/{req.owner}/{req.repo}.git"
    await _run_git(["git", "remote", "set-url", "origin", safe_url], cwd=repo_path)

    # Configure git user for commits
    await _run_git(["git", "config", "user.name", "HarvisAI"], cwd=repo_path)
    await _run_git(["git", "config", "user.email", "harvis@ai.local"], cwd=repo_path)

    # Store in DB
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO workspace_repos (user_id, owner, repo, branch, local_path, last_synced)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (user_id, owner, repo)
            DO UPDATE SET branch = $4, last_synced = NOW()
            RETURNING id, last_synced
        """, uid, req.owner, req.repo, req.branch, repo_path)

    return RepoInfo(
        id=row["id"],
        owner=req.owner,
        repo=req.repo,
        branch=req.branch,
        local_path=repo_path,
        openclaw_path=_openclaw_repo_path(req.owner, req.repo),
        last_synced=str(row["last_synced"]),
    )


@repo_manager_router.post("/sync-repo", response_model=RepoInfo)
async def sync_repo(req: SyncRepoRequest, request: Request, user=Depends(get_current_user_optimized)):
    uid = _user_id(user)
    """Pull latest changes for an already-cloned repo."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    await _ensure_workspace_repos_table(pool)

    # Look up the repo
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, branch, local_path FROM workspace_repos WHERE user_id = $1 AND owner = $2 AND repo = $3",
            uid, req.owner, req.repo,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Repo not found in workspace")

    repo_path = row["local_path"]
    branch = row["branch"]

    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise HTTPException(status_code=404, detail="Repo directory missing — try cloning again")

    # Temporarily set authenticated remote
    gh_token = await _get_github_token(pool, uid)
    clone_url = f"https://x-access-token:{gh_token}@github.com/{req.owner}/{req.repo}.git"
    await _run_git(["git", "remote", "set-url", "origin", clone_url], cwd=repo_path)

    rc, out, err = await _run_git(["git", "pull", "origin", branch], cwd=repo_path)

    # Remove token from remote URL
    safe_url = f"https://github.com/{req.owner}/{req.repo}.git"
    await _run_git(["git", "remote", "set-url", "origin", safe_url], cwd=repo_path)

    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Pull failed: {err[:200]}")

    # Update last_synced
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE workspace_repos SET last_synced = NOW() WHERE id = $1", row["id"]
        )

    return RepoInfo(
        id=row["id"],
        owner=req.owner,
        repo=req.repo,
        branch=branch,
        local_path=repo_path,
        openclaw_path=_openclaw_repo_path(req.owner, req.repo),
        last_synced=str(datetime.utcnow()),
    )


@repo_manager_router.post("/push-changes")
async def push_changes(req: PushChangesRequest, request: Request, user=Depends(get_current_user_optimized)):
    uid = _user_id(user)
    """Commit and push changes OpenClaw made back to GitHub."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    # Look up the repo
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT local_path FROM workspace_repos WHERE user_id = $1 AND owner = $2 AND repo = $3",
            uid, req.owner, req.repo,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Repo not found in workspace")

    repo_path = row["local_path"]
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise HTTPException(status_code=404, detail="Repo directory missing")

    gh_token = await _get_github_token(pool, uid)

    # Safety: never push to main/master
    if req.branch in ("main", "master"):
        raise HTTPException(status_code=400, detail="Cannot push to main/master. Use a feature branch.")

    # Create and checkout branch
    await _run_git(["git", "checkout", "-B", req.branch], cwd=repo_path)

    # Stage all changes
    await _run_git(["git", "add", "-A"], cwd=repo_path)

    # Check if there are changes to commit
    rc, out, _ = await _run_git(["git", "diff", "--cached", "--quiet"], cwd=repo_path)
    if rc == 0:
        return {"status": "no_changes", "message": "No changes to commit"}

    # Commit
    rc, out, err = await _run_git(
        ["git", "commit", "-m", req.commit_message], cwd=repo_path
    )
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Commit failed: {err[:200]}")

    # Set authenticated remote, push, then clear
    clone_url = f"https://x-access-token:{gh_token}@github.com/{req.owner}/{req.repo}.git"
    await _run_git(["git", "remote", "set-url", "origin", clone_url], cwd=repo_path)
    rc, out, err = await _run_git(
        ["git", "push", "-u", "origin", req.branch], cwd=repo_path
    )
    safe_url = f"https://github.com/{req.owner}/{req.repo}.git"
    await _run_git(["git", "remote", "set-url", "origin", safe_url], cwd=repo_path)

    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Push failed: {err[:200]}")

    result = {"status": "pushed", "branch": req.branch}

    # Optionally create a PR
    if req.create_pr:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"https://api.github.com/repos/{req.owner}/{req.repo}/pulls",
                    headers={
                        "Authorization": f"Bearer {gh_token}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                    json={
                        "title": req.pr_title or req.commit_message,
                        "body": req.pr_body or f"Changes made by Harvis AI workspace.",
                        "head": req.branch,
                        "base": "main",
                    },
                )
            if resp.status_code in (200, 201):
                pr_data = resp.json()
                result["pr_url"] = pr_data.get("html_url", "")
                result["pr_number"] = pr_data.get("number")
            else:
                result["pr_error"] = f"PR creation failed: {resp.status_code}"
        except Exception as e:
            result["pr_error"] = str(e)

    return result


@repo_manager_router.get("/repos", response_model=RepoListResponse)
async def list_repos(request: Request, user=Depends(get_current_user_optimized)):
    uid = _user_id(user)
    """List repos the user has cloned into the workspace."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    await _ensure_workspace_repos_table(pool)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, owner, repo, branch, local_path, last_synced FROM workspace_repos WHERE user_id = $1 ORDER BY last_synced DESC",
            uid,
        )

    repos = []
    for r in rows:
        repos.append(RepoInfo(
            id=r["id"],
            owner=r["owner"],
            repo=r["repo"],
            branch=r["branch"],
            local_path=r["local_path"],
            openclaw_path=_openclaw_repo_path(r["owner"], r["repo"]),
            last_synced=str(r["last_synced"]) if r["last_synced"] else None,
        ))

    return RepoListResponse(repos=repos)


@repo_manager_router.get("/user-repos")
async def list_user_github_repos(request: Request, user=Depends(get_current_user_optimized)):
    """List the user's GitHub repos (for the repo picker UI)."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    uid = _user_id(user)
    gh_token = await _get_github_token(pool, uid)

    repos = []
    page = 1
    while page <= 5:  # Cap at 5 pages (500 repos)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.github.com/user/repos?per_page=100&page={page}&sort=updated",
                headers={
                    "Authorization": f"Bearer {gh_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
        if resp.status_code != 200:
            break

        batch = resp.json()
        if not batch:
            break

        for r in batch:
            repos.append(GitHubRepoItem(
                full_name=r["full_name"],
                owner=r["owner"]["login"],
                name=r["name"],
                default_branch=r.get("default_branch", "main"),
                private=r.get("private", False),
                description=r.get("description"),
                html_url=r.get("html_url", ""),
            ))
        page += 1

    return {"repos": [r.model_dump() for r in repos]}


@repo_manager_router.delete("/repos/{repo_id}")
async def delete_repo(repo_id: int, request: Request, user=Depends(get_current_user_optimized)):
    uid = _user_id(user)
    """Remove a cloned repo from the workspace."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT local_path FROM workspace_repos WHERE id = $1 AND user_id = $2",
            repo_id, uid,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Repo not found")

    # Remove from filesystem
    repo_path = row["local_path"]
    if os.path.isdir(repo_path):
        shutil.rmtree(repo_path, ignore_errors=True)

    # Remove from DB
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM workspace_repos WHERE id = $1", repo_id)

    return {"ok": True}
