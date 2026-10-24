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

Every turn also carries a short CATALOG of those skills (name and a one-line
description, never a body), so the model knows what it has and can name one when
the lexical pick would have missed it.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger("hermes_ui.skill_select")

MAX_SKILLS = 2
# Hard cap on the catalog: it rides on every Hermes turn, so it must stay small.
CATALOG_MAX_CHARS = 1500
CATALOG_DESC_CHARS = 90
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


async def trusted_skills(conn, user_id: int) -> list[dict]:
    """Skills a person has approved and switched on, with a body and an approval that
    still matches the text: ``[{id, name, description}]`` sorted by name. The one
    list the catalog, the ``list_skills`` tool and the turn's picker all draw on.
    Hashes are only read for rows that carry one, so a plain row costs nothing extra."""
    from owui_compat.skill_pending import sha_ok

    rows = await conn.fetch(
        "SELECT id, name, description, "
        "CASE WHEN meta->'audit'->>'content_sha' IS NOT NULL THEN content END AS content, "
        "CASE WHEN meta->'audit'->>'content_sha' IS NOT NULL THEN meta END AS meta "
        "FROM owui_skills WHERE user_id=$1 AND enabled=TRUE AND length(btrim(content)) > 0 "
        "AND meta->'audit'->>'verdict' = 'supported'", int(user_id))
    out = []
    for r in rows:
        r = dict(r)
        if r.get("meta") is not None and not sha_ok(r.get("content"), r.get("meta")):
            continue  # edited after approval: not offered, same as the gate
        out.append({"id": r["id"], "name": r["name"], "description": r.get("description") or ""})
    return sorted(out, key=lambda r: str(r["name"]).lower())


def _one_line(text: str, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "\u2026"


def catalog(rows: list[dict]) -> str:
    """One line per skill ('name: first 90 chars of its description'), at most
    CATALOG_MAX_CHARS in all. Names and descriptions only; no bodies."""
    head = "Your saved skills (the person loads one by typing /name; only matching ones are open below):"
    lines: list[str] = []
    used = len(head)
    for i, r in enumerate(rows):
        line = f"- {_one_line(r['name'], 64)}: {_one_line(r.get('description'), CATALOG_DESC_CHARS)}".rstrip(": ")
        # Keep room for the "(+N more)" line in case this is not the last one that fits.
        if used + 1 + len(line) + (0 if i == len(rows) - 1 else 16) > CATALOG_MAX_CHARS:
            lines.append(f"(+{len(rows) - i} more)")
            break
        lines.append(line)
        used += 1 + len(line)
    return "\n".join([head, *lines])[:CATALOG_MAX_CHARS]


async def skill_message(pool, user_id: int, query: str) -> Optional[dict]:
    """A system message for this turn: the catalog of the user's trusted skills, then
    the bodies of the few that match this request. None when there are no trusted
    skills. Never raises: a skill lookup failing must not fail the chat."""
    if pool is None or not (query or "").strip():
        return None
    try:
        async with pool.acquire() as conn:
            rows = await trusted_skills(conn, user_id)
        if not rows:
            return None
        text = catalog(rows)
        ids = pick(query, rows)
        blocks: list[str] = []
        if ids:
            from owui_compat.skills import gated_skill_blocks
            blocks = await gated_skill_blocks(pool, int(user_id), ids)
    except Exception:  # noqa: BLE001
        log.exception("hermes_ui: skill selection failed")
        return None
    if blocks:
        text += ("\n\nSaved skills (playbooks) that match this request \u2014 follow them where they apply:\n\n"
                 + "\n\n".join(blocks))
    return {"role": "system", "content": text}
