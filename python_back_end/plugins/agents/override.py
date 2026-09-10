"""Reading "just do all of it" out of what the user actually typed.

Default behaviour for a teammate is: do the work, then propose what is worth
doing next and WAIT. Override flips that second half — keep going through the
proposals without checking back.

What override does NOT do is widen what the agent may do. The four hard limits
still stop it. The user's request takes priority over the agent's caution, but
"take priority" means "stop asking me whether to continue", not "sign in and
spend money without telling me".
"""

from __future__ import annotations

import re

# Phrases that mean "don't check back with me". Deliberately a short, literal
# list rather than a model call: a misread here changes how autonomous the
# agent is, and a regex is something the user can be shown and can argue with.
_OVERRIDE = re.compile(
    r"(?:"
    r"just\s+do\s+(?:it\s+)?all(?:\s+of\s+it)?|"
    r"do\s+(?:it\s+)?all(?:\s+of\s+it)?\s+(?:now|please)?|"
    r"go\s+(?:ahead\s+)?(?:and\s+)?(?:do|finish|run)\s+(?:it|everything|the\s+whole\s+thing)|"
    r"run\s+(?:it\s+)?(?:all\s+the\s+way\s+)?through|"
    r"don'?t\s+(?:ask|stop|check\s+(?:back|in|with)\s+me)|"
    r"no\s+need\s+to\s+(?:ask|check)|"
    r"without\s+(?:asking|stopping|checking)|"
    r"finish\s+(?:it|everything)\s+(?:yourself|on\s+your\s+own)|"
    r"full\s+auto|autopilot|end\s+to\s+end"
    r")",
    re.IGNORECASE,
)

# The opposite instruction wins when both appear ("do it all but ask me before
# you send anything"): the more cautious reading of a mixed message is the one
# that cannot surprise the user.
_ASK_ME = re.compile(
    r"(?:"
    r"ask\s+me\s+(?:first|before|each|every)|"
    r"check\s+(?:back\s+)?with\s+me|"
    r"let\s+me\s+(?:know|review|approve)\s+(?:first|before)|"
    r"one\s+step\s+at\s+a\s+time|"
    r"propose|suggest\s+(?:first|what)"
    r")",
    re.IGNORECASE,
)


def parse_override(text: str | None) -> bool:
    """True when the user asked the agent to run through without checking back."""
    if not text:
        return False
    body = str(text)
    if _ASK_ME.search(body):
        return False
    return bool(_OVERRIDE.search(body))


def permission_mode_for(agent: dict | None = None) -> str:
    """The rung the teammate's tools run under.

    One rung, always. Override changes whether the run continues past the
    delivery, not what the gate allows — so there is no second mode to pick.
    """
    return "agent"


def cleared_limits(agent: dict | None) -> set[str]:
    """Hard limits this teammate has standing permission for.

    Set on the agent by the user ("you may send messages in this channel"),
    never inferred from a run's wording. An override in the prompt does not add
    to this set.
    """
    if not isinstance(agent, dict):
        return set()
    autonomy = agent.get("autonomy") or {}
    if not isinstance(autonomy, dict):
        return set()
    raw = autonomy.get("cleared_limits") or []
    if not isinstance(raw, list):
        return set()
    return {str(x).strip().lower() for x in raw if str(x).strip()}
