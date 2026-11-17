"""Adding an MCP server whose name is already listed updates that server.

"GitHub" and "github" are the same connector to the person adding it, so no add
path may put a second row beside the first: not the Hermes MCP tab, not the
mcp.json editor's save, not the catalog, not the engine config merge.
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import rest_capabilities  # noqa: E402
from plugins.mcp import http_transport  # noqa: E402
from plugins.mcp.credentials import SEALED  # noqa: E402
from plugins.mcp.server_registry import stored_server_name  # noqa: E402

USER = {"id": 7}


class Conn:
    """Just enough of asyncpg for the mcp_servers statements these routes run."""

    def __init__(self, rows):
        self.rows = rows  # exact server_name -> row dict

    async def fetchval(self, sql, uid, name):
        if "lower(btrim(server_name))" in sql:
            exact = [n for n in self.rows if n == name]
            loose = [n for n in self.rows if n.strip().lower() == name.lower()]
            return (exact or loose or [None])[0]
        row = self.rows.get(name)
        return row and row["env"]

    async def fetch(self, sql, uid):
        return [{"server_name": n} for n in self.rows]

    async def execute(self, sql, uid, name, *rest):
        if sql.startswith("INSERT"):
            transport, url, command, args, env, auth = rest
            self.rows[name] = {**self.rows.get(name, {"enabled": True}), "transport": transport,
                               "url": url, "env": env, "auth_method": auth}
        elif sql.startswith("UPDATE"):
            self.rows[name]["enabled"] = rest[0]
        elif sql.startswith("DELETE"):
            self.rows.pop(name, None)
        return "OK 1"


class Pool:
    def __init__(self, rows):
        self.conn = Conn(rows)

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return Ctx()


class Req:
    def __init__(self, rows, body):
        self._body = body
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=Pool(rows)))

    async def json(self):
        return self._body


def run(coro):
    return asyncio.run(coro)


def _open_urls(monkeypatch):
    async def ok(url, strict):
        return None
    monkeypatch.setattr(http_transport, "guard_url_async", ok)


def _row(url="https://old.example.com/mcp", env="{}"):
    return {"transport": "streamable-http", "url": url, "env": env, "auth_method": "none", "enabled": True}


def test_the_stored_spelling_wins_whatever_the_capitalisation():
    conn = Conn({"GitHub": _row()})
    assert run(stored_server_name(conn, 7, "github")) == "GitHub"
    assert run(stored_server_name(conn, 7, "  GITHUB ")) == "GitHub"
    assert run(stored_server_name(conn, 7, "gitlab")) == "gitlab"


def test_an_exact_match_is_preferred_over_a_loose_one():
    conn = Conn({"GitHub": _row(), "github": _row()})  # rows saved before this rule
    assert run(stored_server_name(conn, 7, "github")) == "github"
    assert run(stored_server_name(conn, 7, "GitHub")) == "GitHub"


def test_adding_a_listed_name_updates_it_instead_of_adding_a_second(monkeypatch):
    _open_urls(monkeypatch)
    rows = {"GitHub": _row()}
    out = run(rest_capabilities.mcp_server_add(
        Req(rows, {"name": "github", "url": "https://new.example.com/mcp"}), USER))
    assert list(rows) == ["GitHub"]
    assert rows["GitHub"]["url"] == "https://new.example.com/mcp"
    assert out["name"] == "GitHub"  # the UI is told which entry it updated


def test_a_readd_keeps_the_stored_token(monkeypatch):
    _open_urls(monkeypatch)
    stored = {"TOKEN": {SEALED: "ciphertext"}}
    rows = {"GitHub": _row(env=json.dumps(stored))}
    run(rest_capabilities.mcp_server_add(
        Req(rows, {"name": "GITHUB", "url": "https://new.example.com/mcp"}), USER))
    assert json.loads(rows["GitHub"]["env"]) == stored


def test_a_new_name_is_still_added(monkeypatch):
    _open_urls(monkeypatch)
    rows = {"GitHub": _row()}
    run(rest_capabilities.mcp_server_add(
        Req(rows, {"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}), USER))
    assert sorted(rows) == ["GitHub", "deepwiki"]


def test_the_editor_save_does_not_delete_the_row_it_just_matched(monkeypatch):
    _open_urls(monkeypatch)
    rows = {"GitHub": _row(), "old": _row()}
    run(rest_capabilities.mcp_servers_replace(
        Req(rows, {"servers": {"github": {"url": "https://new.example.com/mcp", "enabled": False}}}), USER))
    assert list(rows) == ["GitHub"]  # matched and kept; "old" was not in the map, so removed
    assert rows["GitHub"]["url"] == "https://new.example.com/mcp"
    assert rows["GitHub"]["enabled"] is False
