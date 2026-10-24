"""Follow-up turns on a document the assistant already wrote.

"make it shorter", "add a slide about MFA", "Fix these issues in the document: ..."
and "turn this into a deck" carry no document wording of their own, so
``detect_doc_kind`` alone would hand them to plain chat and the model would answer
in prose. Here the latest harvis-doc fence in the history decides: an edit asks for
the whole document again under the same title (the panel keys on the title, so it
updates in place), a conversion asks for the same content as another kind under a
title that cannot collide with the original.

Wording only, like the rest of doc_bridge: a miss costs one prose answer, a false
hit answers "what is phishing?" with a document, so every pattern below is anchored
on an edit verb at the start of a clause and needs a document noun or a pronoun.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import doc_revision_i18n, doc_words

MAX_DOC_CHARS = 12_000   # of the doc kept in the history the model sees
MAX_EDIT_CHARS = 400     # a longer message brings its own material: it is not an edit of the last doc
MAX_NOTE_TITLE = 120    # longer titles are pointed at in the revision note, not quoted
CUT_MARK = "\n[...document cut here for length...]"

NOUNS = {"deck": "deck", "doc": "document", "pdf": "PDF", "sheet": "spreadsheet"}
_LABELS = {"deck": "Deck", "doc": "Document", "pdf": "PDF", "sheet": "Spreadsheet"}

_OPEN = re.compile(r"^[ \t]*(`{3,})[ \t]*harvis-doc[ \t]*$", re.I)
_CLOSE = re.compile(r"^[ \t]*(`{3,})[ \t]*$")
_KIND_LINE = re.compile(r"^[ \t]*(?:kind|type)[ \t]*:[ \t]*([A-Za-z]+)", re.M)
_TITLE_LINE = re.compile(r"^[ \t]*title[ \t]*:[ \t]*(.+?)[ \t]*$", re.M)


@dataclass
class PriorDoc:
    message: int          # index in messages
    start: int            # character span of the whole fence in that message's content
    end: int
    kind: str
    title: str
    body: str


def _kind_of(value: str) -> str:
    v = value.strip().lower()
    if v in ("deck", "slides", "presentation", "pptx"):
        return "deck"
    if v in ("sheet", "spreadsheet", "xlsx", "excel", "csv"):
        return "sheet"
    return "pdf" if v == "pdf" else "doc"


def find_fences(content: str) -> list[tuple[int, int, str]]:
    """(start, end, body) of every harvis-doc fence; an unclosed one runs to the end."""
    found: list[tuple[int, int, str]] = []
    pos, open_at, ticks, body_at = 0, -1, 0, 0
    for line in content.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if open_at < 0:
            m = _OPEN.match(stripped)
            if m:
                open_at, ticks, body_at = pos, len(m.group(1)), pos + len(line)
        else:
            m = _CLOSE.match(stripped)
            if m and len(m.group(1)) >= ticks:
                found.append((open_at, pos + len(line), content[body_at:pos]))
                open_at = -1
        pos += len(line)
    if open_at >= 0:
        found.append((open_at, len(content), content[body_at:]))
    return found


def find_latest_doc(messages: list, before: int) -> Optional[PriorDoc]:
    """The newest harvis-doc fence in an assistant message earlier than ``before``."""
    for i in range(min(before, len(messages)) - 1, -1, -1):
        m = messages[i]
        if not (isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str)):
            continue
        fences = find_fences(m["content"])
        if not fences:
            continue
        start, end, body = fences[-1]
        head = body[:800]
        kind = _KIND_LINE.search(head)
        title = _TITLE_LINE.search(head)
        return PriorDoc(i, start, end, _kind_of(kind.group(1)) if kind else "doc",
                        title.group(1).strip().strip("\"'") if title else "", body)
    return None


# ---- what reads like an edit ------------------------------------------------------------------

_FILLER = (r"^(?:(?:ok|okay|hey|hi|please|pls|plz|now|also|and|then|next|actually|just|thanks|thank\s+you|"
           r"great|cool|nice|good|alright|sure|yes|yeah)[\s,.!-]+)*"
           r"(?:(?:can|could|would|will)\s+(?:you|u)\s+(?:(?:please|pls|just|also|now)\s+)*"
           r"|i(?:'d|\s+would)\s+(?:like|love)\s+(?:you\s+to\s+)?|i\s+(?:want|need)\s+(?:you\s+to\s+)?"
           r"|let'?s\s+|go\s+ahead\s+and\s+)?(?:(?:please|pls|just|also|now)\s+)*")
_FILLER_RE = re.compile(_FILLER)

_VERBS = (r"add|remove|delete|drop|cut|change|rename|replace|swap|update|redo|revise|edit|shorten|lengthen|"
          r"expand|trim|reword|rephrase|reorder|move|insert|include|exclude|fix|correct|tweak|adjust|simplify|"
          r"improve|polish|condense|extend|split|merge|combine|rewrite|regenerate|translate|restructure|"
          r"capitali[sz]e|bold|highlight|sort|reduce|increase|shrink")
_EDIT_VERB = re.compile(rf"^(?:{_VERBS})\b")
_NOUNS = (r"slides?|sections?|bullets?|titles?|subtitles?|headings?|tables?|sheets?|columns?|rows?|cells?|"
          r"formulas?|charts?|graphs?|timelines?|quadrants?|cards?|flows?|diagrams?|paragraphs?|intro|introduction|"
          r"summary|conclusion|document|doc|deck|report|memo|pdf|page|pages|outline|tone|numbers?|figures?|totals?|"
          r"budget|notes|typos?|wording|text|content|examples?|checklist|status|dates?|issues|spreadsheet|"
          r"presentation|handout|runbook|steps?|items?|lines?|colou?rs?|font|layout|order|docx|slideshow|powerpoint|"
          r"onepager|writeup")
_DOC_NOUN = re.compile(rf"\b(?:{_NOUNS})\b")
# Names a part of a document, so an edit may reach back past newer chat to an older document.
_PART_NOUN = re.compile(
    r"\b(?:slides?|sections?|bullets?|subtitles?|headings?|tables?|sheets?|columns?|rows?|cells?|formulas?|"
    r"charts?|timelines?|quadrants?|cards?|diagrams?|paragraphs?|intro|introduction|summary|conclusion|"
    r"document|doc|deck|report|memo|pdf|outline|checklist|spreadsheet|presentation|handout|runbook|docx|"
    r"slideshow|powerpoint)\b")
_PRONOUN = re.compile(r"\b(?:it|this|that|these|those|them)\b")
# "this slide" points at the document; "this list" or "this sentence" points at whatever is pasted after it.
_BARE_PRONOUN = re.compile(rf"\b(?:it|this|that|these|those|them)\b(?!\s+(?:{_NOUNS})\b)")
_PASTED = re.compile(r"^([^:\n]{0,200}):[ \t]*\S|^([^:\n]{0,200}):[ \t]*\n\s*\S")
# "fix this bug", "delete this function": a pronoun alone is not enough when the clause is about software.
_SOFTWARE = frozenset((
    "bug bugs error errors exception crash traceback code script function functions class method methods "
    "program app api query regex command commands test tests build file files folder repo branch commit "
    "server container password wifi chat conversation message messages python javascript typescript java bash git "
    "github docker linux terminal vscode vim postgres postgresql mysql sqlite sql database amazon ebay shipping "
    "parcel invoice").split())
_SOFTWARE_CONTEXT = re.compile(
    r"\b\w+\.(?:py|js|ts|tsx|jsx|sh|md|json|ya?ml|txt|html|css|cpp|java|rb|go|rs|toml|ini|log)\b"
    r"|\bmy\s+orders?\b|\borders?\s+(?:status|number|history)\b")
_LINE_NUMBER = re.compile(r"\blines?\s+\d+")
_STRONG_PART = re.compile(
    r"\b(?:slides?|sections?|rows?|cells?|sheets?|tables?|pages?|paragraphs?|bullets?|deck|document)\b")
# What the message is about comes before "about X" or a quoted title, which may be any topic.
_TOPIC_CUT = re.compile(r"\b(?:about|regarding|covering|titled|called|named|saying)\b|[\"\u201c].*")
_STYLE = (r"shorter|longer|shorten|lengthen|simpler|clearer|briefer|concise|detailed|formal|casual|professional|"
          r"friendly|punchier|visual|colou?rful|bigger|smaller|compact|technical|readable|more\s+\w+|less\s+\w+|"
          r"fewer\s+\w+|better|nicer|cleaner|bolder|tighter|plainer")
_MAKE_EDIT = re.compile(
    rf"^make\s+(?:it|this|that|them|these|those|the\s+\w+(?:\s+\w+)?|each\s+\w+|every\s+\w+|all\s+(?:of\s+)?\w+"
    rf"|(?:slides?|sections?|rows?|columns?|pages?|paragraphs?|bullets?|steps?)\s+(?:\d+|one|two|three|four|five|six|"
    rf"seven|eight|nine|ten|first|second|third|last))"
    rf"\b.*\b(?:{_STYLE}|\d+)\b")
_MORE = re.compile(r"^(?:(?:a\s+)?(?:few|bit|little|couple)\s+)?(?:(?:one|two|three|\d+)\s+)?(?:more|fewer|less|another)\s+"
                   r"(?:slides?|sections?|rows?|bullets?|detail|details|examples?|charts?|tables?|pages?|items?|"
                   r"columns?|steps?|visuals?)\b")
_COMPARATIVE = re.compile(
    r"^(?:(?:a\s+)?(?:bit|little|lot|much|way)\s+)?(?:shorter|longer|simpler|clearer|briefer|tighter|punchier|"
    r"plainer|more\s+(?:formal|casual|concise|detailed|visual|professional|friendly|technical|specific|readable|"
    r"colou?rful|compact)|less\s+(?:formal|wordy|technical|text|detailed|dense))\b")
# Verbs that rework a thing already written: with only a pronoun after them, the pronoun is the document.
_SELF_VERB = re.compile(r"^(?:fix|shorten|lengthen|expand|trim|redo|rewrite|rephrase|reword|simplify|improve|polish|"
                        r"condense|regenerate|revise|tweak|correct|translate|edit|update|restructure|reorder|extend|"
                        r"reduce|shrink|increase)\b")
_TURN_INTO = re.compile(r"^(?:turn|change|convert|reformat|put)\s+(?:the\s+|these\s+|those\s+|this\s+|that\s+|it\s+)?"
                        r"[\w\s-]{0,30}?\b(?:into|to|as)\b")
_FIX_PREFIX = re.compile(r"^\s*fix\s+these\s+issues\s+in\s+the\s+document\s*:", re.I)

_CONVERT = re.compile(
    r"^(?:turn|convert|transform|export|save|put|make|rewrite|reformat|present|print|redo|download)\s+"
    r"(?:(?:it|this|that|them|the\s+above|the\s+(?:doc|document|deck|report|memo|sheet|spreadsheet|table|pdf|"
    r"slides|presentation|slideshow|powerpoint|handout|one))\s+)"
    r"(?:(?:right\s+)?(?:now\s+)?(?:into|as|to|in)\b|an?\b)")


# A format change with no pronoun: "convert to pdf", "export to excel", "download as pdf".
# The target has to close the clause: "save to the document folder" and "turn to the report section" name a
# place or a part, where "convert to pdf", "export to excel please" and "download as a pdf file" name a format.
_CONVERT_BARE_SRC = (
    r"^(?:convert|export|save|print|download|turn|put|make|transform|reformat|redo)\s+(?:(?:right\s+)?now\s+)?"
    r"(?:into|as|to|in)\s+(?:an?\s+|the\s+)?"
    r"(?=(?:{targets})(?:\s+(?:file|format|instead|please|pls|now|asap|thanks|for\s+me))*\s*[.!]*\s*$)")
# "give me this as a pdf", "send me that in word".
_CONVERT_GIVE = re.compile(r"^(?:give|send|get)\s+me\s+(?:this|that|it|the\s+above)\s+(?:as|in|into)\s+(?:an?\s+)?")


# "Thanks!", "Looks good.", "Perfect.": praise that opens a message ahead of the actual request.
_PRAISE = frozenset(
    "looks look sounds sound good great perfect nice awesome cool fine ok okay amazing excellent lovely wonderful "
    "love like it that this thanks thank you thx ty so much very really pretty super works work well done lgtm "
    "is s the job yes yeah yep sure right appreciate nailed got a lot i".split())
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n")


def _pleasantry(sentence: str) -> bool:
    words = re.findall(r"[a-z]+", sentence)
    return len(words) <= 6 and all(w in _PRAISE for w in words)


def _clause(text: str) -> str:
    """The first sentence that is a request: leading praise and empty filler are skipped.

    Read through ``doc_words.normalize``, so "power point", "slide show" and a mistyped
    "sildeshow" are the words the rest of this module knows. "balance sheet" and "tracker
    table" stay as written: they name a spreadsheet, which this module's nouns already know.
    """
    text = doc_words.normalize(text, sheets=False).strip()
    for sentence in _SENTENCE_SPLIT.split(text) if text else []:
        stripped = _FILLER_RE.sub("", sentence.strip()).strip()
        if stripped and not _pleasantry(stripped):
            return stripped
    return ""


_TARGET_WORDS = (
    ("deck", frozenset("deck decks slides slideshow presentation powerpoint pptx ppt keynote".split())),
    ("sheet", frozenset("spreadsheet excel xlsx workbook csv sheet".split())),
    ("pdf", frozenset(("pdf", "pdfs"))),
    ("doc", frozenset("document doc docx word report memo".split())),
)


_TARGET_ALT = "|".join(sorted({w for _, words in _TARGET_WORDS for w in words}, key=len, reverse=True))
_CONVERT_BARE = re.compile(_CONVERT_BARE_SRC.format(targets=_TARGET_ALT))


def _convert_match(text: str):
    if len(text or "") > MAX_EDIT_CHARS:
        return None, None
    clause = _clause(text)
    return clause, _CONVERT.match(clause) or _CONVERT_GIVE.match(clause) or _CONVERT_BARE.match(clause)


def conversion_target(text: str) -> Optional[str]:
    """The kind asked for by "turn this into a deck", "make it a pdf", "export it as xlsx", else None.

    The pronoun is the earlier document. "turn these notes into slides" is not one: the
    material is in the message, so it is a new document.
    """
    clause, m = _convert_match(text)
    if not m:
        return None
    for word in re.findall(r"[a-z0-9]+", clause[m.end():]):
        for kind, words in _TARGET_WORDS:
            if word in words:
                return kind
    return None


def conversion_names_part(text: str) -> bool:
    """"turn the deck into a pdf" names its subject; "turn it into a pdf" does not."""
    clause, m = _convert_match(text)
    return bool(m and _PART_NOUN.search(clause[:m.end()]))


def _about_software(clause: str) -> bool:
    head = _TOPIC_CUT.split(clause)[0]
    words = set(re.findall(r"[a-z0-9']+", head))
    if words & _SOFTWARE or _SOFTWARE_CONTEXT.search(head):
        return True
    return bool(_LINE_NUMBER.search(head) and not _STRONG_PART.search(head))


# "add a section to my essay": a possessive that does not point at a part of the document points at another one.
_POSSESSIVE = re.compile(r"\b(?:my|our|your|his|her|their)\s+((?:[a-z0-9'-]+\s+){0,2}[a-z0-9'-]+)")


# After "about X" the topic may be anything of the user's, but a destination is not a topic.
_DESTINATION = re.compile(r"\b(?:to|in|into|from)\s+(?:my|our|your|his|her|their)\s+((?:[a-z0-9'-]+\s+){0,2}[a-z0-9'-]+)")


def _about_other_document(clause: str) -> bool:
    head = _TOPIC_CUT.split(clause)[0]
    found = list(_POSSESSIVE.finditer(head)) + list(_DESTINATION.finditer(clause))
    return any(not _DOC_NOUN.search(m.group(1)) for m in found)


def is_edit(text: str) -> bool:
    """Reads like a change request to a document rather than a new topic."""
    if not isinstance(text, str) or not text.strip():
        return False
    # Before the length cap: the UI's issue list can run long.
    if _FIX_PREFIX.match(text):
        return True
    if len(text) > MAX_EDIT_CHARS:
        return False
    if doc_revision_i18n.is_edit(text):
        return True
    clause = _clause(text)
    if not clause:
        return False
    # "translate this to Spanish: good morning": the pronoun is the material after the colon.
    pasted = _PASTED.match(text.lower().strip())
    if pasted and _BARE_PRONOUN.search(clause.split(":")[0]):
        return False
    if _MORE.match(clause) or _COMPARATIVE.match(clause) or _MAKE_EDIT.match(clause):
        return True
    words = set(re.findall(r"[a-z0-9']+", clause))
    if _EDIT_VERB.match(clause):
        if _about_software(clause) or _about_other_document(clause):
            return False
        if "issues" in words or _DOC_NOUN.search(clause):
            return True
        return bool(_SELF_VERB.match(clause) and _PRONOUN.search(clause))
    if _TURN_INTO.match(clause):
        return bool(_DOC_NOUN.search(clause)) and not _about_software(clause) and not _about_other_document(clause)
    return False


def has_fix_prefix(text: str) -> bool:
    """Starts with the UI's "Fix these issues in the document:", which always means the document."""
    return isinstance(text, str) and bool(_FIX_PREFIX.match(text))


def names_part(text: str) -> bool:
    """The message names a piece of the document ("the third slide", "the deck"), not just "it"."""
    return bool(_PART_NOUN.search(_clause(text))) or doc_revision_i18n.names_part(text)


# ---- what the model is told -------------------------------------------------------------------

def _base_title(title: str) -> str:
    return re.sub(r"\s*\((?:Deck|Document|PDF|Spreadsheet)\)\s*$", "", title).strip()


def target_title(prior: PriorDoc, kind: str, mode: str) -> str:
    """An edit keeps the title as written (the panel keys on it); a conversion gets a title of its own."""
    title = _base_title(prior.title)
    if mode != "convert":
        return prior.title
    return f"{title} ({_LABELS[kind]})" if title else title


def _title_directive(prior: PriorDoc, kind: str, mode: str) -> str:
    """How the note tells the model which title to write; a long title is pointed at, not repeated."""
    title = target_title(prior, kind, mode)
    if not title:
        return ""
    if len(title) <= MAX_NOTE_TITLE:
        return f" and `title: {title}`" if mode == "convert" else f" and the header line `title: {title}` unchanged, so the app updates the same panel"
    if mode == "convert":
        return " and the same `title:` line as the document above with its new kind in brackets at the end"
    return " and the `title:` header line copied unchanged from the document above, so the app updates the same panel"


def revision_note(mode: str, prior: PriorDoc, kind: str, cut: bool) -> str:
    noun = NOUNS.get(kind, "document")
    named = f' titled "{prior.title}"' if prior.title and len(prior.title) <= MAX_NOTE_TITLE else ""
    if mode == "convert":
        note = (f"CONVERSION. Turn the {NOUNS.get(prior.kind, 'document')}{named} that you wrote above into a "
                f"{noun}. Keep its content. Reply with one short sentence, then ONE harvis-doc block with "
                f"`kind: {kind}`" + _title_directive(prior, kind, mode) + f", following the {noun} rules above.")
    else:
        note = (f"REVISION. The user wants a change to the {noun}{named} that you wrote above. Reply with one short "
                f"sentence, then the COMPLETE updated {noun} in ONE harvis-doc block, not just the changed part: "
                f"same `kind: {kind}`" + _title_directive(prior, kind, mode) + ". Keep everything the user did not "
                "ask to change.")
    if cut:
        note += " The copy above was cut for length: still write the whole document."
    return note


def compact_history(messages: list, prior: PriorDoc) -> bool:
    """Keep only the latest document in the history; cut it if it is long. True when it was cut.

    Earlier documents become a one-line stub, so a long session does not spend the
    context window on drafts the user has moved past. Idempotent.
    """
    cut = False
    for i, m in enumerate(messages):
        if not (isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str)):
            continue
        original = content = m["content"]
        # Last fence first, so the offsets of the earlier ones stay valid while the text changes.
        for start, end, body in reversed(find_fences(content)):
            if (i, start, end) == (prior.message, prior.start, prior.end):
                if CUT_MARK in body:
                    cut = True
                elif len(body) > MAX_DOC_CHARS:
                    opener = content[start:content.find("\n", start) + 1]
                    content = content[:start] + opener + body[:MAX_DOC_CHARS] + CUT_MARK + "\n````\n" + content[end:]
                    cut = True
                continue
            kind = _KIND_LINE.search(body[:800])
            title = _TITLE_LINE.search(body[:800])
            label = f'"{title.group(1).strip()}" ' if title else ""
            noun = NOUNS.get(_kind_of(kind.group(1)), "document") if kind else "document"
            content = content[:start] + f"[earlier {noun} {label}left out]\n" + content[end:]
        if content != original:
            messages[i] = {**m, "content": content}
    return cut
