"""Chat gets documents: "make me a deck about X" answers with a harvis-doc block.

The model writes ONE fenced block (language ``harvis-doc``) holding the whole
deck, document, spreadsheet or PDF; the Hermes UI renders it as it streams and
exports it through POST /hermes-api/api/harvis/docs/export. The block grammar
is read by front_end/hermes-desktop-ui/src/lib/harvis-doc.ts and by
plugins/hermes_ui/docs_parse.py: keep the three in step.

Detection (doc_detect) is wording only, on the latest user message. A request must address
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

from .doc_detect import DOC_PROMPT_MARKER, KINDS, _lone_format, detect_doc_kind, detect_doc_kinds
from .doc_revision import (PriorDoc, compact_history, conversion_names_part, conversion_target, find_latest_doc,
                           has_fix_prefix, is_edit, names_part, revision_note)

logger = logging.getLogger(__name__)

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


_KIND_NAMES = {"deck": "slides (kind: deck)", "pdf": "a PDF (kind: pdf)", "doc": "a Word doc (kind: doc)",
               "sheet": "a spreadsheet (kind: sheet)"}


def docs_system_prompt(kinds: list[str]) -> str:
    """The instruction for a turn that makes several files: doc_skills/multi, with only the asked kinds' lines.

    One full skill per kind would not fit a small model's prompt budget, so each kind gets its
    one-line summary from the multi skill under "Per kind".
    """
    kinds = [k for k in dict.fromkeys(kinds) if k in KINDS]
    if len(kinds) < 2:
        return doc_system_prompt(kinds[0] if kinds else "doc")
    lines = [ln for ln in _skill_body("multi").splitlines()
             if not re.match(r"- (deck|pdf|doc|sheet): ", ln) or ln[2:].split(":")[0] in kinds]
    asked = ", then ".join(_KIND_NAMES[k] for k in kinds)
    return ("\n".join(lines) + f"\n\nThis is a {DOC_PROMPT_MARKER} turn with {len(kinds)} files: {asked}. Reply with "
            f"one sentence, then {len(kinds)} blocks in that order, each opened with four backticks and harvis-doc. "
            "Do not wrap the answer in :::writing or any other colon fence, and do not paste a document outside "
            "its block.")


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
    kinds = detect_doc_kinds(text) if mode == "new" else [kind]
    if len(kinds) > 1:
        # "make a pdf, slides and a doc about cats": one block per file, so the reply names its first kind.
        kind, prompt = kinds[0], docs_system_prompt(kinds)
        logger.info("doc_bridge: %d files in one turn: %s", len(kinds), ", ".join(kinds))
    else:
        prompt = doc_system_prompt(kind, note)
    previous = messages[last - 1] if last > 0 else None
    already = isinstance(previous, dict) and previous.get("role") == "system" and previous.get("content") == prompt
    if not already:
        messages.insert(last, {"role": "system", "content": prompt})
    return kind
