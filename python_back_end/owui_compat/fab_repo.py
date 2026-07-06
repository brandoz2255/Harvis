"""Adaptive Workspace Repo Runner (surface pass) — clone a public repo into an
isolated per-space checkout, read its setup, detect the stack, and surface real
terminal output. Design split for honesty + safety:

  * CLONE + INSPECT are REAL and safe: a shallow ``git clone`` of a validated
    public HTTPS URL into a per-user/per-space dir on the appuser-owned artifact
    volume, then read-only file parsing (README, package manifests). No code from
    the repo executes here — so a plain checkout dir is the correct risk model
    (this is NOT a security sandbox; nothing runs to need one).
  * RUN (install/build/start) is a HIGHER-LANE capability gated behind
    ``HARVIS_ADAPTIVE_REPO_RUN_ENABLED`` (default OFF). Until a real isolated
    toolchain sandbox is wired, the run endpoint refuses honestly rather than
    executing untrusted setup in the backend container. "Sandbox" language is
    reserved for that gated lane — the clone stage never claims it.
  * The terminal shows genuine output only — the git clone log and read-only
    inspection commands (git log, ls). Nothing is fabricated.

Pure standard library (subprocess/os/re/json) — backend picks it up on a restart.
"""
from __future__ import annotations

import os
import re
import subprocess

_TRUTHY = {"1", "true", "yes", "on"}
# Public HTTPS git hosts only — no ssh, no local paths, no arbitrary hosts.
_URL_RE = re.compile(r"^https://(?:www\.)?(github|gitlab|bitbucket)\.(?:com|org)/[\w.\-]+/[\w.\-]+?(?:\.git)?/?$", re.I)
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", ".cache"}
# Cap a single checkout so one huge repo can't fill the shared artifact volume.
_MAX_CLONE_MB = int(os.getenv("HARVIS_ADAPTIVE_REPO_MAX_MB", "500") or "500")


def repo_run_enabled() -> bool:
    return (os.getenv("HARVIS_ADAPTIVE_REPO_RUN_ENABLED") or "").strip().lower() in _TRUTHY


def _root() -> str:
    return os.path.join(os.getenv("ARTIFACT_STORAGE_DIR", "/data/artifacts"), "harvis-adaptive-repos")


def repo_dir(user_id: int, space_id: str) -> str:
    return os.path.join(_root(), str(int(user_id)), space_id)


def validate_url(url: str) -> str | None:
    """Return a normalized clone URL, or None if it isn't an allowed public host."""
    u = (url or "").strip()
    if not _URL_RE.match(u):
        return None
    return u if u.endswith(".git") else u + ".git"


def _run_git(args: list[str], cwd: str | None = None, timeout: int = 90) -> tuple[int, str]:
    """Run a git command with network + credential prompts disabled; return (rc, combined output)."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"  # never hang on an auth prompt
    env["GCM_INTERACTIVE"] = "never"
    try:
        p = subprocess.run(
            ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"$ git {' '.join(args)}\n(timed out after {timeout}s)"
    except Exception as e:  # noqa: BLE001
        return 1, f"$ git {' '.join(args)}\n{e}"


def clone(user_id: int, space_id: str, url: str) -> dict:
    """Shallow-clone a validated public repo into the space's per-space checkout
    dir. Real git, real output; safe (read-only checkout, no build). Returns the
    clone log. Oversized checkouts are removed to protect the shared volume."""
    clone_url = validate_url(url)
    if not clone_url:
        return {"ok": False, "error": "Only public github/gitlab/bitbucket HTTPS URLs are accepted."}
    dest = repo_dir(user_id, space_id)
    # Fresh clone each time (idempotent) — remove any prior checkout.
    if os.path.isdir(dest):
        _rmrf(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    rc, out = _run_git(["clone", "--depth", "1", "--no-tags", clone_url, dest], timeout=120)
    if rc != 0 or not os.path.isdir(dest):
        return {"ok": False, "error": "Clone failed.", "log": f"$ git clone --depth 1 {clone_url}\n{out}"}
    # Disk guard: a shallow clone still has no size bound — reject + clean up an
    # over-cap checkout rather than let one repo fill the shared artifact volume.
    size_mb = _dir_size_mb(dest)
    if size_mb > _MAX_CLONE_MB:
        _rmrf(dest)
        return {"ok": False, "error": f"Repo is too large ({size_mb} MB > {_MAX_CLONE_MB} MB cap).",
                "log": f"$ git clone --depth 1 {clone_url}\n{out}\n\n(checkout was {size_mb} MB — over the {_MAX_CLONE_MB} MB cap, removed)"}
    rc2, log2 = _run_git(["log", "--oneline", "-5"], cwd=dest, timeout=15)
    name = clone_url.rstrip("/").rsplit("/", 1)[-1][:-4]
    return {
        "ok": True,
        "name": name,
        "url": clone_url,
        "log": f"$ git clone --depth 1 {clone_url}\n{out}\n\n$ git log --oneline -5\n{log2}",
    }


def _rmrf(path: str) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _dir_size_mb(path: str) -> int:
    """Total size of a checkout in MB (symlinks not followed)."""
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(dirpath, f)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total // (1024 * 1024)


def build_tree(root: str, max_entries: int = 250, max_depth: int = 3) -> list[dict]:
    """Top few levels of the checkout as {path, dir} entries — skips heavy dirs."""
    out: list[dict] = []
    root = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))[:40]
        for d in dirnames:
            out.append({"path": os.path.relpath(os.path.join(dirpath, d), root), "dir": True})
        for f in sorted(filenames)[:60]:
            out.append({"path": os.path.relpath(os.path.join(dirpath, f), root), "dir": False})
        if len(out) >= max_entries:
            break
    return sorted(out, key=lambda e: (e["path"].count(os.sep), not e["dir"], e["path"]))[:max_entries]


def read_readme(root: str) -> str:
    for name in os.listdir(root):
        if name.lower().startswith("readme"):
            p = os.path.join(root, name)
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        return fh.read(12000)
                except OSError:
                    return ""
    return ""


def detect_stack(root: str) -> dict:
    """Detect the runtime + likely setup commands from manifest files. Suggestions
    only — nothing runs. Real inference from real files."""
    def has(*names: str) -> bool:
        return any(os.path.isfile(os.path.join(root, n)) for n in names)

    if has("package.json"):
        mgr = "pnpm" if has("pnpm-lock.yaml") else "yarn" if has("yarn.lock") else "npm"
        scripts = {}
        try:
            import json
            with open(os.path.join(root, "package.json"), encoding="utf-8") as fh:
                scripts = (json.load(fh) or {}).get("scripts", {}) or {}
        except Exception:  # noqa: BLE001
            scripts = {}
        run = "dev" if "dev" in scripts else "start" if "start" in scripts else None
        return {
            "stack": "Node.js", "manager": mgr,
            "install": f"{mgr} install",
            "build": f"{mgr} run build" if "build" in scripts else None,
            "start": f"{mgr} run {run}" if run else None,
        }
    if has("pyproject.toml"):
        return {"stack": "Python", "manager": "pip", "install": "pip install -e .", "build": None, "start": None}
    if has("requirements.txt"):
        return {"stack": "Python", "manager": "pip", "install": "pip install -r requirements.txt", "build": None,
                "start": "python main.py" if has("main.py") else "python app.py" if has("app.py") else None}
    if has("go.mod"):
        return {"stack": "Go", "manager": "go", "install": "go mod download", "build": "go build ./...", "start": "go run ."}
    if has("Cargo.toml"):
        return {"stack": "Rust", "manager": "cargo", "install": "cargo fetch", "build": "cargo build", "start": "cargo run"}
    if has("Gemfile"):
        return {"stack": "Ruby", "manager": "bundler", "install": "bundle install", "build": None, "start": None}
    if has("Dockerfile"):
        return {"stack": "Docker", "manager": "docker", "install": None, "build": "docker build -t app .", "start": "docker run app"}
    return {"stack": "Unknown", "manager": None, "install": None, "build": None, "start": None}


def inspect(user_id: int, space_id: str, url: str) -> dict:
    """Clone + read setup + detect stack — the whole real, safe intake."""
    res = clone(user_id, space_id, url)
    if not res.get("ok"):
        return res
    dest = repo_dir(user_id, space_id)
    stack = detect_stack(dest)
    return {
        "ok": True,
        "name": res["name"],
        "url": res["url"],
        "log": res["log"],
        "tree": build_tree(dest),
        "readme": read_readme(dest),
        "stack": stack,
    }
