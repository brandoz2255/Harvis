"""Whether a chat turn asks for a skill, and which saved skill an "update the X skill" ask means.

Split out of learn.py, which re-exports these names.
"""
from __future__ import annotations

import re
from typing import Optional

# "update the docker compose skill": a short skill-name phrase (up to 3 words, none of them a
# verb, pronoun or connective) then "skill" as a whole word that ends the phrase. That keeps
# "update my cv so it highlights my python skill" and "update the skill tree" out.
_NOT_NAME_WORD = (r"(?:to|so|it|in|on|at|for|and|or|but|that|which|my|your|i|we|you|is|are|be|show|shows|"
                  r"highlight|highlights|with|by|if|when|as|will|can)")
_UPDATE_SKILL = (rf"\bupdate\s+(?:the|that|my|this)\s+(?P<x>(?:(?!{_NOT_NAME_WORD}\b)[\w-]+\s+){{0,3}}?)"
                 r"skill\b(?!s)(?=\s*(?:$|[.,;:!?)]|\s(?:to|so|and|please|with|that|again|also|now|for|by|"
                 r"next|when|because|after|before|since|using|from|based|then|if)\b))")
_SKILL_ASK_RE = re.compile(
    r"\b(?:save|make|turn|write|create)\b[^.?!\n]{0,40}\bskill\b"
    rf"|{_UPDATE_SKILL}"
    # "add a skill that checks the ports": only as a request (start of a clause), and not
    # "add a skill that I have to my linkedin".
    r"|(?:^|[.!?;,]\s*|\b(?:please|pls|can you|could you|then|also|and)\s+)add\s+a\s+skill\s+that\s+"
    r"(?!(?:i|we|you|he|she|they|my|our|your|the|a|an|this|that|it|is|are|was)\b)"
    r"|\bremember\s+how\s+you\s+did\s+(?:that|this|it)\b", re.I | re.M)
# "update the docker compose skill" -> group 'x' is the name words; "update that skill" -> empty.
_UPDATE_RE = re.compile(_UPDATE_SKILL, re.I | re.M)


# "update my python skill to expert on my resume" is CV talk, not a skill ask: the skill is being
# written onto a CV object ("on my resume", "for the cv", "to my linkedin"), in the same sentence or
# the next one. A CV word on its own is not enough: "the staging profile", "the resume endpoint" and
# "the cv table" are ordinary technical words.
_CV_THING = (r"(?:(?:my|the|your|a)\s+(?:resumes?|r\u00e9sum\u00e9s?|cv|curriculum\s+vitae|portfolio|cover\s+letter|"
             r"job\s+application)\b(?!\s+(?:endpoint|route|api|handler|function|command|flag|job|task|step|button|"
             r"table|column|field|url|service|script|method|hook|process|logic|file|config|parser|pipeline|generator))"
             r"|(?:(?:my|the|your)\s+)?linkedin\b|(?:my|your)\s+profile\b)")
_CV_OBJECT = re.compile(rf"\b(?:on|in|onto|into|to|for|from)\s+{_CV_THING}", re.I)
_CV_NAMES = frozenset({"resume", "resumes", "r\u00e9sum\u00e9", "cv", "linkedin", "linkedin profile", "portfolio"})


def _is_cv_talk(text: str, m: "re.Match[str]") -> bool:
    if (m.groupdict().get("x") or "").strip().lower() in _CV_NAMES:
        return True
    start = max(text.rfind(c, 0, m.start()) for c in ".!?\n") + 1
    # the matched sentence and the one after it ("... to expert. It's for my resume")
    end = m.end()
    for _ in range(2):
        ends = [i for i in (text.find(c, end) for c in ".!?\n") if i >= 0]
        if not ends:
            end = len(text)
            break
        end = min(ends) + 1
    return bool(_CV_OBJECT.search(text[start:end]))


def _update_ask(user_text: str) -> "Optional[re.Match[str]]":
    text = user_text or ""
    return next((m for m in _UPDATE_RE.finditer(text) if not _is_cv_talk(text, m)), None)


def wants_skill(user_text: str) -> bool:
    text = user_text or ""
    return any(not _is_cv_talk(text, m) for m in _SKILL_ASK_RE.finditer(text))


_STOP_TOKENS = frozenset({"the", "a", "an", "my", "this", "that", "and", "to", "for", "of", "skill"})


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def _best_named(rows: list[dict], hint: str) -> str:
    """The skill a spoken name means, ranked rather than first-hit: an exact slug, then
    the names that contain the whole hint on hyphen boundaries (closest length first),
    then the most shared words. A short name that merely sits inside the hint ("do",
    "go") never wins. Ties go to the newest, since ``rows`` are newest first."""
    names = [(str(r["name"]), _slug(r["name"])) for r in rows]
    for n, low in names:
        if low == hint:
            return n
    pat = re.compile(rf"(?<![a-z0-9]){re.escape(hint)}(?![a-z0-9])")
    held = [(len(low) - len(hint), i, n) for i, (n, low) in enumerate(names) if low and pat.search(low)]
    if held:
        return min(held)[2]
    want = {t for t in hint.split("-") if t and t not in _STOP_TOKENS}
    scored = []
    for i, (n, low) in enumerate(names):
        toks = {t for t in low.split("-") if t}
        shared = len(want & toks)
        if shared:
            scored.append((-shared, len(toks), i, n))
    return min(scored)[3] if scored else ""


def pick_update_target(rows: list[dict], user_text: str, session_id: str, transcript: str = "") -> str:
    """The existing skill an "update the X skill" ask means, or "" when it is not an
    update ask or none can be told. ``rows`` are ``{name, meta}`` newest first. A named
    skill wins; "that skill" means the one touched in this chat, else the newest one
    whose name the conversation mentions."""
    from .skill_select import names_skill

    m = _update_ask(user_text)
    if not m:
        return ""
    hint = _slug(m.group("x"))
    if hint:
        return _best_named(rows, hint)
    for r in rows:
        meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
        pending = meta.get("pending") if isinstance(meta.get("pending"), dict) else {}
        if session_id and session_id in (meta.get("session_id"), pending.get("session_id")):
            return str(r["name"])
    low = (transcript or "").lower()
    return next((str(r["name"]) for r in rows if names_skill(low, str(r["name"]).lower())), "")
