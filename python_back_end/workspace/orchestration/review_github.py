"""Review-on-GitHub — the coder↔reviewer review conversation happens on a real
GitHub DRAFT pull request: the agents post their dialogue as labeled PR comments,
and the draft PR is marked ready-for-review when the reviewer approves.

Uses the session author's OWN GitHub token (repo_manager._get_github_token). GitHub
forbids submitting a formal APPROVE / REQUEST_CHANGES review on your own PR, so the
conversation is labeled issue comments (🔎 Reviewer / 🧑‍💻 Coder) + a draft→ready
flip (GraphQL) on agreement — the human still merges. Every helper is FAIL-SOFT
(logs + returns an error marker, never raises) so a GitHub hiccup degrades the
review to thread-only. The token is NEVER logged (scrubbed from git-push errors;
the remote is reset to a token-less URL after each push).
"""
from __future__ import annotations

import logging
import re

import httpx

from .isolation import _run_git

logger = logging.getLogger(__name__)
_GH_API = "https://api.github.com"
_GH_TIMEOUT = 20.0


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


async def resolve_owner_repo(workspace_path: str):
    """(owner, repo) parsed from the workspace's origin remote, else (None, None)."""
    try:
        rc, out, _ = await _run_git(["git", "remote", "get-url", "origin"], cwd=workspace_path)
        m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$", (out or "").strip())
        return (m.group(1), m.group(2)) if m else (None, None)
    except Exception:
        return None, None


async def push_session_branch(workspace_path: str, owner: str, repo: str, branch: str, token: str) -> dict:
    """Commit the working tree (if any changes) and push to origin/<branch>. The
    authed remote URL is set only for the push and reset to a token-less URL after;
    the token is scrubbed from any error. Returns {ok} or {ok:False, error}."""
    if branch in ("main", "master"):
        return {"ok": False, "error": "refusing to push to main/master"}
    try:
        await _run_git(["git", "config", "user.name", "HarvisAI"], cwd=workspace_path)
        await _run_git(["git", "config", "user.email", "harvis@ai.local"], cwd=workspace_path)
        await _run_git(["git", "checkout", "-B", branch], cwd=workspace_path)
        await _run_git(["git", "add", "-A"], cwd=workspace_path)
        rc, _o, _e = await _run_git(["git", "diff", "--cached", "--quiet"], cwd=workspace_path)
        if rc != 0:  # staged changes exist → commit them
            rc, _o, err = await _run_git(
                ["git", "commit", "-m", "Harvis review update"], cwd=workspace_path
            )
            if rc != 0:
                return {"ok": False, "error": f"commit failed: {(err or '')[:120]}"}
        authed = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        safe = f"https://github.com/{owner}/{repo}.git"
        await _run_git(["git", "remote", "set-url", "origin", authed], cwd=workspace_path)
        rc, _o, err = await _run_git(
            ["git", "push", "-u", "--force", "origin", branch], cwd=workspace_path
        )
        await _run_git(["git", "remote", "set-url", "origin", safe], cwd=workspace_path)
        if rc != 0:
            err = (err or "").replace(token, "***") if token else (err or "")
            return {"ok": False, "error": f"push failed: {err[:120]}"}
        return {"ok": True}
    except Exception as exc:
        logger.warning("review_github: push failed (%s)", type(exc).__name__)
        return {"ok": False, "error": "push exception"}


async def open_or_reuse_draft_pr(
    token: str, owner: str, repo: str, head: str, base: str, title: str, body: str
) -> dict:
    """Open a DRAFT PR (or reuse an existing OPEN PR on the same head). Returns
    {number, url, node_id, [reused]} or {error}."""
    try:
        async with httpx.AsyncClient(timeout=_GH_TIMEOUT) as c:
            r = await c.post(
                f"{_GH_API}/repos/{owner}/{repo}/pulls",
                headers=_headers(token),
                json={"title": title, "body": body, "head": head, "base": base, "draft": True},
            )
            if r.status_code in (200, 201):
                d = r.json()
                return {"number": d["number"], "url": d.get("html_url", ""), "node_id": d.get("node_id", "")}
            if r.status_code == 422:  # a PR already exists on this head → reuse it
                g = await c.get(
                    f"{_GH_API}/repos/{owner}/{repo}/pulls",
                    headers=_headers(token),
                    params={"head": f"{owner}:{head}", "state": "open"},
                )
                if g.status_code == 200 and g.json():
                    d = g.json()[0]
                    return {
                        "number": d["number"], "url": d.get("html_url", ""),
                        "node_id": d.get("node_id", ""), "reused": True,
                    }
            return {"error": f"draft PR create failed: HTTP {r.status_code}"}
    except Exception as exc:
        logger.warning("review_github: open_draft_pr failed (%s)", type(exc).__name__)
        return {"error": "draft PR exception"}


async def post_comment(token: str, owner: str, repo: str, number: int, body: str) -> bool:
    """Post a conversation comment on the PR. Fail-soft (returns success bool)."""
    try:
        async with httpx.AsyncClient(timeout=_GH_TIMEOUT) as c:
            r = await c.post(
                f"{_GH_API}/repos/{owner}/{repo}/issues/{number}/comments",
                headers=_headers(token),
                json={"body": (body or "")[:60000]},
            )
            return r.status_code in (200, 201)
    except Exception as exc:
        logger.warning("review_github: post_comment failed (%s)", type(exc).__name__)
        return False


async def mark_ready(token: str, node_id: str) -> bool:
    """Flip a draft PR to ready-for-review (GraphQL — REST has no equivalent). Fail-soft."""
    if not node_id:
        return False
    try:
        query = (
            "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})"
            "{pullRequest{isDraft}}}"
        )
        async with httpx.AsyncClient(timeout=_GH_TIMEOUT) as c:
            r = await c.post(
                f"{_GH_API}/graphql",
                headers=_headers(token),
                json={"query": query, "variables": {"id": node_id}},
            )
            return r.status_code == 200 and "errors" not in (r.json() or {})
    except Exception as exc:
        logger.warning("review_github: mark_ready failed (%s)", type(exc).__name__)
        return False
