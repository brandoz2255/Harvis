"""OAuth tokens and client info are sealed at rest; old plaintext rows still work
and are sealed on first read."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.mcp import credentials, token_storage  # noqa: E402
from plugins.mcp.token_storage import PgTokenStorage  # noqa: E402


class FakePool:
    """Just enough of asyncpg for mcp_oauth_tokens: one row, keyed by (user, server)."""

    def __init__(self):
        self.row = None

    def acquire(self):
        pool = self

        class Ctx:
            async def __aenter__(self_inner):
                return pool

            async def __aexit__(self_inner, *a):
                return False
        return Ctx()

    async def fetchrow(self, sql, *args):
        if self.row is None:
            return None
        return {"tokens_json": self.row.get("tokens_json"), "expires_at": self.row.get("expires_at"),
                "client_info_json": self.row.get("client_info_json")}

    async def execute(self, sql, *args):
        row = self.row = self.row or {}
        if sql.lstrip().startswith("UPDATE"):
            column = "tokens_json" if "tokens_json" in sql else "client_info_json"
            row[column] = args[2]
        elif "INSERT" in sql and "tokens_json" in sql:
            row["tokens_json"], row["expires_at"] = args[2], args[3]
        elif "INSERT" in sql:
            row["client_info_json"] = args[2]
        elif sql.lstrip().startswith("DELETE"):
            self.row = None


@pytest.fixture(autouse=True)
def shim_cipher(monkeypatch):
    """Stand-in for the Fernet helpers in main.py (importing main needs the whole app)."""
    import base64
    monkeypatch.setattr(credentials, "seal", lambda v: {credentials.SEALED: "enc:" + base64.b64encode(v[::-1].encode()).decode()})
    monkeypatch.setattr(credentials, "unseal", lambda v: base64.b64decode(v[credentials.SEALED][4:]).decode()[::-1]
                        if credentials.is_sealed(v) else str(v))


def run(coro):
    return asyncio.run(coro)


def storage(pool):
    return PgTokenStorage(pool=pool, user_id=7, server_name="notion")


def test_tokens_are_stored_sealed_and_read_back_plain():
    pool = FakePool()
    run(storage(pool).set_tokens({"access_token": "SECRET-ACCESS", "refresh_token": "SECRET-REFRESH", "expires_in": 3600}))
    raw = pool.row["tokens_json"]
    assert "SECRET-ACCESS" not in raw and "SECRET-REFRESH" not in raw
    assert credentials.SEALED in json.loads(raw)
    got = run(storage(pool).get_tokens())
    assert got["access_token"] == "SECRET-ACCESS" and 3500 < got["expires_in"] <= 3600


def test_client_info_is_sealed_too():
    pool = FakePool()
    run(storage(pool).set_client_info({"client_id": "id-1", "client_secret": "SECRET-CLIENT"}))
    assert "SECRET-CLIENT" not in pool.row["client_info_json"]
    assert run(storage(pool).get_client_info()) == {"client_id": "id-1", "client_secret": "SECRET-CLIENT"}


def test_legacy_plaintext_rows_still_read_and_are_sealed_on_first_read():
    pool = FakePool()
    pool.row = {"tokens_json": json.dumps({"access_token": "OLD-PLAIN", "refresh_token": "OLD-R"}),
                "client_info_json": json.dumps({"client_id": "c"}),
                "expires_at": datetime.fromtimestamp(4102444800, tz=timezone.utc)}
    assert run(storage(pool).get_tokens())["access_token"] == "OLD-PLAIN"
    assert run(storage(pool).get_client_info()) == {"client_id": "c"}
    assert "OLD-PLAIN" not in pool.row["tokens_json"] and credentials.SEALED in json.loads(pool.row["tokens_json"])
    assert credentials.SEALED in json.loads(pool.row["client_info_json"])
    # and the sealed copy reads back the same
    assert run(storage(pool).get_tokens())["refresh_token"] == "OLD-R"


def test_an_undecryptable_row_reads_as_never_authorized(monkeypatch):
    pool = FakePool()
    run(storage(pool).set_tokens({"access_token": "X", "expires_in": 100}))
    monkeypatch.setattr(credentials, "unseal", lambda v: "")
    assert "access_token" not in (run(storage(pool).get_tokens()) or {})
