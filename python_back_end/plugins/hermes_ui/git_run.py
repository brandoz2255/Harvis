"""Run git for the Hermes UI's review pane, safely, inside one user's sandbox.

The folder is writable by the person (and by anything their sandbox container
runs), so everything inside it is untrusted input to git: ``.git/config`` can name
programs git will run (filters, fsmonitor, diff drivers, editors), ``.git`` can be
a file or symlink pointing at somebody else's repository, and objects can borrow
from other repositories through ``alternates``. This module refuses such a repo
and, for the ones it accepts, pins git down:

* the repo is found by walking up from a path that ``sandbox.resolve`` already
  confined to ``ROOT/u<uid>/<session>``, and never above that folder;
* ``GIT_DIR`` and ``GIT_WORK_TREE`` are set, so git does no discovery of its own;
* ``.git/config`` may only hold a short allowlist of keys (see ``_config_ok``);
* the system and user config, hooks, credential helpers, external diff and text
  conversion programs are all switched off;
* attributes come from the empty tree (``GIT_ATTR_SOURCE``), so a ``.gitattributes``
  in the work tree cannot attach a filter or diff driver, and ``.git/info/attributes``
  must be empty;
* the checks run again right before every git command, because the sandbox can
  rewrite ``.git`` between two commands of one request;
* the command is an argument list handed to ``create_subprocess_exec`` (never a
  shell), with a time limit and an output cap.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from dataclasses import dataclass
from typing import Optional

from . import sandbox

log = logging.getLogger("hermes_ui.git")

GIT = shutil.which("git") or "/usr/bin/git"
MAX_OUTPUT = 4 * 1024 * 1024
READ_TIMEOUT = 15.0
WRITE_TIMEOUT = 60.0
MAX_CONFIG_BYTES = 64 * 1024
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class GitError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


@dataclass(frozen=True)
class Repo:
    sid: str
    root: str   # real path of the work tree
    base: str   # real path of the chat's whole folder; the repo never leaves it

    @property
    def virtual(self) -> str:
        rel = os.path.relpath(self.root, self.base)
        return sandbox.to_virtual(self.sid, "" if rel == "." else rel)


@dataclass
class Result:
    rc: int
    out: str
    err: str
    truncated: bool = False


# ---- finding a repo that is safe to run git in -------------------------------------

_CORE_OK = {"repositoryformatversion", "filemode", "bare", "logallrefupdates", "ignorecase", "precomposeunicode",
            "symlinks", "autocrlf", "eol", "safecrlf", "quotepath"}
_PLAIN_SECTIONS = {"user", "init", "color", "gc", "pack", "push", "pull", "fetch", "advice", "status", "log",
                   "rebase", "merge", "diff", "commit"}
# Keys that name a program or a file to read, anywhere they appear.
_NEVER = {"command", "driver", "external", "textconv", "helper", "program", "editor", "pager", "sshcommand",
          "askpass", "fsmonitor", "hookspath", "worktree", "excludesfile", "attributesfile", "gpgsign",
          "signingkey", "path", "template", "process", "clean", "smudge", "cmd", "tool", "mergetool"}


def _config_ok(key: str) -> bool:
    parts = key.lower().split(".")
    section, name = parts[0], parts[-1]
    if name in _NEVER:
        return False
    if section == "core":
        return len(parts) == 2 and name in _CORE_OK
    if section in ("remote", "branch"):
        return len(parts) == 3 and name != "vcs"
    return section in _PLAIN_SECTIONS and len(parts) == 2


def _env(root: str, write: bool) -> dict[str, str]:
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/nonexistent",
        "LC_ALL": "C",
        "GIT_DIR": os.path.join(root, ".git"),
        "GIT_WORK_TREE": root,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_ATTR_SOURCE": EMPTY_TREE,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
        "GIT_PAGER": "cat",
        "GIT_CEILING_DIRECTORIES": os.path.dirname(root),
    }
    if not write:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _argv(root: str, args: list[str]) -> list[str]:
    return [
        GIT, "--no-pager", "--literal-pathspecs", "--no-replace-objects",
        "-c", f"safe.directory={root}",
        "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.attributesFile=/dev/null",
        "-c", "core.untrackedCache=false", "-c", "core.editor=false", "-c", "core.pager=cat",
        "-c", "credential.helper=", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false",
        "-c", "diff.external=", "-c", "diff.ignoreSubmodules=all", "-c", "status.submoduleSummary=false",
        "-c", "submodule.recurse=false", "-c", "protocol.allow=never", "-c", "gc.auto=0",
        *args,
    ]


def _lstat(path: str) -> Optional[os.stat_result]:
    try:
        return os.lstat(path)
    except OSError:
        return None


async def _check_dotgit(root: str) -> Optional[str]:
    """Why this repo may not be used, or None when it may."""
    dot = os.path.join(root, ".git")
    st = _lstat(dot)
    if st is None:
        return "no repository here"
    if not os.path.isdir(dot) or os.path.islink(dot):
        return "the .git entry must be a plain folder"
    for name in ("HEAD", "config", "index", "objects", "refs", "info", "packed-refs", "shallow"):
        if os.path.islink(os.path.join(dot, name)):
            return f".git/{name} is a link"
    for name in ("commondir", "gitdir", "worktrees", "modules"):
        if _lstat(os.path.join(dot, name)) is not None:
            return f".git/{name} is not supported here"
    for name in ("alternates", "http-alternates"):
        if _lstat(os.path.join(dot, "objects", "info", name)) is not None:
            return "this repository borrows objects from another one"
    attrs = os.path.join(dot, "info", "attributes")
    if _lstat(attrs) is not None:
        try:
            with open(attrs, "rb") as fh:
                lines = fh.read(MAX_CONFIG_BYTES + 1).splitlines()
        except OSError:
            return "unreadable .git/info/attributes"
        if any(ln.strip() and not ln.lstrip().startswith(b"#") for ln in lines):
            return ".git/info/attributes is not supported here"
    cfg = os.path.join(dot, "config")
    cst = _lstat(cfg)
    if cst is None or cst.st_size > MAX_CONFIG_BYTES:
        return "missing or oversized .git/config"
    proc = await asyncio.create_subprocess_exec(
        GIT, "config", "--file", cfg, "--list", "--name-only", "-z",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1"})
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 5)
    except asyncio.TimeoutError:
        proc.kill()
        return "could not read .git/config"
    if proc.returncode != 0:
        return "unreadable .git/config"
    for raw in out.decode("utf-8", "replace").split("\0"):
        if raw and not _config_ok(raw):
            return f"the setting {raw.split('.')[0]}.* in .git/config is not allowed here"
    return None


async def locate(user_id: int, vpath: str) -> tuple[Optional[Repo], str]:
    """(repo, "") for a usable repo at or above ``vpath``; (None, reason) otherwise."""
    try:
        sid, real, _ = sandbox.resolve(int(user_id), vpath)
    except sandbox.SandboxError as exc:
        return None, str(exc)
    base = os.path.realpath(sandbox.session_dir(int(user_id), sid))
    cur = real if os.path.isdir(real) else os.path.dirname(real)
    while cur == base or cur.startswith(base + os.sep):
        if os.path.lexists(os.path.join(cur, ".git")):
            why = await _check_dotgit(cur)
            if why:
                log.warning("refusing git in %s: %s", sandbox.to_virtual(sid, os.path.relpath(cur, base)), why)
                return None, why
            return Repo(sid=sid, root=cur, base=base), ""
        if cur == base:
            break
        cur = os.path.dirname(cur)
    return None, "no repository here"


# ---- paths and refs from the browser ------------------------------------------------

def clean_file(repo: Repo, rel: object) -> str:
    """A repo-relative file path from the browser, or GitError. No absolute paths, no ``..``."""
    if not isinstance(rel, str) or not rel or "\0" in rel or len(rel) > 4096:
        raise GitError("a file path is required")
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or rel.startswith("-") or any(p in ("..", ".git") for p in rel.split("/")):
        raise GitError("that path is not allowed")
    # The leaf may itself be a link (git stores links as links); its parents may not leave the repo.
    parent = os.path.realpath(os.path.dirname(os.path.join(repo.root, rel)))
    if parent != repo.root and not parent.startswith(repo.root + os.sep):
        raise GitError("that path is not allowed")
    return rel


def clean_ref(ref: object, what: str = "branch") -> str:
    if (not isinstance(ref, str) or not ref or len(ref) > 255 or ref.startswith("-") or ref.startswith("/")
            or any(c.isspace() or ord(c) < 32 or c in "~^:?*[\\" for c in ref) or ".." in ref or ref.endswith("/")
            or ref.endswith(".lock") or "@{" in ref):
        raise GitError(f"not a valid {what} name")
    return ref


# ---- running ------------------------------------------------------------------------

async def _read_capped(stream: asyncio.StreamReader, cap: int, on_cut) -> tuple[bytes, bool]:
    chunks, size = [], 0
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return b"".join(chunks), False
        size += len(chunk)
        if size > cap:
            chunks.append(chunk[: max(0, cap - (size - len(chunk)))])
            on_cut()  # a git that is blocked writing to a pipe nobody reads would never exit
            return b"".join(chunks), True
        chunks.append(chunk)


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def run(repo: Repo, args: list[str], *, write: bool = False, timeout: Optional[float] = None,
              cap: int = MAX_OUTPUT, env_extra: Optional[dict[str, str]] = None) -> Result:
    """Run ``git <args>`` in the repo. ``args`` is an argument list; nothing here touches a shell."""
    why = await _check_dotgit(repo.root)
    if why:
        log.warning("refusing git in %s: %s", repo.virtual, why)
        raise GitError(why)
    proc = await asyncio.create_subprocess_exec(
        *_argv(repo.root, args), cwd=repo.root, env={**_env(repo.root, write), **(env_extra or {})},
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)

    async def drain():
        kill = lambda: _kill(proc)  # noqa: E731
        (out, cut), (err, _) = await asyncio.gather(_read_capped(proc.stdout, cap, kill),
                                                    _read_capped(proc.stderr, 64 * 1024, kill))
        await proc.wait()
        return out, err, cut

    try:
        out, err, cut = await asyncio.wait_for(drain(), timeout or (WRITE_TIMEOUT if write else READ_TIMEOUT))
    except asyncio.TimeoutError:
        _kill(proc)
        await proc.wait()
        raise GitError("git took too long", 504)
    return Result(proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), cut)


async def ok(repo: Repo, args: list[str], **kw) -> str:
    res = await run(repo, args, **kw)
    if res.rc != 0:
        raise GitError((res.err or res.out).strip().splitlines()[-1][:300] if (res.err or res.out).strip()
                       else "git failed")
    return res.out
