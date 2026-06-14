"""OpenWebUI-compatibility facade for the Harvis backend.

Lets the (forked) OpenWebUI SvelteKit frontend run against Harvis's existing
FastAPI backend by speaking OWUI's HTTP contract and translating to Harvis logic
in-process. See ``router.py`` for the endpoint map and ``config.py`` for the
boot feature-flag matrix.

Streaming model (Option A): OWUI's normal chat is patched to read HTTP SSE, and
``enable_websocket`` is False in /api/config — so chat reuses Harvis's
``model_proxy`` SSE directly and no Socket.IO server is needed.
"""

from __future__ import annotations

from .persistence import (
    CREATE_OWUI_CHATS_SQL,
    CREATE_OWUI_COMPARISONS_SQL,
    CREATE_OWUI_FILES_SQL,
    CREATE_OWUI_FOLDERS_SQL,
)
from .router import OwuiDeps, create_owui_router

__all__ = [
    "create_owui_router",
    "OwuiDeps",
    "CREATE_OWUI_CHATS_SQL",
    "CREATE_OWUI_COMPARISONS_SQL",
    "CREATE_OWUI_FILES_SQL",
    "CREATE_OWUI_FOLDERS_SQL",
]
