# Adapted shape from NousResearch/hermes-agent (MIT) — agent/memory_provider.py.
# Hermes ships a generic plugin interface that any of 9 backends (honcho,
# holographic, mem0, supermemory, …) can implement. This is the Harvis
# version: same lifecycle shape, but with per-user APIs since Harvis is
# multi-tenant (Hermes is single-user-per-profile).
#
# Memory providers are NOT registered through the Phase 3B hook plugin
# loader — they're singletons selected by config (only one active at a
# time). The MemoryManager in manager.py owns selection and lifecycle.

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryEntry:
    """A single retrievable memory."""

    user_id: int
    content: str
    source: str = "unspecified"            # e.g. "session-extract", "manual", "imported"
    metadata: dict = field(default_factory=dict)
    created_at: Optional[datetime] = None  # populated by the provider on insert


class MemoryProvider(abc.ABC):
    """Per-user memory backend contract.

    Implementations may be Postgres-backed (builtin), file-based, vector-DB,
    or external services (Honcho, mem0, …). Lifecycle is:

        await provider.startup(config)         # connect / init
        ...
        await provider.remember(user_id, ...)  # write
        await provider.recall(user_id, ...)    # read
        await provider.extract_from_session(..)  # post-session ingestion
        ...
        await provider.shutdown()              # close / flush

    All public methods MUST be async-safe. Implementations should be
    forgiving: ``recall`` returns ``[]`` rather than raising on a missing
    user; ``remember`` no-ops if the provider is misconfigured.
    """

    name: str = "abstract"

    async def startup(self, config: Optional[dict] = None) -> None:
        """Connect to the backing store. Default: no-op."""
        return None

    async def shutdown(self) -> None:
        """Close connections / flush. Default: no-op."""
        return None

    @abc.abstractmethod
    async def remember(
        self,
        user_id: int,
        content: str,
        *,
        source: str = "manual",
        metadata: Optional[dict] = None,
    ) -> Optional[MemoryEntry]:
        """Persist a memory for ``user_id``. Returns the stored entry on
        success (with created_at populated), or None on failure.
        """

    @abc.abstractmethod
    async def recall(
        self,
        user_id: int,
        *,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Retrieve memories for ``user_id``. ``query`` is a free-text hint
        that providers MAY use for semantic / substring matching; passing
        None returns the most recent N memories.
        """

    async def extract_from_session(
        self,
        user_id: int,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> list[MemoryEntry]:
        """Optional hook — providers that do post-session memory
        distillation (LLM summarization, fact extraction, …) implement
        this. Default: no-op, returns empty list.
        """
        return []

    async def forget(self, user_id: int, *, memory_id: Any = None) -> int:
        """Optional hook — delete a specific memory or wipe the user's
        memory entirely (when memory_id is None). Default: not supported,
        returns 0.
        """
        return 0
