# Adapted shape from NousResearch/hermes-agent (MIT) — hermes_cli/plugins.py
# Hermes ships 16 named hooks; this is a leaner subset focused on what
# Harvis's plugin surface actually needs in Phase 3. Reserved names are
# pre-declared so plugins fail fast on typos and so the registry is
# stable as later phases (memory, cron, MCP) wire up their own firings.

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable, Union

logger = logging.getLogger(__name__)


# All hook names plugins are allowed to register against. Trying to register
# anything outside this set raises ValueError. We add new names as later
# phases need them — we don't accept arbitrary strings.
VALID_HOOKS: frozenset[str] = frozenset({
    # Gateway lifecycle (Phase 3 — fired by the messaging dispatcher).
    "pre_gateway_dispatch",   # before workspace launch; may skip the message
    "on_session_start",       # workspace launched successfully
    "on_session_end",         # workspace reached terminal status (reserved — not yet fired)

    # Tool lifecycle (reserved for OpenClaw integration).
    "pre_tool_call",
    "post_tool_call",
    "transform_tool_result",

    # LLM lifecycle (reserved).
    "pre_llm_call",
    "post_llm_call",

    # Approval (reserved — needs backend "run paused awaiting approval" state).
    "pre_approval_request",
    "post_approval_response",
})


HookHandler = Callable[..., Union[Any, Awaitable[Any]]]


class HookRegistry:
    """In-process registry of plugin hook handlers.

    Handlers are sync or async; ``invoke`` awaits awaitables and collects
    return values into a list (in registration order). Exceptions in any
    one handler are logged and swallowed — they never break the dispatch
    chain. Plugins are observers by default; the only firings whose return
    values are *interpreted* are documented at each call site.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = {h: [] for h in VALID_HOOKS}

    def register(self, name: str, handler: HookHandler) -> None:
        if name not in VALID_HOOKS:
            raise ValueError(
                f"unknown hook {name!r}; valid hooks: {sorted(VALID_HOOKS)}"
            )
        self._handlers.setdefault(name, []).append(handler)
        logger.info(
            "plugin hook registered: %s -> %s",
            name,
            getattr(handler, "__qualname__", repr(handler)),
        )

    def unregister(self, name: str, handler: HookHandler) -> bool:
        bucket = self._handlers.get(name) or []
        try:
            bucket.remove(handler)
            return True
        except ValueError:
            return False

    def list_handlers(self) -> dict[str, list[str]]:
        return {
            h: [getattr(c, "__qualname__", repr(c)) for c in self._handlers.get(h, [])]
            for h in sorted(VALID_HOOKS)
        }

    def has_handlers(self, name: str) -> bool:
        return bool(self._handlers.get(name))

    async def invoke(self, name: str, **kwargs: Any) -> list[Any]:
        if name not in VALID_HOOKS:
            logger.warning("invoke_hook on unknown hook %r — skipping", name)
            return []
        results: list[Any] = []
        for handler in list(self._handlers.get(name, [])):
            try:
                ret = handler(**kwargs)
                if inspect.isawaitable(ret):
                    ret = await ret
                results.append(ret)
            except Exception:
                logger.exception(
                    "plugin hook handler raised: %s for hook %s",
                    getattr(handler, "__qualname__", repr(handler)),
                    name,
                )
        return results


# Module-global singleton. Plugins register against this; dispatcher fires
# against this. Tests can swap it out via ``set_registry``.
_registry = HookRegistry()


def get_registry() -> HookRegistry:
    return _registry


def set_registry(registry: HookRegistry) -> None:
    """Test/scaffold seam — replace the global registry. Production code
    should call get_registry() directly.
    """
    global _registry
    _registry = registry


def register(name: str, handler: HookHandler) -> None:
    """Convenience: ``register("pre_tool_call", my_handler)``."""
    _registry.register(name, handler)


async def invoke_hook(name: str, **kwargs: Any) -> list[Any]:
    """Convenience: ``await invoke_hook("pre_gateway_dispatch", event=...)``."""
    return await _registry.invoke(name, **kwargs)


def list_handlers() -> dict[str, list[str]]:
    """Diagnostic snapshot of currently-registered handlers."""
    return _registry.list_handlers()
