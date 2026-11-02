"""Messaging links are scoped to a bot. A user's own bot answers that user's links only, so
the same chat identity may be linked to several users; only the house bot's links
(`house`) are one per identity. The database is faked with the constraints the
migration adds (unique per user, plus unique among house rows); nothing here opens a
socket."""
import asyncio
import os
import sys
from types import SimpleNamespace

import asyncpg
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import messaging_pairing  # noqa: E402
from plugins.messaging import routes  # noqa: E402
from plugins.messaging.types import Platform  # noqa: E402


class FakeConn:
    """messaging_platforms as migration 026 leaves it: UNIQUE (user_id, platform, identifier) and
    a unique (platform, identifier) among rows with house = TRUE.

    Answers the statements the link, unlink and resolve paths issue: the two upserts (`$6`
    marks the typed link, which may promote a row to house and never demotes one; the
    pairing upsert never touches house), the per-user delete, and the dispatcher lookups
    (`$3` marks the owner-scoped one, otherwise house rows)."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []

    def find(self, user_id, platform, identifier):
        return next((r for r in self.rows if (r["user_id"], r["platform"], r["identifier"])
                     == (user_id, platform, identifier)), None)

    def _house_taken(self, user_id, platform, identifier):
        return any(r["house"] and r["user_id"] != user_id and (r["platform"], r["identifier"])
                   == (platform, identifier) for r in self.rows)

    async def execute(self, sql, user_id, platform, identifier, *rest):
        if sql.lstrip().startswith("DELETE"):
            self.rows[:] = [r for r in self.rows if (r["user_id"], r["platform"], r["identifier"])
                            != (user_id, platform, identifier)]
            return
        assert sql.lstrip().startswith("INSERT INTO messaging_platforms")
        typed = "$6" in sql
        name, enabled, house = (rest[0], rest[1], rest[2]) if typed else (rest[0], True, False)
        existing = self.find(user_id, platform, identifier)
        wanted_house = (existing["house"] if existing else False) or (house if typed else False)
        if wanted_house and self._house_taken(user_id, platform, identifier):
            raise asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
        if existing is None:
            self.rows.append({"user_id": user_id, "platform": platform, "identifier": identifier,
                              "name": name, "enabled": enabled, "house": wanted_house})
        else:
            existing.update(name=name, enabled=enabled, house=wanted_house)

    async def fetchrow(self, sql, platform, identifier, *rest):
        if "$3" in sql:
            owner = rest[0]
            match = [r for r in self.rows if r["user_id"] == owner and r["platform"] == platform
                     and r["identifier"] == identifier and r["enabled"]]
        else:
            match = [r for r in self.rows if r["house"] and r["platform"] == platform
                     and r["identifier"] == identifier and r["enabled"]]
        return {"user_id": match[0]["user_id"]} if match else None


class FakePool:
    def __init__(self, rows=None):
        self.conn = FakeConn(rows)

    @property
    def rows(self):
        return self.conn.rows

    def find(self, user_id, platform, identifier):
        return self.conn.find(user_id, platform, identifier)

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self_):
                return conn

            async def __aexit__(self_, *a):
                return False

        return Ctx()


def row(user_id, identifier="555", *, house=False, enabled=True, name="Ann", platform="telegram"):
    return {"user_id": user_id, "platform": platform, "identifier": identifier, "name": name,
            "enabled": enabled, "house": house}


def run(coro):
    return asyncio.run(coro)


def _request(pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))


def _link(pool, user_id, identifier="555"):
    body = routes.PlatformLink(platform=Platform.TELEGRAM, identifier=identifier, sender_display_name="Ann")
    return routes.link_platform(body, _request(pool), {"id": user_id})


@pytest.fixture
def local_admin(monkeypatch):
    monkeypatch.setattr(routes.exposure_mode, "shared", lambda: False)
    monkeypatch.setattr(routes, "is_admin", lambda user: True)


@pytest.fixture
def local_user(monkeypatch):
    monkeypatch.setattr(routes.exposure_mode, "shared", lambda: False)
    monkeypatch.setattr(routes, "is_admin", lambda user: False)


def test_admin_typed_link_is_a_house_link(local_admin):
    pool = FakePool()
    assert run(_link(pool, 7)) == {"ok": True}
    assert pool.rows == [row(7, house=True)]


def test_admin_cannot_take_a_house_identity_from_another_user(local_admin):
    pool = FakePool([row(7, house=True)])
    with pytest.raises(HTTPException) as info:
        run(_link(pool, 8))
    assert info.value.status_code == 409
    assert "another user" in info.value.detail
    assert pool.rows == [row(7, house=True)]


def test_admin_typed_link_is_not_blocked_by_someone_elses_own_bot_link(local_admin):
    pool = FakePool([row(7, house=False)])
    assert run(_link(pool, 8)) == {"ok": True}
    assert pool.find(7, "telegram", "555")["house"] is False
    assert pool.find(8, "telegram", "555")["house"] is True


def test_admin_linking_an_identity_held_as_own_bot_makes_it_house(local_admin):
    pool = FakePool([row(7, house=False, name="Old")])
    run(_link(pool, 7))
    assert pool.rows == [row(7, house=True)]


def test_admin_cannot_promote_an_own_bot_link_over_another_users_house_link(local_admin):
    pool = FakePool([row(7, house=True), row(8, house=False)])
    with pytest.raises(HTTPException) as info:
        run(_link(pool, 8))
    assert info.value.status_code == 409
    assert pool.find(8, "telegram", "555")["house"] is False


def test_local_non_admin_types_a_link_for_their_own_bot_only(local_user):
    pool = FakePool([row(7, house=True)])
    assert run(_link(pool, 8)) == {"ok": True}
    assert pool.find(8, "telegram", "555") == row(8, house=False)
    assert pool.find(7, "telegram", "555") == row(7, house=True)


def test_local_non_admin_relink_keeps_a_house_link_house(local_user):
    pool = FakePool([row(7, house=True, name="Old")])
    run(_link(pool, 7))
    assert pool.rows == [row(7, house=True)]


def test_link_platform_on_a_shared_host_is_admin_only(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(routes.exposure_mode, "shared", lambda: True)
    monkeypatch.setattr(routes, "is_admin", lambda user: user["id"] == 1)
    with pytest.raises(HTTPException) as info:
        run(_link(pool, 8))
    assert info.value.status_code == 403
    assert pool.rows == []
    assert run(_link(pool, 1)) == {"ok": True}
    assert pool.rows == [row(1, house=True)]


def test_pairing_links_the_owners_own_bot_without_touching_other_users():
    pool = FakePool([row(7, house=True)])
    run(messaging_pairing.link_sender(pool, 8, "telegram", "555", "Mallory"))
    assert pool.find(8, "telegram", "555") == row(8, house=False, name="Mallory")
    assert pool.find(7, "telegram", "555") == row(7, house=True)


def test_pairing_the_same_sender_again_updates_the_owners_row():
    pool = FakePool()
    run(messaging_pairing.link_sender(pool, 7, "telegram", "555", "Ann"))
    run(messaging_pairing.link_sender(pool, 7, "telegram", "555", "Ann B"))
    assert pool.rows == [row(7, name="Ann B")]


def test_pairing_never_flips_a_house_link_the_owner_already_holds():
    pool = FakePool([row(7, house=True, enabled=False)])
    run(messaging_pairing.link_sender(pool, 7, "telegram", "555", "Ann"))
    assert pool.rows == [row(7, house=True)]


def test_two_users_can_pair_the_same_sender_to_their_own_bots():
    pool = FakePool()
    run(messaging_pairing.link_sender(pool, 7, "telegram", "555", "Ann"))
    run(messaging_pairing.link_sender(pool, 8, "telegram", "555", "Ann"))
    assert sorted(r["user_id"] for r in pool.rows) == [7, 8]
    assert all(r["house"] is False for r in pool.rows)


def test_unlink_removes_only_the_callers_own_row():
    pool = FakePool([row(7), row(8), row(8, "999")])
    run(messaging_pairing.unlink_sender(pool, 8, "telegram", "555"))
    assert sorted((r["user_id"], r["identifier"]) for r in pool.rows) == [(7, "555"), (8, "999")]


def test_pairing_approve_succeeds_when_another_user_holds_the_identity(monkeypatch):
    saved = []
    state = {"approved": [], "pending": [{"platform": "telegram", "request_id": "r1", "user_id": "555",
                                         "user_name": "Ann"}]}

    async def get_key(pool, uid, key, default=None):
        return state

    async def set_key(pool, uid, key, value):
        saved.append(value)

    pool = FakePool([row(7, house=True)])
    monkeypatch.setattr(messaging_pairing.settings_store, "get_key", get_key)
    monkeypatch.setattr(messaging_pairing.settings_store, "set_key", set_key)
    monkeypatch.setattr(messaging_pairing, "_pool", lambda request: pool)
    monkeypatch.setattr(messaging_pairing, "_uid", lambda user: 8)

    class Req:
        async def json(self):
            return {"platform": "telegram", "request_id": "r1"}

    out = run(messaging_pairing.pairing_approve(Req(), {"id": 8}))
    assert out["ok"] is True
    assert saved and saved[0]["pending"] == [] and saved[0]["approved"][0]["user_id"] == "555"
    assert pool.find(8, "telegram", "555")["house"] is False
    assert pool.find(7, "telegram", "555")["house"] is True


def _settings_update(existing, body):
    """Run owui_user_settings_update against a one-row fake and return what it stored."""
    from fastapi import APIRouter

    from owui_compat import user_settings

    stored = {}

    class Conn:
        async def fetchrow(self, sql, uid):
            return {"settings": existing} if existing is not None else None

        async def execute(self, sql, uid, blob):
            import json
            stored.update(json.loads(blob))

        def transaction(self):
            class T:
                async def __aenter__(s):
                    return None

                async def __aexit__(s, *a):
                    return False
            return T()

    class Pool:
        def acquire(self):
            class C:
                async def __aenter__(s):
                    return Conn()

                async def __aexit__(s, *a):
                    return False
            return C()

    router = APIRouter()
    user_settings.register_user_settings_routes(router, lambda: None)
    handler = next(r.endpoint for r in router.routes if r.path.endswith("/settings/update"))

    class Req:
        app = SimpleNamespace(state=SimpleNamespace(pg_pool=Pool()))

        async def json(self):
            return body

    run(handler(Req(), SimpleNamespace(id=8)))
    return stored


def test_settings_update_ignores_forged_server_managed_subtrees():
    forged = {"pairing": {"pending": [{"platform": "discord", "request_id": "x", "user_id": "999"}]}}
    stored = _settings_update({"ui": {}}, {"ui": {"a": 1}, "hermes_ui": forged, "integrations": {"x": 1}})
    assert "hermes_ui" not in stored and "integrations" not in stored
    assert stored["ui"] == {"a": 1}


def test_settings_update_keeps_the_existing_server_managed_subtrees():
    existing = {"hermes_ui": {"pairing": {"approved": []}}, "harvis": {"k": 1}}
    stored = _settings_update(existing, {"ui": {}, "hermes_ui": {"pairing": {"pending": ["forged"]}}})
    assert stored["hermes_ui"] == existing["hermes_ui"]
    assert stored["harvis"] == {"k": 1}
