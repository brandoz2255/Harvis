"""Time-boxing helpers for the chat web-search loop (owui_compat/chat_reach.py).

Two things lived inline in chat_reach and each cost the user a whole answer:

* one slow page fetch held ``asyncio.gather`` until the slowest URL finished, and
  when the overall budget ran out the pages already read were thrown away with
  it, so the chat said the search "timed out" with five good results in hand;
* a long question was cut at a fixed character count, mid-word, so the search
  engine got a query ending in half a word.

Both are small and pure, so they live here where they can be tested without the
network.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

QUERY_LIMIT = 200


def clip_query(text: str, limit: int = QUERY_LIMIT) -> str:
    """Shorten a search query to ``limit`` characters without cutting a word.

    Search engines ignore or mangle a query that ends in half a word, and a
    query that long is already past the point where more words help. Cuts at the
    last whitespace inside the limit; a single unbroken token longer than the
    limit (a URL, a hash) is cut hard because there is no better place.
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Only back up to a boundary when the character after the cut starts a new
    # word; if the cut already fell on a space the whole last word is intact.
    if text[limit] != " ":
        space = cut.rfind(" ")
        if space >= limit // 2:
            cut = cut[:space]
    return cut.rstrip(" ,;:-")


async def read_many(
    urls: list[str],
    reader: Callable[[str], Awaitable[dict]],
    budget_s: float,
    sink: list[dict],
) -> int:
    """Read ``urls`` concurrently for at most ``budget_s``; keep what finished.

    Each page is appended to ``sink`` the moment it completes, so a caller that is
    itself cancelled by an outer deadline still keeps every page that landed.
    Pages still in flight when the budget ends are cancelled. Returns how many
    pages were abandoned.
    """
    if not urls or budget_s <= 0:
        return len(urls)

    async def _one(url: str) -> None:
        page = await reader(url)
        if page.get("ok") and page.get("text"):
            sink.append(page)

    tasks = [asyncio.ensure_future(_one(u)) for u in urls]
    try:
        _done, pending = await asyncio.wait(tasks, timeout=budget_s)
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
    for t in tasks:
        if t.done() and not t.cancelled():
            t.exception()  # consume: a reader that raised must not log "never retrieved"
    return len(pending)
