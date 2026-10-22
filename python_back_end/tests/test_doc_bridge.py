"""A request for a deck, document, spreadsheet or PDF gets the harvis-doc prompt.

Detection is deterministic wording on the latest user message. The cost of a
miss is a plain markdown answer; the cost of a false hit is a chat question
answered with a document block, so every question and code request below must
stay unclaimed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import doc_bridge  # noqa: E402
from owui_compat.doc_bridge import detect_doc_kind, doc_system_prompt, maybe_prepare_doc_turn  # noqa: E402


@pytest.mark.parametrize("text,kind", [
    ("Make me a deck about our Q3 security review", "deck"),
    ("create a 10 slide presentation on zero trust", "deck"),
    ("Can you put together a slideshow for the board?", "deck"),
    ("could you please build a PowerPoint about phishing", "deck"),
    ("I need a pitch deck for my startup", "deck"),
    ("generate 8 slides on cloud costs", "deck"),
    ("please draft a keynote presentation for the conference", "deck"),
    ("turn these notes into slides", "deck"),
    ("Convert this outline into a presentation", "deck"),
    ("export this as a pptx", "deck"),
    ("make it a deck", "deck"),
    ("ok, make me a quick google slides on onboarding", "deck"),
    ("Write a spreadsheet of monthly expenses", "sheet"),
    ("create an excel workbook to track my study hours", "sheet"),
    ("make a budget for a 4 person household", "sheet"),
    ("build me a budget tracker", "sheet"),
    ("Can you generate a csv of 20 sample customers?", "sheet"),
    ("I want an xlsx with sales by region", "sheet"),
    ("put together a sheet with every lab device and its IP", "sheet"),
    ("export this table to excel", "sheet"),
    ("Make a pdf of the onboarding checklist", "pdf"),
    ("generate a PDF report on network segmentation", "pdf"),
    ("save this as a pdf", "pdf"),
    ("give me the pdf", "pdf"),
    ("Write a report on the lab network", "doc"),
    ("draft a memo to the team about the outage", "doc"),
    ("write me a cover letter for a SOC analyst role", "doc"),
    ("Can you create a one-pager for the CISO lab", "doc"),
    ("I need a resume", "doc"),
    ("please produce a whitepaper on passkeys", "doc"),
    ("make a word doc about incident response", "doc"),
    ("write an essay on the history of encryption", "doc"),
    ("create a cheat sheet for nmap flags", "doc"),
    ("give me a handout for the workshop", "doc"),
    ("Generate a proposal for the new SIEM", "doc"),
    ("write a user guide for the lab router", "doc"),
    ("turn my notes into a report", "doc"),
    ("Thanks. Now draft a brief", "doc"),
    ("write a letter to my landlord about the heater", "doc"),
    ("I'd like a deck on onboarding", "deck"),
    ("summarize this article and turn it into a one-pager", "doc"),
    ("extract the tables from this pdf and make a spreadsheet", "sheet"),
    ("make a pdf deck of the roadmap", "deck"),
])
def test_a_request_to_make_a_document_is_detected(text, kind):
    assert detect_doc_kind(text) == kind


@pytest.mark.parametrize("text", [
    "what is a pdf",
    "How do I make slides in google?",
    "how to create a spreadsheet in excel",
    "How can I write a report faster?",
    "what's the difference between a deck and a presentation",
    "explain how pptx files are structured",
    "why are my slides blurry when exported",
    "tell me about the history of the spreadsheet",
    "is a csv better than xlsx for this?",
    "Do you know how to make a pdf from markdown?",
    "can you explain how to write a memo",
    "summarize this pdf",
    "read the attached report and tell me the risks",
    "what are the main points of the deck I uploaded",
    "I like this presentation",
    "i love that spreadsheet",
    "don't make a pdf, just answer",
    "write a function that parses a pdf",
    "write a python script that makes a spreadsheet",
    "create a pdf parser in rust",
    "build a spreadsheet parser",
    "I need a pdf reader",
    "write an excel formula that sums column B",
    "create an excel macro to color rows",
    "write a keynote speech for the wedding",
    "write a brief summary of the lecture",
    "write a short description of this function",
    "make a doc string for this method",
    "create a docker image for the backend",
    "save this file to my documents folder",
    "convert celsius to fahrenheit",
    "generate a random password",
    "make me a sandwich",
    "write a haiku about the lab",
    "build a presentation layer for the app",
    "write a unit test for the report generator",
    "create a table of the ports",
    "hello",
    "",
])
def test_questions_and_code_requests_are_left_alone(text):
    assert detect_doc_kind(text) is None


def test_a_long_paste_is_judged_by_its_ends_not_its_middle():
    filler = "The committee said we should make a deck about this. " * 80
    assert detect_doc_kind(filler) is None
    assert detect_doc_kind(filler + "\n\nPlease make a spreadsheet of the action items.") == "sheet"
    assert detect_doc_kind("Make a deck from this:\n" + filler) == "deck"


def test_multimodal_content_is_read_from_its_text_parts():
    body = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        {"type": "text", "text": "make a deck from this chart"}]}]}
    assert maybe_prepare_doc_turn(body) == "deck"


def test_each_kind_has_a_prompt_that_teaches_the_exact_block():
    for kind in ("deck", "doc", "sheet", "pdf"):
        prompt = doc_system_prompt(kind)
        assert "````harvis-doc" in prompt
        assert f"kind: {kind}" in prompt
        assert "outline:" in prompt
        assert doc_bridge.DOC_PROMPT_MARKER in prompt
    assert "6-12 slides" in doc_system_prompt("deck")
    assert "Notes:" in doc_system_prompt("deck")
    assert "=SUM(" in doc_system_prompt("sheet")
    assert "four backticks" in doc_system_prompt("doc")


def test_an_unknown_kind_falls_back_to_the_document_prompt():
    assert "kind: doc" in doc_system_prompt("nonsense")


def test_the_prompt_lands_right_before_the_last_user_message():
    body = {"messages": [
        {"role": "system", "content": "persona"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "make a deck about phishing"},
    ]}
    assert maybe_prepare_doc_turn(body) == "deck"
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "system", "user"]
    assert body["messages"][3]["content"] == doc_system_prompt("deck")
    assert body["messages"][4]["content"] == "make a deck about phishing"


def test_a_turn_that_is_not_a_document_request_is_untouched():
    body = {"messages": [{"role": "user", "content": "what is a pdf"}]}
    assert maybe_prepare_doc_turn(body) is None
    assert len(body["messages"]) == 1


def test_only_the_latest_user_message_counts():
    body = {"messages": [
        {"role": "user", "content": "make a deck about phishing"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "thanks, that's great"},
    ]}
    assert maybe_prepare_doc_turn(body) is None


def test_it_is_idempotent_when_the_same_body_is_prepared_twice():
    body = {"messages": [{"role": "user", "content": "write a report on the lab"}]}
    assert maybe_prepare_doc_turn(body) == "doc"
    assert maybe_prepare_doc_turn(body) == "doc"
    assert [m["role"] for m in body["messages"]].count("system") == 1


def test_a_group_room_prompt_is_never_a_document_request():
    body = {"messages": [{"role": "user", "content":
                          "[Group chat: lab] Claim work or hand off. Please write a report."}]}
    assert maybe_prepare_doc_turn(body) is None


@pytest.mark.parametrize("body", [{}, {"messages": None}, {"messages": []}, {"messages": "x"},
                                  {"messages": [{"role": "system", "content": "make a deck"}]}])
def test_malformed_bodies_never_raise(body):
    assert maybe_prepare_doc_turn(body) is None


def test_the_block_vocabulary_is_not_appended_to_the_document_prompt():
    from owui_compat import chat_completion

    body = {"messages": [{"role": "user", "content": "make a deck about phishing"}]}
    maybe_prepare_doc_turn(body)
    before = body["messages"][0]["content"]
    chat_completion._inject_block_vocabulary(body)
    assert body["messages"][0]["content"] == before


# ---- format skills: doc_skills/<kind>/SKILL.md is what the model is taught --------------------

import re  # noqa: E402
import shutil  # noqa: E402

KINDS = ("deck", "doc", "pdf", "sheet")
PROMPT_CAP = 3500
SKILLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "owui_compat", "doc_skills")


def _skill_text(kind):
    with open(os.path.join(SKILLS, kind, "SKILL.md"), encoding="utf-8") as fh:
        return fh.read()


def _example(prompt):
    """The first four-backtick harvis-doc block in a prompt."""
    return re.search(r"````harvis-doc\n(.*?)\n````", prompt, re.S).group(1)


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_has_a_skill_file_with_a_one_line_description(kind):
    text = _skill_text(kind)
    head = text.split("\n---\n", 1)[0].splitlines()
    assert head[0] == "---"
    assert head[1].startswith("description: ") and len(head) == 2
    assert len(head[1]) < 260


@pytest.mark.parametrize("kind", KINDS)
def test_the_prompt_is_the_skill_body_without_its_front_matter(kind):
    prompt = doc_system_prompt(kind)
    body = _skill_text(kind).split("\n---\n", 1)[1].strip()
    assert body in prompt
    assert "description:" not in prompt
    assert prompt.rstrip().endswith("outside the block.")


@pytest.mark.parametrize("kind", KINDS)
def test_a_prompt_stays_short_enough_for_a_small_model(kind):
    assert len(doc_system_prompt(kind)) <= PROMPT_CAP


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_lists_its_gotchas_and_the_body_tag_rule(kind):
    prompt = doc_system_prompt(kind)
    assert "Gotchas" in prompt
    assert "<body>" in prompt


def test_the_live_run_failures_are_written_down_as_gotchas():
    deck, sheet = doc_system_prompt("deck"), doc_system_prompt("sheet")
    assert "title slide" in deck and "subtitle" in deck and "every slide has a title" in deck
    assert "ONE sheet" in sheet and "category column" in sheet
    assert "No bold" in sheet
    assert "limit" in sheet and "$2000" in sheet and "gap" in sheet
    assert "column B" in sheet and "=SUM(B2:B4)" in sheet


def test_a_deck_may_use_one_rich_block_per_slide_and_knows_all_six():
    deck = doc_system_prompt("deck")
    for fence in ("```cards", "```timeline", "```quadrant", "```chart", "```flow"):
        assert fence in deck
    assert "table" in deck
    assert "ONE per slide" in deck


@pytest.mark.parametrize("kind", ("doc", "pdf"))
def test_documents_and_pdfs_know_every_block_chips_checklists_math_and_code(kind):
    prompt = doc_system_prompt(kind)
    for fence in ("```cards", "```timeline", "```quadrant", "```chart", "```flow", "```csv"):
        assert fence in prompt
    assert "In progress" in prompt and "Blocked" in prompt
    assert "- [ ]" in prompt and "$$" in prompt


def test_a_spreadsheet_gets_tables_and_formulas_only():
    sheet = doc_system_prompt("sheet")
    for fence in ("```cards", "```timeline", "```quadrant", "```chart", "```flow", "```csv"):
        assert fence not in sheet
    assert "=SUM(" in sheet


@pytest.mark.parametrize("kind", KINDS)
def test_the_example_in_each_skill_is_a_document_the_exporter_accepts(kind):
    from plugins.hermes_ui.docs_export import FORMATS, export_doc
    from plugins.hermes_ui.docs_parse import parse_harvis_doc

    source = _example(doc_system_prompt(kind))
    doc = parse_harvis_doc(source)
    assert doc.kind == kind and doc.header_complete
    assert doc.title and doc.outline
    parts = len(doc.sheets) if kind == "sheet" else len([s for s in doc.sections if s.title or kind == "deck"])
    assert abs(len(doc.outline) - parts) <= 1
    for fmt in FORMATS[kind]:
        assert export_doc(source, fmt).data


def test_a_skill_edit_reaches_the_next_prompt_without_a_restart(tmp_path, monkeypatch):
    copy = tmp_path / "doc_skills"
    shutil.copytree(SKILLS, copy)
    monkeypatch.setattr(doc_bridge, "_SKILLS_DIR", copy)
    monkeypatch.setattr(doc_bridge, "_skill_cache", {})
    assert "Never staple the cat" not in doc_system_prompt("deck")
    path = copy / "deck" / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "- Never staple the cat to a slide.\n", encoding="utf-8")
    os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
    assert "Never staple the cat" in doc_system_prompt("deck")


def test_the_skill_is_read_once_per_mtime(tmp_path, monkeypatch):
    copy = tmp_path / "doc_skills"
    shutil.copytree(SKILLS, copy)
    monkeypatch.setattr(doc_bridge, "_SKILLS_DIR", copy)
    monkeypatch.setattr(doc_bridge, "_skill_cache", {})
    reads = []
    real = type(copy).read_text
    monkeypatch.setattr(type(copy), "read_text", lambda self, *a, **k: reads.append(self) or real(self, *a, **k))
    for _ in range(3):
        doc_system_prompt("pdf")
    assert len(reads) == 1


def test_a_missing_skill_file_still_gives_a_working_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_bridge, "_SKILLS_DIR", tmp_path / "nowhere")
    monkeypatch.setattr(doc_bridge, "_skill_cache", {})
    prompt = doc_system_prompt("sheet")
    assert "kind: sheet" in prompt and "harvis-doc" in prompt and doc_bridge.DOC_PROMPT_MARKER in prompt


def test_a_skill_file_with_bad_bytes_falls_back_instead_of_raising(tmp_path, monkeypatch):
    (tmp_path / "sheet").mkdir()
    (tmp_path / "sheet" / "SKILL.md").write_bytes(b"---\ndescription: x\n---\n\xff\xfe broken")
    monkeypatch.setattr(doc_bridge, "_SKILLS_DIR", tmp_path)
    monkeypatch.setattr(doc_bridge, "_skill_cache", {})
    prompt = doc_system_prompt("sheet")
    assert "kind: sheet" in prompt and doc_bridge.DOC_PROMPT_MARKER in prompt
