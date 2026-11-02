"""GET /api/legal: the general Terms of Use and Acceptable Use (plugins/people/legal.py).

No database needed. Run inside a throwaway backend container:
    docker run --rm --network none -v <repo>/python_back_end:/app:ro --tmpfs /tmp \
        -e IMAGES_DIR=/tmp/images -w /app --entrypoint python harvis-backend:latest \
        -m pytest -q -p no:cacheprovider tests/test_legal.py
"""
import json
import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from auth_optimized import ALGORITHM, SECRET_KEY
from plugins.exposure import BuildSpaceGate
from plugins.people import approval, gate, legal, terms


class _Pool:
    """Stands in for asyncpg: ``users`` rows exist or not, or the database is down."""

    def __init__(self, count=None):
        self.count = count

    def acquire(self):
        pool = self

        class _Conn:
            async def __aenter__(self):
                if pool.count is None:
                    raise RuntimeError("database down")
                return self

            async def __aexit__(self, *exc):
                return False

            async def fetchval(self, sql):
                return pool.count

        return _Conn()


def _client(pool=None, middleware=()):
    app = FastAPI()
    app.include_router(legal.router)
    for m in middleware:
        app.add_middleware(m)
    app.state.pg_pool = pool
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("HARVIS_EXPOSURE", "HARVIS_SIGNUP_TERMS", "HARVIS_HOUSE_RULES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(approval, "_status", {})


def test_sections_are_plain_headed_text():
    assert legal.LEGAL_VERSION == "2026-10-30"
    for sections in (legal.TERMS, legal.ACCEPTABLE_USE):
        assert len(sections) >= 4
        for s in sections:
            assert set(s) == {"heading", "body"}
            assert s["heading"].strip() and s["body"].strip()
    headings = [s["heading"] for s in legal.TERMS]
    assert len(headings) == len(set(headings))


def test_data_claims_name_what_the_code_does():
    body = {s["heading"]: s["body"] for s in legal.TERMS}
    leaves = body["What does leave the machine"]
    for named in ("GitHub", "Hugging Face", "Google Fonts", "VOICE_PREFETCH=0", "VOICE_BROWSER_ASSETS=0"):
        assert named in leaves
    assert "A few themes" not in leaves
    keys = body["Cloud providers and your keys"]
    assert "used only for your own chats" not in keys
    assert "everyone's requests" in keys and "admin" in keys
    assert "NOTICE" in body["Using Harvis"]


def test_endpoint_is_public_and_has_the_agreed_shape():
    r = _client().get("/api/legal")  # no cookie, no token
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"version", "terms", "acceptable_use", "house_rules"}
    assert body["version"] == legal.LEGAL_VERSION
    assert body["terms"] == [dict(s) for s in legal.TERMS]
    assert body["acceptable_use"] == [dict(s) for s in legal.ACCEPTABLE_USE]
    assert set(body["house_rules"]) == {"required", "version", "points"}


def test_house_rules_come_from_the_sign_up_module(monkeypatch):
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "on")
    shown = _client(_Pool(count=3)).get("/api/legal").json()["house_rules"]
    assert shown == {"required": True, "version": terms.VERSION, "points": list(terms.POINTS)}

    monkeypatch.setenv("HARVIS_HOUSE_RULES", "Be kind. | Ask first.")
    shown = _client(_Pool(count=3)).get("/api/legal").json()["house_rules"]
    assert shown["points"] == ["Be kind.", "Ask first."]
    assert shown["version"].startswith(terms.VERSION + "+")

    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "off")
    assert _client(_Pool(count=3)).get("/api/legal").json()["house_rules"] == {
        "required": False, "version": None, "points": []}


def test_nothing_is_asked_before_the_first_account_exists(monkeypatch):
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "on")
    assert _client(_Pool(count=0)).get("/api/legal").json()["house_rules"]["required"] is False
    assert _client(_Pool(count=1)).get("/api/legal").json()["house_rules"]["required"] is True


def test_a_database_blip_does_not_break_the_page(monkeypatch):
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "on")
    for pool in (None, _Pool(count=None)):
        r = _client(pool).get("/api/legal")
        assert r.status_code == 200
        assert r.json()["terms"]


@pytest.mark.parametrize("mode", ["local", "lan", "tunnel", "lan+tunnel"])
def test_open_in_every_exposure_mode(monkeypatch, mode):
    monkeypatch.setenv("HARVIS_EXPOSURE", mode)
    client = _client(middleware=(BuildSpaceGate, gate.BlockedAccountGate))
    assert client.get("/api/legal").status_code == 200


def test_someone_in_the_waiting_room_can_still_read_it(monkeypatch):
    approval.note_status(41, approval.PENDING_STATUS)
    token = jwt.encode({"sub": "41"}, SECRET_KEY, algorithm=ALGORITHM)
    client = _client(middleware=(gate.BlockedAccountGate,))
    assert client.get("/api/legal", cookies={"access_token": token}).status_code == 200
    # Only that read: the waiting room list did not grow to cover writes.
    assert client.post("/api/legal", cookies={"access_token": token}).status_code == 403


def test_it_says_nothing_about_this_host(monkeypatch):
    monkeypatch.setenv("HARVIS_SIGNUP_TERMS", "on")
    text = json.dumps(_client(_Pool(count=2)).get("/api/legal").json())
    host = socket.gethostname()
    assert host not in text
    for leak in ("/home/", "/app/", "/var/", "192.168.", "10.0.", "@", "localhost", "postgres"):
        assert leak not in text, leak


def test_data_claims_name_what_leaves_the_machine():
    """If one of these destinations is dropped from the text, the claim above it is no longer true."""
    leaving = next(s for s in legal.TERMS if s["heading"] == "What does leave the machine")["body"]
    for destination in ("Ollama", "Hugging Face", "r.jina.ai", "Google Fonts", "GitHub"):
        assert destination in leaving
    stays = next(s for s in legal.TERMS if s["heading"].startswith("Your data"))["body"]
    assert "no analytics" in stays.lower()


def test_no_game_is_named():
    text = json.dumps(legal.payload()).lower()
    for name in ("stardew", "nintendo", "concernedape"):
        assert name not in text
