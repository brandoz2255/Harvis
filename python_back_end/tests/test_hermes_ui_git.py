"""/api/git/*: a repo in the signed-in user's sandbox, and nothing else.

Real git, real files in a temp sandbox root. The checks that matter most are the
refusals: a path that leaves the sandbox, a repo whose config would run a program,
another person's folder, and git being started without a shell.
"""
import asyncio
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from auth_optimized import get_current_user_optimized  # noqa: E402
from plugins.hermes_ui import git_run, rest_git, sandbox  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

CWD = "/sandbox/chat-1/workspace"
GIT = shutil.which("git") or "git"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path))
    for key in ("HARVIS_SANDBOX_ENABLED", "HARVIS_EXPOSURE", "HARVIS_BIND_ADDR_PUBLIC", "KUBERNETES_SERVICE_HOST",
                "HARVIS_BUILD_SPACE_ACCESS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    return tmp_path


def make_client(uid: int = 7) -> TestClient:
    app = FastAPI()
    app.include_router(rest_git.router)
    app.dependency_overrides[get_current_user_optimized] = lambda: {"id": uid, "name": "Test Person"}
    return TestClient(app)


def sh(cwd, *args):
    subprocess.run([GIT, *args], cwd=cwd, check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1"})


def workspace(root, uid=7, sid="chat-1"):
    path = root / f"u{uid}" / sid
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_repo(root, uid=7):
    repo = workspace(root, uid)
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "config", "user.name", "T")
    sh(repo, "config", "user.email", "t@example.com")
    (repo / "a.txt").write_text("one\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "first")
    return repo


def get(client, route, **params):
    return client.get(f"/hermes-api/api/git/{route}", params={"path": CWD, **params})


def post(client, route, **body):
    return client.post(f"/hermes-api/api/git/{route}", json={"path": CWD, **body})


# --- the happy path ---------------------------------------------------------------

def test_status_stage_commit_and_revert(env):
    repo = make_repo(env)
    client = make_client()
    assert get(client, "status").json()["changed"] == 0

    (repo / "a.txt").write_text("one\ntwo\n")
    (repo / "new.txt").write_text("fresh\n")
    status = get(client, "status").json()
    assert (status["branch"], status["unstaged"], status["untracked"], status["added"]) == ("main", 1, 1, 1)

    listed = {f["path"]: f for f in get(client, "review/list").json()["files"]}
    assert listed["a.txt"]["status"] == "M" and listed["a.txt"]["staged"] is False
    assert listed["new.txt"]["status"] == "?" and listed["new.txt"]["added"] == 1
    assert "+two" in get(client, "review/diff", file="a.txt").json()["diff"]
    assert "+fresh" in get(client, "review/diff", file="new.txt").json()["diff"]

    assert post(client, "review/stage", file="a.txt").json() == {"ok": True}
    staged = [f for f in get(client, "review/list").json()["files"] if f["path"] == "a.txt"]
    assert staged[0]["staged"] is True
    assert "+two" in get(client, "review/diff", file="a.txt", staged="true").json()["diff"]
    assert post(client, "review/unstage", file="a.txt").status_code == 200
    assert get(client, "status").json()["staged"] == 0

    assert post(client, "review/revert", file="a.txt").status_code == 200
    assert (repo / "a.txt").read_text() == "one\n"
    assert post(client, "review/revert", file="new.txt").status_code == 200
    assert not (repo / "new.txt").exists()

    (repo / "b.txt").write_text("b\n")
    assert post(client, "review/commit", message="add b").json() == {"ok": True}
    assert get(client, "status").json()["changed"] == 0
    log = subprocess.run([GIT, "log", "--format=%an|%s"], cwd=repo, capture_output=True, text=True).stdout
    assert log.splitlines()[0] == "Test Person|add b"
    assert get(client, "review/rev-parse", ref="HEAD").json()["sha"]
    assert get(client, "review/rev-parse", ref="nope").json()["sha"] is None


def test_branches_and_switching(env):
    repo = make_repo(env)
    sh(repo, "branch", "feature")
    client = make_client()
    rows = {b["name"]: b for b in get(client, "branches").json()["branches"]}
    assert rows["main"]["checkedOut"] and rows["main"]["isDefault"] and not rows["feature"]["checkedOut"]
    assert post(client, "branch/switch", branch="feature").json() == {"branch": "feature"}
    assert get(client, "status").json()["branch"] == "feature"
    assert post(client, "branch/switch", branch="topic", create=True).status_code == 200
    assert post(client, "branch/switch", branch="missing").status_code == 400
    assert post(client, "branch/switch", branch="-D").status_code == 400
    assert get(client, "worktrees").json()["worktrees"][0]["branch"] == "topic"


def test_no_repo_means_empty_answers_not_errors(env):
    workspace(env)
    client = make_client()
    assert get(client, "status").json() is None
    assert get(client, "branches").json() == {"branches": []}
    assert get(client, "review/list").json() == {"files": [], "base": None}
    assert post(client, "review/stage", file="x").status_code == 400


def test_harvis_notes_folder_is_never_committed(env):
    repo = make_repo(env)
    (repo / ".harvis").mkdir()
    (repo / ".harvis" / "proxy-salt").write_text("secret")
    (repo / "c.txt").write_text("c\n")
    client = make_client()
    assert [e["path"] for e in get(client, "status").json()["files"]] == ["c.txt"]
    assert post(client, "review/commit", message="c").status_code == 200
    tracked = subprocess.run([GIT, "ls-files"], cwd=repo, capture_output=True, text=True).stdout
    assert ".harvis" not in tracked


# --- containment ----------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../a.txt", "/etc/passwd", ".git/config", "sub/../../a.txt", "-rf", "a\0b"])
def test_file_paths_that_leave_the_repo_are_refused(env, bad):
    make_repo(env)
    client = make_client()
    assert get(client, "file-diff", file=bad).status_code == 400
    assert post(client, "review/revert", file=bad).status_code == 400
    assert post(client, "review/stage", file=bad).status_code == 400


@pytest.mark.parametrize("path", ["/etc", "/sandbox/chat-1", CWD + "/../../u8/chat-1/workspace", "/sandbox/../x/workspace"])
def test_repo_paths_outside_the_sandbox_find_nothing(env, path):
    make_repo(env)
    make_repo(env, uid=8)
    client = make_client(7)
    assert client.get("/hermes-api/api/git/status", params={"path": path}).json() is None
    assert client.post("/hermes-api/api/git/review/stage", json={"path": path}).status_code == 400


def test_a_symlinked_directory_cannot_carry_a_file_out(env):
    repo = make_repo(env)
    outside = env / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret\n")
    (repo / "link").symlink_to(outside)
    client = make_client()
    assert get(client, "file-diff", file="link/secret.txt").status_code == 400
    assert "top secret" not in get(client, "review/diff", file="link/secret.txt").text


def test_a_symlinked_file_is_not_followed_for_untracked_diffs(env):
    repo = make_repo(env)
    target = env / "secret.txt"
    target.write_text("top secret\n")
    (repo / "peek.txt").symlink_to(target)
    client = make_client()
    assert "top secret" not in get(client, "review/diff", file="peek.txt").text


def test_users_cannot_see_each_others_repos(env):
    mine = make_repo(env, uid=7)
    theirs = make_repo(env, uid=8)
    (mine / "mine.txt").write_text("m\n")
    (theirs / "theirs.txt").write_text("t\n")
    seen7 = get(make_client(7), "status").json()["files"]
    seen8 = get(make_client(8), "status").json()["files"]
    assert [f["path"] for f in seen7] == ["mine.txt"]
    assert [f["path"] for f in seen8] == ["theirs.txt"]
    assert get(make_client(9), "status").json() is None


# --- a repo that tries to run something -------------------------------------------------

def append_config(repo, text):
    with open(repo / ".git" / "config", "a") as fh:
        fh.write(text)


@pytest.mark.parametrize("snippet", [
    "[core]\n\tfsmonitor = touch PWNED\n",
    "[core]\n\thooksPath = /tmp\n",
    "[core]\n\tworktree = /\n",
    "[core]\n\tsshCommand = touch PWNED\n",
    '[filter "x"]\n\tclean = touch PWNED\n',
    '[diff "x"]\n\ttextconv = touch PWNED\n',
    '[merge "x"]\n\tdriver = touch PWNED\n',
    '[include]\n\tpath = /etc/passwd\n',
    '[credential]\n\thelper = !touch PWNED\n',
    '[alias]\n\tstatus = !touch PWNED\n',
    "[extensions]\n\tworktreeConfig = true\n",
])
def test_a_config_that_would_run_a_program_is_refused(env, snippet):
    repo = make_repo(env)
    marker = repo / "PWNED"
    append_config(repo, snippet.replace("PWNED", str(marker)))
    (repo / ".gitattributes").write_text("* filter=x diff=x merge=x\n")
    (repo / "a.txt").write_text("changed\n")
    client = make_client()
    assert get(client, "status").json() is None
    assert post(client, "review/stage").status_code == 400
    assert post(client, "review/commit", message="x").status_code == 400
    assert not marker.exists()


def test_a_filter_added_after_the_repo_was_checked_does_not_run(env):
    repo_dir = make_repo(env)
    repo, why = asyncio.run(git_run.locate(7, CWD))
    assert repo is not None, why
    marker = repo_dir / "PWNED"
    append_config(repo_dir, f'[filter "x"]\n\tclean = touch {marker}; cat\n')
    (repo_dir / ".gitattributes").write_text("* filter=x\n")
    (repo_dir / "a.txt").write_text("changed\n")
    with pytest.raises(git_run.GitError):
        asyncio.run(git_run.run(repo, ["add", "-A"], write=True))
    assert not marker.exists()


def test_work_tree_attributes_cannot_attach_a_filter(env, monkeypatch):
    repo_dir = make_repo(env)
    repo, _ = asyncio.run(git_run.locate(7, CWD))
    marker = repo_dir / "PWNED"
    append_config(repo_dir, f'[filter "x"]\n\tclean = touch {marker}; cat\n')
    (repo_dir / ".gitattributes").write_text("* filter=x\n")
    (repo_dir / "a.txt").write_text("changed\n")

    async def no_check(root):
        return None

    monkeypatch.setattr(git_run, "_check_dotgit", no_check)  # even if the race were won
    for args in (["status", "--porcelain"], ["diff", "--numstat"], ["add", "-A"]):
        asyncio.run(git_run.run(repo, args, write=args[0] == "add"))
    assert not marker.exists()


def test_info_attributes_are_refused(env):
    repo = make_repo(env)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("* filter=x\n")
    assert get(make_client(), "status").json() is None


def test_alternates_and_linked_git_dirs_are_refused(env):
    repo = make_repo(env)
    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text("/somewhere/else/objects\n")
    assert get(make_client(), "status").json() is None


def test_dot_git_pointing_elsewhere_is_refused(env):
    other = make_repo(env, uid=8)
    mine = workspace(env, 7)
    (mine / ".git").write_text(f"gitdir: {other}/.git\n")
    assert get(make_client(), "status").json() is None
    shutil.rmtree(mine / ".git", ignore_errors=True) if (mine / ".git").is_dir() else (mine / ".git").unlink()
    (mine / ".git").symlink_to(other / ".git")
    assert get(make_client(), "status").json() is None


def test_hooks_do_not_run(env):
    repo = make_repo(env)
    marker = repo / "HOOKED"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    (repo / "z.txt").write_text("z\n")
    assert post(make_client(), "review/commit", message="z").status_code == 200
    assert not marker.exists()


def test_push_is_not_offered(env):
    repo = make_repo(env)
    (repo / "z.txt").write_text("z\n")
    client = make_client()
    assert post(client, "review/commit", message="z", push=True).status_code == 400
    assert get(client, "review/ship-info").json() == {"ghReady": False, "pr": None}
    for route in ("review/push", "review/create-pr", "worktree/add"):
        assert post(client, route).status_code in (404, 405)


# --- how git is started ----------------------------------------------------------------------

def test_git_is_run_with_an_argument_list_and_no_shell(env, monkeypatch):
    repo = make_repo(env)
    nasty = "x; touch HACKED $(touch HACKED2) `touch HACKED3`.txt"
    (repo / nasty).write_text("n\n")
    calls = []
    real = asyncio.create_subprocess_exec

    async def spy(*argv, **kw):
        calls.append((argv, kw))
        return await real(*argv, **kw)

    monkeypatch.setattr(git_run.asyncio, "create_subprocess_exec", spy)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", lambda *a, **k: pytest.fail("a shell was used"))
    client = make_client()
    assert post(client, "review/stage", file=nasty).status_code == 200
    assert post(client, "review/commit", message="m; touch HACKED4").status_code == 200
    assert not list(repo.glob("HACKED*"))
    assert calls and all(argv[0] == git_run.GIT and "shell" not in kw for argv, kw in calls)
    calls = [c for c in calls if "--file" not in c[0]]  # the one-off config read has its own bare environment
    assert all(kw["env"]["GIT_DIR"] == str(repo / ".git") and kw["cwd"] == str(repo) for _, kw in calls)
    assert all(kw["env"]["GIT_CONFIG_GLOBAL"] == "/dev/null" for _, kw in calls)
    argv = next(a for a, _ in calls if "commit" in a)
    assert "core.hooksPath=/dev/null" in argv and "--no-verify" in argv and "m; touch HACKED4" in argv


def test_pathspec_magic_is_literal(env):
    repo = make_repo(env)
    (repo / "keep.txt").write_text("k\n")
    client = make_client()
    # Read literally, ":(top)*" names no file, so git matches nothing instead of treating it as a glob.
    assert post(client, "review/stage", file=":(top)*").status_code == 400
    assert get(client, "status").json()["staged"] == 0


def test_runaway_output_is_capped(env):
    repo = make_repo(env)
    (repo / "big.txt").write_text("x" * 5_000_000)
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "big")
    real = os.path.realpath(repo)
    res = asyncio.run(git_run.run(git_run.Repo("chat-1", real, real), ["cat-file", "-p", "HEAD:big.txt"], cap=1000))
    assert res.truncated and len(res.out) == 1000


# --- who may use it -------------------------------------------------------------------------------

def test_on_a_shared_server_only_admins_get_git(env, monkeypatch):
    make_repo(env, uid=1)
    make_repo(env, uid=2)
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert get(make_client(2), "status").status_code == 403
    assert post(make_client(2), "review/stage").status_code == 403
    assert get(make_client(1), "status").status_code == 200
    monkeypatch.setenv("HARVIS_BUILD_SPACE_ACCESS", "everyone")
    assert get(make_client(2), "status").status_code == 200


def test_sandbox_switched_off(env, monkeypatch):
    make_repo(env)
    monkeypatch.setenv("HARVIS_SANDBOX_ENABLED", "false")
    assert get(make_client(), "status").status_code == 403
