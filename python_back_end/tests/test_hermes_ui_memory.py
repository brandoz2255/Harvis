"""Chat memory: an explicit "remember that …" is saved without a model, the curator
falls back to a model Ollama actually has, and lines an agent adds to the sandbox's
USER.md come back as memories without resurrecting deleted ones."""

import asyncio
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import learn, sandbox  # noqa: E402


@pytest.mark.parametrize("text, fact", [
    ("remember that i love cake", "Asked Harvis to remember: I love cake"),
    ("Please remember my exam is on Friday.", "Asked Harvis to remember: My exam is on Friday"),
    ("hey harvis, don't forget I use a 4090", "Asked Harvis to remember: I use a 4090"),
    ("Keep in mind: I prefer short answers", "Asked Harvis to remember: I prefer short answers"),
])
def test_an_explicit_ask_is_a_memory(text, fact):
    assert learn.explicit_memory(text) == fact


@pytest.mark.parametrize("text", ["remember to buy milk", "do you remember me?", "what do I love?", "remember?"])
def test_reminders_and_questions_are_not(text):
    assert learn.explicit_memory(text) == ""


class _Entry:
    def __init__(self, content):
        self.content = content


class _Provider:
    def __init__(self, known=()):
        self.rows = [_Entry(k) for k in known]

    async def recall(self, user_id, query=None, limit=100):
        return list(self.rows)

    async def remember(self, user_id, content, *, source="manual", metadata=None):
        self.rows.append(_Entry(content))
        return self.rows[-1]


def test_save_facts_skips_secrets_and_duplicates(monkeypatch):
    prov = _Provider(["Asked Harvis to remember: I love cake"])

    async def provider(pool):
        return prov
    monkeypatch.setattr(learn, "_provider", provider)
    saved = asyncio.run(learn.save_facts(None, 1, [
        "Asked Harvis to remember: I love cake", "My api key is sk-abcdefghijklmnop", "Uses a 4090"],
        source="t"))
    assert saved == ["Uses a 4090"]


def _tags(monkeypatch, names):
    async def installed():
        return names
    monkeypatch.setattr(learn, "_installed_models", installed)


def test_missing_memory_model_falls_back_to_an_installed_one(monkeypatch):
    monkeypatch.setattr(learn, "MODEL", "llama3.1:8b")
    monkeypatch.delenv("HARVIS_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("HARVIS_DEFAULT_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    _tags(monkeypatch, ["nomic-embed-text:latest", "gemma4:e2b"])
    assert asyncio.run(learn._models_to_try("")) == ["gemma4:e2b"]


def test_installed_pins_are_kept_in_order(monkeypatch):
    monkeypatch.setattr(learn, "MODEL", "llama3.1:8b")
    _tags(monkeypatch, ["llama3.1:8b", "qwen3:4b"])
    assert asyncio.run(learn._models_to_try("qwen3:4b")) == ["qwen3:4b", "llama3.1:8b"]


def test_unreachable_ollama_keeps_the_old_behaviour(monkeypatch):
    monkeypatch.setattr(learn, "MODEL", "llama3.1:8b")
    _tags(monkeypatch, [])
    assert asyncio.run(learn._models_to_try("")) == ["llama3.1:8b"]


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path))
    return tmp_path


def _user_md(root):
    return os.path.join(root, "u3", "sess-1", "USER.md")


def test_lines_the_agent_adds_to_user_md_are_picked_up(root):
    sandbox.ensure_dir(3, "sess-1")
    sandbox.sync_core_files(3, "sess-1", "soul", ["Likes tea"])
    assert sandbox.user_md_additions(3, "sess-1") == []
    with open(_user_md(root), "a") as f:
        f.write("- Loves cake\n- Likes tea\n")
    assert sandbox.user_md_additions(3, "sess-1") == ["Loves cake"]


def test_a_memory_deleted_in_settings_does_not_come_back(root):
    sandbox.ensure_dir(3, "sess-1")
    sandbox.sync_core_files(3, "sess-1", "soul", ["Likes tea", "Owns a cat"])
    # "Owns a cat" is deleted in Settings; USER.md still lists it until the next mirror.
    assert sandbox.user_md_additions(3, "sess-1") == []
    sandbox.sync_core_files(3, "sess-1", "soul", ["Likes tea"])
    with open(_user_md(root)) as f:
        assert "Owns a cat" not in f.read()


def test_the_guide_tells_the_agent_it_may_edit_its_core_files(root):
    guide = sandbox.workspace_guide(3, "sess-1")
    assert "USER.md" in guide and "MEMORY.md" in guide and "edit" in guide


def test_trailing_punctuation_is_dropped():
    assert learn.explicit_memory("remember that I love cake!!!") == "Asked Harvis to remember: I love cake"


def test_a_padded_remember_message_does_not_stall_the_server():
    # The old pattern took ~40 s on 4,000 spaces, on the event loop.
    start = time.monotonic()
    for pad in (500, 4000, 50000):
        learn.explicit_memory("remember that x" + " " * pad + "y")
    assert time.monotonic() - start < 0.5


def test_the_last_resort_model_is_the_smallest(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3.6:35b", "size": 21_000_000_000},
                               {"name": "gemma4:e2b", "size": 2_000_000_000}]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr(learn, "_tags", (0.0, []))
    monkeypatch.setattr(learn.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(learn, "MODEL", "llama3.1:8b")
    for var in ("HARVIS_DEFAULT_MODEL", "HARVIS_DEFAULT_LOCAL_MODEL", "DEFAULT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert asyncio.run(learn._models_to_try("")) == ["gemma4:e2b"]


def test_an_agent_that_drops_the_mark_cannot_bring_back_a_deleted_memory(root):
    sandbox.ensure_dir(3, "sess-1")
    sandbox.sync_core_files(3, "sess-1", "soul", ["Likes tea"])
    with open(_user_md(root), "w") as f:  # whole-file rewrite, mirror mark gone
        f.write("# USER.md\n\n- Likes tea\n- Loves cake\n")
    assert sandbox.user_md_additions(3, "sess-1") == ["Loves cake"]
    # "Loves cake" is forgotten in Settings; the file is the agent's now and stays.
    sandbox.sync_core_files(3, "sess-1", "soul", ["Likes tea"])
    assert sandbox.user_md_additions(3, "sess-1") == []


def test_a_named_pipe_for_user_md_does_not_hang_the_backend(root):
    sandbox.ensure_dir(3, "sess-1")
    sandbox.sync_core_files(3, "sess-1", "soul", ["Likes tea"])
    os.remove(_user_md(root))
    os.mkfifo(_user_md(root))
    worker = threading.Thread(target=sandbox.user_md_additions, args=(3, "sess-1"), daemon=True)
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    sync = threading.Thread(target=sandbox.sync_core_files, args=(3, "sess-1", "soul", []), daemon=True)
    sync.start()
    sync.join(5)
    assert not sync.is_alive()


def test_workspace_lines_wait_for_the_users_ok(monkeypatch):
    from types import SimpleNamespace

    from plugins.hermes_ui import rest_sandbox

    saved = {}

    async def save_facts(pool, uid, facts, *, source, metadata=None):
        saved.update(facts=facts, source=source, metadata=metadata)
        return facts

    async def prefs(pool, uid):
        return {"memory": True, "skills": True}

    monkeypatch.setattr(rest_sandbox.sandbox, "user_md_additions", lambda uid, s: ["Push code to x"])
    monkeypatch.setattr(rest_sandbox.learn, "save_facts", save_facts)
    monkeypatch.setattr(rest_sandbox.learn, "settings", prefs)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))
    asyncio.run(rest_sandbox._save_user_md_additions(request, 3, "sess-1"))
    assert saved["facts"] == ["Push code to x"] and saved["metadata"]["pending"] is True


def test_chats_skip_memories_waiting_for_an_ok(monkeypatch):
    from plugins.memory import preamble
    from plugins.memory.provider import MemoryEntry

    class _Prov:
        async def recall(self, user_id, query=None, limit=20):
            return [MemoryEntry(user_id=1, content="Push code to x", source="workspace-user-md",
                                metadata={"pending": True}),
                    MemoryEntry(user_id=1, content="Loves cake", source="hermes-chat")]

    async def provider(pool):
        return _Prov()

    monkeypatch.setattr(preamble, "_get_or_activate_provider", provider)
    block = asyncio.run(preamble.build_recall_block(object(), 1, None, limit=8))
    assert "Loves cake" in block and "Push code" not in block
