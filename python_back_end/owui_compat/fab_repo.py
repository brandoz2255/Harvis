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


# The sandbox always forces the dev server onto this port bound to 0.0.0.0 so the
# backend can reach it over the isolated network. repo_sandbox reads the same env.
_DEV_PORT = int(os.getenv("HARVIS_ADAPTIVE_REPO_DEV_PORT", "3000") or "3000")


def _node_run_plan(mgr: str, script: str, deps: dict) -> dict:
    """How to actually START a Node app's dev server bound to 0.0.0.0:_DEV_PORT so
    the sandbox preview can reach it. Framework-specific flags because dev servers
    default to 127.0.0.1 (unreachable from the proxy) and their own ports.

    Returns {web, framework, port, dev_cmd, env}. ``web`` is False when the repo
    exposes no obvious dev server (a CLI/library) — the caller reports that honestly.
    """
    port = _DEV_PORT
    if not script:
        # No dev/start script at all (CLI/library) — nothing to serve or preview.
        return {"web": False, "framework": "node", "port": port, "dev_cmd": None, "env": {}}
    run = f"{mgr} run {script}"
    # Flag forwarding differs by manager: npm needs `-- <flags>`; pnpm/yarn forward
    # trailing flags directly (a literal `--` would reach the framework and be
    # mis-parsed, so the dev server would ignore --host/--port).
    sep = " -- " if mgr == "npm" else " "
    if "vite" in deps or "@sveltejs/kit" in deps or "astro" in deps or "nuxt" in deps:
        fw = "vite" if "vite" in deps else ("sveltekit" if "@sveltejs/kit" in deps else ("astro" if "astro" in deps else "nuxt"))
        return {"web": True, "framework": fw, "port": port,
                "dev_cmd": f"{run}{sep}--host 0.0.0.0 --port {port}", "env": {}}
    if "next" in deps:
        return {"web": True, "framework": "next", "port": port,
                "dev_cmd": f"{run}{sep}-H 0.0.0.0 -p {port}", "env": {}}
    if "@angular/core" in deps or "@angular/cli" in deps:
        return {"web": True, "framework": "angular", "port": port,
                "dev_cmd": f"{run}{sep}--host 0.0.0.0 --port {port}", "env": {}}
    if "react-scripts" in deps or "vue-cli-service" in deps:
        # CRA / vue-cli honor HOST + PORT env, no CLI flags.
        fw = "cra" if "react-scripts" in deps else "vue-cli"
        return {"web": True, "framework": fw, "port": port, "dev_cmd": run,
                "env": {"HOST": "0.0.0.0", "PORT": str(port)}}
    # Unknown framework with a dev/start script — best effort: HOST/PORT env is the
    # widest-honored convention (express, http-server, custom node servers).
    return {"web": True, "framework": "node", "port": port, "dev_cmd": run,
            "env": {"HOST": "0.0.0.0", "PORT": str(port)}}


def _read_pyproject(root: str) -> str:
    try:
        with open(os.path.join(root, "pyproject.toml"), encoding="utf-8", errors="replace") as fh:
            return fh.read(120000)
    except OSError:
        return ""


def _poetry_dep_names(root: str) -> list[str]:
    """Package names from [tool.poetry.dependencies] (minus python). Poetry uses
    caret/tilde constraints pip can't parse, so we install names unpinned — the
    sandbox synthesizes a runnable env, it isn't reproducing a lockfile."""
    text = _read_pyproject(root)
    m = re.search(r"(?ms)^\s*\[tool\.poetry\.dependencies\]\s*$(.*?)(?=^\s*\[|\Z)", text)
    if not m:
        return []
    names: list[str] = []
    for km in re.finditer(r"(?m)^\s*([A-Za-z0-9._\-]+)\s*=", m.group(1)):
        n = km.group(1).lower()
        if n != "python" and n not in names:
            names.append(n)
    return names


def _python_manager(root: str, has) -> tuple[str, str | None, str]:
    """(manager, install_cmd, run_prefix) for a Python checkout — from lockfiles
    and manifests only, nothing runs. The prefix goes in front of dev commands so
    they execute inside the manager's environment (``uv run``).

    Installs run in a throwaway Debian sandbox whose system Python is
    externally-managed (PEP 668), so plain ``pip install`` is blocked. uv is the
    fast, reliable path; system installs need --break-system-packages (safe — the
    container is disposable). uv-managed projects use their own venv (no override)."""
    pyproject = has("pyproject.toml")
    reqs = has("requirements.txt")
    setup = has("setup.py")
    text = _read_pyproject(root) if pyproject else ""
    # Line-anchored table headers, not bare substrings — a literal "[project]" inside
    # a description string or comment must not flip the install strategy.
    has_project = bool(re.search(r"(?m)^\s*\[project\]\s*$", text))
    has_uv = bool(re.search(r"(?m)^\s*\[tool\.uv\]", text))
    has_poetry = bool(re.search(r"(?m)^\s*\[tool\.poetry\b", text))
    SYS = "uv pip install --system --break-system-packages"

    # 1. uv-managed (lockfile or [tool.uv]) — uv builds + uses its own venv, exact.
    if has("uv.lock") or has_uv:
        return "uv", "uv sync", "uv run "
    # 2. explicit requirements.txt — uv follows -r/-c includes; plain system install.
    if reqs:
        return "pip", f"{SYS} -r requirements.txt", ""
    # 3. PEP 621 pyproject ([project] table) with no lock — uv sync resolves it.
    if pyproject and has_project:
        return "uv", "uv sync", "uv run "
    # 4. poetry project — poetry isn't in the image and poetry-core's build fails on
    #    app-shaped repos (package-mode=false / flat layout), so install the declared
    #    deps directly (unpinned) instead of trying to build the project.
    if pyproject and has_poetry:
        names = _poetry_dep_names(root)
        if names:
            return "poetry", f"{SYS} " + " ".join(names), ""
        return "poetry", f"{SYS} .", ""
    # 5. setuptools pyproject / setup.py — editable install of the project itself.
    if pyproject or setup:
        return "pip", f"{SYS} -e .", ""
    return "pip", None, ""


def _toml_array(body: str, key: str) -> str:
    """Content of a ``key = [ ... ]`` array from a TOML table body, extracted with a
    bracket-balanced scan so a multi-line array — and bracketed extras like
    ``"uvicorn[standard]"`` — don't truncate it. Returns '' when the key is absent."""
    m = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*\[", body)
    if not m:
        return ""
    start = m.end() - 1  # index of the opening '['
    depth = 0
    for i in range(start, len(body)):
        c = body[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return body[start + 1:i]
    return body[start + 1:]


def _python_deps(root: str) -> set[str]:
    """Lowercase python dependency names from requirements.txt (following nested
    ``-r`` includes, cycle-safe) + the real dependency declarations in pyproject.toml.
    Regex-based (stdlib only) — membership checks like 'fastapi' in deps; never
    executed. Deliberately ignores keywords/classifiers/optional-extras, tool config,
    and ``-c`` constraints so an *optional* (or merely pinned) postgres client isn't
    mistaken for a hard service requirement."""
    names: set[str] = set()
    seen: set[str] = set()

    def scan_requirements(path: str, depth: int) -> None:
        path = os.path.normpath(path)
        if depth > 3 or path in seen or not os.path.isfile(path):
            return
        seen.add(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return
        base = os.path.dirname(path)
        root_prefix = os.path.normpath(root) + os.sep
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Follow -r/--requirement includes (real deps). NOT -c/--constraint:
            # constraint files pin transitive packages that aren't necessarily used,
            # so treating them as deps would falsely flag services.
            inc = re.match(r"^(?:-r|--requirement)[=\s]+(\S+)", line)
            if inc:
                ref = os.path.normpath(os.path.join(base, inc.group(1)))
                if ref == os.path.normpath(root) or ref.startswith(root_prefix):
                    scan_requirements(ref, depth + 1)
                continue
            if line.startswith("-"):
                continue
            m = re.match(r"[A-Za-z0-9._\-]+", line)
            if m:
                names.add(m.group(0).lower())

    scan_requirements(os.path.join(root, "requirements.txt"), 0)

    text = _read_pyproject(root)
    if text:
        # [project] main dependency array only — anchored to the table body so a
        # tool-table `dependencies=[...]` can't be captured instead, and NOT
        # optional-dependencies/keywords.
        proj = re.search(r"(?ms)^\s*\[project\]\s*$(.*?)(?=^\s*\[|\Z)", text)
        if proj:
            for q in re.finditer(r'["\']([A-Za-z0-9._\-]+)', _toml_array(proj.group(1), "dependencies")):
                names.add(q.group(1).lower())
        # [tool.poetry.dependencies] table keys (minus python).
        pm = re.search(r"(?ms)^\s*\[tool\.poetry\.dependencies\]\s*$(.*?)(?=^\s*\[|\Z)", text)
        if pm:
            for km in re.finditer(r"(?m)^\s*([A-Za-z0-9._\-]+)\s*=", pm.group(1)):
                names.add(km.group(1).lower())
    names.discard("python")
    return names


def _node_deps(pkg_dir: str) -> dict:
    """dependencies + devDependencies from a dir's package.json ({} on any miss)."""
    try:
        import json
        with open(os.path.join(pkg_dir, "package.json"), encoding="utf-8") as fh:
            pkg = json.load(fh) or {}
        return {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    except Exception:  # noqa: BLE001
        return {}


def _file_mentions(root: str, name: str, needle: str) -> bool:
    p = os.path.join(root, name)
    if not os.path.isfile(p):
        return False
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return needle in fh.read(20000)
    except OSError:
        return False


def _python_run_plan(root: str, deps: set | dict, has) -> dict:
    """How to START a Python app's web server bound to 0.0.0.0:_DEV_PORT — the
    python twin of _node_run_plan. Framework-specific commands because each dev
    server has its own host/port flags. Returns {web, framework, port, dev_cmd,
    env}; ``web`` is False when the repo exposes no single-process web server."""
    port = _DEV_PORT
    _mgr, _install, prefix = _python_manager(root, has)
    uv_managed = prefix.strip() == "uv run"

    def first(*names: str) -> str | None:
        for n in names:
            if os.path.isfile(os.path.join(root, n)):
                return n
        return None

    if "streamlit" in deps:
        entry = first("streamlit_app.py", "Home.py", "app.py", "main.py",
                      "src/streamlit_app.py", "src/app.py", "src/main.py")
        if entry:
            return {"web": True, "framework": "streamlit", "port": port,
                    "dev_cmd": (f"{prefix}streamlit run {entry} --server.address 0.0.0.0 "
                                f"--server.port {port} --server.headless true"),
                    "env": {}}
    if "fastapi" in deps or "uvicorn" in deps or "starlette" in deps:
        fw = "fastapi" if "fastapi" in deps else ("starlette" if "starlette" in deps else "asgi")
        for path, module in (("api/main.py", "api.main:app"), ("app/main.py", "app.main:app"),
                             ("backend/main.py", "backend.main:app"), ("server/main.py", "server.main:app"),
                             ("src/main.py", "src.main:app"), ("src/app/main.py", "src.app.main:app"),
                             ("main.py", "main:app"), ("app.py", "app:app"),
                             ("asgi.py", "asgi:app"), ("src/app.py", "src.app:app")):
            if has(path):
                # The sandbox image ships no ASGI server; if the repo doesn't declare
                # uvicorn, add it (uv projects get it ephemerally via --with; system
                # installs get it appended to the install command in detect_stack).
                needs_uvicorn = "uvicorn" not in deps
                if needs_uvicorn and uv_managed:
                    cmd = f"uv run --with uvicorn uvicorn {module} --host 0.0.0.0 --port {port}"
                else:
                    cmd = f"{prefix}uvicorn {module} --host 0.0.0.0 --port {port}"
                plan = {"web": True, "framework": fw, "port": port, "dev_cmd": cmd, "env": {}}
                if needs_uvicorn and not uv_managed:
                    plan["pip_extras"] = ["uvicorn"]
                return plan
    if has("manage.py"):
        return {"web": True, "framework": "django", "port": port,
                "dev_cmd": f"{prefix}python manage.py runserver 0.0.0.0:{port}", "env": {}}
    if "flask" in deps or _file_mentions(root, "app.py", "Flask"):
        entry = first("app.py", "main.py", "wsgi.py", "src/app.py", "src/main.py")
        if entry:
            return {"web": True, "framework": "flask", "port": port,
                    "dev_cmd": f"{prefix}flask run --host 0.0.0.0 --port {port}",
                    "env": {"FLASK_APP": entry}}
        # flask is in deps but no entry file is locatable — don't invent a
        # nonexistent app.py that would fail with "Could not locate a Flask app".
    return {"web": False, "framework": "python", "port": port, "dev_cmd": None, "env": {}}


# External services we can recognize in compose files / dependency lists, with
# the human label used in blocked_reason ("needs a SurrealDB database + ...").
_KNOWN_SERVICES = {
    "surrealdb": "a SurrealDB database",
    "postgres": "a PostgreSQL database",
    "pgvector": "a PostgreSQL (pgvector) database",
    "mysql": "a MySQL database",
    "mariadb": "a MariaDB database",
    "redis": "a Redis cache/queue",
    "mongo": "a MongoDB database",
    "minio": "a MinIO object store",
    "elasticsearch": "an Elasticsearch index",
    "opensearch": "an OpenSearch index",
    "rabbitmq": "a RabbitMQ broker",
    "kafka": "a Kafka broker",
    "qdrant": "a Qdrant vector DB",
    "weaviate": "a Weaviate vector DB",
    "milvus": "a Milvus vector DB",
    "clickhouse": "a ClickHouse database",
}

# Python client packages that fingerprint an external service requirement. Kept in
# sync with _KNOWN_SERVICES so a dependency-only signal (no compose file) is still
# caught — otherwise the same app is honestly refused with a compose file but
# wrongly approved without one.
_PY_DEP_SERVICES = (
    ("surrealdb", "surrealdb"),
    ("psycopg", "postgres"), ("psycopg2", "postgres"),
    ("psycopg2-binary", "postgres"), ("asyncpg", "postgres"),
    ("redis", "redis"), ("aioredis", "redis"),
    ("pymongo", "mongo"), ("motor", "mongo"),
    ("mysqlclient", "mysql"), ("pymysql", "mysql"), ("aiomysql", "mysql"), ("mysql-connector-python", "mysql"),
    ("elasticsearch", "elasticsearch"), ("opensearch-py", "opensearch"),
    ("pika", "rabbitmq"), ("kombu", "rabbitmq"), ("aio-pika", "rabbitmq"),
    ("confluent-kafka", "kafka"), ("aiokafka", "kafka"),
    ("qdrant-client", "qdrant"), ("weaviate-client", "weaviate"), ("pymilvus", "milvus"),
    ("clickhouse-driver", "clickhouse"), ("clickhouse-connect", "clickhouse"),
    ("minio", "minio"),
)


def _parse_compose(root: str) -> list[tuple[str, str | None]]:
    """(service_name, image) pairs from a docker-compose file. Line-regex parse —
    the compose file is READ, never executed (Phase C provisioning is design-only)."""
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                lines = fh.read(120000).splitlines()
        except OSError:
            return []
        out: list[list] = []
        in_services, svc_indent = False, None
        for ln in lines:
            if re.match(r"^services:\s*(#.*)?$", ln):
                in_services = True
                continue
            if in_services and re.match(r"^\S", ln):
                in_services = False  # next top-level key ends the block
            if not in_services:
                continue
            m = re.match(r"^(\s+)([\w.\-]+):\s*(#.*)?$", ln)
            if m:
                indent = len(m.group(1))
                if svc_indent is None:
                    svc_indent = indent
                if indent == svc_indent:
                    out.append([m.group(2), None])
                    continue
            m = re.match(r"^\s+image:\s*[\"']?([^\s\"'#]+)", ln)
            if m and out:
                out[-1][1] = m.group(1)
        return [(n, img) for n, img in out]
    return []


def _env_required(root: str) -> list[str]:
    """Env var names from .env.example/.env.sample that look REQUIRED (keys,
    secrets, passwords, DB URLs, encryption material). Names only — no values."""
    keys: list[str] = []
    for name in (".env.example", ".env.sample", ".env.template"):
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    m = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", ln)
                    if not m:
                        continue
                    k = m.group(1)
                    if (k.endswith(("_KEY", "_SECRET", "_PASSWORD", "_TOKEN"))
                            or k == "DATABASE_URL" or k.startswith("SURREAL_")
                            or "ENCRYPTION" in k) and k not in keys:
                        keys.append(k)
        except OSError:
            pass
    return keys[:20]


def detect_services(root: str, run_plan: dict | None = None) -> dict:
    """The honest service-requirement graph for a checkout — compose files, .env
    examples, directory layout, and manifests are READ, nothing executes. Answers:
    what does this repo actually need to run, and can the CURRENT single-container
    sandbox run it? Multi-service repos (DB + worker + separate frontend) get a
    truthful blocked_reason instead of a doomed start attempt; provisioning those
    services is Phase C (design-only for now — see provision_note)."""
    def has(*names: str) -> bool:
        return any(os.path.isfile(os.path.join(root, n)) for n in names)

    py_deps = _python_deps(root)
    node_root_deps = _node_deps(root) if has("package.json") else {}
    fe_dir = next((d for d in ("frontend", "ui", "web", "client")
                   if os.path.isfile(os.path.join(root, d, "package.json"))), None)
    fe_deps = _node_deps(os.path.join(root, fe_dir)) if fe_dir else {}
    api_dir = next((d for d in ("api", "backend", "server")
                    if os.path.isdir(os.path.join(root, d))), None)

    py_present = has("pyproject.toml", "requirements.txt", "setup.py")
    node_present = has("package.json") or fe_dir is not None
    runtime = ("python+node" if (py_present and node_present)
               else "node" if node_present else "python" if py_present else "unknown")

    managers: list[str] = []
    if py_present:
        managers.append(_python_manager(root, has)[0])
    if node_present:
        node_dir = os.path.join(root, fe_dir) if (fe_dir and not has("package.json")) else root
        managers.append("pnpm" if os.path.isfile(os.path.join(node_dir, "pnpm-lock.yaml"))
                        else "yarn" if os.path.isfile(os.path.join(node_dir, "yarn.lock")) else "npm")
    package_manager = "+".join(managers) or "unknown"

    frameworks: list[str] = []
    for dep in ("fastapi", "starlette", "django", "flask", "streamlit"):
        if dep in py_deps:
            frameworks.append(dep)
    node_deps_all = {**node_root_deps, **fe_deps}
    for dep, fw in (("next", "next"), ("vite", "vite"), ("@sveltejs/kit", "sveltekit"),
                    ("astro", "astro"), ("nuxt", "nuxt"), ("@angular/core", "angular"),
                    ("react-scripts", "cra"), ("express", "express")):
        if dep in node_deps_all and fw not in frameworks:
            frameworks.append(fw)

    # External services: compose declarations first, then client-lib fingerprints.
    services: list[dict] = []

    def add_service(name: str, image_hint: str | None, why: str) -> None:
        if not any(s["name"] == name for s in services):
            services.append({"name": name, "image_hint": image_hint, "why": why})

    worker = False
    for svc, image in _parse_compose(root):
        blob = f"{svc} {image or ''}".lower()
        if "worker" in svc.lower():
            worker = True
            continue
        for key in _KNOWN_SERVICES:
            if key in blob:
                add_service(key, image, f"docker-compose declares service '{svc}'"
                            + (f" (image {image})" if image else ""))
                break
    for dep, key in _PY_DEP_SERVICES:
        if dep in py_deps:
            add_service(key, None, f"python dependency '{dep}'")
    if "celery" in py_deps:
        worker = True
    if os.path.isdir(os.path.join(root, "worker")) or os.path.isdir(os.path.join(root, "workers")):
        worker = True

    env_required = _env_required(root)
    web = bool(run_plan and run_plan.get("web"))

    processes: list[dict] = []
    if py_present:
        processes.append({"name": api_dir or "api", "role": "api",
                          "cmd": (run_plan or {}).get("dev_cmd")})
    if fe_dir:
        fe_mgr = ("pnpm" if os.path.isfile(os.path.join(root, fe_dir, "pnpm-lock.yaml"))
                  else "yarn" if os.path.isfile(os.path.join(root, fe_dir, "yarn.lock")) else "npm")
        processes.append({"name": fe_dir, "role": "frontend", "cmd": f"{fe_mgr} run dev"})
    elif node_present and not py_present:
        processes.append({"name": "web", "role": "frontend", "cmd": (run_plan or {}).get("dev_cmd")})
    if worker:
        processes.append({"name": "worker", "role": "worker", "cmd": None})

    multi_service = bool(services) or bool(fe_dir and (api_dir or py_present)) or worker
    runnable_now = web and not multi_service

    blocked_reason = None
    provision_note = None
    if multi_service:
        needs = [_KNOWN_SERVICES.get(s["name"], f"a {s['name']} service") for s in services]
        if fe_dir and (api_dir or py_present):
            fe_labels = {"next": "Next.js", "vite": "Vite", "sveltekit": "SvelteKit", "astro": "Astro", "nuxt": "Nuxt"}
            fe_fw = next((f for f in fe_labels if f in frameworks), None)
            needs.append(f"a separate {fe_labels.get(fe_fw, 'Node.js')} frontend")
        if worker:
            needs.append("a background worker process")
        if env_required:
            shown = ", ".join(env_required[:3]) + ("…" if len(env_required) > 3 else "")
            needs.append(f"required env ({shown})")
        blocked_reason = ("needs " + " + ".join(needs) + "; the single-container sandbox can start "
                          "one process but can't provision external services yet.")
        side = "/".join(s["name"] for s in services) or "service"
        provision_note = (f"Phase C: a trusted {side} sidecar + a multi-process "
                          "supervisor would fully open this.")
    elif not web:
        blocked_reason = "no web server entrypoint detected — looks like a CLI tool or library; nothing to serve."

    return {
        "runtime": runtime,
        "package_manager": package_manager,
        "frameworks": frameworks,
        "processes": processes,
        "services": services,
        "env_required": env_required,
        "multi_service": multi_service,
        "runnable_now": runnable_now,
        "blocked_reason": blocked_reason,
        "provision_note": provision_note,
    }


def _node_stack(root: str, has) -> dict:
    """The stack dict for a repo with a root package.json (no requirements yet)."""
    mgr = "pnpm" if has("pnpm-lock.yaml") else "yarn" if has("yarn.lock") else "npm"
    scripts, deps = {}, {}
    try:
        import json
        with open(os.path.join(root, "package.json"), encoding="utf-8") as fh:
            pkg = json.load(fh) or {}
        scripts = pkg.get("scripts", {}) or {}
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    except Exception:  # noqa: BLE001
        scripts, deps = {}, {}
    run = "dev" if "dev" in scripts else "start" if "start" in scripts else None
    return {
        "stack": "Node.js", "manager": mgr,
        "install": f"{mgr} install",
        "build": f"{mgr} run build" if "build" in scripts else None,
        "start": f"{mgr} run {run}" if run else None,
        "run_plan": _node_run_plan(mgr, run, deps),
    }


def _python_stack(root: str, has) -> dict:
    """The stack dict for a Python checkout (pyproject/requirements/setup.py)."""
    p_mgr, install, _prefix = _python_manager(root, has)
    plan = _python_run_plan(root, _python_deps(root), has)
    extras = plan.get("pip_extras")
    if extras and install:
        # The chosen dev server isn't a declared dependency — add it to the system
        # install so the run doesn't die at start with "<server>: not found".
        install = install + " && uv pip install --system --break-system-packages " + " ".join(extras)
    return {
        "stack": "Python", "manager": p_mgr,
        "install": install,
        "build": None,
        "start": plan["dev_cmd"] or ("python main.py" if has("main.py")
                                     else "python app.py" if has("app.py") else None),
        "run_plan": plan,
    }


def detect_stack(root: str) -> dict:
    """Detect the runtime + likely setup commands from manifest files. Suggestions
    only — nothing runs. Real inference from real files. Every result also carries
    run_plan (the single-process web dev server, if any) and requirements (the
    honest service graph — whether the current sandbox can actually run this)."""
    def has(*names: str) -> bool:
        return any(os.path.isfile(os.path.join(root, n)) for n in names)

    node = has("package.json")
    py = has("pyproject.toml", "requirements.txt", "setup.py")
    if node and py:
        # Many Python web apps also carry a package.json for asset tooling (tailwind,
        # webpack), and many Node apps carry a stray setup.py. Pick the runtime that
        # can actually serve a single-process web app: Python wins when it exposes a
        # web server (Flask/FastAPI/Django/Streamlit) — even alongside a package.json;
        # otherwise Node wins if IT can run (a dev/start script or a known framework);
        # only when neither can serve do we fall back to Python.
        n_out = _node_stack(root, has)
        p_out = _python_stack(root, has)
        p_web = bool(p_out["run_plan"].get("web"))
        n_web = bool(n_out["run_plan"].get("web"))
        out = p_out if p_web else (n_out if n_web else p_out)
    elif node:
        out = _node_stack(root, has)
    elif py:
        out = _python_stack(root, has)
    elif has("go.mod"):
        out = {"stack": "Go", "manager": "go", "install": "go mod download", "build": "go build ./...", "start": "go run ."}
    elif has("Cargo.toml"):
        out = {"stack": "Rust", "manager": "cargo", "install": "cargo fetch", "build": "cargo build", "start": "cargo run"}
    elif has("Gemfile"):
        out = {"stack": "Ruby", "manager": "bundler", "install": "bundle install", "build": None, "start": None}
    elif has("Dockerfile"):
        out = {"stack": "Docker", "manager": "docker", "install": None, "build": "docker build -t app .", "start": "docker run app"}
    else:
        out = {"stack": "Unknown", "manager": None, "install": None, "build": None, "start": None}
    if "run_plan" not in out:
        out["run_plan"] = {"web": False, "framework": (out["stack"] or "unknown").lower(),
                           "port": _DEV_PORT, "dev_cmd": None, "env": {}}
    out["requirements"] = detect_services(root, out["run_plan"])
    return out


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
