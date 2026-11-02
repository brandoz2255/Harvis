"""Podcast speaker/episode profiles: per-user CRUD, voice validation, ownership, generation."""
import ast
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notebooks import podcast_audio, podcast_profiles as pp
from notebooks.router import get_current_user_from_request, get_notebook_manager
from onb_compat import podcasts as onb_podcasts
from onb_compat import router as onb_router_mod

USER_A, USER_B = 1, 2
NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


class FakeDB:
    """In-memory podcast_profiles (+ the one standalone_podcasts insert generate makes)."""

    def __init__(self):
        self.rows = {}
        self.podcasts = []
        self.profile_queries = 0


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def execute(self, sql, *args):
        return "OK"

    def _view(self, pid, r):
        return {"id": pid, "name": r["name"], "config": r["config"], "created_at": NOW, "updated_at": NOW}

    async def fetchval(self, sql, *args):
        assert sql == pp.SQL_COUNT, sql[:60]
        self.db.profile_queries += 1
        return sum(1 for r in self.db.rows.values() if r["user"] == args[0] and r["kind"] == args[1])

    async def fetch(self, sql, *args):
        assert sql == pp.SQL_LIST, sql[:60]
        self.db.profile_queries += 1
        return [self._view(i, r) for i, r in self.db.rows.items() if r["user"] == args[0] and r["kind"] == args[1]]

    async def fetchrow(self, sql, *args):
        db = self.db
        if "INSERT INTO standalone_podcasts" in sql:
            db.podcasts.append(args)
            return {"id": uuid.uuid4()}
        db.profile_queries += 1
        if sql == pp.SQL_INSERT:
            pid = uuid.uuid4()
            db.rows[pid] = {"user": args[0], "kind": args[1], "name": args[2], "config": args[3]}
            return self._view(pid, db.rows[pid])
        if sql == pp.SQL_GET:
            r = db.rows.get(args[0])
            return self._view(args[0], r) if r and r["user"] == args[1] and r["kind"] == args[2] else None
        if sql == pp.SQL_UPDATE:
            r = db.rows.get(args[2])
            if not r or r["user"] != args[3] or r["kind"] != args[4]:
                return None
            r["name"], r["config"] = args[0], args[1]
            return self._view(args[2], r)
        if sql == pp.SQL_DELETE:
            r = db.rows.get(args[0])
            if not r or r["user"] != args[1] or r["kind"] != args[2]:
                return None
            del db.rows[args[0]]
            return {"id": args[0]}
        raise AssertionError(f"unexpected fetchrow: {sql[:80]}")


class FakePool:
    def __init__(self, db):
        self.conn = FakeConn(db)

    def acquire(self):
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(pp, "_ready", False)
    db = FakeDB()
    manager = SimpleNamespace(db_pool=FakePool(db))
    app = FastAPI()
    app.include_router(onb_podcasts.router)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(401, "Could not validate credentials")
        return {"id": int(uid), "username": f"user{uid}"}

    app.dependency_overrides[get_current_user_from_request] = fake_user
    app.dependency_overrides[get_notebook_manager] = lambda: manager

    started = []

    async def fake_task(pool, podcast_id, user_id, title, content, style, speakers, minutes, model=None, cast=None):
        started.append({"user": user_id, "content": content, "style": style, "speakers": speakers, "cast": cast})

    async def fake_model():
        return "test-model"

    monkeypatch.setattr(onb_podcasts, "_generate_episode_task", fake_task)
    monkeypatch.setattr(onb_router_mod, "_default_chat_model", fake_model)
    return SimpleNamespace(db=db, started=started, client=TestClient(app, raise_server_exceptions=False))


def as_user(uid):
    return {"X-Test-User": str(uid)}


def duo(voice_a="af_bella", voice_b="bm_george"):
    return {
        "name": "Morning show",
        "description": "Two friends",
        "speakers": [
            {"name": "Ana", "voice_id": voice_a, "backstory": "Curious", "personality": "Warm"},
            {"name": "Ben", "voice_id": voice_b},
        ],
    }


def make_speaker(env, uid=USER_A, **kw):
    r = env.client.post("/onb-api/speaker-profiles", json=duo(**kw), headers=as_user(uid))
    assert r.status_code == 200, r.text
    return r.json()


# ── voices ────────────────────────────────────────────────────────────────────

def test_voice_catalog_is_the_services_own_list():
    models = Path(__file__).resolve().parents[2] / "services" / "voice-onnx" / "app" / "models.py"
    if not models.is_file():
        pytest.skip("voice-onnx source not in this checkout")
    for node in ast.parse(models.read_text()).body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "KOKORO_VOICES":
            service = ast.literal_eval(node.value)["kokoro-multi-lang-v1_0"]
            assert tuple(podcast_audio.KOKORO_VOICES) == tuple(service)
            return
    pytest.fail("KOKORO_VOICES not found in the voice service")


def test_default_voices_are_all_offered():
    assert set(podcast_audio.VOICES) <= set(podcast_audio.KOKORO_VOICES)


def test_voices_route_lists_the_catalog(env):
    r = env.client.get("/onb-api/podcasts/voices", headers=as_user(USER_A))
    assert r.status_code == 200
    ids = [v["id"] for v in r.json()["voices"]]
    assert ids == list(podcast_audio.KOKORO_VOICES) and len(ids) > 4
    assert env.client.get("/onb-api/podcasts/voices").status_code == 401


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_speaker_profile_create_list_update_delete(env):
    made = make_speaker(env)
    assert made["name"] == "Morning show" and made["builtin"] is False
    assert [s["voice_id"] for s in made["speakers"]] == ["af_bella", "bm_george"]

    listed = env.client.get("/onb-api/speaker-profiles", headers=as_user(USER_A)).json()
    assert [p["id"] for p in listed] == ["default-duo", made["id"]]
    assert listed[0]["builtin"] is True

    changed = duo(voice_a="am_adam")
    changed["name"] = "Renamed"
    r = env.client.put(f"/onb-api/speaker-profiles/{made['id']}", json=changed, headers=as_user(USER_A))
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed" and r.json()["speakers"][0]["voice_id"] == "am_adam"

    r = env.client.delete(f"/onb-api/speaker-profiles/{made['id']}", headers=as_user(USER_A))
    assert r.status_code == 200
    ids = [p["id"] for p in env.client.get("/onb-api/speaker-profiles", headers=as_user(USER_A)).json()]
    assert ids == ["default-duo"]
    assert env.client.delete(f"/onb-api/speaker-profiles/{made['id']}", headers=as_user(USER_A)).status_code == 404


def test_speaker_profile_left_on_automatic_voice(env):
    made = make_speaker(env, voice_a="", voice_b="__default__")
    assert [s["voice_id"] for s in made["speakers"]] == ["__default__", "__default__"]


def test_episode_profile_create_list_update_delete(env):
    cast = make_speaker(env)
    body = {"name": "Debate night", "style": "debate", "speaker_config": cast["id"], "default_briefing": "Be fair."}
    r = env.client.post("/onb-api/episode-profiles", json=body, headers=as_user(USER_A))
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["style"] == "debate" and made["speaker_config"] == cast["id"]
    assert made["outline_llm"] == "test-model"  # same non-null model refs the built-ins carry

    listed = env.client.get("/onb-api/episode-profiles", headers=as_user(USER_A)).json()
    assert listed[-1]["id"] == made["id"] and listed[0]["builtin"] is True

    r = env.client.put(f"/onb-api/episode-profiles/{made['id']}", json={**body, "style": "interview"}, headers=as_user(USER_A))
    assert r.status_code == 200 and r.json()["style"] == "interview"
    assert env.client.delete(f"/onb-api/episode-profiles/{made['id']}", headers=as_user(USER_A)).status_code == 200


def test_duplicate_a_builtin_and_an_own_profile(env):
    r = env.client.post("/onb-api/speaker-profiles/default-duo/duplicate", headers=as_user(USER_A))
    assert r.status_code == 200 and r.json()["builtin"] is False
    assert r.json()["name"].endswith("(copy)") and len(r.json()["speakers"]) == 2
    r = env.client.post("/onb-api/episode-profiles/debate/duplicate", headers=as_user(USER_A))
    assert r.status_code == 200 and r.json()["style"] == "debate"
    own = make_speaker(env)
    r = env.client.post(f"/onb-api/speaker-profiles/{own['id']}/duplicate", headers=as_user(USER_A))
    assert r.status_code == 200 and r.json()["id"] != own["id"]


def test_builtins_are_read_only_and_unknown_ids_are_404(env):
    for path in ("speaker-profiles/default-duo", "episode-profiles/debate"):
        assert env.client.put(f"/onb-api/{path}", json=duo(), headers=as_user(USER_A)).status_code == 403
        assert env.client.delete(f"/onb-api/{path}", headers=as_user(USER_A)).status_code == 403
    assert env.client.delete("/onb-api/speaker-profiles/nope", headers=as_user(USER_A)).status_code == 404
    assert env.client.put("/onb-api/speaker-profiles/nope", json=duo(), headers=as_user(USER_A)).status_code == 404


# ── validation ────────────────────────────────────────────────────────────────

def test_invalid_voice_is_rejected_and_nothing_is_saved(env):
    r = env.client.post("/onb-api/speaker-profiles", json=duo(voice_b="not_a_voice"), headers=as_user(USER_A))
    assert r.status_code == 400 and "not_a_voice" in r.json()["detail"]
    assert env.db.rows == {}


def test_invalid_voice_is_rejected_on_update_too(env):
    made = make_speaker(env)
    r = env.client.put(f"/onb-api/speaker-profiles/{made['id']}", json=duo(voice_a="voice-0"), headers=as_user(USER_A))
    assert r.status_code == 400
    assert json.loads(env.db.rows[uuid.UUID(made["id"])]["config"])["speakers"][0]["voice_id"] == "af_bella"


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(name="  "),
    lambda b: b.update(speakers=[]),
    lambda b: b.update(speakers=[{"name": f"S{i}"} for i in range(5)]),
    lambda b: b.update(speakers=[{"name": "Ana"}, {"name": "ana"}]),
    lambda b: b.update(speakers=["Ana"]),
    lambda b: b.update(name="x" * 81),
])
def test_bad_speaker_profiles_are_rejected(env, mutate):
    body = duo()
    mutate(body)
    assert env.client.post("/onb-api/speaker-profiles", json=body, headers=as_user(USER_A)).status_code == 400


def test_bad_episode_profiles_are_rejected(env):
    post = lambda b: env.client.post("/onb-api/episode-profiles", json=b, headers=as_user(USER_A)).status_code
    assert post({"name": "x", "style": "opera"}) == 400
    assert post({"name": "x", "num_segments": 99}) == 400
    assert post({"name": "x", "num_segments": "many"}) == 400
    assert post({"name": ""}) == 400
    assert post({"name": "x", "speaker_config": str(uuid.uuid4())}) == 404


def test_profile_count_is_capped(env, monkeypatch):
    monkeypatch.setattr(pp, "MAX_PER_KIND", 2)
    make_speaker(env)
    make_speaker(env)
    r = env.client.post("/onb-api/speaker-profiles", json=duo(), headers=as_user(USER_A))
    assert r.status_code == 400
    assert env.client.post("/onb-api/speaker-profiles", json=duo(), headers=as_user(USER_B)).status_code == 200


# ── ownership ─────────────────────────────────────────────────────────────────

def test_user_b_cannot_see_or_touch_user_a_profiles(env):
    mine = make_speaker(env, USER_A)
    listed = env.client.get("/onb-api/speaker-profiles", headers=as_user(USER_B)).json()
    assert [p["id"] for p in listed] == ["default-duo"]
    url = f"/onb-api/speaker-profiles/{mine['id']}"
    assert env.client.put(url, json=duo(), headers=as_user(USER_B)).status_code == 404
    assert env.client.delete(url, headers=as_user(USER_B)).status_code == 404
    assert env.client.post(f"{url}/duplicate", headers=as_user(USER_B)).status_code == 404
    assert len(env.db.rows) == 1
    assert json.loads(env.db.rows[uuid.UUID(mine["id"])]["config"])["speakers"][0]["voice_id"] == "af_bella"


def test_user_b_cannot_use_user_a_speaker_profile_to_generate(env):
    mine = make_speaker(env, USER_A)
    body = {"content": "text", "speaker_profile": mine["id"]}
    r = env.client.post("/onb-api/podcasts/generate", json=body, headers=as_user(USER_B))
    assert r.status_code == 404
    assert env.db.podcasts == [] and env.started == []


def test_user_b_cannot_use_user_a_episode_profile_or_point_one_at_a_foreign_cast(env):
    cast = make_speaker(env, USER_A)
    r = env.client.post("/onb-api/episode-profiles", json={"name": "x", "speaker_config": cast["id"]}, headers=as_user(USER_B))
    assert r.status_code == 404
    ep = env.client.post("/onb-api/episode-profiles", json={"name": "x", "speaker_config": cast["id"]}, headers=as_user(USER_A)).json()
    r = env.client.post("/onb-api/podcasts/generate", json={"content": "t", "episode_profile": ep["id"]}, headers=as_user(USER_B))
    assert r.status_code == 404 and env.started == []


def test_anonymous_gets_401(env):
    assert env.client.get("/onb-api/speaker-profiles").status_code == 401
    assert env.client.post("/onb-api/speaker-profiles", json=duo()).status_code == 401
    assert env.client.delete(f"/onb-api/speaker-profiles/{uuid.uuid4()}").status_code == 401


# ── generation ────────────────────────────────────────────────────────────────

def test_generate_with_no_profile_uses_defaults_and_never_reads_profiles(env):
    r = env.client.post("/onb-api/podcasts/generate", json={"content": "some text"}, headers=as_user(USER_A))
    assert r.status_code == 200
    assert env.started[0]["cast"] is None and env.started[0]["speakers"] == 2
    assert env.started[0]["style"] == "conversational"
    assert env.db.profile_queries == 0


def test_generate_with_a_speaker_profile_passes_its_cast(env):
    mine = make_speaker(env, USER_A)
    r = env.client.post("/onb-api/podcasts/generate", json={"content": "t", "speaker_profile": mine["id"]}, headers=as_user(USER_A))
    assert r.status_code == 200
    assert env.started[0]["cast"] == [{"name": "Ana", "voice_id": "af_bella"}, {"name": "Ben", "voice_id": "bm_george"}]
    assert env.started[0]["speakers"] == 2
    stored = json.loads(env.db.podcasts[0][5])
    assert [m["name"] for m in stored] == ["Ana", "Ben"]


def test_generate_with_an_episode_profile_takes_its_style_cast_and_briefing(env):
    cast = make_speaker(env, USER_A)
    ep = env.client.post(
        "/onb-api/episode-profiles",
        json={"name": "Debate night", "style": "debate", "speaker_config": cast["id"], "default_briefing": "Stay fair."},
        headers=as_user(USER_A),
    ).json()
    r = env.client.post("/onb-api/podcasts/generate", json={"content": "text", "episode_profile": ep["id"]}, headers=as_user(USER_A))
    assert r.status_code == 200
    run = env.started[0]
    assert run["style"] == "debate" and [m["name"] for m in run["cast"]] == ["Ana", "Ben"]
    assert run["content"].endswith("Stay fair.")


def test_an_episode_profile_whose_cast_was_deleted_falls_back_to_the_default_duo(env):
    cast = make_speaker(env, USER_A)
    ep = env.client.post("/onb-api/episode-profiles", json={"name": "x", "speaker_config": cast["id"]}, headers=as_user(USER_A)).json()
    env.client.delete(f"/onb-api/speaker-profiles/{cast['id']}", headers=as_user(USER_A))
    r = env.client.post("/onb-api/podcasts/generate", json={"content": "t", "episode_profile": ep["id"]}, headers=as_user(USER_A))
    assert r.status_code == 200 and env.started[0]["cast"] is None


# ── voices reach the audio step ───────────────────────────────────────────────

def test_chosen_voices_skip_automatic_and_unknown_ids():
    cast = [
        {"name": "Ana", "voice_id": "af_bella"},
        {"name": " Ben ", "voice_id": "__default__"},
        {"name": "Cy", "voice_id": "made_up"},
        {"name": "Di", "voice_id": "bm_lewis"},
    ]
    assert podcast_audio.chosen_voices(cast) == {"ana": "af_bella", "di": "bm_lewis"}
    assert podcast_audio.chosen_voices(None) == {}


def test_automatic_speakers_avoid_voices_a_picked_speaker_holds():
    order = dict(podcast_audio.chosen_voices([{"name": "Ana", "voice_id": podcast_audio.VOICES[0]}]))
    assert podcast_audio.voice_for("Ana", order) == podcast_audio.VOICES[0]
    assert podcast_audio.voice_for("Ben", order) == podcast_audio.VOICES[1]


def test_synthesis_speaks_each_line_in_the_picked_voice(monkeypatch, tmp_path):
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x01\x00" * 100)
    clip = buf.getvalue()
    sent = []

    class Resp:
        content = clip

        def raise_for_status(self):
            pass

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):
            sent.append(json["voice"])
            return Resp()

    monkeypatch.setattr(podcast_audio.httpx, "AsyncClient", Client)
    monkeypatch.setattr(podcast_audio, "AUDIO_DIR", tmp_path)
    monkeypatch.delenv("TTS_URL", raising=False)
    import asyncio

    segments = [{"speaker": "Ana", "text": "Hi"}, {"speaker": "Ben", "text": "Hello"}, {"speaker": "Ana", "text": "Again"}]
    voices = podcast_audio.chosen_voices([{"name": "Ana", "voice_id": "zf_xiaoxiao"}])
    made = asyncio.run(podcast_audio.make_audio(segments, voices=voices))
    assert made["audio_path"].startswith("/api/notebooks/podcasts/tts-audio/")
    assert sent == ["zf_xiaoxiao", podcast_audio.VOICES[0], "zf_xiaoxiao"]
