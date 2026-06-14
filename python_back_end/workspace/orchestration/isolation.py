"""Isolated per-agent workspaces for P5 orchestration.

Each sub-agent gets its own scratch directory; we snapshot a baseline when it's
created and produce a real unified diff + changed-files list (via ``difflib``)
when it finishes. This is the "isolation" pillar of P5 (scratch dir — NOT a
worktree of the user's repo, which is a later mode). All sub-agent file/tool
access is bounded to this directory via ``validate_agent_path``; the durable
output is the collected diff, stored as an AgentArtifact (the dir is ephemeral).

Why difflib, not git: the backend image ships without a `git` binary, and the
scratch dir starts empty, so a baseline-snapshot + difflib gives the same result
(additions + modifications + deletions) with no external dependency and no image
rebuild. A future "worktree of an attached repo" mode would use git directly.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Root under which every agent's scratch workspace is created. Ephemeral by
# design — the durable output is the collected diff (stored as an artifact).
AGENT_WORKSPACE_ROOT = os.getenv(
    "HARVIS_AGENT_WORKSPACE_ROOT", "/tmp/harvis-agent-workspaces"
)

# Hidden manifest of the baseline file contents, written at create time. Diffs
# are computed against this (empty for a fresh scratch dir → all additions).
_BASELINE_FILE = ".harvis-baseline.json"
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
_MAX_FILE_BYTES = 512 * 1024  # don't snapshot huge/binary blobs


def validate_agent_path(workspace_path: str, requested_path: str) -> bool:
    """True iff ``requested_path`` resolves to inside ``workspace_path``.

    Blocks ``../`` traversal, absolute escapes, and symlink escapes. Relative
    requests are resolved against the workspace. This is the path-safety gate
    every native tool must call BEFORE reading/writing/executing.
    """
    try:
        ws = Path(workspace_path).resolve()
        target = Path(requested_path)
        if not target.is_absolute():
            target = ws / target
        target = target.resolve()
        return target == ws or str(target).startswith(str(ws) + os.sep)
    except Exception:
        return False


def _snapshot(path: str) -> dict[str, str]:
    """Map of {relpath: text content} for every (small, text) file under path."""
    snap: dict[str, str] = {}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if fn == _BASELINE_FILE:
                continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, path)
            try:
                if os.path.getsize(fp) > _MAX_FILE_BYTES:
                    snap[rel] = f"<{os.path.getsize(fp)} bytes — not snapshotted>"
                    continue
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    snap[rel] = fh.read()
            except Exception:
                snap[rel] = "<unreadable>"
    return snap


class WorkspaceIsolationManager:
    """Creates + tears down isolated scratch dirs for sub-agents, and collects
    their diffs/changed-files via a baseline snapshot (no git dependency)."""

    def __init__(self, root: str = AGENT_WORKSPACE_ROOT):
        self.root = root

    async def create_workspace_for_agent(
        self, agent_run_id: str, role: str = "agent"
    ) -> dict:
        """Make a fresh scratch dir + write the baseline manifest. Returns
        ``{workspace_path, branch_name}`` (branch_name is a display label)."""
        safe = "".join(c for c in agent_run_id if c.isalnum() or c in "-_")[:64] or "agent"
        path = os.path.join(self.root, safe)
        os.makedirs(path, exist_ok=True)
        baseline = _snapshot(path)  # empty for a fresh dir
        try:
            with open(os.path.join(path, _BASELINE_FILE), "w", encoding="utf-8") as f:
                json.dump(baseline, f)
        except Exception:
            logger.warning("orchestration: failed to write baseline for %s", path, exc_info=True)
        safe_role = "".join(c for c in (role or "agent") if c.isalnum() or c in "-_") or "agent"
        branch = f"agent-{safe_role}-{safe}"
        logger.info("orchestration: created agent workspace %s (label %s)", path, branch)
        return {"workspace_path": path, "branch_name": branch}

    def _baseline(self, path: str) -> dict[str, str]:
        try:
            with open(os.path.join(path, _BASELINE_FILE), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    async def collect_changed_files(self, workspace_path: str) -> list[str]:
        """Files the agent created / changed / deleted vs the baseline."""
        baseline = self._baseline(workspace_path)
        current = _snapshot(workspace_path)
        changed = {rel for rel, c in current.items() if baseline.get(rel) != c}
        changed |= {rel for rel in baseline if rel not in current}  # deletions
        return sorted(changed)

    async def collect_diff(self, workspace_path: str) -> str:
        """Unified diff of everything the agent produced (vs the baseline)."""
        baseline = self._baseline(workspace_path)
        current = _snapshot(workspace_path)
        chunks: list[str] = []
        for rel in sorted(set(baseline) | set(current)):
            old = baseline.get(rel)
            new = current.get(rel)
            if old == new:
                continue
            old_lines = (old or "").splitlines(keepends=True)
            new_lines = (new or "").splitlines(keepends=True)
            from_f = f"a/{rel}" if old is not None else "/dev/null"
            to_f = f"b/{rel}" if new is not None else "/dev/null"
            body = "".join(
                difflib.unified_diff(old_lines, new_lines, fromfile=from_f, tofile=to_f)
            )
            header = f"diff --git a/{rel} b/{rel}"
            if old is None:
                header += "\nnew file"
            elif new is None:
                header += "\ndeleted file"
            chunks.append(header + "\n" + body.rstrip("\n"))
        return "\n".join(chunks) + ("\n" if chunks else "")

    async def cleanup(self, workspace_path: str) -> None:
        """Remove the scratch dir — guarded so we only ever delete under our root."""
        try:
            p = Path(workspace_path).resolve()
            root = Path(self.root).resolve()
            if p != root and str(p).startswith(str(root) + os.sep) and p.exists():
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            logger.warning("orchestration: cleanup skipped for %s", workspace_path, exc_info=True)
