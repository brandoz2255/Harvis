"""Which of the user's skills a Hermes chat turn should carry.

A skill is a playbook Harvis (or the user) wrote to remember how a hard job is
done. Loading every enabled skill into every chat is what bled a "pirate" skill
into unrelated conversations in OWUI, so a turn only carries the few whose name
or description overlap the message, or that the message names outright.

Only TRUSTED skills are candidates: enabled, with a human ``supported`` audit
verdict. Switching a skill on in Capabilities ▸ Skills (or the "Harvis learned a
skill" toast) is that human approval — see rest_capabilities.skill_toggle. The
bodies then pass the same fail-closed gate OWUI chat and sub-agent runs use
(owui_compat.skills.gated_skill_blocks).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger("hermes_ui.skill_select")

MAX_SKILLS = 2
# Weighted word overlap a skill needs before it rides along uninvited. A name
# word counts double, so "docker compose won't start" clears it for a skill
# named docker-compose-debug while one shared description word never does.
MIN_SCORE = 3

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.]*[a-z0-9+#]|[a-z0-9]")
_STOP = frozenset("""
a an and are as at be but by can could do does for from get got has have how i if in into is it
its just let me my no not of on or our out please so some that the their them then there these
this to up us use using want was we what when where which while who why will with would you your
make need help thing things something about also any all been being more most very like
""".split())


def _words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


def score(query: str, name: str, description: str) -> int:
    """Weighted overlap between a message and one skill (name words count twice)."""
    q = _words(query)
    name_words = _words(name.replace("-", " ").replace("_", " "))
    return 2 * len(q & name_words) + len(q & (_words(description) - name_words))


def names_skill(query: str, name: str) -> bool:
    """The message names the skill outright: `/pirate`, `$pirate`, or a multi-word
    slug written out (`docker-compose-debug`). A bare one-word name ("pirate") is
    an ordinary word too often to count on its own."""
    if not name:
        return False
    prefix = "[/$]?" if "-" in name else "[/$]"
    return re.search(rf"(?<![\w-]){prefix}{re.escape(name.lower())}(?![\w-])",
                     (query or "").lower()) is not None


def pick(query: str, rows: list[dict]) -> list[str]:
    """Ids of the skills this message should carry, best first."""
    named = [r["id"] for r in rows if names_skill(query, r["name"])]
    scored = sorted(((score(query, r["name"], r.get("description") or ""), r["id"])
                     for r in rows if r["id"] not in named), reverse=True)
    return (named + [sid for s, sid in scored if s >= MIN_SCORE])[:MAX_SKILLS]


async def skill_message(pool, user_id: int, query: str) -> Optional[dict]:
    """A system message with the relevant trusted skills for this turn, or None.
    Never raises: a skill lookup failing must not fail the chat."""
    if pool is None or not (query or "").strip():
        return None
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, description FROM owui_skills WHERE user_id=$1 AND enabled=TRUE "
                "AND meta->'audit'->>'verdict' = 'supported'", int(user_id))
        ids = pick(query, [dict(r) for r in rows])
        if not ids:
            return None
        from owui_compat.skills import gated_skill_blocks
        blocks = await gated_skill_blocks(pool, int(user_id), ids)
    except Exception:  # noqa: BLE001
        log.exception("hermes_ui: skill selection failed")
        return None
    if not blocks:
        return None
    return {"role": "system",
            "content": "Saved skills (playbooks) that match this request — follow them where they apply:\n\n"
                       + "\n\n".join(blocks)}
