"""Read-side helpers for rest_git.py: repo state, status parsing, diffs of untracked files."""
from __future__ import annotations

import os
import re
from typing import Any, Optional

from . import git_run
from .git_run import GitError, Repo

TRUNKS = ("main", "master", "trunk", "develop")
MAX_UNTRACKED_BYTES = 1024 * 1024
HIDDEN = re.compile(r"^\.harvis(/|$)")  # Harvis's own notes folder in every sandbox


async def has_head(repo: Repo) -> bool:
    return (await git_run.run(repo, ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"])).rc == 0


async def current_branch(repo: Repo) -> Optional[str]:
    res = await git_run.run(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    return res.out.strip() or None if res.rc == 0 else None


async def heads(repo: Repo) -> list[str]:
    out = await git_run.ok(repo, ["for-each-ref", "--format=%(refname:short)", "refs/heads"])
    return [b for b in out.splitlines() if b]


async def remotes(repo: Repo) -> list[str]:
    out = await git_run.ok(repo, ["for-each-ref", "--format=%(refname:short)", "refs/remotes"])
    return [b for b in out.splitlines() if b and not b.endswith("/HEAD")]


async def default_branch(repo: Repo) -> Optional[str]:
    res = await git_run.run(repo, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])
    if res.rc == 0 and res.out.strip().startswith("origin/"):
        return res.out.strip()[len("origin/"):]
    names = await heads(repo)
    return next((t for t in TRUNKS if t in names), None)


def hide_notes(repo: Repo) -> None:
    """Keep Harvis's own ``.harvis`` folder out of "add everything" and "clean everything"."""
    if repo.root != repo.base:
        return
    info = os.path.join(repo.root, ".git", "info")
    exclude = os.path.join(info, "exclude")
    try:
        os.makedirs(info, exist_ok=True)
        if os.path.islink(info) or os.path.islink(exclude):
            return
        fd = os.open(exclude, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "r+") as fh:
            if "/.harvis/" not in fh.read().splitlines():
                fh.seek(0, os.SEEK_END)
                fh.write("\n/.harvis/\n")
    except OSError:
        pass


def count_lines(path: str) -> int:
    """Lines in an untracked text file (0 for links, directories, big or binary files)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return 0
    try:
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(MAX_UNTRACKED_BYTES + 1)
    except OSError:
        return 0
    if len(data) > MAX_UNTRACKED_BYTES or b"\0" in data:
        return 0
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def untracked_diff(repo: Repo, rel: str) -> str:
    """A unified diff that adds a whole untracked file; no git, no following links."""
    try:
        fd = os.open(os.path.join(repo.root, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(MAX_UNTRACKED_BYTES + 1)
    except OSError:
        return ""
    head = f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n"
    if b"\0" in data:
        return head + "Binary file added\n"
    text = data[:MAX_UNTRACKED_BYTES].decode("utf-8", "replace")
    lines = text.splitlines()
    body = "".join(f"+{ln}\n" for ln in lines)
    note = "\\ No newline at end of file\n" if text and not text.endswith("\n") else ""
    more = "+... (file truncated)\n" if len(data) > MAX_UNTRACKED_BYTES else ""
    return head + (f"@@ -0,0 +1,{len(lines)} @@\n" + body + more + note if lines else "")


# ---- parsing ------------------------------------------------------------------------------

async def numstat(repo: Repo, args: list[str]) -> dict[str, tuple[int, int]]:
    res = await git_run.run(repo, ["diff", "--numstat", "-z", "--no-renames", "--no-ext-diff", "--no-textconv",
                                   "--ignore-submodules=all", *args])
    out: dict[str, tuple[int, int]] = {}
    if res.rc == 0:
        for rec in res.out.split("\0"):
            parts = rec.split("\t", 2)
            if len(parts) == 3:
                a, r, path = parts
                out[path] = (int(a) if a.isdigit() else 0, int(r) if r.isdigit() else 0)
    return out


async def porcelain(repo: Repo) -> dict[str, Any]:
    """`git status --porcelain=v2 --branch` as {branch, detached, ahead, behind, entries}."""
    res = await git_run.run(repo, ["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all",
                                   "--ignore-submodules=all"])
    if res.rc != 0:
        raise GitError("could not read the repository status")
    info: dict[str, Any] = {"branch": None, "detached": False, "ahead": 0, "behind": 0, "entries": []}
    records = res.out.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not rec:
            continue
        if rec.startswith("# branch.head "):
            head = rec[len("# branch.head "):]
            info["detached"] = head == "(detached)"
            info["branch"] = None if info["detached"] else head
        elif rec.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", rec)
            if m:
                info["ahead"], info["behind"] = int(m.group(1)), int(m.group(2))
        elif rec[0] == "1":
            f = rec.split(" ", 8)
            info["entries"].append({"xy": f[1], "path": f[8]})
        elif rec[0] == "2":
            f = rec.split(" ", 9)
            info["entries"].append({"xy": f[1], "path": f[9]})
            i += 1  # the original path of a rename
        elif rec[0] == "u":
            f = rec.split(" ", 10)
            info["entries"].append({"xy": "UU", "path": f[10]})
        elif rec[0] == "?":
            info["entries"].append({"xy": "??", "path": rec[2:]})
    info["entries"] = [e for e in info["entries"] if not HIDDEN.match(e["path"])]
    return info


def letter(code: str) -> str:
    return {"T": "M", ".": "M"}.get(code, code if code in "MADRCU" else "M")


async def diff_text(repo: Repo, args: list[str], rel: str) -> str:
    res = await git_run.run(repo, ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
                                   "--ignore-submodules=all", *args, "--", rel])
    return res.out if res.rc == 0 else ""


async def is_untracked(repo: Repo, rel: str) -> bool:
    res = await git_run.run(repo, ["ls-files", "--error-unmatch", "--", rel])
    return res.rc != 0


async def resolve_base(repo: Repo, scope: str, base: Optional[str]) -> Optional[str]:
    """The commit a branch/last-turn review diffs against, or None for the uncommitted view."""
    if scope == "uncommitted" or not await has_head(repo):
        return None
    if base:
        res = await git_run.run(repo, ["rev-parse", "--verify", "--quiet", git_run.clean_ref(base, "ref") + "^{commit}"])
        return res.out.strip() or None if res.rc == 0 else None
    if scope == "lastTurn":
        return None
    default = await default_branch(repo)
    current = await current_branch(repo)
    if not default or default == current:
        return None
    res = await git_run.run(repo, ["merge-base", "HEAD", default])
    return res.out.strip() or None if res.rc == 0 else None
