"""MemoryManager — selects and lifecycles a single active memory provider.

Configuration is via ``HARVIS_MEMORY_PROVIDER`` env var (default ``builtin``).
Provider lookup is import-by-convention: the manager imports
``plugins.memory.<name>.provider`` and expects a top-level
``register_memory_provider(config)`` callable that returns a
``MemoryProvider`` instance.

The manager is a process-global singleton. Tests can swap it via
``set_manager`` exactly the way the hook registry does in Phase 3.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Optional

from .provider import MemoryProvider

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self) -> None:
        self._provider: Optional[MemoryProvider] = None
        self._provider_name: Optional[str] = None

    @property
    def provider(self) -> Optional[MemoryProvider]:
        return self._provider

    @property
    def provider_name(self) -> Optional[str]:
        return self._provider_name

    async def activate(
        self,
        name: Optional[str] = None,
        *,
        config: Optional[dict] = None,
    ) -> Optional[MemoryProvider]:
        """Resolve, instantiate, and start up the configured provider.

        Idempotent: calling activate() a second time tears down the prior
        provider before bringing the new one up.
        """
        if self._provider is not None:
            await self.deactivate()

        target = name or os.getenv("HARVIS_MEMORY_PROVIDER", "builtin").strip()
        if not target:
            logger.info("memory: HARVIS_MEMORY_PROVIDER empty — no provider active")
            return None

        package = f"plugins.memory.{target}.provider"
        try:
            module = importlib.import_module(package)
        except Exception:
            logger.exception("memory: provider %r failed to import (%s)", target, package)
            return None

        register = getattr(module, "register_memory_provider", None)
        if register is None or not callable(register):
            logger.error(
                "memory: provider %r in %s missing register_memory_provider() factory",
                target, package,
            )
            return None

        try:
            instance = register(config or {})
        except Exception:
            logger.exception("memory: register_memory_provider raised for %r", target)
            return None

        if not isinstance(instance, MemoryProvider):
            logger.error(
                "memory: provider %r returned %r, not a MemoryProvider subclass",
                target, type(instance).__name__,
            )
            return None

        try:
            await instance.startup(config or {})
        except Exception:
            logger.exception("memory: provider %r startup raised — leaving inactive", target)
            return None

        self._provider = instance
        self._provider_name = target
        logger.info("memory: provider activated — %s", target)
        return instance

    async def deactivate(self) -> None:
        if self._provider is None:
            return
        try:
            await self._provider.shutdown()
        except Exception:
            logger.exception("memory: provider %r shutdown raised", self._provider_name)
        self._provider = None
        self._provider_name = None


# Module-global singleton.
_manager = MemoryManager()


def get_manager() -> MemoryManager:
    return _manager


def set_manager(manager: MemoryManager) -> None:
    """Test seam — swap the global manager."""
    global _manager
    _manager = manager
