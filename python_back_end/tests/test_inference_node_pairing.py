"""PIN pairing for inference nodes — POST /api/inference-nodes/pair.

No network and no database. The node helper is an ``httpx.MockTransport`` handed to
``pairing._client``; the store is a fake pool (so the real ``store.upsert_node`` runs and
the encrypted-token column can be inspected) with ``store._encrypt`` replaced by a marker
so the test does not need ``main`` (and its Fernet key) imported.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth_optimized import get_current_user_optimized  # noqa: E402
from plugins.inference_nodes import pairing, probe, registry, routes, store  # noqa: E402
from plugins.inference_nodes.pairing import PairError  # noqa: E402
from plugins.inference_nodes.types import NodeSpec, NodeState  # noqa: E402

PIN = "123456"
TOKEN = "tok-9f8e7d6c5b4a-SECRET"
BASE = "http://192.168.4.50:11437"


# ── fakes ───────────────────────────────────────────────────────────────────

class FakeConn:
    def __init__(self, db):
        self.db = db

    async def execute(self, sql, *args):
        if sql.lstrip().upper().startswith("INSERT INTO INFERENCE_NODES"):
            name, base_url, dialect, label, hardware, token_enc = args[:6]
            self.db.rows[name] = {
                "name": name, "base_url": base_url, "dialect": dialect, "label": label,
                "hardware": hardware, "token_encrypted": token_enc,
            }
        return "OK"

    async def fetchrow(self, sql, name):
        row = self.db.rows.get(name)
        return {"base_url": row["base_url"]} if row else None


class _Acquire:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return FakeConn(self.db)

    async def __aexit__(self, *a):
        return False


class FakePool:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def acquire(self):
        return _Acquire(self)


class Helper:
    """A scriptable stand-in for harvis_node.py."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.down = False
        self.info = {"name": "Lab PC A", "version": "1", "paired": False, "dialect": "ollama"}
        self.pair_status = 200
        self.pair_body = {"token": TOKEN, "name": "Lab PC A", "dialect": "ollama"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, body))
        if self.down:
            raise httpx.ConnectError("refused")
        if request.url.path == "/harvis-node/info":
            return httpx.Response(200, json=self.info)
        if request.url.path == "/harvis-node/pair":
            return httpx.Response(self.pair_status, json=self.pair_body)
        return httpx.Response(404)


@pytest.fixture
def helper(monkeypatch):
    h = Helper()
    real = httpx.AsyncClient

    def _client():
        return real(transport=httpx.MockTransport(h.handler), timeout=5.0, follow_redirects=False)

    monkeypatch.setattr(pairing, "_client", _client)
    return h


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pairing._attempts.clear()
    probe._cache.clear()
    probe._cache_at = 0.0
    probe._lock = asyncio.Lock()
    monkeypatch.delenv(registry.ENV_VAR, raising=False)
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.setattr(store, "_schema_ready", True)
    monkeypatch.setattr(store, "_encrypt", lambda t: f"enc::{t[::-1]}" if t else None)

    async def _snapshot(force=False, timeout=4.0):
        return dict(probe._cache)
    monkeypatch.setattr(probe, "snapshot", _snapshot)
    yield
    pairing._attempts.clear()
    probe._cache.clear()
    probe._cache_at = 0.0


@pytest.fixture
def pool():
    return FakePool()


def make_client(pool, user_id=1):
    app = FastAPI()
    app.include_router(routes.router)
    app.state.pg_pool = pool
    app.dependency_overrides[get_current_user_optimized] = lambda: {"id": user_id}
    return TestClient(app)


def post(client, **over):
    body = {"address": "192.168.4.50", "pin": PIN}
    body.update(over)
    return client.post("/api/inference-nodes/pair", json=body)


def seed_probe_for(name, base=BASE, models=("llama3:8b",)):
    spec = NodeSpec(name=name, base_url=base, dialect="ollama", label="Lab PC A", token=TOKEN,
                    source="db")
    probe._cache[name] = NodeState(spec=spec, reachable=True, models=set(models))


# ── success ─────────────────────────────────────────────────────────────────

def test_success_registers_an_ollama_node_with_an_encrypted_token(helper, pool):
    seed_probe_for("lab-pc-a")
    r = post(make_client(pool))
    assert r.status_code == 200, r.text
    node = r.json()["node"]
    assert node["name"] == "lab-pc-a" and node["label"] == "Lab PC A"
    assert node["dialect"] == "ollama" and node["base_url"] == BASE
    assert node["has_token"] is True and node["reachable"] is True
    assert set(node) == set(NodeState(spec=NodeSpec(name="x", base_url="http://x:1")).public())

    row = pool.rows["lab-pc-a"]
    assert row["label"] == "Lab PC A"
    assert row["dialect"] == "ollama" and row["base_url"] == BASE
    assert row["token_encrypted"] == f"enc::{TOKEN[::-1]}"
    assert TOKEN not in json.dumps(row)                      # stored encrypted, not plain

    # The helper saw exactly: info (no body), then pair with the PIN and a hub name.
    assert [(m, p) for m, p, _ in helper.calls] == [
        ("GET", "/harvis-node/info"), ("POST", "/harvis-node/pair")]
    sent = helper.calls[1][2]
    assert sent["pin"] == PIN and sent["hub_name"]


def test_neither_pin_nor_token_is_returned_or_logged(helper, pool, caplog):
    caplog.set_level("DEBUG")
    r = post(make_client(pool))
    assert r.status_code == 200
    assert TOKEN not in r.text and PIN not in r.text
    assert TOKEN not in caplog.text and PIN not in caplog.text


def test_explicit_name_beats_the_helpers_and_is_slugged(helper, pool):
    r = post(make_client(pool), name="Dorm 4090")
    assert r.status_code == 200, r.text
    assert r.json()["node"]["name"] == "dorm-4090"
    assert r.json()["node"]["label"] == "Dorm 4090"
    assert "dorm-4090" in pool.rows


@pytest.mark.parametrize("typed,base", [
    ("192.168.4.50", "http://192.168.4.50:11437"),
    ("192.168.4.50:11437", "http://192.168.4.50:11437"),
    ("192.168.4.50:9000", "http://192.168.4.50:9000"),
    ("http://lab-pc.local", "http://lab-pc.local:11437"),
    ("https://box.example.com:8443/", "https://box.example.com:8443"),
    ("  HTTP://Host:11437  ", "http://host:11437"),
    ("[fe80::1]:11437", "http://[fe80::1]:11437"),
])
def test_address_normalisation(typed, base):
    assert pairing.normalize_address(typed) == base


@pytest.mark.parametrize("typed", [
    "", "   ", "ftp://192.168.4.50", "file:///etc/passwd", "http://192.168.4.50/api",
    "http://192.168.4.50:11437/harvis-node/info", "http://user:pw@192.168.4.50",
    "http://192.168.4.50?x=1", "http://192.168.4.50#frag", "192.168.4.50:notaport",
    "192.168.4.50:99999", "host name", "http://", "javascript:alert(1)",
])
def test_bad_addresses_are_400_with_a_sentence(typed, helper, pool):
    r = post(make_client(pool), address=typed)
    assert r.status_code == 400, (typed, r.text)
    assert r.json()["detail"].endswith(".")
    assert helper.calls == []                                # nothing was sent anywhere


@pytest.mark.parametrize("pin", ["", "12345", "1234567", "12345a", "12 456", "١٢٣٤٥٦", "123-456"])
def test_bad_pins_are_400_and_never_leave_the_hub(pin, helper, pool):
    r = post(make_client(pool), pin=pin)
    assert r.status_code == 400, (pin, r.text)
    assert "6 digits" in r.json()["detail"]
    assert helper.calls == []


def test_a_name_with_nothing_usable_is_400(helper, pool):
    r = post(make_client(pool), name="!!!")
    assert r.status_code == 400
    assert helper.calls == []


# ── helper failures ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,body", [
    (403, {"detail": "Wrong PIN.", "tries_left": 2}),
    (403, {"detail": "That PIN has been retired. Restart the helper to get a new one."}),
    (409, {"detail": "This node is already paired."}),
])
def test_helper_403_and_409_pass_through(status, body, helper, pool):
    helper.pair_status, helper.pair_body = status, body
    r = post(make_client(pool))
    assert r.status_code == status
    assert r.json()["detail"] == body["detail"]
    assert r.json().get("tries_left") == body.get("tries_left")
    assert pool.rows == {}                                   # nothing registered


def test_helper_detail_that_echoes_the_pin_is_scrubbed(helper, pool):
    helper.pair_status, helper.pair_body = 403, {"detail": f"PIN {PIN} is wrong"}
    r = post(make_client(pool))
    assert r.status_code == 403 and PIN not in r.text


def test_helper_down_is_502_with_the_documented_sentence(helper, pool):
    helper.down = True
    r = post(make_client(pool))
    assert r.status_code == 502
    assert r.json()["detail"] == (
        f"Could not reach a Harvis node at {BASE}. Is harvis_node.py running there?")
    assert pool.rows == {}


def test_info_that_is_not_json_is_treated_as_not_a_harvis_node(helper, pool, monkeypatch):
    real = httpx.AsyncClient

    def _client():
        return real(transport=httpx.MockTransport(lambda req: httpx.Response(200, text="<html>")),
                    timeout=5.0)

    monkeypatch.setattr(pairing, "_client", _client)
    r = post(make_client(pool))
    assert r.status_code == 502 and "Could not reach a Harvis node" in r.json()["detail"]


def test_token_missing_from_a_200_is_502_and_registers_nothing(helper, pool):
    helper.pair_body = {"name": "x", "dialect": "ollama"}
    r = post(make_client(pool))
    assert r.status_code == 502 and pool.rows == {}


def test_redirects_are_not_followed():
    assert pairing._client().follow_redirects is False


def test_name_clash_with_a_node_elsewhere_is_409_before_the_pin_is_spent(helper, pool):
    pool.rows["lab-pc-a"] = {"name": "lab-pc-a", "base_url": "http://10.0.0.9:11437"}
    r = post(make_client(pool))
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    assert [p for _, p, _ in helper.calls] == ["/harvis-node/info"]     # PIN not sent


def test_repairing_the_same_address_replaces_the_node(helper, pool):
    pool.rows["lab-pc-a"] = {"name": "lab-pc-a", "base_url": BASE, "token_encrypted": "old"}
    r = post(make_client(pool))
    assert r.status_code == 200
    assert pool.rows["lab-pc-a"]["token_encrypted"] == f"enc::{TOKEN[::-1]}"


# ── authorisation and rate limit ────────────────────────────────────────────

def test_non_admin_is_403_and_nothing_is_contacted(helper, pool):
    r = post(make_client(pool, user_id=7))
    assert r.status_code == 403
    assert helper.calls == [] and pool.rows == {}


def test_rate_limit_is_429_after_ten_attempts_per_user(helper, pool, monkeypatch):
    helper.pair_status, helper.pair_body = 403, {"detail": "Wrong PIN.", "tries_left": 1}
    c = make_client(pool)
    for _ in range(pairing.RATE_MAX_ATTEMPTS):
        assert post(c).status_code == 403
    r = post(c)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert "Too many" in r.json()["detail"]
    sent = [p for _, p, _ in helper.calls if p == "/harvis-node/pair"]
    assert len(sent) == pairing.RATE_MAX_ATTEMPTS            # the 11th never reached the node

    # Another admin has their own budget.
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1,2")
    assert post(make_client(pool, user_id=2)).status_code == 403       # reaches the node again


def test_rate_limit_window_expires():
    for i in range(pairing.RATE_MAX_ATTEMPTS):
        pairing.reserve_attempt("1", now=1000.0 + i)
    with pytest.raises(PairError) as ei:
        pairing.reserve_attempt("1", now=1000.0 + 20)
    assert ei.value.status == 429
    pairing.reserve_attempt("1", now=1000.0 + pairing.RATE_WINDOW_S + 1)   # old attempts aged out


def test_malformed_attempts_do_not_burn_the_budget(helper, pool):
    c = make_client(pool)
    for _ in range(pairing.RATE_MAX_ATTEMPTS + 3):
        assert post(c, pin="abc").status_code == 400
    assert post(c).status_code == 200


# ── the token must ride on every call to an ollama node ─────────────────────

def test_ollama_probe_sends_the_bearer_token(monkeypatch):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.url.path, req.headers.get("authorization")))
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"detail": "no"})
        return httpx.Response(200, json={"models": [{"model": "llama3:8b"}, {"name": "qwen3:4b"}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        probe.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    spec = NodeSpec(name="lab", base_url=BASE, dialect="ollama", token=TOKEN, source="db")
    st = asyncio.new_event_loop().run_until_complete(probe._probe(spec, 2.0))
    assert seen == [("/api/tags", f"Bearer {TOKEN}")]
    assert st.reachable and st.models == {"llama3:8b", "qwen3:4b"}

    # And without a token the same node is reported as an auth failure, not as empty.
    seen.clear()
    bare = NodeSpec(name="lab", base_url=BASE, dialect="ollama", source="db")
    st = asyncio.new_event_loop().run_until_complete(probe._probe(bare, 2.0))
    assert not st.reachable and st.error == "HTTP 401"


def test_routing_headers_and_chat_url_for_an_ollama_node():
    spec = NodeSpec(name="lab", base_url=BASE, dialect="ollama", token=TOKEN)
    assert spec.headers()["Authorization"] == f"Bearer {TOKEN}"
    assert spec.chat_url == f"{BASE}/v1/chat/completions"
    assert TOKEN not in json.dumps(spec.public())


def test_a_db_row_round_trips_token_into_the_spec(monkeypatch):
    spec = registry.from_mapping(
        {"name": "lab", "base_url": BASE, "dialect": "ollama", "token": TOKEN}, source="db")
    assert spec.dialect == "ollama" and spec.headers()["Authorization"] == f"Bearer {TOKEN}"
