"""The 6-digit first-admin code a shared server shows on the host.

A fake connection stands in for Postgres: it knows the users count and the
instance_settings rows, which is all the module touches.
"""
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from plugins.exposure import first_admin  # noqa: E402


class FakeConn:
    def __init__(self, users=0):
        self.users = users
        self.settings = {}

    async def fetchval(self, sql, *args):
        if "COUNT(*) FROM users" in sql:
            return self.users
        if "FROM instance_settings" in sql:
            return self.settings.get(args[0])
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if sql.startswith("INSERT INTO instance_settings"):
            self.settings[args[0]] = args[1]
        elif sql.startswith("DELETE FROM instance_settings"):
            self.settings.pop(args[0], None)
        elif "pg_advisory_xact_lock" not in sql:
            raise AssertionError(sql)

    @asynccontextmanager
    async def transaction(self):
        yield


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("HARVIS_EXPOSURE", "HARVIS_SETUP_CODE"):
        monkeypatch.delenv(key, raising=False)


def test_local_server_needs_no_code():
    conn = FakeConn()
    assert not first_admin.required()
    run(first_admin.on_startup(conn))
    assert conn.settings == {}


def test_shared_server_makes_a_code_and_keeps_only_its_hash(monkeypatch, caplog):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    conn = FakeConn()
    assert first_admin.required()
    with caplog.at_level("WARNING"):
        run(first_admin.on_startup(conn))
    stored = json.loads(conn.settings[first_admin.KEY])
    assert set(stored) == {"salt", "hash", "tries"}
    code = next(w for w in caplog.text.split() if w.isdigit() and len(w) == 6)
    assert code not in conn.settings[first_admin.KEY]
    assert run(first_admin.check(conn, code))


def test_restart_keeps_the_waiting_code(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    conn = FakeConn()
    code = run(first_admin.issue(conn))
    run(first_admin.on_startup(conn))
    assert run(first_admin.check(conn, code))


def test_five_wrong_codes_retire_it(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    conn = FakeConn()
    code = run(first_admin.issue(conn))
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(first_admin.MAX_TRIES):
        assert not run(first_admin.check(conn, wrong))
    assert run(first_admin.retired(conn))
    assert not run(first_admin.check(conn, code))
    # A restart replaces a retired code with a working one.
    run(first_admin.on_startup(conn))
    assert not run(first_admin.retired(conn))


def test_new_code_replaces_the_old_one(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    conn = FakeConn()
    old = run(first_admin.issue(conn))
    new = run(first_admin.issue(conn))
    if old != new:
        assert not run(first_admin.check(conn, old))
    assert run(first_admin.check(conn, new))


def test_claiming_and_existing_users_delete_the_code(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    conn = FakeConn()
    run(first_admin.issue(conn))
    run(first_admin.claimed(conn))
    assert conn.settings == {}
    run(first_admin.issue(conn))
    conn.users = 1
    run(first_admin.on_startup(conn))
    assert conn.settings == {}


def test_manual_setup_code_wins(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    monkeypatch.setenv("HARVIS_SETUP_CODE", "fixed-code")
    conn = FakeConn()
    run(first_admin.on_startup(conn))
    assert conn.settings == {}
    assert run(first_admin.check(conn, " fixed-code "))
    assert not run(first_admin.check(conn, "123456"))
    assert not run(first_admin.check(conn, None))


def test_no_code_on_file_is_a_no(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert not run(first_admin.check(FakeConn(), "123456"))
