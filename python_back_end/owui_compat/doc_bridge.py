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

from . import doc_words
from .doc_revision import (PriorDoc, compact_history, conversion_names_part, conversion_target, find_latest_doc,
                           has_fix_prefix, is_edit, names_part, revision_note)

logger = logging.getLogger(__name__)

KINDS = ("deck", "doc", "pdf", "sheet")

# Carried by every document prompt so later prompt steps can tell it apart.
DOC_PROMPT_MARKER = "harvis-doc block"

_LONG = 1500   # a paste longer than this is judged by its first and last lines
_EDGE = 600

# Words that make the phrase about software, not about the thing to make. They veto anywhere in
# the noun phrase.
_CODE_HEADS = frozenset((
    "code script scripts function functions program programs class classes app apps application "
    "api apis bot parser parsers parse parses parsing library libraries module modules query "
    "queries endpoint endpoints command commands extension extensions plugin plugins tool tools "
    "component components image formula formulas macro macros vba reader readers viewer viewers "
    "editor editors converter converters generator generators layer string strings speech speeches "
    "address talk music test tests website webpage framework package sdk cli "
).split())

# Language and tool names. They veto a software request that names a format ("write a bash pdf
# merger", "build a python spreadsheet", "write a javascript slideshow"), unless the head noun is
# a document: "make me a python cheat sheet" is a handout about python, not code.
_CODE_TOPICS = frozenset((
    "python javascript typescript js ts bash shell rust java golang sql json yaml yml docker dockerfile regex "
    "html css node nodejs react"
).split())

# The noun phrase after the verb ends at the first of these.
_STOPPERS = frozenset((
    "of from about for on in with using that which where who whose to into as by when if so "
    "because and but or than at via over under like around regarding covering explaining "
    "describing summarizing showing listing comparing outlining based called named titled"
).split())

_DECK = frozenset("deck decks slide slides slideshow slideshows presentation presentations powerpoint "
                  "powerpoints pptx ppt keynote slidedeck".split())
_SHEET = frozenset("spreadsheet spreadsheets excel xlsx xls workbook workbooks csv".split())
_PDF = frozenset("pdf pdfs".split())
_DOCX = frozenset(("docx",))
# These count only as the head noun (last word) of the phrase: "write a brief
# summary" is a summary, "write a brief" is a document.
_GENERIC_DOC = frozenset(
    "document documents doc docs report reports memo memos memorandum essay essays letter letters "
    "proposal proposals onepager resume resumes cv cvs brief briefs handout handouts guide guides "
    "whitepaper whitepapers writeup writeups".split())
_GENERIC_SHEET = frozenset("budget budgets tracker trackers sheet sheets".split())

_CLAUSE_SPLIT = re.compile(r"[.!?;\n:]+|,\s*|\s+(?:and|then|and\s+then|but|also)\s+")

_LEAD = re.compile(
    r"^(?:(?:ok|okay|hey|hi|yo|harvis|please|pls|plz|now|so|then|next|and|thanks|thank\s+you|great|cool|"
    r"alright|sure)[\s,!-]+)*"
    r"(?:(?:can|could|would|will)\s+(?:you|u)\s+(?:(?:please|pls|just|go\s+ahead\s+and|quickly)\s+)*"
    r"(?:help\s+me\s+(?:to\s+)?)?"
    r"|(?:can|could)\s+i\s+(?:please\s+)?(?:get|have)\s+"
    r"|i(?:'ve|\s+have)?\s+(?:gotta|got\s+to|have\s+to)\s+(?:(?:have|get)\s+)?"
    r"|(?:i|we)(?:'ll|\s+will)\s+need\s+(?:to\s+)?"
    r"|(?:(?:i|we)\s+)?(?:need|want)\s+(?:you\s+to\s+|to\s+)?"
    r"|i'?m\s+trying\s+to\s+"
    r"|i(?:'d|\s+would)\s+(?:like|love)\s+(?:you\s+to\s+|to\s+)?"
    r"|let'?s\s+|help\s+me\s+(?:to\s+)?|go\s+ahead\s+and\s+|you\s+should\s+)?"
    r"(?:(?:please|pls|just|quickly|now)\s+)*")
# Words in the lead that say the user wants the thing itself, with no verb: "I need a deck", "can I get slides".
_WANT = re.compile(r"\b(?:need|want|like|love|get|have|gotta|got)\b")
# "I need to present on X": a talk to give, which a deck answers.
# A day, time, platform or place after "on" is logistics ("present on Friday", "present on zoom").
_PRESENT = re.compile(
    r"^(?:(?:ok|okay|hey|so|well|hi)[\s,!-]+)*(?:(?:i|we)(?:'ve|\s+have)?\s+(?:need|have|gotta|got)\s+to\s+present"
    r"|(?:i|we)'?(?:m|re)\s+presenting|(?:i|we)\s+(?:am|are)\s+presenting)\s+(?:on|about)\s+"
    r"(?!(?:\d|(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|"
    r"today|tomorrow|tonight|yesterday|zoom|teams|meet|stage|call|camera|webcam|screen|video|next|this|"
    r"later|soon|campus|site|location|time)\b))")
# Someone asking how to present, or for tips, wants an answer rather than a deck.
_ADVICE = re.compile(r"\b(?:tips?|advice|advise|help|how\s+(?:do|should|can|to|would)|nervous|anxious|scared|"
                     r"stressed|worried|suggest\w*|ideas?\s+for)\b")

_MAKE = re.compile(
    r"^(?:make|create|write|draft|generate|build|compose|prepare|produce|design|give|put\s+together|"
    r"whip\s+(?:me\s+)?up|throw\s+together|knock\s+out|come\s+up\s+with|set\s+up|get\s+me|gimme|send\s+me|do)\b\s*")
_CONVERT = re.compile(
    r"^(?:turn|convert|transform|export|save|put|make|rewrite|reformat|format|present|summari[sz]e|"
    r"condense|distill|print)\b")
# After "turn this", the target: "into a deck", "as a pdf", "to excel".
_TARGET = re.compile(r"\b(into|as|to|in)\s+(.*)$")
# "write a report as a pdf": a format named after a generic document noun settles the kind.
_FORMAT_TAIL = re.compile(r"\b(?:as|in|into)\s+(?:an?\s+)?([a-z0-9]+)")

_TOKEN = re.compile(r"[a-z0-9']+")
_TRAILING = frozenset("please pls plz thanks thx now for me us asap".split())

_FORMATS = ((_DECK, "deck"), (_SHEET, "sheet"), (_PDF, "pdf"), (_DOCX, "doc"))
# A request that is only a format noun and what it is about: "slide deck on k3s", "a powerpoint about dogs".
_BARE_LEAD = re.compile(r"^(?:(?:ok|okay|hey|hi|yo|harvis|please|pls|plz|now|so)[\s,!-]+)*(an?\s+|some\s+)?")
_BARE_STOPPERS = frozenset("about on for of from regarding covering explaining describing summarizing showing "
                           "listing comparing outlining".split())
_BARE_MAX_WORDS = 12
# The subject after "about/on/from" is a noun phrase. A verb, an auxiliary, a contraction or a
# pronoun subject means the message reports something ("powerpoint on my laptop keeps crashing",
# "slides from the lecture are attached"), not a request.
_BARE_REPORT = frozenset((
    "is are was were be been being am has have had having do does did done will would can could should shall may "
    "might must keeps keep kept went go goes gone going looks look looked seems seem seemed open opens opened opening "
    "crash crashes crashed crashing freeze freezes froze freezing frozen load loads loaded loading attached attach "
    "work works worked working fail fails failed failing broke broken stuck missing need needs needed got get gets "
    "getting say says said show shows showed take takes took makes made came come comes happen happens happened "
    "i you we they he she it thanks thank sorry help".split()))

# A noun phrase that ends in one of these describes a file that exists, not one to make: "a pdf
# smaller", "the slides printed", "a pdf searchable".
_PREDICATE = frozenset((
    "smaller bigger larger shorter longer better faster lighter easier cleaner searchable editable printable "
    "readable accessible selectable shareable printed done finished signed sent shared emailed attached merged "
    "compressed encrypted locked protected uploaded downloaded saved opened fixed"
).split())
# A definite or possessive object after a want/get/have lead points at a file that exists.
_DEFINITE = frozenset("the my our your his her their that this these those".split())
# "get me the report" asks for an existing file; "give me the pdf" and "make the slides" stay requests.
_GET_VERB = re.compile(r"(?:get\s+me|gimme|send\s+me)\b")

# (kind, strong): a named format is strong, a generic document noun ("report") is not.
_Hit = tuple[str, bool]


def _classify(words: list[str], *, generic: bool) -> Optional[_Hit]:
    """The kind a noun phrase names, or None. A software head noun anywhere in it vetoes."""
    while words and words[-1] in _TRAILING:
        words = words[:-1]
    if not words or any(w in _CODE_HEADS for w in words):
        return None
    if words[-1] in _PREDICATE and len(words) > 1:
        return None
    if words[-1] not in _GENERIC_DOC and any(w in _CODE_TOPICS for w in words):
        return None
    for group, kind in _FORMATS:
        if any(w in group for w in words):
            return kind, True
    if generic:
        last = words[-1]
        if last in _GENERIC_DOC:
            return "doc", False
        if last in _GENERIC_SHEET:
            return "sheet", False
    return None


def _noun_phrase(rest: str) -> list[str]:
    """The words up to the first stopper, at most ten of them."""
    words: list[str] = []
    for w in _TOKEN.findall(rest)[:10]:
        if w in _STOPPERS:
            break
        words.append(w)
    return words


def _requested(rest: str) -> Optional[_Hit]:
    """What a make-style clause asks for; a format named later settles a generic document noun."""
    hit = _classify(_noun_phrase(rest), generic=True)
    if hit and hit[0] == "doc" and not hit[1]:
        tail = _FORMAT_TAIL.search(rest)
        if tail:
            for group, kind in _FORMATS:
                if tail.group(1) in group:
                    return kind, True
    return hit


def _clause_hit(clause: str, *, allow_present: bool = True) -> Optional[_Hit]:
    clause = clause.strip()
    if not clause:
        return None
    if allow_present and _PRESENT.match(clause):
        return "deck", True
    lead = _LEAD.match(clause)
    # "I need a deck": the want itself says "make", so no verb is required.
    # "I need to finish my report" wants no document: after "to" only a make verb counts.
    wanted = bool(lead and _WANT.search(lead.group(0)) and not re.search(r"\bto\s*$", lead.group(0)))
    rest = clause[lead.end():] if lead else clause
    make = _MAKE.match(rest)
    if make:
        after = rest[make.end():]
        # "get me the report from yesterday" asks for a file that exists; "get me a pdf of the notes" does not.
        if _GET_VERB.match(make.group(0)) and after.split()[:1] and after.split()[0] in _DEFINITE:
            return None
        hit = _requested(after)
        # "make this into slides" is a conversion, whose target comes after "into".
        if hit or not _CONVERT.match(rest):
            return hit
    if _CONVERT.match(rest):
        target = _TARGET.search(rest)
        if target:
            # "to"/"in" also mean a place ("save it to my documents"): only a named format counts.
            return _classify(_noun_phrase(target.group(2)), generic=target.group(1) in ("into", "as"))
    if wanted:
        # "I gotta get the slides printed", "can I get the report by friday": a definite file already exists.
        if rest.split()[:1] and rest.split()[0] in _DEFINITE:
            return None
        return _requested(rest)
    return doc_words.foreign_hit(clause)


# What a bare format noun followed by one of these is talking about, not asking for: "slides on monday",
# "powerpoint on mac", "a pdf from my professor", "deck of the ship". "from" is a request only when it points
# at material in the message ("slides from this"); "of" only matters for a deck, which is also a ship's deck.
# A day, date or time counts only when it is the whole tail, optionally with a part of the day or a clock
# time after it, so "slides on monday at 9" is logistics and "slides on sunday school lessons" is a topic.
# Month names are spelled out or followed by a word boundary, so "junit 5" and "mars 2 rover" are topics.
_BARE_CLOCK = r"\d{1,2}(?:\s\d\d)?\s*(?:am|pm)"
_BARE_WHEN = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|"
              rf"sun|today|tomorrow|tonight|yesterday|weekend|{_BARE_CLOCK}|"
              r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|"
              r"oct|october|nov|november|dec|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?)")
_BARE_WHEN_END = (rf"(?:\s+(?:morning|afternoon|evening|night|noon|midnight|{_BARE_CLOCK}|"
                  rf"at\s+(?:noon|midnight|\d{{1,2}}(?:\s\d\d)?\s*(?:am|pm)?)))?$")
# A platform or device names where the file is being used. It counts only when it ends the message, so
# "presentation on linux kernel scheduling" is still a topic.
_BARE_WHERE = (r"(?:(?:my|the|our|your|his|her|their)\s+)?(?:mac|macbook|windows|linux|ubuntu|android|ios|iphone|ipad|"
               r"chromebook|phone|laptop|computer|pc|tablet|desktop|screen|device|machine|usb|zoom|teams|campus)"
               r"(?:\s+\d+(?:\.\d+)*)?$")
_BARE_LOGISTICS = re.compile(rf"^on\s+(?:{_BARE_WHEN}{_BARE_WHEN_END}|{_BARE_WHERE})")
_SLIDE_DECK = re.compile(r"\b(?:slide|pitch)[\s-]*decks?\b", re.I)
_BARE_FROM = re.compile(r"^from\s+(?!(?:this|these|that|those|below|above)\b)")
# "deck of 10 slides on X" and "deck of slides on X" are requests; only "deck of the ship" is a ship.
_DECK_COUNT = frozenset("few some several two three four five six seven eight nine ten twelve fifteen twenty".split())


def _bare_parts(text: str) -> Optional[tuple[str, str, list[str]]]:
    """(kind, noun, rest) for a short message that opens with a format noun, else None.

    ``rest`` is the words after the noun, with trailing "please" and the like dropped.
    """
    if "?" in text:
        return None
    text = text.strip()
    if not text or len(_TOKEN.findall(text)) > _BARE_MAX_WORDS:
        return None
    lead = _BARE_LEAD.match(text)
    body = text[lead.end():]
    words = _TOKEN.findall(body)
    # The format noun has to open the message: "怎么做ppt" tokenises to "ppt" but is a question.
    if not words or not body.startswith(words[0]):
        return None
    # A lone "slide" is a playground slide or a verb; "excel" without an article is the verb.
    if words[0] == "slide" or (words[0] == "excel" and not lead.group(1)):
        return None
    kind = next((k for group, k in _FORMATS if words[0] in group), None)
    if not kind:
        return None
    rest = words[1:]
    while rest and rest[-1] in _TRAILING:
        rest = rest[:-1]
    return kind, words[0], rest


def _bare_hit(text: str, raw: str = "") -> Optional[_Hit]:
    """A short message that is just a format noun and its subject, with no verb.

    ``raw`` is the message before ``normalize``, which turns "slide deck" into "deck".
    """
    parts = _bare_parts(text)
    if not parts:
        return None
    kind, noun, rest = parts
    if rest and (rest[0] not in _BARE_STOPPERS or any(w in _CODE_HEADS for w in rest)
                 or any(w in _BARE_REPORT or w.endswith("n't") for w in rest)):
        return None
    if rest:
        tail = " ".join(rest)
        if _BARE_LOGISTICS.match(tail) or _BARE_FROM.match(tail):
            return None
        if noun in ("deck", "decks") and rest[0] == "of" and not _SLIDE_DECK.search(raw):
            after_of = rest[1] if len(rest) > 1 else ""
            if not (after_of.isdigit() or after_of in _DECK or after_of in _DECK_COUNT):
                return None
    return kind, True


def _lone_format(text: str) -> Optional[str]:
    """The kind when the whole message is one format word ("pdf", "a pdf please", "slides"), else None."""
    parts = _bare_parts(doc_words.normalize(_window(text)))
    return parts[0] if parts and not parts[2] else None


def _window(text: str) -> str:
    if len(text) <= _LONG:
        return text
    return text[:_EDGE] + "\n" + text[-_EDGE:]


def detect_doc_kind(text: str) -> Optional[str]:
    """``deck`` / ``sheet`` / ``pdf`` / ``doc`` when the message asks the assistant to make one.

    Every clause is read and a named format wins over a generic document noun, so "write the
    outline, then make the slides" is a deck.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    norm = doc_words.normalize(_window(text))
    allow_present = "?" not in text and not _ADVICE.search(norm)
    hits = [h for h in (_clause_hit(c, allow_present=allow_present) for c in _CLAUSE_SPLIT.split(norm)) if h]
    if not hits:
        hits = [h for h in (_bare_hit(norm, text),) if h]
    strong = next((h for h in hits if h[1]), None)
    if strong:
        return strong[0]
    return hits[0][0] if hits else None


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
        # A lone "pdf" or "slides" with a document in the chat answers "which format?" or asks for a
        # conversion; it is not a new document about nothing. Only when that document is the last answer.
        if not target and recent:
            target = _lone_format(text)
        if target and target != prior.kind:
            if recent or conversion_names_part(text):
                return "convert", target
        elif target:
            # "make it a power point" on a deck: the same kind, so the panel is updated in place with
            # the content carried over, not a second panel built from scratch.
            if recent or conversion_names_part(text):
                return "revise", prior.kind
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
