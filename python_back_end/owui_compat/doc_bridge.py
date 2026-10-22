"""Chat gets documents: "make me a deck about X" answers with a harvis-doc block.

The model writes ONE fenced block (language ``harvis-doc``) holding the whole
deck, document, spreadsheet or PDF; the Hermes UI renders it as it streams and
exports it through POST /hermes-api/api/harvis/docs/export. The block grammar
is read by front_end/hermes-desktop-ui/src/lib/harvis-doc.ts and by
plugins/hermes_ui/docs_parse.py: keep the three in step.

Detection is wording only, on the latest user message. A request must address
the assistant (an imperative, "can you", "please", "I need") and name a thing to
make; questions about documents ("what is a pdf", "how do I make slides in
google") and code that handles documents ("write a function that parses a pdf")
are left to the ordinary chat path. A turn that is detected skips the workspace
auto-launch, which would otherwise grab "write a report" as a sandbox task.

What the model is told per kind lives in doc_skills/<kind>/SKILL.md, read at call
time: a failure seen in a live run becomes a line under that file's Gotchas.
Follow-ups on a document already in the chat are handled in doc_revision.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .doc_revision import (PriorDoc, compact_history, conversion_names_part, conversion_target, find_latest_doc,
                           has_fix_prefix, is_edit, names_part, revision_note)

logger = logging.getLogger(__name__)

KINDS = ("deck", "doc", "pdf", "sheet")

# Carried by every document prompt so later prompt steps can tell it apart.
DOC_PROMPT_MARKER = "harvis-doc block"

_LONG = 1500   # a paste longer than this is judged by its first and last lines
_EDGE = 600

# Words that make the phrase about software, not about the thing to make.
_CODE_WORDS = frozenset((
    "code script scripts function functions program programs class classes app apps application "
    "api apis bot parser parsers parse parses parsing library libraries module modules regex query "
    "queries endpoint endpoints command commands extension extensions plugin plugins tool tools "
    "component components sql python javascript typescript bash rust java golang json yaml docker "
    "dockerfile image formula formulas macro macros vba reader readers viewer viewers editor "
    "editors converter converters generator generators layer string strings speech speeches "
    "address talk music test tests website webpage framework package sdk cli "
).split())

# The noun phrase after the verb ends at the first of these.
_STOPPERS = frozenset((
    "of from about for on in with using that which where who whose to into as by when if so "
    "because and but or than at via over under like around regarding covering explaining "
    "describing summarizing showing listing comparing outlining based called named titled"
).split())

_DECK = frozenset("deck decks slides slideshow slideshows presentation presentations powerpoint "
                  "pptx ppt keynote slidedeck".split())
_SHEET = frozenset("spreadsheet spreadsheets excel xlsx xls workbook workbooks csv".split())
_PDF = frozenset("pdf pdfs".split())
_DOCX = frozenset(("docx",))
# These count only as the head noun (last word) of the phrase: "write a brief
# summary" is a summary, "write a brief" is a document.
_GENERIC_DOC = frozenset(
    "document documents doc docs report reports memo memos memorandum essay essays letter letters "
    "proposal proposals onepager resume resumes cv cvs brief briefs handout handouts guide guides "
    "whitepaper whitepapers writeup writeups outline outlines".split())
_GENERIC_SHEET = frozenset("budget budgets tracker trackers sheet sheets".split())

# Phrases rewritten to one token before the words are read.
_PHRASES = (
    (re.compile(r"\b(?:cheat|fact|info|study)[\s-]*(?:sheet|guide)s?\b"), "handout"),
    (re.compile(r"\b(?:style|answer|time|balance)[\s-]*sheets?\b"), "stylesheet"),
    (re.compile(r"\bone[\s-]*pagers?\b"), "onepager"),
    (re.compile(r"\bwrite[\s-]*ups?\b"), "writeup"),
    (re.compile(r"\bword\s+(?:docs?|documents?|files?)\b"), "docx"),
    (re.compile(r"\bgoogle\s+(?:docs?|documents?)\b"), "document"),
    (re.compile(r"\bgoogle\s+slides\b"), "slides"),
    (re.compile(r"\bgoogle\s+sheets?\b"), "spreadsheet"),
    (re.compile(r"\b(?:slide|pitch)[\s-]*decks?\b"), "deck"),
    (re.compile(r"\btracker\s+tables?\b"), "tracker"),
)

_CLAUSE_SPLIT = re.compile(r"[.!?;\n:]+|,\s*|\s+(?:and|then|and\s+then|but|also)\s+")

_LEAD = re.compile(
    r"^(?:(?:ok|okay|hey|hi|yo|harvis|please|pls|plz|now|so|thanks|thank\s+you|great|cool|alright|sure)"
    r"[\s,!-]+)*"
    r"(?:(?:can|could|would|will)\s+(?:you|u)\s+(?:(?:please|pls|just|go\s+ahead\s+and|quickly)\s+)*"
    r"|(?:i\s+)?(?:need|want)\s+(?:you\s+to\s+)?"
    r"|i(?:'d|\s+would)\s+(?:like|love)\s+(?:you\s+to\s+)?"
    r"|let'?s\s+|help\s+me\s+|go\s+ahead\s+and\s+|you\s+should\s+)?"
    r"(?:(?:please|pls|just|quickly|now)\s+)*")

_MAKE = re.compile(
    r"^(?:make|create|write|draft|generate|build|compose|prepare|produce|design|give|put\s+together|"
    r"whip\s+up|throw\s+together|knock\s+out|come\s+up\s+with|set\s+up|do)\b\s*")
_CONVERT = re.compile(
    r"^(?:turn|convert|transform|export|save|put|make|rewrite|reformat|format|present|summari[sz]e|"
    r"condense|distill|print)\b")
# After "turn this", the target: "into a deck", "as a pdf", "to excel".
_TARGET = re.compile(r"\b(into|as|to|in)\s+(.*)$")

_TOKEN = re.compile(r"[a-z0-9']+")
_TRAILING = frozenset("please pls plz thanks thx now for me us asap".split())


def _normalize(text: str) -> str:
    text = (text or "").lower().replace("’", "'")
    for pattern, repl in _PHRASES:
        text = pattern.sub(repl, text)
    return text


def _classify(words: list[str], *, generic: bool) -> Optional[str]:
    """The kind a noun phrase names, or None. A software word anywhere in it vetoes."""
    while words and words[-1] in _TRAILING:
        words = words[:-1]
    if not words or any(w in _CODE_WORDS for w in words):
        return None
    for group, kind in ((_DECK, "deck"), (_SHEET, "sheet"), (_PDF, "pdf"), (_DOCX, "doc")):
        if any(w in group for w in words):
            return kind
    if generic:
        last = words[-1]
        if last in _GENERIC_DOC:
            return "doc"
        if last in _GENERIC_SHEET:
            return "sheet"
    return None


def _noun_phrase(rest: str) -> list[str]:
    """The words up to the first stopper, at most ten of them."""
    words: list[str] = []
    for w in _TOKEN.findall(rest)[:10]:
        if w in _STOPPERS:
            break
        words.append(w)
    return words


def _clause_kind(clause: str) -> Optional[str]:
    clause = clause.strip()
    if not clause:
        return None
    lead = _LEAD.match(clause)
    # "I need a deck": the want itself says "make", so no verb is required.
    wanted = bool(lead and re.search(r"\b(?:need|want|like|love)\b", lead.group(0)))
    rest = clause[lead.end():] if lead else clause
    make = _MAKE.match(rest)
    if make:
        return _classify(_noun_phrase(rest[make.end():]), generic=True)
    if _CONVERT.match(rest):
        target = _TARGET.search(rest)
        if target:
            # "to"/"in" also mean a place ("save it to my documents"): only a named format counts.
            return _classify(_noun_phrase(target.group(2)), generic=target.group(1) in ("into", "as"))
    if wanted:
        return _classify(_noun_phrase(rest), generic=True)
    return None


def _window(text: str) -> str:
    if len(text) <= _LONG:
        return text
    return text[:_EDGE] + "\n" + text[-_EDGE:]


def detect_doc_kind(text: str) -> Optional[str]:
    """``deck`` / ``sheet`` / ``pdf`` / ``doc`` when the message asks the assistant to make one."""
    if not isinstance(text, str) or not text.strip():
        return None
    for clause in _CLAUSE_SPLIT.split(_normalize(_window(text))):
        kind = _clause_kind(clause)
        if kind:
            return kind
    return None


_SKILLS_DIR = Path(__file__).resolve().parent / "doc_skills"
_SKILL_FALLBACK = (
    "Answer with one sentence, then ONE block opened with four backticks and `harvis-doc` and closed with four "
    "backticks. It starts with a header: `---`, `kind: {kind}`, `title: <title>`, `outline:` (one `  - item` line "
    "per part), `---`, then the body."
)
_skill_cache: dict[str, tuple[float, str]] = {}


def _skill_body(kind: str) -> str:
    """The rules for this kind, from doc_skills/<kind>/SKILL.md without its front matter.

    Re-read when the file's mtime changes, so a new gotcha is a one-line edit to the markdown.
    """
    path = _SKILLS_DIR / kind / "SKILL.md"
    try:
        mtime = path.stat().st_mtime
        cached = _skill_cache.get(kind)
        if cached and cached[0] == mtime:
            return cached[1]
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning("doc skill %s is missing; using the one-line fallback", path)
        return _SKILL_FALLBACK.format(kind=kind)
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            text = text[text.find("\n", end + 1) + 1:]
    body = text.strip()
    _skill_cache[kind] = (mtime, body)
    return body


def doc_system_prompt(kind: str, note: str = "") -> str:
    """The instruction that teaches the harvis-doc block for this kind, plus a revision note if any."""
    if kind not in KINDS:
        kind = "doc"
    return (_skill_body(kind) + ("\n\n" + note if note else "") + "\n\nThis is a " + DOC_PROMPT_MARKER + " turn: reply with one sentence, then the block "
            "opened with four backticks and harvis-doc. Do not wrap the answer in :::writing or any other colon "
            "fence, and do not paste the document outside the block.")


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str))
    return ""


def _plan(text: str, prior: Optional[PriorDoc], recent: bool) -> Optional[tuple[str, str]]:
    """(mode, kind) for this message: a new document, a conversion of the last one, or an edit of it.

    ``recent`` is whether the document is in the newest assistant message. A vague
    "make it shorter" after other answers means the newest answer, not the old
    document, so it needs the document to be recent or to be named ("the deck").
    """
    if prior:
        target = conversion_target(text)
        if target and target != prior.kind:
            if recent or conversion_names_part(text):
                return "convert", target
        elif is_edit(text) and (recent or has_fix_prefix(text) or names_part(text)):
            return "revise", prior.kind
    kind = detect_doc_kind(text)
    return ("new", kind) if kind else None


def maybe_prepare_doc_turn(owui_body: dict) -> Optional[str]:
    """Add the document prompt right before the last user message; return the kind, or None.

    Inserted next to the question rather than merged into an earlier system
    message, so a persona or project instruction stays intact and the format
    rules are the last thing the model reads before the request. A follow-up on
    a document already in the history ("make it shorter", "turn this into a
    deck") gets the same prompt plus a note saying which document it changes.
    """
    messages = owui_body.get("messages") if isinstance(owui_body, dict) else None
    if not isinstance(messages, list):
        return None
    last = next((i for i in range(len(messages) - 1, -1, -1)
                 if isinstance(messages[i], dict) and messages[i].get("role") == "user"), -1)
    if last < 0:
        return None
    text = _text_of(messages[last].get("content"))
    # A group room's prompt wraps the log in long "claim or hand off work" rules.
    if text.lstrip().startswith("[Group chat:"):
        return None
    prior = find_latest_doc(messages, last)
    newest = next((i for i in range(last - 1, -1, -1)
                   if isinstance(messages[i], dict) and messages[i].get("role") == "assistant"), -1)
    plan = _plan(text, prior, bool(prior) and prior.message == newest)
    if not plan:
        return None
    mode, kind = plan
    note = ""
    if mode != "new" and prior:
        note = revision_note(mode, prior, kind, compact_history(messages, prior))
    prompt = doc_system_prompt(kind, note)
    previous = messages[last - 1] if last > 0 else None
    already = isinstance(previous, dict) and previous.get("role") == "system" and previous.get("content") == prompt
    if not already:
        messages.insert(last, {"role": "system", "content": prompt})
    return kind
