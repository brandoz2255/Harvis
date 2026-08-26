"""Gate 8A — the text-inlining fetcher cannot be pointed at internal services.

`_download_text_attachment` takes a URL straight off a client-supplied attachment
and inlines the response body into the model's context. Before this it was a
plain `httpx.get(url, follow_redirects=True)`, which made it a read primitive for
anything the backend can reach — the Ollama admin API, Postgres' port, a cloud
metadata endpoint — with the answer delivered back to the caller inside their own
agent transcript.

These tests assert the two rules that close it, and assert them the only way that
proves anything: by failing if a socket is opened at all. A test that merely
checks the return is None would pass on a network error and tell us nothing.
"""

import importlib

import pytest

# `from workspace import workspace_router` returns the APIRouter object the
# package re-exports under that name, not the module. Import the module itself.
wr = importlib.import_module("workspace.workspace_router")


@pytest.fixture
def attempts(monkeypatch):
    """Records every request that reaches the wire, and blocks it.

    Both the old code path and the new one go out through
    ``httpx.AsyncClient.send``, so this catches either. Recording rather than
    just raising is deliberate: `_download_text_attachment` swallows every
    exception and returns None, so a fixture that only raised would leave the
    vulnerable and the fixed versions indistinguishable — both return None.
    The tests assert on this list instead, and it is the assertion that fails
    on the pre-Gate-8A code.
    """
    import httpx

    log: list[str] = []

    async def record_send(_self, request, *_a, **_kw):
        log.append(str(request.url))
        raise RuntimeError("blocked by test")

    monkeypatch.setattr(httpx.AsyncClient, "send", record_send)
    return log


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        # The web composer's own shape. Never fetchable here; it carries a
        # file_id and resolves through the ownership-checked store instead.
        "/api/v1/files/2f0c1f6e-0000-4000-8000-000000000000/content",
        "files/notes.txt",
        "",
    ],
)
async def test_relative_urls_are_not_fetched(url, attempts):
    assert await wr._download_text_attachment(url) is None
    assert attempts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://ollama:11434/api/tags",
        "http://openclaw:18789/health",
        "http://pgsql:5432/",
        "http://127.0.0.1:8000/api/config",
        "http://localhost:8000/api/config",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:8000/",
        "file:///etc/passwd",
        "gopher://internal/",
    ],
)
async def test_internal_and_non_http_targets_are_refused(url, attempts):
    """Nothing reaches the wire — the allowlist rejects before DNS or connect."""
    assert await wr._download_text_attachment(url) is None
    assert attempts == [], f"{url} produced an outbound request: {attempts}"


@pytest.mark.asyncio
async def test_allowlist_is_the_one_attachments_uses():
    """Two copies of this list would drift, and the drift would be a hole."""
    from vision_to_code.attachments import REMOTE_ATTACHMENT_HOSTS, _REMOTE_HOSTS

    assert _REMOTE_HOSTS is REMOTE_ATTACHMENT_HOSTS
    assert "cdn.discordapp.com" in REMOTE_ATTACHMENT_HOSTS


@pytest.mark.asyncio
async def test_an_allowlisted_host_still_goes_through_the_hardened_fetcher(monkeypatch):
    """The Discord CDN is allowed — but via _safe_get, not a bare httpx call.

    This is what keeps redirect-to-internal closed: _safe_get re-validates every
    hop, where the old follow_redirects=True would have jumped blind.
    """
    seen = {}

    class _Resp:
        content = b"hello from discord"

    async def fake_safe_get(url, **kwargs):
        seen["url"] = url
        seen["allowlist"] = kwargs.get("host_allowlist")
        return _Resp()

    monkeypatch.setattr("agent_reach.tools._safe_get", fake_safe_get)

    out = await wr._download_text_attachment(
        "https://cdn.discordapp.com/attachments/1/2/notes.txt"
    )

    assert out == "hello from discord"
    assert seen["url"].startswith("https://cdn.discordapp.com/")
    assert "cdn.discordapp.com" in seen["allowlist"]
