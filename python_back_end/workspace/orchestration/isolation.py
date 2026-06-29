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

import asyncio
import base64
import difflib
import json
import logging
import os
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Root under which every agent's scratch workspace is created. Ephemeral by
# design — the durable output is the collected diff (stored as an artifact).
AGENT_WORKSPACE_ROOT = os.getenv(
    "HARVIS_AGENT_WORKSPACE_ROOT", "/tmp/harvis-agent-workspaces"
)

# Root for PERSISTENT VibeCode-session workspaces (clone-mode cumulative sessions).
# Deliberately NOT under /tmp — a session's working clone must survive across turns
# and restarts (a tmp-reaper would silently eat a live session mid-conversation).
# /data/artifacts is the appuser-owned writable volume on the dev box.
SESSION_WORKSPACE_ROOT = os.getenv(
    "HARVIS_SESSION_WORKSPACE_ROOT", "/data/artifacts/harvis-vibecode-sessions"
)

# Hidden manifest of the baseline file contents, written at create time. Diffs
# are computed against this (empty for a fresh scratch dir → all additions).
_BASELINE_FILE = ".harvis-baseline.json"
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
_MAX_FILE_BYTES = 512 * 1024  # text snapshot cap
_MAX_BINARY_BYTES = 8 * 1024 * 1024  # base64-in-DB cap for binary artifacts (images/pdf/office)
# Binary artifacts are stored base64-encoded with this sentinel prefix so the serve route can
# unambiguously decode them (vs a text artifact). Children never see this — it's a storage detail.
_B64_SENTINEL = "__HARVIS_B64__"

# Binary file extensions captured as base64; everything else is read as text.
_BINARY_EXTS = {
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "tiff",
    "pdf", "docx", "pptx", "xlsx", "doc", "ppt", "xls", "odt", "ods", "odp",
    "zip", "tar", "gz", "tgz", "bz2", "7z", "rar",
    "woff", "woff2", "ttf", "otf", "mp3", "mp4", "wav", "ogg", "webm", "mov", "avi",
}
# Secret-looking files are NEVER collected as artifacts (no preview/download). Mirrors the
# hermes-import deny-list. The diff still shows config changes; artifacts must not expose secrets.
_ARTIFACT_SECRET_HINTS = (
    ".env", "credential", "secret", ".key", ".pem", "id_rsa", "id_ed25519",
    "apikey", "api_key", ".npmrc", ".netrc", ".pgpass", ".htpasswd", ".aws", ".ssh",
)


def _ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _is_secret_artifact(name: str) -> bool:
    n = (name or "").lower().rsplit("/", 1)[-1]
    return any(h in n for h in _ARTIFACT_SECRET_HINTS)


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


_GIT_SAFE_CONFIG_PATH: str | None = None


def _ensure_git_safe_config() -> str:
    """Write (once) a global gitconfig that trusts the bind-mounted repos.

    The attached repo is bind-mounted from the host (uid 1000) but the backend runs
    as uid 1001 → git's "dubious ownership" guard blocks every command on it. Crucially
    ``safe.directory`` can ONLY be set via a config FILE (system/global), never via
    ``-c`` or ``GIT_CONFIG_COUNT`` — git ignores command-line ``safe.directory`` by
    design (so an attacker can't bypass the guard). So we point GIT_CONFIG_GLOBAL at a
    file that trusts everything (these are deliberately-mounted repos)."""
    global _GIT_SAFE_CONFIG_PATH
    if _GIT_SAFE_CONFIG_PATH and os.path.exists(_GIT_SAFE_CONFIG_PATH):
        return _GIT_SAFE_CONFIG_PATH
    path = os.path.join(AGENT_WORKSPACE_ROOT, ".harvis-gitconfig")
    try:
        os.makedirs(AGENT_WORKSPACE_ROOT, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("[safe]\n\tdirectory = *\n")
        _GIT_SAFE_CONFIG_PATH = path
        return path
    except Exception:
        logger.warning("orchestration: could not write git safe-config", exc_info=True)
        return ""


async def _run_git(cmd: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command async; return (returncode, stdout, stderr). Used by the
    'attached' (clone-local) isolation mode. Mirrors repo_manager._run_git."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"  # never block on an auth prompt
    env["GIT_CREDENTIAL_HELPER"] = ""  # disable any credential helper → never cache a clone token
    _cfg = _ensure_git_safe_config()
    if _cfg:
        # safe.directory=* (trusts the cross-uid bind-mount) lives in this file —
        # the only place git honors it. Propagates to clone --local's child git.
        env["GIT_CONFIG_GLOBAL"] = _cfg
        env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")
    except Exception as e:  # noqa: BLE001 — surfaced to the caller as a non-zero rc
        return 1, "", str(e)


class WorkspaceIsolationManager:
    """Creates + tears down isolated per-agent workspaces and collects their
    diffs/changed-files. Two modes:
      - "scratch" (default): an empty scratch dir + baseline snapshot + difflib.
      - "attached": a `git clone --local` of a (read-only) bind-mounted repo, with
        a real `git diff` vs HEAD. Selected when a run carries an attached repo."""

    def __init__(
        self,
        root: str = AGENT_WORKSPACE_ROOT,
        isolation_mode: str = "scratch",
        repo_config: dict | None = None,
    ):
        self.root = root
        # "attached" → clone-local of a RO source, diff vs HEAD (one-shot).
        # "session"  → a PERSISTENT clone reused across turns, diff vs a fixed base_sha
        #              (cumulative VibeCode sessions); the caller never cleans it up per-turn.
        # anything else → scratch.
        # "inplace"  → the agent works ON the real repo (RW mount) on a session branch
        #              (no clone); diff vs base_sha like "session"; teardown = delete the
        #              branch, never the repo. The opt-in, permission-gated mode.
        self.isolation_mode = (
            isolation_mode if isolation_mode in ("attached", "session", "inplace") else "scratch"
        )
        self.repo_config = repo_config or {}

    async def create_workspace_for_agent(
        self, agent_run_id: str, role: str = "agent"
    ) -> dict:
        """Make an isolated workspace. Attached mode → `git clone --local` of the
        attached repo; scratch mode → empty dir + baseline manifest. Returns
        ``{workspace_path, branch_name, ...}`` (branch_name is also the real branch
        in attached mode)."""
        safe = "".join(c for c in agent_run_id if c.isalnum() or c in "-_")[:64] or "agent"
        safe_role = "".join(c for c in (role or "agent") if c.isalnum() or c in "-_") or "agent"
        branch = f"agent-{safe_role}-{safe}"
        path = os.path.join(self.root, safe)
        os.makedirs(self.root, exist_ok=True)
        if os.path.exists(path):  # re-run safety — `git clone` needs a fresh dest
            shutil.rmtree(path, ignore_errors=True)

        if self.isolation_mode == "attached":
            repo_path = (self.repo_config or {}).get("repo_path")
            base_branch = (self.repo_config or {}).get("base_branch") or ""
            if repo_path and os.path.isdir(os.path.join(repo_path, ".git")):
                info = await self._create_attached(path, branch, repo_path, base_branch)
                if info is not None:
                    logger.info(
                        "orchestration: created ATTACHED workspace %s (clone-local from %s, label %s)",
                        path, repo_path, branch,
                    )
                    return info
                logger.warning("orchestration: attached clone failed for %s — falling back to scratch", repo_path)
            else:
                logger.warning("orchestration: attached mode but %r is not a git repo — falling back to scratch", repo_path)

        # scratch mode (default + attached fallback)
        os.makedirs(path, exist_ok=True)
        baseline = _snapshot(path)  # empty for a fresh dir
        try:
            with open(os.path.join(path, _BASELINE_FILE), "w", encoding="utf-8") as f:
                json.dump(baseline, f)
        except Exception:
            logger.warning("orchestration: failed to write baseline for %s", path, exc_info=True)
        logger.info("orchestration: created agent workspace %s (label %s)", path, branch)
        return {"workspace_path": path, "branch_name": branch}

    async def _create_attached(
        self, path: str, branch: str, repo_path: str, base_branch: str
    ) -> dict | None:
        """`git clone --local` a read-only source repo into our writable root, then
        check out the base branch + a fresh agent branch. Returns the workspace dict,
        or None if the clone failed (caller falls back to scratch)."""
        # --no-hardlinks: the source bind-mount and our workspace root are different
        # filesystems (/data vs /tmp), so hardlinks fail with "Invalid cross-device
        # link". Copy the objects instead (correct, just disk-heavier — the documented
        # same-filesystem caveat). Still skips the git network protocol (local copy).
        rc, out, err = await _run_git(
            ["git", "clone", "--local", "--no-hardlinks", repo_path, path], cwd=self.root
        )
        if rc != 0:
            logger.warning("orchestration: git clone --local failed: %s", (err or out)[:300])
            return None
        if base_branch:
            rcb, _o, errb = await _run_git(["git", "checkout", base_branch], cwd=path)
            if rcb != 0:
                logger.warning("orchestration: checkout base '%s' failed: %s", base_branch, errb[:200])
        # Work on a fresh branch so the diff is vs the base commit + the later PR has a head.
        await _run_git(["git", "checkout", "-B", branch], cwd=path)
        await _run_git(["git", "config", "user.name", "HarvisAgent"], cwd=path)
        await _run_git(["git", "config", "user.email", "agent@harvis.local"], cwd=path)
        return {
            "workspace_path": path,
            "branch_name": branch,
            "mode": "attached",
            "base_branch": base_branch,
            "repo_path": repo_path,
        }

    def _baseline(self, path: str) -> dict[str, str]:
        try:
            with open(os.path.join(path, _BASELINE_FILE), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    async def collect_changed_files(self, workspace_path: str) -> list[str]:
        """Files the agent created / changed / deleted (vs HEAD / the baseline)."""
        if self.isolation_mode in ("attached", "session", "inplace"):
            await _run_git(["git", "add", "-A"], cwd=workspace_path)
            if self.isolation_mode in ("session", "inplace"):
                # Cumulative across turns: diff the working tree vs the fixed baseline
                # commit. `add -A` above is MANDATORY — without it, NEW files created in
                # a later turn are untracked and silently drop from `git diff <base>`.
                base = (self.repo_config or {}).get("base_sha") or "HEAD"
                _rc, out, _e = await _run_git(["git", "diff", base, "--name-only"], cwd=workspace_path)
            else:
                _rc, out, _e = await _run_git(["git", "diff", "--cached", "--name-only"], cwd=workspace_path)
            return [ln for ln in out.splitlines() if ln.strip()]
        baseline = self._baseline(workspace_path)
        current = _snapshot(workspace_path)
        changed = {rel for rel, c in current.items() if baseline.get(rel) != c}
        changed |= {rel for rel in baseline if rel not in current}  # deletions
        return sorted(changed)

    async def collect_file_contents(self, workspace_path: str) -> dict[str, str]:
        """Current content of every CHANGED file, for live artifact previews/downloads.

        Text files → their text (capped). Recognised BINARY files (images/pdf/office/...) →
        base64 with the ``_B64_SENTINEL`` prefix (capped). Secret-named files (.env/keys) are
        EXCLUDED entirely — artifacts must never expose credentials. Huge blobs → a placeholder."""
        if self.isolation_mode in ("attached", "session", "inplace"):
            result: dict[str, str] = {}
            for rel in await self.collect_changed_files(workspace_path):
                if _is_secret_artifact(rel):
                    continue  # never expose secrets as artifacts
                fp = os.path.join(workspace_path, rel)
                try:
                    if not os.path.exists(fp):
                        continue  # deleted file → no content to preview
                    size = os.path.getsize(fp)
                    if _ext_of(rel) in _BINARY_EXTS:
                        if size > _MAX_BINARY_BYTES:
                            result[rel] = f"<{size} bytes — too large to snapshot>"
                        else:
                            with open(fp, "rb") as fh:
                                result[rel] = _B64_SENTINEL + base64.b64encode(fh.read()).decode("ascii")
                    elif size > _MAX_FILE_BYTES:
                        result[rel] = f"<{size} bytes — not snapshotted>"
                    else:
                        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                            result[rel] = fh.read()
                except Exception:
                    result[rel] = "<unreadable>"
            return result
        baseline = self._baseline(workspace_path)
        current = _snapshot(workspace_path)
        return {
            rel: content for rel, content in current.items()
            if baseline.get(rel) != content and not _is_secret_artifact(rel)
        }

    async def collect_diff(self, workspace_path: str) -> str:
        """Unified diff of everything the agent produced (vs HEAD / the baseline)."""
        if self.isolation_mode in ("attached", "session", "inplace"):
            await _run_git(["git", "add", "-A"], cwd=workspace_path)
            if self.isolation_mode in ("session", "inplace"):
                base = (self.repo_config or {}).get("base_sha") or "HEAD"
                _rc, out, _e = await _run_git(["git", "diff", base], cwd=workspace_path)
            else:
                _rc, out, _e = await _run_git(["git", "diff", "--cached"], cwd=workspace_path)
            return out
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


async def create_or_attach_session_workspace(
    session_id: str,
    repo_path: str | None,
    base_branch: str | None = None,
    github_source: dict | None = None,
    root: str = SESSION_WORKSPACE_ROOT,
) -> dict:
    """Create (or reuse) a PERSISTENT per-session working clone for a cumulative
    VibeCode session. Called ONCE at session-create time, not per turn.

    - If the workspace dir already exists as a git repo, return it UNTOUCHED (the
      turns share this one evolving tree; we never re-clone or reset it).
    - ``github_source`` ({owner, repo, branch, token}) → clone that GitHub repo
      (token-authed for private), STRIP the token from the stored remote, capture
      ``base_sha``. Clone-mode only; Create-PR resolves the origin from the remote.
    - A non-git directory → COPY its files into a fresh git workspace (clone-mode).
    - Else `git clone --local --no-hardlinks` the read-only source, checkout the
      base branch, capture ``base_sha`` (the fixed cumulative-diff baseline) BEFORE
      cutting a session branch, then `checkout -B vibecode-<id>`.
    - No git repo to attach → a persistent empty scratch dir (still session-scoped).

    Returns ``{workspace_path, branch_name, base_sha, reused, [error]}``. ``base_sha``
    is None on reuse (the caller already has it stored on the session row) and on the
    no-repo path.
    """
    safe = "".join(c for c in (session_id or "") if c.isalnum() or c in "-_")[:64] or "session"
    path = os.path.join(root, safe)
    branch = f"vibecode-{safe}"
    os.makedirs(root, exist_ok=True)

    # Reuse an existing clone verbatim — this is the persistent shared working tree.
    if os.path.isdir(os.path.join(path, ".git")):
        return {"workspace_path": path, "branch_name": branch, "base_sha": None, "reused": True}

    # A GitHub repo → clone it (token-authed for private repos), then STRIP the token from the
    # stored remote so it never lands on disk. Clone-mode only; the cumulative diff is vs base_sha
    # and Create-PR resolves the GitHub origin from this clone's remote.url (unchanged PR flow).
    if github_source and str(github_source.get("repo") or "").strip():
        owner = str(github_source.get("owner") or "").strip()
        name = str(github_source.get("repo") or "").strip()
        gh_branch = str(github_source.get("branch") or "").strip()
        token = str(github_source.get("token") or "").strip()
        # Validate owner/repo against GitHub's naming rules BEFORE building the URL — a clean
        # rejection beats a confusing git failure, and bounds what reaches the URL/CLI.
        if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$", owner) or not re.match(
            r"^[A-Za-z0-9._-]{1,100}$", name
        ):
            return {"workspace_path": path, "branch_name": branch, "base_sha": None,
                    "reused": False, "error": "Invalid GitHub owner/repo."}
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
        safe_url = f"https://github.com/{owner}/{name}.git"
        auth_url = f"https://x-access-token:{token}@github.com/{owner}/{name}.git" if token else safe_url
        clone_cmd = ["git", "clone"]
        if gh_branch:
            clone_cmd += ["--branch", gh_branch]
        clone_cmd += [auth_url, path]
        rc, out, err = await _run_git(clone_cmd, cwd=root)
        if rc != 0:
            scrub = (err or out) or ""
            if token:
                scrub = scrub.replace(token, "***")  # never echo the token in an error
            logger.warning("vibecode: GitHub clone failed for %s/%s: %s", owner, name, scrub[:300])
            os.makedirs(path, exist_ok=True)
            return {"workspace_path": path, "branch_name": branch, "base_sha": None,
                    "reused": False, "error": f"GitHub clone failed: {scrub[:200]}"}
        # Strip the embedded token from the stored remote (keep the clean https origin so
        # Create-PR can resolve owner/repo + re-inject a fresh token at push time).
        await _run_git(["git", "remote", "set-url", "origin", safe_url], cwd=path)
        _rc, sha, _e = await _run_git(["git", "rev-parse", "HEAD"], cwd=path)
        base_sha = sha.strip()
        await _run_git(["git", "checkout", "-B", branch], cwd=path)
        await _run_git(["git", "config", "user.name", "HarvisVibeCode"], cwd=path)
        await _run_git(["git", "config", "user.email", "vibecode@harvis.local"], cwd=path)
        logger.info("vibecode: created SESSION workspace %s (github clone %s/%s)", path, owner, name)
        return {"workspace_path": path, "branch_name": branch, "base_sha": base_sha,
                "reused": False, "repo_path": path}

    # A non-git DIRECTORY (e.g. a browsed folder that isn't a repo) → COPY its files into a
    # fresh git-init'd workspace (clone-mode: the real folder is only READ, never modified; the
    # cumulative diff is vs this seeded baseline). Lets "Use this folder" work on ANY folder.
    # symlinks=True keeps symlinks AS symlinks (don't follow) — path-safety still blocks the
    # agent from reading through an escaping symlink; skip-dirs cut node_modules/dist/etc bloat.
    if repo_path and os.path.isdir(repo_path) and not os.path.isdir(os.path.join(repo_path, ".git")):
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)

        def _ignore(dir_path: str, names: list[str]) -> list[str]:
            # Skip junk dirs by name + oversized files + binaries (null-byte sniff) so the
            # seed is clean + fast — the agent works on source, not blobs/build artifacts.
            skip: list[str] = []
            for n in names:
                if n in _LOCAL_FOLDER_SKIP_PARTS:
                    skip.append(n)
                    continue
                fp = os.path.join(dir_path, n)
                try:
                    if os.path.isfile(fp) and not os.path.islink(fp):
                        if os.path.getsize(fp) > _MAX_FILE_BYTES:
                            skip.append(n)
                            continue
                        with open(fp, "rb") as fh:
                            if b"\x00" in fh.read(1024):  # binary → skip
                                skip.append(n)
                except Exception:
                    # Unreadable (perm denied / race) → SKIP it: copytree would raise on the same
                    # file and abort the seed, leaving a partial tree. Dropping one file is safer.
                    skip.append(n)
            return skip

        try:
            shutil.copytree(repo_path, path, ignore=_ignore, symlinks=True, dirs_exist_ok=True)
        except Exception:
            logger.warning("vibecode: copy-seed from %s partly failed", repo_path, exc_info=True)
            os.makedirs(path, exist_ok=True)
        await _run_git(["git", "init"], cwd=path)
        await _run_git(["git", "config", "user.name", "HarvisVibeCode"], cwd=path)
        await _run_git(["git", "config", "user.email", "vibecode@harvis.local"], cwd=path)
        await _run_git(["git", "add", "-A"], cwd=path)
        await _run_git(["git", "commit", "--allow-empty", "-m", "vibecode folder baseline"], cwd=path)
        _rc, sha, _e = await _run_git(["git", "rev-parse", "HEAD"], cwd=path)
        await _run_git(["git", "checkout", "-B", branch], cwd=path)
        logger.info("vibecode: created SESSION workspace %s (copy-seed from non-git %s)", path, repo_path)
        return {"workspace_path": path, "branch_name": branch, "base_sha": sha.strip(), "reused": False}

    # No attachable git repo → a persistent, git-initialised empty session dir with
    # an empty baseline commit, so cumulative diffs (vs base_sha) still work.
    if not (repo_path and os.path.isdir(os.path.join(repo_path, ".git"))):
        os.makedirs(path, exist_ok=True)
        await _run_git(["git", "init"], cwd=path)
        await _run_git(["git", "config", "user.name", "HarvisVibeCode"], cwd=path)
        await _run_git(["git", "config", "user.email", "vibecode@harvis.local"], cwd=path)
        await _run_git(["git", "commit", "--allow-empty", "-m", "vibecode session baseline"], cwd=path)
        _rc, sha, _e = await _run_git(["git", "rev-parse", "HEAD"], cwd=path)
        await _run_git(["git", "checkout", "-B", branch], cwd=path)
        return {
            "workspace_path": path, "branch_name": branch,
            "base_sha": sha.strip(), "reused": False,
        }

    if os.path.exists(path):  # stale non-git dir — clear so `git clone` has a fresh dest
        shutil.rmtree(path, ignore_errors=True)
    rc, out, err = await _run_git(
        ["git", "clone", "--local", "--no-hardlinks", repo_path, path], cwd=root
    )
    if rc != 0:
        logger.warning("vibecode: session clone --local failed: %s", (err or out)[:300])
        os.makedirs(path, exist_ok=True)
        return {
            "workspace_path": path, "branch_name": branch, "base_sha": None,
            "reused": False, "error": (err or out)[:300],
        }
    if base_branch:
        rcb, _o, errb = await _run_git(["git", "checkout", base_branch], cwd=path)
        if rcb != 0:
            logger.warning("vibecode: checkout base '%s' failed: %s", base_branch, errb[:200])
    # Capture the baseline commit BEFORE cutting the session branch — the cumulative
    # diff for every turn is measured against this fixed sha, never against HEAD.
    _rc, sha, _e = await _run_git(["git", "rev-parse", "HEAD"], cwd=path)
    base_sha = sha.strip()
    await _run_git(["git", "checkout", "-B", branch], cwd=path)
    await _run_git(["git", "config", "user.name", "HarvisVibeCode"], cwd=path)
    await _run_git(["git", "config", "user.email", "vibecode@harvis.local"], cwd=path)
    logger.info(
        "vibecode: created SESSION workspace %s (clone-local from %s, base_sha=%s)",
        path, repo_path, base_sha[:10] if base_sha else "?",
    )
    return {"workspace_path": path, "branch_name": branch, "base_sha": base_sha, "reused": False}


# ─── Local-folder mode (browser File System Access API) ───────────────────────
# The user's REAL folder is held by the browser (Chromium FileSystemDirectoryHandle).
# The backend can't see it, so the browser seeds the session workspace with the folder's
# files, the agent edits that container working tree (git/run_code/run_tests all work),
# and changed files are written BACK to the real folder by the browser after each turn.
# This is "browser-as-filesystem" with the real folder as source of truth + live sink.

_LOCAL_FOLDER_SKIP_PARTS = _SKIP_DIRS | {"dist", ".next", "build", ".cache", "venv", ".turbo"}


async def create_local_folder_session_workspace(
    session_id: str, root: str = SESSION_WORKSPACE_ROOT
) -> dict:
    """Init an EMPTY git workspace for a local-folder session. The baseline commit is
    deferred until the browser seeds the folder's files (see ``seed_local_folder_workspace``),
    so the cumulative diff is measured against the folder's ORIGINAL contents (not "all
    files added"). Returns ``{workspace_path, branch_name, base_sha: None, needs_seed}``."""
    safe = "".join(c for c in (session_id or "") if c.isalnum() or c in "-_")[:64] or "session"
    path = os.path.join(root, safe)
    branch = f"vibecode-{safe}"
    os.makedirs(root, exist_ok=True)
    if os.path.isdir(os.path.join(path, ".git")):
        # Reuse an existing seeded workspace verbatim (persistent across turns/restarts).
        return {"workspace_path": path, "branch_name": branch, "base_sha": None, "reused": True}
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    await _run_git(["git", "init"], cwd=path)
    await _run_git(["git", "config", "user.name", "HarvisVibeCode"], cwd=path)
    await _run_git(["git", "config", "user.email", "vibecode@harvis.local"], cwd=path)
    return {"workspace_path": path, "branch_name": branch, "base_sha": None, "needs_seed": True}


async def seed_local_folder_workspace(
    workspace_path: str, files: list[dict], branch: str
) -> dict:
    """Write the browser-supplied folder snapshot into the workspace, commit it as the
    fixed baseline (``base_sha``), then cut the session branch. ``files`` is a list of
    ``{path, content}`` (relative paths). Path-validated + skip-dir filtered so a hostile
    manifest can't escape the workspace. Returns ``{base_sha, written}``."""
    written = 0
    for f in files or []:
        rel = str((f or {}).get("path") or "").strip().lstrip("/")
        if not rel:
            continue
        norm = rel.replace("\\", "/")
        if any(part in _LOCAL_FOLDER_SKIP_PARTS for part in norm.split("/")):
            continue
        if not validate_agent_path(workspace_path, rel):
            logger.warning("vibecode: rejected out-of-tree seed path %r", rel)
            continue
        dest = os.path.join(workspace_path, rel)
        try:
            os.makedirs(os.path.dirname(dest) or workspace_path, exist_ok=True)
            with open(dest, "w", encoding="utf-8", errors="replace") as fh:
                fh.write((f or {}).get("content") or "")
            written += 1
        except Exception:
            logger.warning("vibecode: failed to seed %r", rel, exc_info=True)
    await _run_git(["git", "add", "-A"], cwd=workspace_path)
    await _run_git(
        ["git", "commit", "--allow-empty", "-m", "vibecode local-folder baseline"],
        cwd=workspace_path,
    )
    _rc, sha, _e = await _run_git(["git", "rev-parse", "HEAD"], cwd=workspace_path)
    await _run_git(["git", "checkout", "-B", branch], cwd=workspace_path)
    logger.info(
        "vibecode: seeded local-folder workspace %s (%d files, base_sha=%s)",
        workspace_path, written, sha.strip()[:10],
    )
    return {"base_sha": sha.strip(), "written": written}


async def collect_local_folder_writeback(workspace_path: str, base_sha: str | None) -> dict:
    """Files the agent CHANGED or DELETED vs the baseline — the payload the browser writes
    back into the user's real folder. Returns ``{changed: [{path, content}], deleted: [path]}``.
    Mirrors the git-mode diff machinery (``add -A`` so new files count)."""
    await _run_git(["git", "add", "-A"], cwd=workspace_path)
    base = base_sha or "HEAD"
    _rc, out, _e = await _run_git(
        ["git", "diff", base, "--name-status", "-z"], cwd=workspace_path
    )
    changed: list[dict] = []
    deleted: list[str] = []
    # `-z` → NUL-separated: STATUS\0PATH\0 (rename = STATUS\0OLD\0NEW\0). Robust to spaces.
    tokens = [t for t in out.split("\0") if t != ""]
    i = 0
    while i < len(tokens):
        status = tokens[i]
        i += 1
        if i >= len(tokens):
            break
        if status and status[0] in ("R", "C"):  # rename/copy: old, new (two paths)
            old = tokens[i]; i += 1
            new = tokens[i] if i < len(tokens) else ""; i += 1
            if status[0] == "R" and old:
                deleted.append(old)  # copy keeps the original; only a rename removes it
            rel = new
        else:
            rel = tokens[i]; i += 1
        if not rel:
            continue
        if status and status[0] == "D":
            deleted.append(rel)
            continue
        fp = os.path.join(workspace_path, rel)
        try:
            if not os.path.exists(fp):
                deleted.append(rel)
            elif os.path.getsize(fp) <= _MAX_FILE_BYTES:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    changed.append({"path": rel, "content": fh.read()})
            # else: too large/binary — skip (the agent rarely writes these)
        except Exception:
            logger.warning("vibecode: writeback read failed for %r", rel, exc_info=True)
    return {"changed": changed, "deleted": deleted}


async def cleanup_session_workspace(workspace_path: str, root: str = SESSION_WORKSPACE_ROOT) -> None:
    """Remove a VibeCode session's PERSISTENT working clone — guarded so we only ever
    delete UNDER the session root. Called on explicit session delete (never per-turn);
    this is the one teardown point for the otherwise-persistent session workspace."""
    try:
        p = Path(workspace_path).resolve()
        r = Path(root).resolve()
        if p != r and str(p).startswith(str(r) + os.sep) and p.exists():
            shutil.rmtree(p, ignore_errors=True)
    except Exception:
        logger.warning("vibecode: session cleanup skipped for %s", workspace_path, exc_info=True)


async def is_clean_tree(repo_path: str) -> bool:
    """True iff the repo's working tree has no uncommitted changes (porcelain empty).
    The clean-tree PRECONDITION for entering in-place mode — a dirty tree would mix the
    user's uncommitted work into the agent's accumulated diff."""
    rc, out, _e = await _run_git(["git", "status", "--porcelain"], cwd=repo_path)
    return rc == 0 and not out.strip()


async def create_inplace_session_workspace(
    session_id: str, repo_path: str, base_branch: str | None = None,
) -> dict:
    """Set up an IN-PLACE VibeCode session: cut a session branch ON the real repo (a
    RW-mounted working tree — NO clone). The agent edits the real files on this branch;
    the diff accumulates vs ``base_sha``. Requires a CLEAN tree (else the diff would mix
    the user's uncommitted work with the agent's). Returns ``{workspace_path=repo_path,
    branch_name, base_sha, base_branch}`` or ``{error}``."""
    if not (repo_path and os.path.isdir(os.path.join(repo_path, ".git"))):
        return {"error": "not a git repo"}
    if not await is_clean_tree(repo_path):
        return {"error": "the repo's working tree is not clean — commit or stash your changes first"}
    safe = "".join(c for c in (session_id or "") if c.isalnum() or c in "-_")[:64] or "session"
    branch = f"vibecode/{safe}"
    if base_branch:
        await _run_git(["git", "checkout", base_branch], cwd=repo_path)
    _rc, cur, _e = await _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    resolved_base = (base_branch or cur.strip() or "main")
    _rc, sha, _e = await _run_git(["git", "rev-parse", "HEAD"], cwd=repo_path)
    base_sha = sha.strip()
    rc, _o, err = await _run_git(["git", "checkout", "-B", branch], cwd=repo_path)
    if rc != 0:
        return {"error": f"could not create the session branch: {(err or _o)[:200]}"}
    await _run_git(["git", "config", "user.name", "HarvisVibeCode"], cwd=repo_path)
    await _run_git(["git", "config", "user.email", "vibecode@harvis.local"], cwd=repo_path)
    logger.info(
        "vibecode: created IN-PLACE session %s on %s (branch %s, base %s, base_sha=%s)",
        session_id, repo_path, branch, resolved_base, base_sha[:10] if base_sha else "?",
    )
    return {
        "workspace_path": repo_path, "branch_name": branch,
        "base_sha": base_sha, "base_branch": resolved_base,
    }


async def cleanup_inplace_session(repo_path: str, base_branch: str | None, branch: str | None) -> None:
    """Tear down an in-place session: discard the session branch's uncommitted changes,
    restore the base branch, delete the session branch. NEVER touches the repo itself
    (it's the user's real repo). Discarding is correct — the user PR'd the work to keep it,
    or is abandoning the session (mirrors clone-mode's rmtree)."""
    try:
        if not (repo_path and os.path.isdir(os.path.join(repo_path, ".git"))):
            return
        await _run_git(["git", "reset", "--hard"], cwd=repo_path)   # drop session-branch edits
        await _run_git(["git", "clean", "-fd"], cwd=repo_path)      # drop untracked files
        if base_branch:
            await _run_git(["git", "checkout", base_branch], cwd=repo_path)
        if branch and branch not in ("main", "master", base_branch or ""):
            await _run_git(["git", "branch", "-D", branch], cwd=repo_path)
        logger.info(
            "vibecode: cleaned up in-place session on %s (deleted %s, restored %s)",
            repo_path, branch, base_branch,
        )
    except Exception:
        logger.warning("vibecode: in-place cleanup skipped for %s", repo_path, exc_info=True)
