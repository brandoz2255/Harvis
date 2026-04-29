# Plugin discovery + loading.
#
# Two configuration knobs:
#   HARVIS_PLUGINS_ENABLED   CSV of plugin ids ("category/name" or "name");
#                            "*" loads everything discovered.
#                            Empty/unset = nothing loaded (safe default).
#   HARVIS_PLUGINS_ROOT      Override the plugins directory. Defaults to
#                            <python_back_end>/plugins/.
#
# A plugin is loaded only if BOTH:
#   1. Its id (or "*") is in HARVIS_PLUGINS_ENABLED.
#   2. Every env var named in plugin.yaml's requires_env is set (non-empty).
#
# Failures during import or handler resolution are caught per-plugin and
# logged; one broken plugin never breaks the rest of the load.

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .hooks import HookRegistry, VALID_HOOKS, get_registry
from .manifest import PluginManifest, discover_manifests

logger = logging.getLogger(__name__)


@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    status: str           # "loaded" | "disabled" | "missing_env:<VAR>" | "import_failed" | "no_handlers"
    registered_hooks: list[str]
    detail: Optional[str] = None


def _enabled_set() -> tuple[bool, frozenset[str]]:
    """Parse HARVIS_PLUGINS_ENABLED. Returns (load_all, explicit_ids)."""
    raw = (os.getenv("HARVIS_PLUGINS_ENABLED") or "").strip()
    if not raw:
        return False, frozenset()
    ids = {p.strip() for p in raw.split(",") if p.strip()}
    if "*" in ids:
        return True, frozenset(ids - {"*"})
    return False, frozenset(ids)


def _missing_env_var(manifest: PluginManifest) -> Optional[str]:
    for var in manifest.requires_env:
        if not (os.getenv(var) or "").strip():
            return var
    return None


def _resolve_plugins_root() -> Path:
    override = os.getenv("HARVIS_PLUGINS_ROOT")
    if override:
        return Path(override).resolve()
    # Walk up from this file: python_back_end/plugins/core/loader.py
    return Path(__file__).resolve().parent.parent


def load_all(
    *,
    registry: Optional[HookRegistry] = None,
    plugins_root: Optional[Path] = None,
) -> list[LoadedPlugin]:
    """Discover, gate, and load every plugin under ``plugins_root``.

    Idempotent across registries: if you re-call with a fresh ``registry``
    you get a fresh registration. Same registry = duplicate handlers
    (registry doesn't dedupe). Production callers should pass the global
    registry exactly once at startup.
    """
    registry = registry if registry is not None else get_registry()
    plugins_root = plugins_root if plugins_root is not None else _resolve_plugins_root()

    load_all_flag, explicit_ids = _enabled_set()
    manifests = discover_manifests(plugins_root)
    out: list[LoadedPlugin] = []

    if not manifests:
        logger.info("plugin loader: no manifests found under %s", plugins_root)
        return out

    for m in manifests:
        if not (load_all_flag or m.id in explicit_ids):
            out.append(LoadedPlugin(m, "disabled", []))
            continue

        missing = _missing_env_var(m)
        if missing is not None:
            out.append(LoadedPlugin(m, f"missing_env:{missing}", []))
            logger.info("plugin %s skipped: required env var %s not set", m.id, missing)
            continue

        try:
            module = importlib.import_module(m.package)
        except Exception as exc:
            logger.exception("plugin %s import failed", m.id)
            out.append(LoadedPlugin(m, "import_failed", [], detail=str(exc)))
            continue

        registered: list[str] = []
        for hook_name in m.hooks:
            if hook_name not in VALID_HOOKS:
                logger.warning(
                    "plugin %s declares unknown hook %r — skipping (valid: %s)",
                    m.id, hook_name, sorted(VALID_HOOKS),
                )
                continue
            handler = getattr(module, hook_name, None)
            if handler is None or not callable(handler):
                logger.warning(
                    "plugin %s declares hook %s but %s.%s is missing or not callable",
                    m.id, hook_name, m.package, hook_name,
                )
                continue
            try:
                registry.register(hook_name, handler)
                registered.append(hook_name)
            except Exception:
                logger.exception("plugin %s register failed for hook %s", m.id, hook_name)

        if registered:
            out.append(LoadedPlugin(m, "loaded", registered))
            logger.info(
                "plugin %s loaded (v%s) — registered %d hook(s): %s",
                m.id, m.version, len(registered), ", ".join(registered),
            )
        else:
            out.append(LoadedPlugin(m, "no_handlers", []))

    return out


def status_summary(loaded: list[LoadedPlugin]) -> dict:
    """Diagnostic snapshot for /api/plugins/status (when added)."""
    return {
        "plugins": [
            {
                "id": p.manifest.id,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "status": p.status,
                "registered_hooks": list(p.registered_hooks),
                "detail": p.detail,
            }
            for p in loaded
        ]
    }
