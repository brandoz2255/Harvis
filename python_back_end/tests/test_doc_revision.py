"""A follow-up on a document already in the chat: edits, format conversions, and what must stay plain chat.

"make it shorter" has no document wording, so the latest harvis-doc fence in the history decides. A false hit
answers "what is phishing?" with a document, so the negatives below matter as much as the positives.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import doc_revision  # noqa: E402
from owui_compat.doc_bridge import doc_system_prompt, maybe_prepare_doc_turn  # noqa: E402

KINDS = ("deck", "doc", "pdf", "sheet")
PROMPT_CAP = 3500

DECK = """Here is the deck.

````harvis-doc
---
kind: deck
title: Fire Drill Results
outline:
  - Title
  - Why it matters
---
# Fire Drill Results
Keep every inbox one step ahead
---
## Why it matters
- Ransomware dwell time fell to five days
````

Tell me which to expand."""


def _chat(follow_up, doc=DECK, extra=()):
    return {"messages": [
        {"role": "user", "content": "make a deck about phishing awareness"},
        {"role": "assistant", "content": doc},
        *extra,
        {"role": "user", "content": follow_up},
    ]}


def _system(body):
    return [m["content"] for m in body["messages"] if m["role"] == "system"]


@pytest.mark.parametrize("text", [
    "make it shorter",
    "Can you make it a bit shorter?",
    "add a slide about MFA",
    "please add a row for the printer",
    "remove the timeline",
    "rename the title to Q4 Review",
    "replace the chart with a table",
    "turn the bullets into a table",
    "more slides",
    "two more slides please",
    "make the deck 8 slides",
    "make the report more formal",
    "update the numbers for 2027",
    "redo it",
    "translate it to Spanish",
    "shorter",
    "also add a checklist",
    "Fix these issues in the document:\n- slide 2 has no title",
])
def test_an_edit_request_after_a_document_revises_that_document(text):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) == "deck"
    [prompt] = _system(body)
    assert prompt.startswith(doc_system_prompt("deck").split("\n\nThis is a")[0])
    assert "REVISION" in prompt
    assert 'title: Fire Drill Results' in prompt
    assert "COMPLETE" in prompt
    assert body["messages"][-1]["content"] == text


@pytest.mark.parametrize("text", [
    "thanks",
    "thank you!",
    "what is phishing?",
    "how do I add a slide in PowerPoint?",
    "why is slide 2 empty",
    "fix this bug in my python code",
    "add this to my todo list",
    "delete this chat",
    "change my password",
    "tell me about MFA",
    "great, that looks good",
    "brief me on zero trust",
    "can you explain slide 3?",
    "update me on the news",
    "hello",
])
def test_an_unrelated_follow_up_does_not_trigger_doc_mode(text):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) is None
    assert _system(body) == []


def test_an_edit_wording_with_no_document_in_the_chat_is_plain_chat():
    body = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                         {"role": "user", "content": "make it shorter"}]}
    assert maybe_prepare_doc_turn(body) is None


def test_a_fix_these_issues_prefix_revises_the_document_with_its_own_kind():
    doc = DECK.replace("kind: deck", "kind: sheet").replace("Fire Drill Results", "Lab Budget")
    body = _chat("Fix these issues in the document:\n- The total formula points at column A", doc=doc)
    assert maybe_prepare_doc_turn(body) == "sheet"
    [prompt] = _system(body)
    assert "kind: sheet" in prompt and 'title: Lab Budget' in prompt and "REVISION" in prompt


def test_a_new_request_after_a_document_is_still_a_new_document():
    body = _chat("make a spreadsheet of monthly expenses")
    assert maybe_prepare_doc_turn(body) == "sheet"
    [prompt] = _system(body)
    assert "REVISION" not in prompt and "CONVERSION" not in prompt


def test_make_the_deck_shorter_is_an_edit_not_a_new_deck():
    body = _chat("make the deck shorter")
    assert maybe_prepare_doc_turn(body) == "deck"
    assert "REVISION" in _system(body)[0]


@pytest.mark.parametrize("text,kind", [
    ("turn this into a pdf", "pdf"),
    ("make it a spreadsheet", "sheet"),
    ("convert this to a document", "doc"),
    ("export it as an xlsx", "sheet"),
    ("save this as a pdf", "pdf"),
])
def test_asking_for_another_format_converts_the_same_content(text, kind):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) == kind
    [prompt] = _system(body)
    assert "CONVERSION" in prompt
    assert f"kind: {kind}" in prompt
    assert "Fire Drill Results (" in prompt  # a title of its own, so the original panel stays


def test_notes_pasted_into_the_message_are_not_a_conversion_of_the_last_document():
    body = _chat("turn these notes into slides: " + "the lab is cold. " * 40)
    assert maybe_prepare_doc_turn(body) == "deck"
    assert "CONVERSION" not in _system(body)[0]


def test_only_the_latest_document_stays_in_the_history_the_model_sees():
    older = DECK.replace("Fire Drill Results", "Zero Trust Primer")
    body = {"messages": [
        {"role": "user", "content": "make a deck about zero trust"},
        {"role": "assistant", "content": older},
        {"role": "user", "content": "now make a deck about phishing"},
        {"role": "assistant", "content": DECK},
        {"role": "user", "content": "add a slide about MFA"},
    ]}
    assert maybe_prepare_doc_turn(body) == "deck"
    assert "Zero Trust Primer" in body["messages"][1]["content"]       # as a stub only
    assert "````harvis-doc" not in body["messages"][1]["content"]
    assert "````harvis-doc" in body["messages"][3]["content"]
    assert body["messages"][3]["content"].count("# Fire Drill Results") >= 1


def test_the_document_is_pointed_at_not_pasted_a_second_time():
    body = _chat("make it shorter")
    maybe_prepare_doc_turn(body)
    assert "Ransomware dwell time" not in _system(body)[0]
    assert sum(m["content"].count("Ransomware dwell time") for m in body["messages"]) == 1


def test_a_very_long_document_is_cut_in_the_history_and_the_model_is_told():
    long_doc = DECK.replace("- Ransomware dwell time fell to five days", "- filler line\n" * 2500)
    assert len(long_doc) > doc_revision.MAX_DOC_CHARS * 2
    body = _chat("make it shorter", doc=long_doc)
    assert maybe_prepare_doc_turn(body) == "deck"
    assistant = body["messages"][1]["content"]
    assert len(assistant) < doc_revision.MAX_DOC_CHARS + 1000
    assert assistant.rstrip().endswith("````") or "Tell me which to expand." in assistant
    assert "cut for length" in _system(body)[0]


def test_revision_turns_are_idempotent():
    body = _chat("make it shorter")
    maybe_prepare_doc_turn(body)
    snapshot = [dict(m) for m in body["messages"]]
    assert maybe_prepare_doc_turn(body) == "deck"
    assert body["messages"] == snapshot


def test_the_revision_prompt_stays_under_the_cap_for_every_kind():
    for kind in KINDS:
        doc = DECK.replace("kind: deck", f"kind: {kind}")
        body = _chat("make it shorter", doc=doc)
        assert maybe_prepare_doc_turn(body) == kind
        assert len(_system(body)[0]) <= PROMPT_CAP


def test_a_document_without_a_closing_fence_is_still_found():
    unfinished = DECK.split("Tell me")[0].rsplit("````", 1)[0]
    body = _chat("add a slide about MFA", doc=unfinished)
    assert maybe_prepare_doc_turn(body) == "deck"


def test_assistant_content_that_is_not_text_never_raises():
    body = {"messages": [{"role": "assistant", "content": [{"type": "text", "text": "x"}]},
                         {"role": "assistant", "content": None},
                         {"role": "user", "content": "make it shorter"}]}
    assert maybe_prepare_doc_turn(body) is None


def test_the_group_room_prompt_is_never_a_revision():
    body = _chat("[Group chat: lab] make it shorter")
    assert maybe_prepare_doc_turn(body) is None


def test_editing_a_converted_document_keeps_its_title_exactly():
    doc = DECK.replace("kind: deck", "kind: pdf").replace("Fire Drill Results", "Fire Drill Results (PDF)")
    body = _chat("add a section on lessons learned", doc=doc)
    assert maybe_prepare_doc_turn(body) == "pdf"
    assert "`title: Fire Drill Results (PDF)`" in _system(body)[0]


@pytest.mark.parametrize("text", [
    "fix the typo in my python script",
    "fix the error on line 12 of my script",
    "fix the bug on line 3",
    "remove the lines that print debug output from main.py",
    "add a column to my postgres table",
    "update the status of my amazon order",
    "change the font in vscode",
    "translate this to Spanish: good morning",
    "fix this sentence: me and him goes to store",
    "sort the items in this list for me: b, a, c",
    "make this shorter:\nThe committee, having met on several occasions, resolved to proceed.",
])
def test_code_and_pasted_material_after_a_document_stay_plain_chat(text):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) is None
    assert _system(body) == []


@pytest.mark.parametrize("text", [
    "add a slide about the app launch",
    "rename the title to \"Build Pipeline\"",
    "add a slide: Risks",
    "change this slide: make the title shorter",
    "fix the typo on slide 2",
    "remove line 3 from the table",
])
def test_document_edits_that_mention_software_words_still_revise(text):
    assert maybe_prepare_doc_turn(_chat(text)) == "deck"


def test_a_long_fix_these_issues_list_still_revises_the_document():
    issues = "".join(f"- slide {i} has a title that is too long and should be shortened\n" for i in range(10))
    text = "Fix these issues in the document:\n" + issues
    assert len(text) > doc_revision.MAX_EDIT_CHARS
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) == "deck"
    assert "REVISION" in _system(body)[0]


HAIKU = ({"role": "user", "content": "write a haiku about the lab"},
         {"role": "assistant", "content": "Cold racks hum softly\nblue LEDs blink in the dark"})


def test_a_vague_edit_after_a_later_answer_targets_that_answer_not_the_old_document():
    body = _chat("make it shorter", extra=HAIKU)
    assert maybe_prepare_doc_turn(body) is None
    assert _system(body) == []


@pytest.mark.parametrize("text", ["make the deck shorter", "add a slide about MFA",
                                  "Fix these issues in the document:\n- slide 2 has no title"])
def test_an_edit_that_names_the_document_reaches_back_past_later_answers(text):
    assert maybe_prepare_doc_turn(_chat(text, extra=HAIKU)) == "deck"


def test_a_vague_conversion_needs_the_document_to_be_the_latest_answer():
    # Plain "new pdf" wording, not a conversion of the old deck: the haiku is what "it" is.
    vague = _chat("turn it into a pdf", extra=HAIKU)
    assert maybe_prepare_doc_turn(vague) == "pdf"
    assert "CONVERSION" not in _system(vague)[0]
    named = _chat("turn the deck into a pdf", extra=HAIKU)
    assert maybe_prepare_doc_turn(named) == "pdf"
    assert "CONVERSION" in _system(named)[0]


def test_a_very_long_title_is_pointed_at_not_repeated_in_the_note():
    title = "Fire Drill " + "Results " * 60
    for text in ("make it shorter", "turn it into a pdf"):
        body = _chat(text, doc=DECK.replace("Fire Drill Results", title.strip(), 1))
        assert maybe_prepare_doc_turn(body)
        prompt = _system(body)[0]
        assert title.strip() not in prompt.split("REVISION")[-1].split("CONVERSION")[-1]
        assert len(prompt) <= PROMPT_CAP


@pytest.mark.parametrize("text", [
    "Thanks! Make it shorter.",
    "Looks good. Add a slide about passkeys.",
    "Perfect.\nRemove the timeline",
    "Great job. Thank you. Rename the title to Q4 Review",
])
def test_praise_before_the_request_does_not_hide_the_edit(text):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) == "deck"
    assert "REVISION" in _system(body)[0]


def test_praise_before_a_conversion_still_converts_with_a_title_of_its_own():
    body = _chat("Perfect. Now turn it into a pdf")
    assert maybe_prepare_doc_turn(body) == "pdf"
    [prompt] = _system(body)
    assert "CONVERSION" in prompt
    assert "Fire Drill Results (PDF)" in prompt


@pytest.mark.parametrize("text", [
    "add a section about budgets to my essay",
    "update my resume",
    "rewrite my cover letter to sound more formal",
    "turn my essay into a table",
])
def test_an_edit_to_someone_elses_document_is_plain_chat(text):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) is None


@pytest.mark.parametrize("text", [
    "add a bullet to my first slide",
    "fix my typo in the intro",
    "shorten my deck",
    "add a slide about my budget",
])
def test_a_possessive_that_points_at_the_document_still_revises(text):
    assert maybe_prepare_doc_turn(_chat(text)) == "deck"


# ---- format changes worded the way people type them ----------------------------------------------

DOC = DECK.replace("kind: deck", "kind: doc")


@pytest.mark.parametrize("text", [
    "turn it into a slide show",
    "make it a power point",
    "can you make that a slide show",
    "make it a powerpint",
    "turn it into a sildeshow",
    "export it as a Power Point",
])
def test_after_a_document_slide_show_wording_converts_it_to_a_deck(text):
    body = _chat(text, doc=DOC)
    assert maybe_prepare_doc_turn(body) == "deck"
    [prompt] = _system(body)
    assert "CONVERSION" in prompt and "kind: deck" in prompt
    assert "Fire Drill Results (Deck)" in prompt


@pytest.mark.parametrize("text,kind", [
    ("convert to pdf", "pdf"),
    ("Convert to PDF", "pdf"),
    ("export to excel", "sheet"),
    ("download as pdf", "pdf"),
    ("save as a word doc", "doc"),
    ("give me this as a pdf", "pdf"),
    ("send me that in word", "doc"),
])
def test_a_format_change_with_no_pronoun_converts_instead_of_revising(text, kind):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) == kind
    [prompt] = _system(body)
    assert "CONVERSION" in prompt and f"kind: {kind}" in prompt and "REVISION" not in prompt


def test_a_deck_asked_to_become_a_slide_show_is_edited_in_place_not_copied():
    body = _chat("turn it into a slide show")
    assert maybe_prepare_doc_turn(body) == "deck"
    [prompt] = _system(body)
    assert "REVISION" in prompt and "CONVERSION" not in prompt


@pytest.mark.parametrize("doc", [DECK, DOC])
def test_make_it_shorter_still_revises_whatever_the_document_is(doc):
    body = _chat("make it shorter", doc=doc)
    assert maybe_prepare_doc_turn(body) == ("deck" if doc is DECK else "doc")
    assert "REVISION" in _system(body)[0]


@pytest.mark.parametrize("text,kind", [("convert to pdf", "pdf"), ("export to excel", "sheet")])
def test_a_bare_format_change_with_no_document_in_the_chat_is_only_a_new_request(text, kind):
    body = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                         {"role": "user", "content": text}]}
    assert maybe_prepare_doc_turn(body) == kind
    assert "CONVERSION" not in "".join(_system(body))


@pytest.mark.parametrize("text", [
    "save to my documents folder",
    "put it in the fridge",
    "convert to celsius",
    "export to the cloud",
    "turn to page 4",
    "make it a table",
    "save to the document folder",
    "turn to the report section",
    "export to the excel folder",
    "convert to the pdf page",
])
def test_a_place_or_unit_after_a_convert_verb_is_not_a_format_change(text):
    assert doc_revision.conversion_target(text) is None


@pytest.mark.parametrize("text", ["convert to pdf please", "export to excel", "download as a pdf file",
                                  "save as the word format", "convert to pdf."])
def test_a_target_that_closes_the_clause_is_still_a_format_change(text):
    assert doc_revision.conversion_target(text) is not None


@pytest.mark.parametrize("text", ["save to the document folder", "turn to the report section"])
def test_a_place_or_section_after_a_deck_is_not_a_conversion_in_the_chat(text):
    body = _chat(text)
    maybe_prepare_doc_turn(body)
    assert "CONVERSION" not in "".join(_system(body))


@pytest.mark.parametrize("text", ["add a slide on the pool party", "add a slide on the playground safety rules",
                                  "add a slide at the park cleanup"])
def test_a_slide_about_a_place_topic_is_still_an_edit_of_the_deck(text):
    body = _chat(text)
    assert maybe_prepare_doc_turn(body) == "deck"
    assert "REVISION" in _system(body)[0]


def test_conversion_names_part_sees_a_slide_show_by_name():
    assert doc_revision.conversion_names_part("turn the power point into a pdf")
    assert not doc_revision.conversion_names_part("convert to pdf")
