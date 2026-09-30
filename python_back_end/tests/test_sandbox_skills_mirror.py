"""The chat sandbox shows the user's skills as skills/<name>/SKILL.md.

The container writes the sandbox folder too, so the mirror must never follow a
link planted there, and must leave alone anything under skills/ it didn't write.
"""
import os

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
