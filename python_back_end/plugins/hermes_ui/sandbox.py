"""Each Hermes chat's sandbox: a folder plus a hardened container, shown in the right sidebar.

The folder lives under the backend's own artifact volume at
``<HARVIS_SANDBOX_ROOT>/u<user>/<session>`` and is created the first time the
sidebar looks at it. The container is only started when someone opens a
terminal (or, later, when the chat's agent needs to run something), so a chat
that never uses its sandbox costs one empty directory.

The container is the Build Space's hardened per-session runner
(workspace.terminal_container.ensure_isolated): every capability dropped,
no-new-privileges, uid 1001, memory/CPU/pid limits, the chat's folder as its
only mount at /workspace, and the ``repo-sandbox`` network, which reaches the
internet (pip, npm, git clone) but no Harvis service: not pgsql, not ollama,
not OpenClaw. If that network is missing it starts with no network at all.

The UI addresses the sandbox by a virtual path, ``/sandbox/<session>/workspace``
(the files pane shows the last segment, "workspace"). Everything here resolves
such a path to a real one INSIDE the caller's own ``u<user>`` folder and refuses
anything that escapes it, so a guessed session id can never reach another
person's files. ``HARVIS_SANDBOX_ENABLED=false`` turns the whole thing off.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import os
import re
import secrets
import shutil
from typing import Optional

ROOT = os.getenv("HARVIS_SANDBOX_ROOT", "/data/artifacts/sandboxes")
VIRTUAL = "/sandbox"
CONTAINER_DIR = "/workspace"
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_DATA_URL_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 2000
# Above this the UI warns (no hard cap — the user decided): big app installs are the point.
WARN_BYTES = int(float(os.getenv("HARVIS_SANDBOX_WARN_GB", "20")) * 1024 ** 3)
META = ".harvis"             # Harvis's notes inside a sandbox (the app link prefix, the GPU switch)
_SALT = "proxy-salt"         # per-sandbox secret the app links are signed with; deleting the sandbox rotates it
APP_PREFIX = "/hermes-api/sandbox-app"

_SID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class SandboxError(ValueError):
    """A path or request the sandbox refuses; the message is safe to show."""


def enabled() -> bool:
    return os.getenv("HARVIS_SANDBOX_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def _check_sid(session_id: str) -> str:
    if not _SID_RE.match(session_id or "") or session_id in (".", ".."):
        raise SandboxError("not a sandbox session")
    return session_id


def virtual_cwd(session_id: str) -> Optional[str]:
    """What the UI shows as this chat's working directory (None when off)."""
    if not enabled():
        return None
    try:
        return f"{VIRTUAL}/{_check_sid(session_id)}/workspace"
    except SandboxError:
        return None


def session_dir(user_id: int, session_id: str) -> str:
    return os.path.join(ROOT, f"u{int(user_id)}", _check_sid(session_id))


def runner_key(user_id: int, session_id: str) -> str:
    """The runner container's session key: user-scoped, and short enough that the
    manager's 40-character container-name cut can't make two chats share one."""
    digest = hashlib.sha256(_check_sid(session_id).encode()).hexdigest()[:16]
    return f"hs-u{int(user_id)}-{digest}"


def container_name(user_id: int, session_id: str) -> str:
    """The runner's container name (terminal_container._spawn_isolated's naming)."""
    key = runner_key(user_id, session_id)
    return "harvis-vc-run-" + "".join(c if c.isalnum() or c in "_.-" else "-" for c in key)[:40]


def ensure_dir(user_id: int, session_id: str) -> str:
    """Create the chat's folder (idempotent) with its link secret and a note telling
    the agent where its apps will be served. Returns the folder."""
    base = session_dir(user_id, session_id)
    meta = os.path.join(base, META)
    os.makedirs(meta, mode=0o750, exist_ok=True)
    salt = os.path.join(meta, _SALT)
    if not os.path.exists(salt):
        with open(salt, "w") as f:
            f.write(secrets.token_hex(16))
    prefix = app_prefix(user_id, session_id)
    with open(os.path.join(meta, "app-url-prefix"), "w") as f:
        f.write(prefix + "\n")
    return base


def _key() -> bytes:
    secret = os.getenv("JWT_SECRET") or os.getenv("HARVIS_SANDBOX_LINK_SECRET") or "harvis-dev"
    return hashlib.sha256(("sandbox-app:" + secret).encode()).digest()


def _sign(user_id: int, session_id: str, salt: str) -> str:
    msg = f"{int(user_id)}:{session_id}:{salt}".encode()
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()[:32]


def _salt(user_id: int, session_id: str) -> str:
    try:
        with open(os.path.join(session_dir(user_id, session_id), META, _SALT)) as f:
            return f.read().strip()
    except OSError:
        return ""


def app_prefix(user_id: int, session_id: str) -> str:
    """Where this sandbox's apps are served: ``/hermes-api/sandbox-app/<cap>`` + ``/<port>/``.
    The capability is signed with the sandbox's own secret, so it works without cookies
    (apps run on an opaque origin, see rest_sandbox) and dies when the sandbox is deleted."""
    sid = _check_sid(session_id)
    return f"{APP_PREFIX}/{int(user_id)}.{sid}.{_sign(user_id, sid, _salt(user_id, sid))}"


def verify_cap(cap: str) -> Optional[tuple[int, str]]:
    """``<uid>.<sid>.<sig>`` → (uid, sid) when the signature matches the live sandbox."""
    try:
        uid_raw, rest = cap.split(".", 1)
        sid, sig = rest.rsplit(".", 1)
        uid = int(uid_raw)
        _check_sid(sid)
    except (ValueError, SandboxError):
        return None
    salt = _salt(uid, sid)
    if not salt or not hmac.compare_digest(sig, _sign(uid, sid, salt)):
        return None
    return uid, sid


def gpu_wanted(user_id: int, session_id: str) -> bool:
    return os.path.exists(os.path.join(session_dir(user_id, session_id), META, "gpu"))


def set_gpu(user_id: int, session_id: str, on: bool) -> None:
    marker = os.path.join(ensure_dir(user_id, session_id), META, "gpu")
    if on:
        open(marker, "w").close()
    elif os.path.exists(marker):
        os.remove(marker)


def usage_bytes(user_id: int, session_id: str, limit_files: int = 200_000) -> int:
    """Bytes on disk under the chat's folder (symlinks not followed; stops counting after limit_files)."""
    total, seen = 0, 0
    for dirpath, dirnames, filenames in os.walk(session_dir(user_id, session_id)):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_blocks * 512
            except OSError:
                pass
            seen += 1
            if seen >= limit_files:
                return total
    return total


def delete_dir(user_id: int, session_id: str) -> None:
    shutil.rmtree(session_dir(user_id, session_id), ignore_errors=True)


def resolve(user_id: int, vpath: str, *, create: bool = False) -> tuple[str, str, str]:
    """``/sandbox/<sid>/workspace[/rest]`` → (session_id, real path, path inside the container).

    Raises SandboxError for anything that isn't such a path or that would
    leave the session's folder (``..``, symlinks pointing out)."""
    if not enabled():
        raise SandboxError("the sandbox is turned off on this server")
    parts = [p for p in (vpath or "").replace("\\", "/").split("/") if p]
    if len(parts) < 3 or "/" + parts[0] != VIRTUAL or parts[2] != "workspace":
        raise SandboxError("not a sandbox path")
    sid = _check_sid(parts[1])
    rest = parts[3:]
    if any(p in (".", "..") for p in rest):
        raise SandboxError("path escapes the sandbox")
    base = ensure_dir(user_id, sid) if create else session_dir(user_id, sid)
    real = os.path.join(base, *rest)
    base_real = os.path.realpath(base)
    real_real = os.path.realpath(real)
    if real_real != base_real and not real_real.startswith(base_real + os.sep):
        raise SandboxError("path escapes the sandbox")
    inner = CONTAINER_DIR + ("/" + "/".join(rest) if rest else "")
    return sid, real_real, inner


def to_virtual(session_id: str, rel: str) -> str:
    rel = rel.replace(os.sep, "/").strip("/")
    return f"{VIRTUAL}/{session_id}/workspace" + (f"/{rel}" if rel and rel != "." else "")


def list_dir(user_id: int, vpath: str) -> dict:
    sid, real, _ = resolve(user_id, vpath, create=True)
    if not os.path.isdir(real):
        raise SandboxError("not a folder")
    base = os.path.realpath(session_dir(user_id, sid))
    entries = []
    with os.scandir(real) as it:
        for e in it:
            if len(entries) >= MAX_ENTRIES:
                break
            if real == base and e.name == META:
                continue  # Harvis's own bookkeeping (link secret, GPU switch) stays out of the tree
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            entries.append({"name": e.name, "isDirectory": is_dir,
                            "path": to_virtual(sid, os.path.relpath(os.path.join(real, e.name), base))})
    entries.sort(key=lambda x: (not x["isDirectory"], x["name"].lower()))
    return {"entries": entries}


def read_text(user_id: int, vpath: str) -> dict:
    _, real, _ = resolve(user_id, vpath)
    if not os.path.isfile(real):
        raise SandboxError("not a file")
    size = os.path.getsize(real)
    if size > MAX_TEXT_BYTES:
        raise SandboxError("file is too large to open here")
    with open(real, "rb") as f:
        raw = f.read()
    if b"\x00" in raw[:8192]:
        return {"content": "", "binary": True, "path": vpath, "size": size}
    return {"content": raw.decode("utf-8", errors="replace"), "path": vpath, "size": size}


def read_data_url(user_id: int, vpath: str) -> dict:
    _, real, _ = resolve(user_id, vpath)
    if not os.path.isfile(real):
        raise SandboxError("not a file")
    if os.path.getsize(real) > MAX_DATA_URL_BYTES:
        raise SandboxError("file is too large to preview")
    mime = mimetypes.guess_type(real)[0] or "application/octet-stream"
    with open(real, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return {"dataUrl": f"data:{mime};base64,{data}"}


def write_text(user_id: int, vpath: str, content: str) -> dict:
    _, real, _ = resolve(user_id, vpath)
    if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
        raise SandboxError("file is too large to save here")
    if not os.path.isdir(os.path.dirname(real)):
        raise SandboxError("the folder doesn't exist")
    if os.path.isdir(real):
        raise SandboxError("that's a folder")
    with open(real, "w", encoding="utf-8") as f:
        f.write(content)
    return {"ok": True, "path": vpath}


def git_root(user_id: int, vpath: str) -> dict:
    """Nearest folder holding .git, walking up but never past the session folder."""
    sid, real, _ = resolve(user_id, vpath)
    base = os.path.realpath(session_dir(user_id, sid))
    cur = real if os.path.isdir(real) else os.path.dirname(real)
    while cur.startswith(base):
        if os.path.exists(os.path.join(cur, ".git")):
            return {"root": to_virtual(sid, os.path.relpath(cur, base))}
        if cur == base:
            break
        cur = os.path.dirname(cur)
    return {"root": None}


def agent_note(user_id: int, session_id: str) -> str:
    """What an agent working in this chat's sandbox needs to know, prepended to its task."""
    prefix = app_prefix(user_id, session_id)
    gpu = "The GPU is ON for this sandbox." if gpu_wanted(user_id, session_id) else (
        "There is no GPU unless the user turns it on for this chat (sandbox menu); prefer CPU builds.")
    return f"""You are working in this chat's own sandbox: a Linux container (Debian, Node 20,
Python 3, git) with internet access but no access to Harvis's services. Its folder is
/workspace; everything you create there persists and the user sees it in the Files pane.
- Put each repo/app in its own folder under /workspace (e.g. /workspace/apps/<name>).
  Use a virtualenv (python3 -m venv) or local node_modules; there is no root/sudo.
- Start servers in the background so your command returns, bound to 0.0.0.0:
  nohup <command> > /workspace/.harvis/<name>.log 2>&1 &   then check the log.
- Apps are served to the user at {prefix}/<port>/ . Web UIs that need a base path
  (Gradio: GRADIO_ROOT_PATH; others: --root-path/--base-url) should be given
  {prefix}/<port> . When one is up, tell the user the port and that it's in the
  sandbox menu (Open).
- {gpu}
- Big downloads cost the user disk; say roughly how large an install is before starting it."""
