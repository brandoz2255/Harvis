"""Adding an MCP server by URL: no transport needed, either sign-in field name,
stdio stays admin-only, private addresses stay blocked, and catalog entries that
cannot be added say what to do instead of failing."""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import mcp_inputs, rest_capabilities  # noqa: E402

USER = {"id": 7}


class Req:
    def __init__(self, body):
        self._body = body
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=None))

    async def json(self):
        return self._body


@pytest.fixture
def saved(monkeypatch):
    calls = []

    async def fake_upsert(request, user, **kw):
        calls.append(kw)
        return {"ok": True}
    monkeypatch.setattr(rest_capabilities, "_upsert_server", fake_upsert)
    return calls


def add(body):
    return asyncio.run(rest_capabilities.mcp_server_add(Req(body), USER))


@pytest.mark.parametrize("url,expected", [
    ("https://mcp.deepwiki.com/mcp", "streamable-http"),
    ("https://example.com/", "streamable-http"),
    ("https://example.com/sse", "sse"),
    ("https://example.com/v1/SSE/", "sse"),
])
def test_transport_is_inferred_from_the_url(url, expected):
    assert mcp_inputs.infer_transport(None, url, None) == expected
    assert mcp_inputs.infer_transport("", url, None) == expected


def test_explicit_transport_wins_and_aliases_fold():
    assert mcp_inputs.infer_transport("sse", "https://x.io/mcp", None) == "sse"
    assert mcp_inputs.infer_transport("HTTP", "https://x.io/mcp", None) == "streamable-http"
    assert mcp_inputs.infer_transport("streamable_http", None, None) == "streamable-http"
    assert mcp_inputs.infer_transport(None, None, "npx") == "stdio"


def test_both_auth_field_names_work():
    assert mcp_inputs.normalize_auth({"auth": "oauth"}) == "oauth"
    assert mcp_inputs.normalize_auth({"auth_method": "oauth"}) == "oauth"
    assert mcp_inputs.normalize_auth({"auth_method": "OAuth", "auth": "none"}) == "oauth"
    assert mcp_inputs.normalize_auth({"auth_method": "none", "auth": "oauth"}) == "none"
    assert mcp_inputs.normalize_auth({}) == "none"


def test_ui_payload_with_only_name_and_url_is_saved_as_remote(saved):
    out = add({"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"})
    assert out["transport"] == "streamable-http" and out["url"] == "https://mcp.deepwiki.com/mcp"
    assert saved[0]["transport"] == "streamable-http" and saved[0]["command"] is None
    assert saved[0]["auth_method"] == "none"


def test_ui_auth_field_is_honored(saved):
    add({"name": "linear", "url": "https://mcp.linear.app/mcp", "auth": "oauth"})
    assert saved[0]["auth_method"] == "oauth"


def test_sse_url_is_stored_as_sse(saved):
    add({"name": "old", "url": "https://example.com/sse"})
    assert saved[0]["transport"] == "sse"


def test_command_without_url_is_stdio(saved):
    add({"name": "fs", "command": "npx", "args": ["-y", "server"]})
    assert saved[0]["transport"] == "stdio" and saved[0]["command"] == "npx"


def test_nothing_to_connect_to_explains_both_options(saved):
    with pytest.raises(HTTPException) as exc:
        add({"name": "empty"})
    assert exc.value.status_code == 400 and "URL" in exc.value.detail and saved == []


def test_name_is_required(saved):
    with pytest.raises(HTTPException) as exc:
        add({"url": "https://x.io/mcp"})
    assert exc.value.status_code == 400


def test_unknown_transport_is_rejected(saved):
    with pytest.raises(HTTPException) as exc:
        add({"name": "x", "url": "https://x.io", "transport": "carrier-pigeon"})
    assert exc.value.status_code == 400


def test_stdio_still_needs_the_build_space(monkeypatch):
    from plugins import exposure

    def deny(user):
        raise HTTPException(403, "stdio servers are admin-only")
    monkeypatch.setattr(exposure, "require_build_space", deny)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rest_capabilities._upsert_server(
            Req({}), USER, name="x", transport="stdio", url=None, command="npx", args=[],
            auth_method="none", env={}, credentials={}))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/mcp", "http://169.254.169.254/latest", "http://localhost/mcp",
                                 "http://10.0.0.5/sse"])
def test_private_addresses_stay_blocked(url):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rest_capabilities._upsert_server(
            Req({}), USER, name="x", transport="streamable-http", url=url, command=None, args=[],
            auth_method="none", env={}, credentials={}))
    assert exc.value.status_code == 400


# ─── catalog: entries with nothing to install say what to do ────────────────

EXTERNAL = {"id": "salesforce", "name": "Salesforce", "connect": "external", "homepage": "https://sf.example"}
HOSTED = {"id": "sentry", "name": "Sentry", "connect": "remote_oauth", "mcp_url": "https://mcp.sentry.dev/mcp"}
CUSTOM = {"id": "custom-url", "name": "Custom server (URL)", "connect": "install", "transport": "sse",
          "fields": [{"key": "url", "label": "Server URL", "required": True}]}


def test_external_entry_is_flagged_with_where_to_go():
    row = rest_capabilities._catalog_entry(EXTERNAL, {})
    assert row["needs_setup"] is True
    assert "sf.example" in row["setup_note"] and "Import" in row["setup_note"]
    assert row["url"] is None


def test_hosted_and_custom_entries_are_not_flagged():
    assert rest_capabilities._catalog_entry(HOSTED, {})["needs_setup"] is False
    assert rest_capabilities._catalog_entry(CUSTOM, {})["needs_setup"] is False
    assert rest_capabilities._catalog_entry(HOSTED, {})["setup_note"] == ""


def test_installing_an_external_entry_is_a_clear_409(monkeypatch):
    async def merged():
        return {"salesforce": EXTERNAL}
    monkeypatch.setattr(rest_capabilities, "_merged_catalog", merged)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rest_capabilities.mcp_catalog_install(Req({"name": "Salesforce"}), USER))
    assert exc.value.status_code == 409 and "needs setup" in exc.value.detail


def test_custom_url_card_uses_the_address_typed(monkeypatch, saved):
    async def merged():
        return {"custom-url": CUSTOM}
    monkeypatch.setattr(rest_capabilities, "_merged_catalog", merged)
    asyncio.run(rest_capabilities.mcp_catalog_install(
        Req({"name": "custom-url", "env": {"url": "https://example.com/mcp"}}), USER))
    assert saved[0]["url"] == "https://example.com/mcp" and saved[0]["transport"] == "streamable-http"
    assert saved[0]["env"] == {}


def test_every_real_catalog_entry_is_either_installable_or_explains_itself():
    merged = asyncio.run(rest_capabilities._merged_catalog())
    assert merged
    for src in merged.values():
        row = rest_capabilities._catalog_entry(src, {})
        installable = bool(src.get("mcp_url") or src.get("command_template")
                           or any(f.get("key") == "url" for f in src.get("fields") or []))
        assert row["needs_setup"] is (not installable)
        assert bool(row["setup_note"]) is row["needs_setup"]
