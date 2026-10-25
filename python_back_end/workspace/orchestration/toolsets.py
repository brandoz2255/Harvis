"""Toolsets: the named groups of tools the Capabilities screen can switch off.

One definition serves both halves of the feature. The Hermes Toolsets tab
(plugins/hermes_ui/rest_capabilities.py) draws its cards from ``build_toolsets``
and saves the user's choice as ``disabled_toolsets``; the runner calls
``disabled_tool_names`` before it assembles a run's tool schema, so a toggle that
reads "off" really does keep those tools away from the model. Before this module
the second half did not exist: the choice was stored and never read.

The grouping is presentation plus policy, nothing more. ``lane`` still decides
what each tool is allowed to do, and ``authorize_action`` remains the backstop.
"""
from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)

# (name, label, description, member tool names | None for a prefix match)
TOOLSET_GROUPS = (
    ("harvis-files", "Workspace files",
     "Read, write and patch files inside the run's workspace, and commit them.",
     ("read_file", "edit_file", "str_replace", "apply_patch", "git_commit")),
    ("harvis-terminal", "Sandbox terminal",
     "Run commands inside the sandboxed project container.",
     ("exec",)),
    ("harvis-browser", "Computer use",
     "Drive a real browser: open a page, snapshot it, click, type and scroll.",
     None),  # prefix-matched
    ("harvis-reach", "Agent Reach",
     "Read the outside world: web search, page text, YouTube transcripts, "
     "GitHub views and RSS.",
     None),
    ("harvis-media", "Images and previews",
     "Generate images and screenshot a live preview of what was built.",
     ("generate_image", "screenshot_preview")),
    ("harvis-agent", "Agent control",
     "How a run reports itself: reading and proposing skills, and finishing.",
     ("propose_skill", "list_skills", "read_skill", "finish")),
)

TOOLSET_PREFIXES = {"harvis-browser": "computer_", "harvis-reach": "agent_reach_"}

OTHER = "harvis-other"

# A run that cannot call `finish` cannot end, so no toggle may withhold it.
NEVER_WITHHELD = frozenset({"finish"})


def registry_tools() -> list[tuple[str, int]]:
    """(tool name, lane) for every tool in Harvis's registry, deduped in order."""
    try:
        from workspace.orchestration.tools import TOOL_SCHEMA
    except Exception:
        logger.exception("toolsets: tool registry unavailable")
        return []
    seen: dict[str, int] = {}
    for entry in TOOL_SCHEMA:
        name = str((entry.get("function") or {}).get("name") or "")
        if name and name not in seen:
            seen[name] = int(entry.get("lane") or 0)
    return list(seen.items())


def _members(group: str, members, tools: list[tuple[str, int]]) -> list[str]:
    prefix = TOOLSET_PREFIXES.get(group)
    if prefix is not None:
        return [t for t, _lane in tools if t.startswith(prefix)]
    return [t for t, _lane in tools if t in (members or ())]


def build_toolsets(disabled: set, tools: list[tuple[str, int]] | None = None) -> list[dict]:
    """The cards the Toolsets tab shows, each with its member tools."""
    tools = registry_tools() if tools is None else tools
    claimed: set = set()
    out: list[dict] = []
    for name, label, description, members in TOOLSET_GROUPS:
        picked = _members(name, members, tools)
        if not picked:
            continue
        claimed.update(picked)
        out.append({"name": name, "label": label, "description": description,
                    "tools": picked, "configured": True, "enabled": name not in disabled})
    # Anything the registry grows that no group claims still has to be visible,
    # or a new tool would silently vanish from the UI instead of looking wrong.
    rest = [t for t, _lane in tools if t not in claimed]
    if rest:
        out.append({"name": OTHER, "label": "Other Harvis tools",
                    "description": "Registered tools that are not part of a named toolset yet.",
                    "tools": rest, "configured": True, "enabled": OTHER not in disabled})
    return out


def withheld_tools(disabled_toolsets: Iterable[str],
                   tools: list[tuple[str, int]] | None = None) -> set[str]:
    """Tool names to keep from the model, given the toolsets the user turned off."""
    off = {str(n) for n in (disabled_toolsets or ())}
    if not off:
        return set()
    withheld: set[str] = set()
    for card in build_toolsets(set(), tools):
        if card["name"] in off:
            withheld.update(card["tools"])
    return withheld - NEVER_WITHHELD


async def disabled_tool_names(pool, user_id) -> set[str]:
    """The tools this user has switched off. Fail-open: a read error withholds nothing."""
    if pool is None or user_id is None:
        return set()
    try:
        from plugins.hermes_ui import store

        section = await store.get_section(pool, int(user_id))
    except Exception:
        logger.warning("toolsets: could not read the user's toolset choices", exc_info=True)
        return set()
    raw = section.get("disabled_toolsets")
    return withheld_tools(raw) if isinstance(raw, list) else set()


def toolset_enabled(disabled_toolsets: Iterable[str] | None, name: str) -> bool:
    """Is one named toolset on? (The chat web-search loop checks ``harvis-reach``.)"""
    return name not in {str(n) for n in (disabled_toolsets or ())}
