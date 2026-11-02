"""Evaluate the rules tier: the declarative hooks of a person's approved mods.

A rule can only tighten. ``block`` and ``require-approval`` feed the same
authorize_action gate every tool call already passes; nothing here can allow a
call the gate would refuse. ``prepend-context`` adds the person's own approved
text to the model's context, labelled with the mod it came from.

Loading fails toward asking: when the rules cannot be read, every tool asks
first instead of running unchecked (a block mod is never skipped silently), and
no prepend-context text is added. Nothing is hard-blocked by a database blip.
"""
from __future__ import annotations

import logging
from fnmatch import fnmatchcase

from . import store

log = logging.getLogger("mods.rules")

MAX_CONTEXT = 4000
_STRENGTH = {"require-approval": 1, "block": 2}


UNAVAILABLE_REASON = "your mods could not be loaded, so this asks first"


class ModRules:
    def __init__(self, hooks: list[tuple[str, dict]] | None = None, *, unavailable: bool = False):
        self.hooks = list(hooks or [])
        self.unavailable = unavailable

    def __bool__(self) -> bool:
        return bool(self.hooks) or self.unavailable

    @staticmethod
    def _matches(hook: dict, tool_name: str) -> bool:
        pattern = str(hook.get("match") or "tool:*")[len("tool:"):].lower()
        return fnmatchcase((tool_name or "").lower(), pattern)

    def tool_rule(self, tool_name: str) -> tuple[str, str] | None:
        """The strictest PreToolUse rule for this tool: ("block" | "require-approval", reason)."""
        if self.unavailable:
            return ("require-approval", UNAVAILABLE_REASON)
        best: tuple[str, str] | None = None
        for mod, h in self.hooks:
            if h.get("event") != "PreToolUse" or not self._matches(h, tool_name):
                continue
            act = h.get("action")
            if act == "log":
                continue
            if act not in _STRENGTH:
                continue
            why = h.get("reason") or (f"blocks {tool_name}" if act == "block" else f"asks before {tool_name}")
            reason = f"your mod '{mod}' {why}" if not h.get("reason") else f"your mod '{mod}': {why}"
            if best is None or _STRENGTH[act] > _STRENGTH[best[0]]:
                best = (act, reason)
        return best

    def log_tool(self, event: str, tool_name: str, *, ok: bool | None = None) -> None:
        """Write a line for each approved ``log`` rule matching this Pre/PostToolUse call."""
        for mod, h in self.hooks:
            if h.get("action") == "log" and h.get("event") == event and self._matches(h, tool_name):
                outcome = "" if ok is None else (" ok" if ok else " failed")
                log.info("mod %s: %s %s%s", mod, event, tool_name, outcome)

    def context_text(self, first_turn: bool) -> str:
        """Approved prepend-context text for this turn (SessionStart only on the first)."""
        parts: list[str] = []
        for mod, h in self.hooks:
            if h.get("action") != "prepend-context":
                continue
            if h.get("event") == "PreSend" or (first_turn and h.get("event") == "SessionStart"):
                parts.append(f"[From the user's mod '{mod}']\n{h.get('text', '').strip()}")
        return "\n\n".join(parts)[:MAX_CONTEXT]


async def for_user(pool, user_id: int | None) -> ModRules:
    if pool is None or user_id is None:
        return ModRules()
    try:
        return ModRules(await store.active_rules(pool, int(user_id)))
    except Exception as exc:  # noqa: BLE001 - see module docstring
        log.warning("mod rules unavailable for user %s, tools will ask first: %s", user_id, exc)
        return ModRules(unavailable=True)
