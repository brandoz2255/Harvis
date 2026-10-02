"""Voice talks to Harvis in its own hidden conversation, never the open chat,
and the sandbox carries Harvis's core files (AGENTS.md, SOUL.md, USER.md, MEMORY.md)."""
import asyncio
import json
import os
from types import SimpleNamespace

from plugins.hermes_ui import rest_voice, sandbox, sessions, store


def _request(body):
    async def json_body():
        return body

    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())),
                           headers={"host": "localhost:9000"}, cookies={}, json=json_body)


def _fake_turn(monkeypatch, seen, gate=None):
    live = sessions.Live(id="voice-1", user_id=7, persisted=True, title=rest_voice.VOICE_TITLE)

    async def open_session(pool, uid):
        return live, []

    async def append(pool, s, role, content, reasoning=""):
        return [{"role": "user", "content": f"old {i}"} for i in range(30)] + [{"role": role, "content": content}]

    async def run_turn(self, s, msgs, voice=False, note="", plain=False):
        seen.update(msgs=msgs, voice=voice, note=note, plain=plain)
        try:
            await self.emit("message.delta", s.id, {"text": "Done. "})
            await self.emit("reasoning.delta", s.id, {"text": "hidden"})
            if gate:
                await gate.wait()
            await self.emit("message.complete", s.id, {"text": "Done. <chat-draft>milk</chat-draft>"})
        except asyncio.CancelledError:
            seen["cancelled"] = True
            raise
        finally:
            s.running = False

    monkeypatch.setattr(rest_voice, "open_session", open_session)
    monkeypatch.setattr(rest_voice.sessions, "append", append)
    monkeypatch.setattr(rest_voice.VoiceConnection, "_run_turn", run_turn)
    return live


def test_hidden_from_the_sidebar():
    assert "NOT LIKE 'Voice: %'" in store._NOT_ROOM_SQL
    assert rest_voice.VOICE_TITLE.startswith("Voice: ")


def test_note_names_the_page_and_the_chat_draft_rule():
    note = rest_voice.voice_note("Settings\n<script>")
    assert "Settings" in note and "<script>" not in note and "\n<script" not in note
    assert "<chat-draft>" in note and "Never say you sent anything" in note
    assert "Never say you cannot navigate" in note
    assert "no tools" in note and "workspace job" not in note


def test_a_reply_spoken_over_shows_as_stopped():
    shown = rest_voice._shown([
        {"role": "user", "content": "Go to this code."},
        {"role": "assistant", "content": "\n\n[interrupted]"},
        {"role": "assistant", "content": "Opening it.\n\n[interrupted]"},
    ])
    assert [m["text"] for m in shown] == ["Go to this code.", "Stopped.", "Opening it."]


def test_warmup_opens_the_voice_session_before_choosing_a_model(monkeypatch):
    seen = {}
    live = sessions.Live(id="voice-1", user_id=7, model="hermes3:3b", persisted=True)

    async def open_session(pool, uid):
        seen["opened"] = (pool, uid)
        return live, []

    def schedule(pool, uid, model):
        seen["scheduled"] = (pool, uid, model)

    monkeypatch.setattr(rest_voice, "open_session", open_session)
    monkeypatch.setattr(rest_voice.voice_warm, "schedule", schedule)

    result = asyncio.run(rest_voice.voice_warm_model(_request({}), {"id": 7}))

    assert result == {"ok": True}
    assert seen["opened"][1] == 7
    assert seen["scheduled"][1:] == (7, "hermes3:3b")


def test_a_turn_streams_its_own_reply(monkeypatch):
    seen = {}
    _fake_turn(monkeypatch, seen)

    async def run():
        resp = await rest_voice.voice_turn(_request({"text": "put milk in my chat", "page": "Chat"}), {"id": 7})
        return [json.loads(line) async for line in resp.body_iterator]

    lines = asyncio.run(run())

    assert [ln["t"] for ln in lines] == ["start", "delta", "done"]
    assert lines[-1]["text"].endswith("<chat-draft>milk</chat-draft>")
    assert seen["voice"] is True and "The user is looking at: Chat." in seen["note"]
    assert seen["plain"] is True  # no workspace, research, recall or thinking on a voice turn
    assert len(seen["msgs"]) == rest_voice.HISTORY_TURNS
    assert seen["msgs"][-1]["content"] == "put milk in my chat"


def test_hanging_up_stops_the_turn(monkeypatch):
    seen = {}

    async def run():
        live = _fake_turn(monkeypatch, seen, asyncio.Event())
        resp = await rest_voice.voice_turn(_request({"text": "build me a site"}), {"id": 7})
        it = resp.body_iterator
        assert json.loads(await it.__anext__())["t"] == "start"
        assert json.loads(await it.__anext__())["t"] == "delta"
        await it.aclose()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return live

    live = asyncio.run(run())
    assert seen.get("cancelled") is True
    assert live.running is False


def test_sandbox_has_core_files_and_keeps_user_edits(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path / "root"))
    base = sandbox.ensure_dir(7, "chat1")

    names = sandbox.sync_core_files(7, "chat1", "# Soul\nCalm and direct.", ["Likes short answers"])

    assert names == ["AGENTS.md", "SOUL.md", "USER.md", "MEMORY.md"]
    read = lambda n: open(os.path.join(base, n)).read()  # noqa: E731
    assert "Calm and direct." in read("SOUL.md")
    assert "- Likes short answers" in read("USER.md")
    assert "MEMORY.md" in read("AGENTS.md") and "/workspace/skills" in read("AGENTS.md")

    with open(os.path.join(base, "MEMORY.md"), "a") as f:
        f.write("- built apps/site\n")
    with open(os.path.join(base, "SOUL.md"), "w") as f:
        f.write("my own soul")
    sandbox.sync_core_files(7, "chat1", "# Soul\nChanged.", [])

    assert read("SOUL.md") == "my own soul"
    assert read("MEMORY.md").endswith("- built apps/site\n")
    assert "Nothing yet." in read("USER.md")


def test_core_files_never_write_through_a_link(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path / "root"))
    outside = tmp_path / "outside.md"
    outside.write_text("untouched")
    base = sandbox.ensure_dir(7, "chat1")
    os.symlink(str(outside), os.path.join(base, "SOUL.md"))
    os.symlink(str(tmp_path / "made.md"), os.path.join(base, "MEMORY.md"))

    names = sandbox.sync_core_files(7, "chat1", "soul", [])

    assert "SOUL.md" not in names and "MEMORY.md" not in names
    assert outside.read_text() == "untouched"
    assert not (tmp_path / "made.md").exists()
