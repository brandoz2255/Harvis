"""Build Space · Phase 1 — repo preflight.

Captures a persisted preflight report for a coding session BEFORE any AI work: is
this a real git repo, does its remote match the registered repo, what base branch /
current branch / HEAD SHA is it on, and is the working tree clean? The report is
stored on ``vibecode_sessions.preflight`` and rendered in the Build header; the CALLER
(workspace_router) applies the blocking rules (no unknown remote, no
dirty-without-approval). "Never edit main directly" stays enforced where it already
is — at commit/PR time — so branching FROM main is fine here.

Built on the existing async git primitive ``orchestration.isolation._run_git`` (which
sets up the cross-uid ``safe.directory`` guard for bind-mounted repos). Never raises —
any failure is reported as a blocker so the endpoint can decide.
"""
from __future__ import annotations

import logging
from typing import Optional

from .isolation import _run_git

logger = logging.getLogger(__name__)


def normalize_remote(url: str) -> str:
    """Normalize a git remote for equality: collapse ``git@host:owner/repo(.git)`` and
    ``https://host/owner/repo(.git)`` (and ssh:// / user@ variants) to ``host/owner/repo``
    lowercased, so the SSH and HTTPS forms of the same repo compare equal."""
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if u.endswith(".git"):
        u = u[:-4]
    for pre in ("https://", "http://", "ssh://git@", "ssh://"):
        if u.startswith(pre):
            u = u[len(pre):]
            break
    if u.startswith("git@"):
        u = u[4:].replace(":", "/", 1)  # git@github.com:owner/repo → github.com/owner/repo
    head = u.split("/", 1)[0]
    if "@" in head:  # strip any leftover user@host
        u = u.split("@", 1)[1]
    return u.lower()


async def run_preflight(
    repo_path: str,
    *,
    expected_remote: Optional[str] = None,
    base_branch: Optional[str] = None,
    require_clean: bool = False,
) -> dict:
    """Return a preflight report for ``repo_path``. Never raises.

    Report keys: repo_ok, remote_ok (None if no expected_remote), remote_url,
    base_branch, current_branch, head_sha, clean, dirty_count, blockers (list of
    {code, message}), ok (True ⇔ no blockers).
    """
    report: dict = {
        "repo_ok": False,
        "remote_ok": None,
        "remote_url": None,
        "base_branch": base_branch,
        "current_branch": None,
        "head_sha": None,
        "clean": None,
        "dirty_count": 0,
        "blockers": [],
        "ok": False,
    }
    blockers: list[dict] = report["blockers"]

    try:
        rc, out, _err = await _run_git(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_path)
        if rc != 0 or out.strip() != "true":
            blockers.append({"code": "not_a_repo", "message": "Not a git repository."})
            return report
        report["repo_ok"] = True

        rc, out, _ = await _run_git(["git", "remote", "get-url", "origin"], cwd=repo_path)
        remote_url = out.strip() if rc == 0 else ""
        report["remote_url"] = remote_url or None
        if expected_remote:
            match = normalize_remote(remote_url) == normalize_remote(expected_remote)
            report["remote_ok"] = match
            if not match:
                blockers.append({
                    "code": "unknown_remote",
                    "message": f"Remote '{remote_url or '(none)'}' does not match the registered repo.",
                })

        rc, out, _ = await _run_git(["git", "branch", "--show-current"], cwd=repo_path)
        report["current_branch"] = (out.strip() or None) if rc == 0 else None

        rc, out, _ = await _run_git(["git", "rev-parse", "HEAD"], cwd=repo_path)
        report["head_sha"] = out.strip() if rc == 0 else None

        rc, out, _ = await _run_git(["git", "status", "--porcelain"], cwd=repo_path)
        if rc == 0:
            dirty = [ln for ln in out.splitlines() if ln.strip()]
            report["clean"] = len(dirty) == 0
            report["dirty_count"] = len(dirty)
            if dirty and require_clean:
                blockers.append({
                    "code": "dirty_tree",
                    "message": f"Working tree has {len(dirty)} uncommitted change(s); commit or stash first.",
                })
    except Exception:
        logger.warning("preflight: unexpected failure on %s", repo_path, exc_info=True)
        blockers.append({"code": "preflight_error", "message": "Preflight check failed to run."})

    report["ok"] = len(blockers) == 0
    return report
