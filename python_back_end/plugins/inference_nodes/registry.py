"""Where the node list comes from.

Two sources, merged by name with the database winning:

* ``HARVIS_INFERENCE_NODES`` — the operator's static list. Either a JSON array of
  objects (``name``, ``base_url``, ``dialect``, ``label``, ``hardware``, ``token_env``,
  ``priority``, ``enabled``) or the shorthand::

      freetoken=http://host.docker.internal:1919|dialect=openai|label=FreeToken (laptop)

  Entries separated by commas, attributes by ``|``. Anything with a comma in it goes
  in the JSON form. A token is never written into this string — ``token_env=VAR``
  names the environment variable that holds it, so the value stays out of compose
  files and out of ``docker inspect``.

* ``inference_nodes`` table — nodes an administrator registered through the API.
  Read through ``store`` and fail-open: a missing table or a down database leaves
  the env list intact rather than taking the model picker down.

A bad entry is logged and skipped. One typo in a list of three nodes must not
silence the other two.
"""

from __future__ import annotations

import json
import logging
import os

from .types import NodeSpec

logger = logging.getLogger(__name__)

ENV_VAR = "HARVIS_INFERENCE_NODES"

_KEY_ALIASES = {"hw": "hardware", "url": "base_url", "base": "base_url", "prio": "priority"}
_TRUE = ("1", "true", "yes", "on")


def from_mapping(d: dict, *, source: str) -> NodeSpec:
    """Build a spec from a loosely-typed dict (env JSON, shorthand, or a DB row)."""
    d = {_KEY_ALIASES.get(str(k).lower(), str(k).lower()): v for k, v in d.items()}
    token = str(d.get("token") or "")
    token_env = str(d.get("token_env") or "").strip()
    if not token and token_env:
        token = os.getenv(token_env, "")
    enabled = d.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in _TRUE
    try:
        priority = int(d.get("priority") if d.get("priority") not in (None, "") else 100)
    except (TypeError, ValueError):
        priority = 100
    return NodeSpec(
        name=str(d.get("name") or ""),
        base_url=str(d.get("base_url") or ""),
        dialect=str(d.get("dialect") or "openai"),
        label=str(d.get("label") or ""),
        token=token,
        hardware=str(d.get("hardware") or ""),
        source=source,
        enabled=bool(enabled),
        priority=priority,
    )


def parse_env(raw: str | None) -> list[NodeSpec]:
    raw = (raw or "").strip()
    if not raw:
        return []
    specs: dict[str, NodeSpec] = {}

    if raw.startswith("["):
        try:
            items = json.loads(raw)
        except ValueError as e:
            logger.warning("inference_nodes: %s is not valid JSON (%s) — no env nodes", ENV_VAR, e)
            return []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                logger.warning("inference_nodes: skipping non-object entry %r", item)
                continue
            try:
                spec = from_mapping(item, source="env")
            except ValueError as e:
                logger.warning("inference_nodes: skipping entry: %s", e)
                continue
            specs[spec.name] = spec
        return list(specs.values())

    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        head, *attrs = [p.strip() for p in entry.split("|")]
        if "=" not in head:
            logger.warning("inference_nodes: entry %r is not name=url — skipped", head)
            continue
        name, url = head.split("=", 1)
        d: dict = {"name": name, "base_url": url}
        for attr in attrs:
            if "=" in attr:
                k, v = attr.split("=", 1)
                d[k.strip().lower()] = v.strip()
        try:
            spec = from_mapping(d, source="env")
        except ValueError as e:
            logger.warning("inference_nodes: skipping entry: %s", e)
            continue
        specs[spec.name] = spec
    return list(specs.values())


def env_nodes() -> list[NodeSpec]:
    return parse_env(os.getenv(ENV_VAR))


async def configured_nodes(pool=None) -> list[NodeSpec]:
    """Every enabled node, env then DB (DB overrides a same-named env node), sorted
    by priority so ``resolve`` can take the first hit."""
    by_name = {s.name: s for s in env_nodes()}
    if pool is not None:
        try:
            from .store import list_nodes

            for row in await list_nodes(pool):
                try:
                    spec = from_mapping(row, source="db")
                except ValueError as e:
                    logger.warning("inference_nodes: skipping DB row: %s", e)
                    continue
                by_name[spec.name] = spec
        except Exception as e:  # fail-open: the DB must never take the picker down
            logger.warning(
                "inference_nodes: DB registry unavailable (%s) — env nodes only",
                type(e).__name__,
            )
    return sorted((s for s in by_name.values() if s.enabled), key=lambda s: (s.priority, s.name))
