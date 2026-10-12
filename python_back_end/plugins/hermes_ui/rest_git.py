"""/api/git/* — the coding rail and review pane, over a repo in the person's own sandbox.

The Hermes UI's remote git facade (front_end/hermes-desktop-ui/src/lib/desktop-git.ts)
calls these with the chat's working directory (``/sandbox/<chat>/workspace``). The
path is resolved with ``sandbox.resolve`` for the signed-in user only, so nobody
can name another person's folder, and git runs through ``git_run`` (argument
lists, pinned config, time and output limits). There is no push, pull, clone,
pull-request or worktree route: nothing here talks to a remote.

On a shared server these are admin-only, like the sandbox itself (the exposure
gate cannot see this prefix, so it is checked here).
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from . import git_run, git_view as view, sandbox
from .git_run import GitError, Repo
from .rest import _uid

router = APIRouter(prefix="/hermes-api/api/git")

STATUS_FILE_CAP = 200
SCOPES = ("uncommitted", "branch", "lastTurn")
MAX_COMMIT_MESSAGE = 20_000


# ---- plumbing ---------------------------------------------------------------------------

def _gate(user) -> int:
    from owui_compat.authz import user_id_of
    from plugins.exposure.gate import MESSAGE, build_space_allowed

    uid = user_id_of(user)
    if uid is None or not sandbox.enabled() or not build_space_allowed(uid):
        raise HTTPException(403, MESSAGE)
    return int(uid)


async def _find(user, path: object, *, need: bool = False) -> Optional[Repo]:
    """The repo under ``path`` for this user. None when there is none, unless ``need``."""
    uid = _gate(user)
    repo, why = await git_run.locate(uid, path if isinstance(path, str) else "")
    if repo is None and need:
        raise HTTPException(400, why or "no repository here")
    return repo


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


def _fail(exc: GitError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


# ---- routes: reading ---------------------------------------------------------------------------

@router.get("/status")
async def repo_status(path: str = "", user=Depends(get_current_user_optimized)):
    repo = await _find(user, path)
    if repo is None:
        return None
    try:
        info = await view.porcelain(repo)
        tracked = await view.numstat(repo, ["HEAD"] if await view.has_head(repo) else [])
        if not await view.has_head(repo):
            tracked = {**await view.numstat(repo, ["--cached"]), **tracked}
    except GitError as exc:
        raise _fail(exc)
    files, staged, unstaged, untracked, conflicted = [], 0, 0, 0, 0
    for e in info["entries"]:
        x, y = (e["xy"] + "..")[:2]
        is_untracked, is_conflict = e["xy"] == "??", e["xy"] == "UU"
        is_staged = not is_untracked and not is_conflict and x != "."
        is_unstaged = not is_untracked and not is_conflict and y != "."
        staged += is_staged
        unstaged += is_unstaged
        untracked += is_untracked
        conflicted += is_conflict
        if len(files) < STATUS_FILE_CAP:
            files.append({"path": e["path"], "staged": is_staged, "unstaged": is_unstaged,
                          "untracked": is_untracked, "conflicted": is_conflict})
    return {"branch": info["branch"], "defaultBranch": await view.default_branch(repo), "detached": info["detached"],
            "ahead": info["ahead"], "behind": info["behind"], "staged": staged, "unstaged": unstaged,
            "untracked": untracked, "conflicted": conflicted, "changed": len(info["entries"]),
            "added": sum(a for a, _ in tracked.values()), "removed": sum(r for _, r in tracked.values()),
            "files": files}


@router.get("/worktrees")
async def worktrees(path: str = "", user=Depends(get_current_user_optimized)):
    """Only the checkout itself: Harvis does not create extra worktrees."""
    repo = await _find(user, path)
    if repo is None:
        return {"worktrees": []}
    branch = await view.current_branch(repo)
    return {"worktrees": [{"path": repo.virtual, "branch": branch, "isMain": True,
                           "detached": branch is None, "locked": False}]}


@router.get("/branches")
async def branches(path: str = "", user=Depends(get_current_user_optimized)):
    repo = await _find(user, path)
    if repo is None:
        return {"branches": []}
    try:
        current, default = await view.current_branch(repo), await view.default_branch(repo)
        heads = await view.heads(repo)
        rows = [{"name": b, "checkedOut": b == current, "isDefault": b == default, "isRemote": False,
                 "worktreePath": repo.virtual if b == current else None} for b in heads]
        for name in await view.remotes(repo):
            if name.split("/", 1)[-1] not in heads:
                rows.append({"name": name, "checkedOut": False, "isDefault": False, "isRemote": True,
                             "worktreePath": None})
    except GitError as exc:
        raise _fail(exc)
    return {"branches": rows}


@router.get("/base-branches")
async def base_branches(path: str = "", user=Depends(get_current_user_optimized)):
    repo = await _find(user, path)
    if repo is None:
        return {"branches": []}
    try:
        default = await view.default_branch(repo)
        rows = [{"name": b, "isRemote": False, "isDefault": b == default} for b in await view.heads(repo)]
        rows += [{"name": b, "isRemote": True, "isDefault": b == f"origin/{default}"} for b in await view.remotes(repo)]
    except GitError as exc:
        raise _fail(exc)
    return {"branches": rows}


@router.get("/file-diff")
async def file_diff(file: str = "", path: str = "", user=Depends(get_current_user_optimized)):
    repo = await _find(user, path)
    if repo is None:
        return {"diff": ""}
    try:
        rel = git_run.clean_file(repo, file)
        if await view.is_untracked(repo, rel):
            return {"diff": view.untracked_diff(repo, rel)}
        return {"diff": await view.diff_text(repo, ["HEAD"] if await view.has_head(repo) else [], rel)}
    except GitError as exc:
        raise _fail(exc)


@router.get("/review/list")
async def review_list(path: str = "", scope: str = "uncommitted", base: Optional[str] = None,
                      user=Depends(get_current_user_optimized)):
    repo = await _find(user, path)
    if repo is None:
        return {"files": [], "base": None}
    if scope not in SCOPES:
        raise HTTPException(400, "unknown scope")
    try:
        info = await view.porcelain(repo)
        since = await view.resolve_base(repo, scope, base)
        files: list[dict[str, Any]] = []
        if since:
            stats = await view.numstat(repo, [since])
            names = await git_run.ok(repo, ["diff", "--name-status", "-z", "--no-renames", "--ignore-submodules=all",
                                            since])
            toks = names.split("\0")
            for code, name in zip(toks[0::2], toks[1::2]):
                if name and not view.HIDDEN.match(name):
                    a, r = stats.get(name, (0, 0))
                    files.append({"path": name, "added": a, "removed": r, "status": view.letter(code[:1]), "staged": False})
            seen = {f["path"] for f in files}
            for e in info["entries"]:
                if e["xy"] == "??" and e["path"] not in seen:
                    files.append({"path": e["path"], "added": view.count_lines(os.path.join(repo.root, e["path"])),
                                  "removed": 0, "status": "?", "staged": False})
            return {"files": files, "base": since}
        cached = await view.numstat(repo, ["--cached"])
        loose = await view.numstat(repo, [])
        for e in info["entries"]:
            x, y = (e["xy"] + "..")[:2]
            p = e["path"]
            if e["xy"] == "??":
                files.append({"path": p, "added": view.count_lines(os.path.join(repo.root, p)), "removed": 0,
                              "status": "?", "staged": False})
                continue
            if e["xy"] == "UU":
                files.append({"path": p, "added": 0, "removed": 0, "status": "U", "staged": False})
                continue
            if x != ".":
                files.append({"path": p, "added": cached.get(p, (0, 0))[0], "removed": cached.get(p, (0, 0))[1],
                              "status": view.letter(x), "staged": True})
            if y != ".":
                files.append({"path": p, "added": loose.get(p, (0, 0))[0], "removed": loose.get(p, (0, 0))[1],
                              "status": view.letter(y), "staged": False})
        return {"files": files, "base": None}
    except GitError as exc:
        raise _fail(exc)


@router.get("/review/diff")
async def review_diff(file: str = "", path: str = "", scope: str = "uncommitted", base: Optional[str] = None,
                      staged: Optional[str] = None, user=Depends(get_current_user_optimized)):
    repo = await _find(user, path)
    if repo is None:
        return {"diff": ""}
    if scope not in SCOPES:
        raise HTTPException(400, "unknown scope")
    try:
        rel = git_run.clean_file(repo, file)
        since = await view.resolve_base(repo, scope, base)
        if since:
            args = [since]
        elif (staged or "").lower() == "true":
            args = ["--cached"]
        else:
            args = []
        if not args and await view.is_untracked(repo, rel):
            return {"diff": view.untracked_diff(repo, rel)}
        if since and await view.is_untracked(repo, rel):
            return {"diff": view.untracked_diff(repo, rel)}
        return {"diff": await view.diff_text(repo, args, rel)}
    except GitError as exc:
        raise _fail(exc)


@router.get("/review/rev-parse")
async def rev_parse(path: str = "", ref: Optional[str] = None, user=Depends(get_current_user_optimized)):
    repo = await _find(user, path)
    if repo is None:
        return {"sha": None}
    try:
        name = git_run.clean_ref(ref, "ref") if ref else "HEAD"
    except GitError as exc:
        raise _fail(exc)
    res = await git_run.run(repo, ["rev-parse", "--verify", "--quiet", name + "^{commit}"])
    return {"sha": res.out.strip() or None if res.rc == 0 else None}


@router.get("/review/commit-context")
async def commit_context(path: str = "", user=Depends(get_current_user_optimized)):
    repo = await _find(user, path)
    if repo is None:
        return {"diff": "", "recent": ""}
    flags = ["--no-ext-diff", "--no-textconv", "--no-color", "--ignore-submodules=all"]
    staged = await git_run.run(repo, ["diff", "--cached", *flags], cap=200_000)
    diff = staged.out if staged.rc == 0 and staged.out.strip() else (
        await git_run.run(repo, ["diff", *flags], cap=200_000)).out
    recent = (await git_run.run(repo, ["log", "-n", "10", "--format=%s"])).out if await view.has_head(repo) else ""
    return {"diff": diff[:60_000], "recent": recent}


@router.get("/review/ship-info")
async def ship_info(path: str = "", user=Depends(get_current_user_optimized)):
    """No pull requests here: there is no remote to open one on."""
    _gate(user)
    return {"ghReady": False, "pr": None}


# ---- routes: changing -----------------------------------------------------------------------------

@router.post("/review/stage")
async def stage(request: Request, user=Depends(get_current_user_optimized)):
    body = await _body(request)
    repo = await _find(user, body.get("path"), need=True)
    try:
        view.hide_notes(repo)
        rel = git_run.clean_file(repo, body["file"]) if body.get("file") else None
        await git_run.ok(repo, ["add", "-A", "--", rel] if rel else ["add", "-A"], write=True)
    except GitError as exc:
        raise _fail(exc)
    return {"ok": True}


@router.post("/review/unstage")
async def unstage(request: Request, user=Depends(get_current_user_optimized)):
    body = await _body(request)
    repo = await _find(user, body.get("path"), need=True)
    try:
        rel = git_run.clean_file(repo, body["file"]) if body.get("file") else None
        if await view.has_head(repo):
            await git_run.ok(repo, ["reset", "-q", "--", rel] if rel else ["reset", "-q"], write=True)
        else:  # nothing committed yet: there is no HEAD to reset to
            await git_run.ok(repo, ["rm", "-r", "-q", "--cached", "--", rel] if rel
                             else ["rm", "-r", "-q", "--cached", "--ignore-unmatch", "."], write=True)
    except GitError as exc:
        raise _fail(exc)
    return {"ok": True}


@router.post("/review/revert")
async def revert(request: Request, user=Depends(get_current_user_optimized)):
    """Throw away uncommitted work for one file, or for everything. The UI confirms first."""
    body = await _body(request)
    repo = await _find(user, body.get("path"), need=True)
    try:
        has_head = await view.has_head(repo)
        if body.get("file"):
            rel = git_run.clean_file(repo, body["file"])
            if await view.is_untracked(repo, rel):
                await git_run.ok(repo, ["clean", "-f", "-d", "-q", "--", rel], write=True)
            elif has_head and (await git_run.run(repo, ["cat-file", "-e", f"HEAD:{rel}"])).rc == 0:
                await git_run.ok(repo, ["checkout", "HEAD", "--", rel], write=True)
            else:  # added but never committed
                await git_run.ok(repo, ["rm", "-f", "-q", "--", rel], write=True)
        else:
            if has_head:
                await git_run.ok(repo, ["reset", "--hard", "-q", "HEAD"], write=True)
            view.hide_notes(repo)
            await git_run.ok(repo, ["clean", "-f", "-d", "-q"], write=True)
    except GitError as exc:
        raise _fail(exc)
    return {"ok": True}


@router.post("/review/commit")
async def commit(request: Request, user=Depends(get_current_user_optimized)):
    body = await _body(request)
    repo = await _find(user, body.get("path"), need=True)
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "a commit message is required")
    if len(message) > MAX_COMMIT_MESSAGE:
        raise HTTPException(400, "the commit message is too long")
    if body.get("push"):
        raise HTTPException(400, "Pushing is not available here: this repository has no remote.")
    who = user.get("name") if isinstance(user, dict) else getattr(user, "name", None)
    name = str(who or "Harvis user")[:100]
    email = f"u{_uid(user)}@harvis.local"
    ident = {"GIT_AUTHOR_NAME": name, "GIT_COMMITTER_NAME": name, "GIT_AUTHOR_EMAIL": email,
             "GIT_COMMITTER_EMAIL": email}
    try:
        view.hide_notes(repo)
        staged = await git_run.run(repo, ["diff", "--cached", "--quiet", "--ignore-submodules=all"])
        if staged.rc == 0:  # nothing staged: commit what changed, as the desktop does
            await git_run.ok(repo, ["add", "-A"], write=True)
        await git_run.ok(repo, ["commit", "--no-verify", "--no-gpg-sign", "--no-edit", "-m", message],
                         write=True, env_extra=ident)
    except GitError as exc:
        raise _fail(exc)
    return {"ok": True}


@router.post("/branch/switch")
async def branch_switch(request: Request, user=Depends(get_current_user_optimized)):
    body = await _body(request)
    repo = await _find(user, body.get("path"), need=True)
    try:
        name = git_run.clean_ref(body.get("branch"))
        if body.get("create"):
            args = ["switch", "-c", name]
            if body.get("base"):
                args.append(git_run.clean_ref(body["base"], "base"))
        elif name in await view.heads(repo):
            args = ["switch", name]
        elif name in await view.remotes(repo):
            args = ["switch", "--track", name]
        else:
            raise GitError(f"there is no branch named {name}")
        await git_run.ok(repo, args, write=True)
    except GitError as exc:
        raise _fail(exc)
    return {"branch": name}
