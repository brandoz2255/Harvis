# Adapted shape from NousResearch/hermes-agent (MIT) —
# plugins/observability/langfuse/plugin.yaml as exemplar.
#
# Each plugin.yaml describes a plugin's identity, what env vars it needs at
# runtime, and which hook names it implements. The loader uses this to
# discover plugins, gate them on env availability, and wire their handlers
# into the HookRegistry.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginManifest:
    """Parsed contents of a ``plugin.yaml``.

    The plugin's id is derived from its filesystem location relative to the
    plugins root: ``<category>/<name>`` for nested layouts (Hermes-style)
    or ``<name>`` for the flat layout.
    """

    id: str
    name: str
    version: str
    description: str = ""
    author: str = "unknown"
    requires_env: tuple[str, ...] = ()
    hooks: tuple[str, ...] = ()
    plugin_dir: Optional[Path] = None
    package: str = ""  # importable Python module name, e.g. "plugins.observability.audit_log"

    @property
    def category(self) -> str:
        if "/" in self.id:
            return self.id.split("/", 1)[0]
        return ""


def parse_manifest_file(path: Path, *, plugins_root: Path, package_root: str = "plugins") -> Optional[PluginManifest]:
    """Read a plugin.yaml and return a PluginManifest, or None on failure.

    Failures (missing yaml lib, invalid YAML, missing required fields)
    are logged and the plugin is skipped — fail-open at the discovery
    boundary.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML not installed; plugin discovery disabled")
        return None

    try:
        raw = yaml.safe_load(path.read_text())
    except Exception:
        logger.exception("plugin manifest parse failed: %s", path)
        return None

    if not isinstance(raw, dict):
        logger.warning("plugin manifest %s did not parse as a mapping", path)
        return None

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        logger.warning("plugin manifest %s missing required field 'name'", path)
        return None

    plugin_dir = path.parent
    try:
        rel = plugin_dir.relative_to(plugins_root)
    except ValueError:
        logger.warning("plugin %s is outside plugins root %s", plugin_dir, plugins_root)
        return None

    parts = rel.parts
    if len(parts) == 1:
        plugin_id = parts[0]
        package_parts = (package_root, parts[0])
    elif len(parts) >= 2:
        # Use only the last two segments as <category>/<name>; deeper nesting
        # is allowed but its package path follows the actual filesystem.
        plugin_id = "/".join(parts[-2:])
        package_parts = (package_root, *parts)
    else:
        logger.warning("plugin manifest %s has empty path", path)
        return None

    requires_env = raw.get("requires_env") or []
    if not isinstance(requires_env, list):
        logger.warning("plugin %s requires_env must be a list, got %r", plugin_id, type(requires_env))
        requires_env = []
    requires_env = tuple(str(x) for x in requires_env)

    hooks = raw.get("hooks") or []
    if not isinstance(hooks, list):
        logger.warning("plugin %s hooks must be a list, got %r", plugin_id, type(hooks))
        hooks = []
    hooks = tuple(str(x) for x in hooks)

    return PluginManifest(
        id=plugin_id,
        name=name,
        version=str(raw.get("version", "0.0.0")),
        description=str(raw.get("description", "")),
        author=str(raw.get("author", "unknown")),
        requires_env=requires_env,
        hooks=hooks,
        plugin_dir=plugin_dir,
        package=".".join(package_parts),
    )


def discover_manifests(plugins_root: Path, *, package_root: str = "plugins") -> list[PluginManifest]:
    """Walk ``plugins_root`` for plugin.yaml files; return parsed manifests."""
    if not plugins_root.is_dir():
        logger.info("plugin discovery: root %s does not exist", plugins_root)
        return []
    out: list[PluginManifest] = []
    for path in sorted(plugins_root.rglob("plugin.yaml")):
        manifest = parse_manifest_file(path, plugins_root=plugins_root, package_root=package_root)
        if manifest is not None:
            out.append(manifest)
    return out
