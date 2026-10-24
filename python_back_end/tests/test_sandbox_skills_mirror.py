"""The chat sandbox shows the user's skills as skills/<name>/SKILL.md.

The container writes the sandbox folder too, so the mirror must never follow a
link planted there, and must leave alone anything under skills/ it didn't write.
An approved skill's script files are mirrored under its own folder only, and are
never executed by the backend.
"""
import os

from owui_compat.skill_pending import SCRIPT_MARK
from plugins.hermes_ui import sandbox


def _use_tmp_root(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path))


def test_mirrors_enabled_skills_and_removes_dropped_ones(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path)
    skills = [{"name": "Docker Debug", "description": "When compose breaks", "content": "Check logs."},
              {"name": "notes", "description": "", "content": "Write it down."}]

    assert sandbox.sync_skills(7, "chat1", skills) == 2

    base = sandbox.session_dir(7, "chat1")
    text = open(os.path.join(base, "skills", "docker-debug", "SKILL.md")).read()
    assert "# Docker Debug" in text and "Check logs." in text

    sandbox.sync_skills(7, "chat1", skills[:1])
    assert not os.path.exists(os.path.join(base, "skills", "notes"))


def test_keeps_files_the_user_put_under_skills(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path)
    base = sandbox.ensure_dir(7, "chat1")
    mine = os.path.join(base, "skills", "mine")
    os.makedirs(mine)
    with open(os.path.join(mine, "SKILL.md"), "w") as f:
        f.write("my own notes")

    sandbox.sync_skills(7, "chat1", [{"name": "mine", "content": "from Harvis"}])

    assert open(os.path.join(mine, "SKILL.md")).read() == "my own notes"


def test_never_writes_through_a_planted_symlink(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path / "root")
    outside = tmp_path / "outside"
    outside.mkdir()
    base = sandbox.ensure_dir(7, "chat1")
    os.symlink(str(outside), os.path.join(base, "skills"))

    assert sandbox.sync_skills(7, "chat1", [{"name": "x", "content": "y"}]) == 0
    assert list(outside.iterdir()) == []

    os.unlink(os.path.join(base, "skills"))
    os.makedirs(os.path.join(base, "skills"))
    os.symlink(str(outside), os.path.join(base, "skills", "x"))
    sandbox.sync_skills(7, "chat1", [{"name": "x", "content": "y"}])
    assert list(outside.iterdir()) == []


def test_opening_a_chat_starts_its_sandbox_once(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    from plugins.hermes_ui import rest_sandbox

    _use_tmp_root(monkeypatch, tmp_path)
    monkeypatch.delenv("HARVIS_SANDBOX_AUTOSTART", raising=False)
    started = []
    cold_start = None

    class Manager:
        _client = object()

        async def ensure_isolated(self, key, path):
            started.append((key, path))
            await cold_start.wait()

    async def manager():
        return Manager()

    async def not_running(uid, sid):
        return False, []

    async def no_gpu():
        return False

    monkeypatch.setattr(rest_sandbox, "_manager", manager)
    monkeypatch.setattr(rest_sandbox, "_listening", not_running)
    monkeypatch.setattr(rest_sandbox, "gpu_available", no_gpu)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=None)))

    async def open_twice():
        nonlocal cold_start
        cold_start = asyncio.Event()
        first = await rest_sandbox.sandbox_info(request, "chat1", {"id": 7})
        second = await rest_sandbox.sandbox_info(request, "chat1", {"id": 7})
        cold_start.set()
        await asyncio.gather(*rest_sandbox._warming.values())
        return first, second

    first, second = asyncio.run(open_twice())

    assert first["starting"] and second["starting"]
    assert started == [(sandbox.runner_key(7, "chat1"), sandbox.session_dir(7, "chat1"))]
    assert rest_sandbox._warming == {}


# ─── approved script files ───────────────────────────────────────────────────

def _skill(files, name="Docker Debug"):
    return {"name": name, "description": "d", "content": "Check logs.", "files": files}


def test_mirrors_script_files_under_the_skill_folder_with_the_mirror_mark(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path)
    files = {"scripts/check.py": "print('ok')\n", "scripts/run.sh": "#!/bin/sh\necho hi\n", "scripts/a.js": "1\n"}

    assert sandbox.sync_skills(7, "chat1", [_skill(files)]) == 1

    scripts = os.path.join(sandbox.session_dir(7, "chat1"), "skills", "docker-debug", "scripts")
    assert sorted(os.listdir(scripts)) == ["a.js", "check.py", "run.sh"]
    assert open(os.path.join(scripts, "check.py")).read() == f"# {SCRIPT_MARK}\nprint('ok')\n"
    assert open(os.path.join(scripts, "a.js")).read() == f"// {SCRIPT_MARK}\n1\n"
    # a shebang stays on the first line so the script still runs when the user runs it
    assert open(os.path.join(scripts, "run.sh")).read() == f"#!/bin/sh\n# {SCRIPT_MARK}\necho hi\n"
    # written, never made executable: the backend does not run them
    assert all(os.stat(os.path.join(scripts, n)).st_mode & 0o111 == 0 for n in os.listdir(scripts))
    assert sandbox.sync_skills(7, "chat1", [_skill(files)]) == 1  # a second sync changes nothing
    assert sorted(os.listdir(scripts)) == ["a.js", "check.py", "run.sh"]


def test_dropped_scripts_and_dropped_skills_are_removed_but_the_users_files_stay(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path)
    sandbox.sync_skills(7, "chat1", [_skill({"scripts/a.py": "1", "scripts/b.py": "2"})])
    base = sandbox.session_dir(7, "chat1")
    scripts = os.path.join(base, "skills", "docker-debug", "scripts")
    with open(os.path.join(scripts, "mine.py"), "w") as f:
        f.write("my own script")

    sandbox.sync_skills(7, "chat1", [_skill({"scripts/a.py": "1"})])
    assert sorted(os.listdir(scripts)) == ["a.py", "mine.py"]

    sandbox.sync_skills(7, "chat1", [])  # the skill is no longer approved + enabled
    assert os.listdir(scripts) == ["mine.py"]
    assert open(os.path.join(scripts, "mine.py")).read() == "my own script"

    os.unlink(os.path.join(scripts, "mine.py"))
    sandbox.sync_skills(7, "chat1", [])
    assert not os.path.exists(os.path.join(base, "skills", "docker-debug"))


def test_a_script_the_user_edited_or_wrote_under_the_same_name_is_not_overwritten(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path)
    base = sandbox.ensure_dir(7, "chat1")
    scripts = os.path.join(base, "skills", "docker-debug", "scripts")
    os.makedirs(scripts)
    with open(os.path.join(scripts, "check.py"), "w") as f:
        f.write("the user's version")

    sandbox.sync_skills(7, "chat1", [_skill({"scripts/check.py": "from Harvis", "scripts/new.py": "x"})])

    assert open(os.path.join(scripts, "check.py")).read() == "the user's version"
    assert os.path.exists(os.path.join(scripts, "new.py"))


def test_a_skill_folder_with_the_users_own_skill_md_gets_no_scripts(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path)
    base = sandbox.ensure_dir(7, "chat1")
    mine = os.path.join(base, "skills", "docker-debug")
    os.makedirs(mine)
    with open(os.path.join(mine, "SKILL.md"), "w") as f:
        f.write("my own notes")

    sandbox.sync_skills(7, "chat1", [_skill({"scripts/a.py": "x"})])

    assert os.listdir(mine) == ["SKILL.md"]


def test_bad_script_paths_write_nothing_anywhere(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path / "root")
    for bad in ({"../x.py": "x"}, {"scripts/../x.py": "x"}, {"scripts/a.exe": "x"}, {"/etc/x.py": "x"},
                {"scripts/sub/a.py": "x"}, {"scripts/a.py": "x" * 30000}, "scripts/a.py", ["scripts/a.py"]):
        sandbox.sync_skills(7, "chat1", [_skill(bad)])
    found = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert [f for f in found if not f.endswith("SKILL.md") and "/.harvis/" not in f] == []
    assert not (tmp_path / "root" / "u7" / "chat1" / "skills" / "docker-debug" / "scripts").exists()


def test_never_writes_scripts_through_a_planted_symlink(monkeypatch, tmp_path):
    _use_tmp_root(monkeypatch, tmp_path / "root")
    outside = tmp_path / "outside"
    outside.mkdir()
    base = sandbox.ensure_dir(7, "chat1")
    skill = os.path.join(base, "skills", "docker-debug")
    os.makedirs(skill)
    os.symlink(str(outside), os.path.join(skill, "scripts"))

    sandbox.sync_skills(7, "chat1", [_skill({"scripts/a.py": "x"})])
    assert list(outside.iterdir()) == []

    os.unlink(os.path.join(skill, "scripts"))
    os.makedirs(os.path.join(skill, "scripts"))
    os.symlink(str(outside / "target.py"), os.path.join(skill, "scripts", "a.py"))
    sandbox.sync_skills(7, "chat1", [_skill({"scripts/a.py": "x"})])
    assert list(outside.iterdir()) == []

    sandbox.sync_skills(7, "chat1", [])  # removal does not follow a link out either
    assert list(outside.iterdir()) == []
