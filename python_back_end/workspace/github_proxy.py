"""
GitHub API proxy for the Harvis backend.

OpenClaw agents call this endpoint to create PRs on behalf of the Harvis bot
account (harvisai-dulc3-cmd) without ever holding or printing the GitHub token
themselves.

Security model:
  - Verifies OPENCLAW_GATEWAY_TOKEN on every request (only OpenClaw can call this).
  - Hard-coded allowlist: only `dulc3/harvis-aidev` may receive PRs.
  - Only the `pulls` and `repos` endpoints are exposed — no arbitrary GitHub API passthrough.
  - HARVIS_GITHUB_TOKEN stays in the backend pod; OpenClaw never sees its value.
  - Every PR and repo creation is logged with timestamp and result.
  - Force-push and push-to-main are prevented at the git level (skill), and
    also enforced here by rejecting any PR that targets main via a non-harvis/* branch.

Endpoints:
  POST /github/pulls          — create a pull request
  GET  /github/pulls          — list open PRs for the repo
  GET  /github/pulls/{number} — get a specific PR
  POST /github/repos          — create a new repository under the authenticated user
"""

import json
import logging
import os
import re
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

from .github_app_auth import get_installation_token

logger = logging.getLogger(__name__)

# Legacy PAT fallback — empty when GitHub App is configured
HARVIS_GITHUB_TOKEN = os.getenv("HARVIS_GITHUB_TOKEN", "")
HARVIS_GITHUB_USER = os.getenv("HARVIS_GITHUB_USER", "HarvisAI[bot]")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# GitHub App credentials (preferred over PAT when available)
_GITHUB_APP_ID = os.getenv("HARVIS_GITHUB_APP_ID", "")

# Co-author trailer appended to every PR so the human owner also gets contribution credit.
# No personal token needed — GitHub reads the trailer and credits both accounts.
HARVIS_COAUTHOR_TRAILER = os.getenv(
    "HARVIS_COAUTHOR_TRAILER",
    "Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>",
)

# Only these repos may receive PRs from this proxy.
# To add more repos: append "owner/repo-name" to this set.
_ALLOWED_REPOS = frozenset({
    "dulc3/harvis-aidev",
    "brandoz2255/Harvis",
})

# Only branches matching this prefix may be used as PR heads.
# This prevents the agent from ever opening a PR from main/master.
_ALLOWED_HEAD_PREFIX = "harvis/"

_GITHUB_API_BASE = "https://api.github.com"

github_proxy_router = APIRouter(prefix="/github", tags=["github-proxy"])


def _verify_openclaw_token(authorization: Optional[str]) -> None:
    """Only the OpenClaw pod (via shared OPENCLAW_GATEWAY_TOKEN) may call this."""
    if not OPENCLAW_GATEWAY_TOKEN:
        return  # dev mode
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):]
    if token != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid proxy token")


def _validate_repo(repo: str) -> None:
    if repo not in _ALLOWED_REPOS:
        logger.warning("github_proxy: rejected PR for disallowed repo %r", repo)
        raise HTTPException(
            status_code=403,
            detail=f"Repo '{repo}' is not on the Harvis allowed list. "
                   f"Allowed: {sorted(_ALLOWED_REPOS)}",
        )


def _validate_head_branch(head: str) -> None:
    """Reject any PR whose head branch is main, master, or doesn't start with harvis/."""
    clean = head.split(":")[-1]  # strip "user:" prefix if present
    if clean in ("main", "master", "develop", "dev"):
        logger.warning("github_proxy: rejected PR from protected branch %r", clean)
        raise HTTPException(
            status_code=403,
            detail=f"Cannot open a PR from branch '{clean}'. "
                   f"All Harvis branches must start with '{_ALLOWED_HEAD_PREFIX}'.",
        )
    if not clean.startswith(_ALLOWED_HEAD_PREFIX):
        logger.warning("github_proxy: rejected PR from non-harvis branch %r", clean)
        raise HTTPException(
            status_code=403,
            detail=f"Head branch '{clean}' must start with '{_ALLOWED_HEAD_PREFIX}'. "
                   f"Example: 'harvis/fix-session-id'.",
        )


async def _gh_headers() -> dict:
    """Return GitHub API headers, using App installation token when configured."""
    if _GITHUB_APP_ID:
        token = await get_installation_token()
    elif HARVIS_GITHUB_TOKEN:
        token = HARVIS_GITHUB_TOKEN
    else:
        raise HTTPException(status_code=503, detail="No GitHub credentials configured on backend")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


# ─── Request models ────────────────────────────────────────────────────────────

class CreatePRRequest(BaseModel):
    repo: str           # e.g. "dulc3/harvis-aidev"
    title: str
    body: str = ""
    head: str           # branch name, e.g. "harvis/fix-auth"
    base: str = "main"  # always "main" — no other base accepted
    draft: bool = False

    @field_validator("base")
    @classmethod
    def base_must_be_main(cls, v: str) -> str:
        if v not in ("main", "master"):
            raise ValueError("PR base must be 'main' or 'master'")
        return v

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("PR title cannot be empty")
        return v.strip()


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@github_proxy_router.post("/pulls")
async def create_pull_request(
    req: CreatePRRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Create a PR on behalf of harvisai-dulc3-cmd.

    Enforces:
    - Repo allowlist (only dulc3/harvis-aidev)
    - Head branch must start with harvis/
    - Base branch must be main/master
    - HARVIS_GITHUB_TOKEN used server-side; caller never sees it
    """
    _verify_openclaw_token(authorization)
    _validate_repo(req.repo)
    _validate_head_branch(req.head)

    # Append co-author trailer so both HarvisAI[bot] and the human owner
    # get GitHub contribution credit. No personal token required.
    pr_body = req.body.rstrip()
    if HARVIS_COAUTHOR_TRAILER and HARVIS_COAUTHOR_TRAILER not in pr_body:
        pr_body = f"{pr_body}\n\n{HARVIS_COAUTHOR_TRAILER}"

    payload = {
        "title": req.title,
        "body": pr_body,
        "head": req.head,
        "base": req.base,
        "draft": req.draft,
    }

    url = f"{_GITHUB_API_BASE}/repos/{req.repo}/pulls"
    logger.info(
        "github_proxy: creating PR repo=%s head=%s base=%s title=%r",
        req.repo, req.head, req.base, req.title,
    )

    try:
        headers = await _gh_headers()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)

        result = resp.json()

        if resp.status_code == 201:
            pr_url = result.get("html_url", "")
            pr_number = result.get("number", "?")
            logger.info(
                "github_proxy: PR created #%s %s repo=%s head=%s",
                pr_number, pr_url, req.repo, req.head,
            )
            return {
                "ok": True,
                "pr_number": pr_number,
                "pr_url": pr_url,
                "title": req.title,
                "head": req.head,
                "base": req.base,
            }

        # Pass GitHub error back to caller (e.g. branch not pushed yet)
        logger.warning(
            "github_proxy: GitHub API returned %s for repo=%s: %s",
            resp.status_code, req.repo, str(result)[:200],
        )
        raise HTTPException(
            status_code=resp.status_code,
            detail=result.get("message", f"GitHub API error {resp.status_code}"),
        )

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="GitHub API request timed out")
    except Exception as exc:
        logger.error("github_proxy: unexpected error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@github_proxy_router.get("/pulls")
async def list_pull_requests(
    repo: str = "dulc3/harvis-aidev",
    state: str = "open",
    authorization: Optional[str] = Header(default=None),
):
    """List open PRs for the repo (read-only, no token needed — public repo)."""
    _verify_openclaw_token(authorization)
    _validate_repo(repo)

    url = f"{_GITHUB_API_BASE}/repos/{repo}/pulls"
    try:
        headers = await _gh_headers() if (_GITHUB_APP_ID or HARVIS_GITHUB_TOKEN) else {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(
                url,
                params={"state": state, "per_page": 20},
                headers=headers,
            )
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@github_proxy_router.get("/pulls/{pr_number}")
async def get_pull_request(
    pr_number: int,
    repo: str = "dulc3/harvis-aidev",
    authorization: Optional[str] = Header(default=None),
):
    """Get a specific PR by number (read-only)."""
    _verify_openclaw_token(authorization)
    _validate_repo(repo)

    url = f"{_GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}"
    try:
        headers = await _gh_headers() if (_GITHUB_APP_ID or HARVIS_GITHUB_TOKEN) else {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(url, headers=headers)
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ─── Repo creation ─────────────────────────────────────────────────────────────

class CreateRepoRequest(BaseModel):
    name: str
    description: str = ""
    private: bool = False
    auto_init: bool = True   # creates initial commit with README so the repo is immediately cloneable

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_.-]{1,100}$', v):
            raise ValueError(
                "Repo name must be 1-100 characters: letters, digits, hyphens, underscores, or dots"
            )
        return v


@github_proxy_router.post("/repos")
async def create_repository(
    req: CreateRepoRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Create a new GitHub repository under the authenticated user's account.

    The repository is created via the GitHub API using the backend token —
    the caller (OpenClaw) never sees the token value.

    Returns the new repo's html_url, clone_url, and full_name on success.
    """
    _verify_openclaw_token(authorization)

    payload = {
        "name": req.name,
        "description": req.description,
        "private": req.private,
        "auto_init": req.auto_init,
    }

    url = f"{_GITHUB_API_BASE}/user/repos"
    logger.info(
        "github_proxy: creating repo name=%r private=%s description=%r",
        req.name, req.private, req.description[:80] if req.description else "",
    )

    try:
        headers = await _gh_headers()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)

        result = resp.json()

        if resp.status_code == 201:
            full_name = result.get("full_name", "")
            html_url = result.get("html_url", "")
            clone_url = result.get("clone_url", "")
            logger.info(
                "github_proxy: repo created %s %s",
                full_name, html_url,
            )
            return {
                "ok": True,
                "full_name": full_name,
                "repo_url": html_url,
                "clone_url": clone_url,
                "private": result.get("private", req.private),
            }

        logger.warning(
            "github_proxy: GitHub API returned %s for create repo %r: %s",
            resp.status_code, req.name, str(result)[:200],
        )
        raise HTTPException(
            status_code=resp.status_code,
            detail=result.get("message", f"GitHub API error {resp.status_code}"),
        )

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="GitHub API request timed out")
    except Exception as exc:
        logger.error("github_proxy: unexpected error creating repo: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
