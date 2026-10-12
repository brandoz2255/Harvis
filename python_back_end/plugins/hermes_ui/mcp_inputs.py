"""Reading what the MCP tab and the chat "add a server" card send.

The desktop UI sends ``{name, url}`` for a remote server and spells the sign-in
choice ``auth``; the OWUI connections page and the Hermes CLI spell it
``auth_method`` and always name a transport. Both shapes have to work, and a URL
alone has to be enough — the person pasting a link does not know (or care)
whether the server speaks streamable HTTP or the older SSE transport.
"""
from __future__ import annotations

from urllib.parse import urlparse

TRANSPORTS = ("stdio", "sse", "streamable-http")

_ALIASES = {
    "http": "streamable-http", "https": "streamable-http", "streamable_http": "streamable-http",
    "streamablehttp": "streamable-http", "streamable-http": "streamable-http",
    "sse": "sse", "stdio": "stdio",
}


def infer_transport(transport, url, command) -> str:
    """The transport to store.

    An explicit value wins (after alias folding). Otherwise a URL means a remote
    server — streamable HTTP, unless the path says ``/sse``, which is the one
    unambiguous signal of the legacy transport — and a bare command means stdio.
    The runtime's ``open_http_session`` falls back from one HTTP transport to the
    other at connect time, so a wrong guess here is not fatal.
    """
    raw = str(transport or "").strip().lower()
    if raw:
        return _ALIASES.get(raw, raw)
    if url:
        path = urlparse(str(url).strip()).path.rstrip("/").lower()
        return "sse" if path.endswith("/sse") else "streamable-http"
    return "stdio" if command else "stdio"


def normalize_auth(body: dict) -> str:
    """``oauth`` or ``none``, from either field name (``auth_method`` wins)."""
    raw = body.get("auth_method")
    if raw in (None, ""):
        raw = body.get("auth")
    return "oauth" if str(raw or "").strip().lower() == "oauth" else "none"


def needs_setup_note(src: dict) -> str | None:
    """Why a catalog entry cannot be added with one click, or None if it can.

    An entry with neither a hosted URL nor a command template is a pointer to a
    product, not something Harvis can run; saying so beats an Install button that
    fails after the click.
    """
    if src.get("mcp_url") or src.get("command_template"):
        return None
    # "Custom server (URL)" has no address of its own: the person supplies it.
    if any(f.get("key") == "url" for f in (src.get("fields") or [])):
        return None
    where = src.get("homepage") or src.get("docs_url")
    tail = f" Setup steps: {where}" if where else ""
    return ("This connector has no hosted MCP address Harvis knows of. Find its MCP "
            "server URL (or run command) in its own docs, then paste it with Import on the MCP page." + tail)
