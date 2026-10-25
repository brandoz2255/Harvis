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
    ("make me a slide show", "deck"),
    ("make me a slide show about cats", "deck"),
    ("create a slide-show on k3s", "deck"),
    ("build me a power point about phishing", "deck"),
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
    ("slide deck on k3s", "deck"),
    ("a powerpoint about dogs", "deck"),
    ("powerpoint about dogs please", "deck"),
    ("can i get slides for class", "deck"),
    ("could I have a presentation on dna", "deck"),
    ("get me a pdf of the notes", "pdf"),
    ("get me a pdf", "pdf"),
    ("send me a presentation about dna", "deck"),
    ("gimme a deck on the market", "deck"),
    ("make me a python cheat sheet", "doc"),
    ("make a docker cheat sheet", "doc"),
    ("write a python tutorial document", "doc"),
    ("i need to present on climate change tomorrow", "deck"),
    ("I have to present about phishing on Monday", "deck"),
    ("i'm presenting on zero trust friday", "deck"),
    ("make me a sildeshow", "deck"),
    ("make a powerpint", "deck"),
    ("make a pwerpoint about dogs", "deck"),
    ("make a presentaion about cats", "deck"),
    ("make me a speadsheet of expenses", "sheet"),
    ("make a spreedsheet", "sheet"),
    ("make a spredsheet", "sheet"),
    ("make a presention on dogs", "deck"),
    ("make a presentaton on dogs", "deck"),
    ("make a slide about dogs", "deck"),
    ("make a title slide for my talk", "deck"),
    ("write the outline, then make the slides", "deck"),
    ("write the report and then build a spreadsheet of the costs", "sheet"),
    ("explain k3s, then make a deck about it", "deck"),
    ("set up a slideshow for the standup", "deck"),
    ("whip me up a presentation", "deck"),
    ("I need to make a deck", "deck"),
    ("can you help me make a slideshow", "deck"),
    ("make this into slides", "deck"),
    ("write a report as a pdf", "pdf"),
    ("presentation on k3s", "deck"),
    ("pptx please", "deck"),
    ("a pdf of the onboarding checklist", "pdf"),
    ("hazme una presentacion", "deck"),
    ("hazme una presentación sobre el cambio climático", "deck"),
    ("fais-moi un diaporama sur les chats", "deck"),
    ("erstelle eine Präsentation über Katzen", "deck"),
    ("crea una hoja de cálculo de gastos", "sheet"),
    ("做一个关于猫的幻灯片", "deck"),
    ("写一份关于网络安全的报告", "doc"),
    ("帮我做一个ppt", "deck"),
    ("make a deck on the pool party", "deck"),
    ("make slides on the pool safety rules", "deck"),
    ("build a deck on my house renovation", "deck"),
    ("make a deck for our home buyers", "deck"),
    ("make me a python cheat sheet", "doc"),
    ("write a python guide", "doc"),
    ("I need to present on climate change tomorrow", "deck"),
    ("get me a pdf of the notes", "pdf"),
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
    "build a deck for my house",
    "build a deck for my backyard",
    "make a patio deck",
    "make a deck of cards",
    "shuffle a deck of cards",
    "give me an outline of the french revolution",
    "draft an outline",
    "make an outline for my presentation",
    "write a python script that makes a pdf",
    "write a function that parses a pdf",
    "write a javascript function that builds a deck",
    "create a pdf parser in rust",
    "how do I make slides in google",
    "a slide on the playground",
    "slide on over here",
    "pdf reader for linux",
    "excel in college",
    "csv or xlsx for this?",
    "is the presentation ready",
    "slides are blurry when i export",
    "i need to finish my report",
    "i want to know how to make a pdf",
    "cómo hago una presentación",
    "how do I make a presentation in powerpoint",
    "explica la diferencia entre un pdf y un docx",
    "crea un script que genere un pdf",
    "怎么做ppt",
    # a request to do something with a file that exists, in another language
    "帮我总结一下这份报告",
    "请把这个pdf翻译成中文",
    "帮我打开这个pdf",
    "给我解释一下这个表格",
    "我想要学习excel",
    "请问ppt",
    "帮我检查简历",
    "fais un resume de ce pdf",
    "haz que el pdf sea mas pequeno",
    "mach das pdf kleiner",
    "haz una pregunta sobre el excel",
    "quiero hacer mi tarea sobre el pdf",
    # software that happens to name a format
    "write a javascript slideshow",
    "build a javascript slideshow for my website",
    "write a bash pdf merger",
    "make a typescript excel exporter",
    "create a python excel automation",
    "build a python spreadsheet",
    "write a sql spreadsheet importer",
    # presenting is logistics, advice or a question, not a request for a deck
    "I have to present on zoom tomorrow, how do I share my screen",
    "I'm presenting on Friday and I'm nervous, any tips for calming down?",
    "I need to present on Monday, how should I prepare?",
    "we're presenting on stage at 3",
    # a file that exists, with something to do to it
    "I'm trying to make a pdf smaller",
    "I'm trying to make a pdf searchable",
    "I gotta get the slides printed",
    "can I get the report by friday",
    "get me the report from yesterday",
    "I've got to have the slides done by tomorrow",
    "",
])
def test_questions_and_code_requests_are_left_alone(text):
    assert detect_doc_kind(text) is None


def test_a_named_format_beats_a_generic_document_in_a_multi_clause_request():
    assert detect_doc_kind("write the outline, then make the slides") == "deck"
    assert detect_doc_kind("make the slides, then write a report") == "deck"
    assert detect_doc_kind("write a report, then make a memo") == "doc"


def test_a_bare_format_noun_needs_a_short_message_and_a_subject_word_next():
    assert detect_doc_kind("deck on k3s") == "deck"
    assert detect_doc_kind("a deck " + "about the history of everything " * 5) is None
    assert detect_doc_kind("pdf reader") is None
    assert detect_doc_kind("slides on k3s?") is None


def test_a_foreign_request_needs_the_file_to_be_the_direct_object():
    assert detect_doc_kind("hazme una presentacion corta") == "deck"
    assert detect_doc_kind("hazme 10 diapositivas sobre gatos") == "deck"
    assert detect_doc_kind("erstelle mir eine Präsentation über Katzen") == "deck"
    assert detect_doc_kind("hazme una pregunta sobre la presentacion") is None
    assert detect_doc_kind("mach mir ein pdf") == "pdf"
    assert detect_doc_kind("mach dieses pdf kleiner") is None
    assert detect_doc_kind("帮我做一份简短的报告") == "doc"
    assert detect_doc_kind("请做一个关于猫的ppt") == "deck"


def test_a_language_name_vetoes_a_software_phrase_unless_a_document_noun_ends_it():
    assert detect_doc_kind("make me a docker cheat sheet") == "doc"
    assert detect_doc_kind("write a bash handout") == "doc"
    assert detect_doc_kind("make a python slideshow") is None
    assert detect_doc_kind("make a deck about python") == "deck"
    assert detect_doc_kind("a slide deck on docker") == "deck"


def test_presenting_logistics_stay_chat_even_with_a_document_already_in_the_chat():
    prior_deck = "Here.\n\n````harvis-doc\n---\nkind: deck\ntitle: Fire Drill\n---\n# Fire Drill\n````\n"

    for text in ("I'm presenting on Friday, any tips?", "I need to present on Monday",
                 "I'm presenting on zoom at 3"):
        body = {"messages": [{"role": "user", "content": "make a deck"},
                             {"role": "assistant", "content": prior_deck},
                             {"role": "user", "content": text}]}
        assert detect_doc_kind(text) is None
        assert maybe_prepare_doc_turn(body) is None


def test_a_definite_file_after_a_get_or_want_lead_is_not_a_make_request_but_make_still_is():
    assert detect_doc_kind("can I get a pdf of this") == "pdf"
    assert detect_doc_kind("I need a resume") == "doc"
    assert detect_doc_kind("give me the pdf") == "pdf"
    assert detect_doc_kind("make the slides") == "deck"
    assert detect_doc_kind("get me the slides") is None
    assert detect_doc_kind("I'm trying to make a deck") == "deck"


def test_typos_and_phrases_are_rewritten_to_the_words_the_detector_knows():
    from owui_compat import doc_words

    assert doc_words.normalize("A SILDESHOW and a Power Point") == "a slideshow and a powerpoint"
    assert doc_words.normalize("make a slide-show") == "make a slideshow"
    assert doc_words.normalize("a python cheat sheet") == "a python handout"
    for typo, word in doc_words.TYPOS.items():
        assert doc_words.normalize(f"make a {typo}") == f"make a {word}"


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


@pytest.mark.parametrize("text", [
    "slides on monday",
    "presentation on monday",
    "powerpoint on mac",
    "powerpoint on my phone",
    "slides on friday",
    "a pdf from my professor",
    "csv from the server",
    "deck of the ship",
    "presentation on windows",
])
def test_a_bare_format_noun_followed_by_logistics_is_conversation_not_a_request(text):
    assert detect_doc_kind(text) is None


@pytest.mark.parametrize("text,kind", [
    ("pdf", "pdf"), ("slides please", "deck"), ("slides on dogs", "deck"), ("a deck on k3s", "deck"),
    ("presentation on linux kernel scheduling", "deck"), ("pdf from this", "pdf"),
    ("a slide deck of the roadmap", "deck"), ("a pdf of the onboarding checklist", "pdf"),
])
def test_the_logistics_rule_keeps_real_bare_requests(text, kind):
    assert detect_doc_kind(text) == kind


@pytest.mark.parametrize("text,kind", [
    ("presentation on 1st amendment rights", "deck"), ("slides on 3rd grade fractions", "deck"),
    ("pdf on 2nd world war", "pdf"), ("slides on sat prep", "deck"), ("slides on sun safety", "deck"),
    ("slides on wed design", "deck"), ("slides on junit 5", "deck"), ("deck on mars 2 rover", "deck"),
    ("presentation on decision 2", "deck"), ("presentation on sunday school lessons", "deck"),
    ("slides on monday motivation habits", "deck"), ("presentation on tomorrow's technology", "deck"),
    ("deck of 10 slides on climate change", "deck"), ("deck of slides on climate change", "deck"),
])
def test_a_day_or_date_word_that_starts_a_topic_does_not_veto_a_bare_request(text, kind):
    assert detect_doc_kind(text) == kind


@pytest.mark.parametrize("text", [
    "slides on monday morning", "slides on friday at 9", "slides on monday at 9 30am", "slides on sat",
    "presentation on may 3rd", "powerpoint on tomorrow", "slides on 3pm", "pdf on october 7",
    "deck of the boat",
])
def test_a_day_date_or_time_that_is_the_whole_tail_is_still_logistics(text):
    assert detect_doc_kind(text) is None


LONE_DOC = ("Here is the report.\n\n````harvis-doc\n---\nkind: doc\ntitle: Fire Drill\n---\n# Fire Drill\n"
            "Short body.\n````")


def _chat_with_doc(follow_up, extra=()):
    return {"messages": [
        {"role": "user", "content": "write a report about the fire drill"},
        {"role": "assistant", "content": LONE_DOC},
        *extra,
        {"role": "user", "content": follow_up},
    ]}


@pytest.mark.parametrize("text,kind", [("pdf", "pdf"), ("slides", "deck"), ("slideshow", "deck"), ("a pdf please", "pdf")])
def test_a_lone_format_word_after_a_document_converts_it_instead_of_starting_a_new_one(text, kind):
    body = _chat_with_doc(text)
    assert maybe_prepare_doc_turn(body) == kind
    note = next(m["content"] for m in body["messages"] if m["role"] == "system")
    assert "CONVERSION" in note


def test_a_lone_format_word_with_no_document_is_still_a_new_document():
    body = {"messages": [{"role": "user", "content": "pdf"}]}
    assert maybe_prepare_doc_turn(body) == "pdf"
    assert not any("CONVERSION" in m["content"] for m in body["messages"] if m["role"] == "system")


def test_a_format_word_with_a_topic_after_a_document_is_a_new_document():
    body = _chat_with_doc("slides on dogs")
    assert maybe_prepare_doc_turn(body) == "deck"
    assert not any("CONVERSION" in m["content"] for m in body["messages"] if m["role"] == "system")


def test_a_lone_format_word_after_unrelated_answers_is_not_read_as_a_conversion():
    extra = [{"role": "user", "content": "what is a haiku?"},
             {"role": "assistant", "content": "A haiku is a short three-line poem."}]
    body = _chat_with_doc("pdf", extra=extra)
    assert maybe_prepare_doc_turn(body) == "pdf"
    assert not any("CONVERSION" in m["content"] for m in body["messages"] if m["role"] == "system")


@pytest.mark.parametrize("text", [
    "give me that as a list instead of a deck",
    "turn this into a list rather than a deck",
    "convert it to a table, not a deck",
    "make it a list, not slides",
    "convert it into a table, not into a deck",
])
def test_a_format_the_user_turned_down_is_not_the_conversion_target(text):
    from owui_compat.doc_revision import conversion_target

    assert conversion_target(text) is None
    # It may still be read as an edit of the document, but never as a conversion to the deck.
    assert maybe_prepare_doc_turn(_chat_with_doc(text)) != "deck"


def test_the_accepted_format_wins_over_the_one_turned_down():
    from owui_compat.doc_revision import conversion_target

    assert conversion_target("make it a pdf instead of a deck") == "pdf"
    assert conversion_target("turn it into a deck") == "deck"
    assert detect_doc_kind("make a pdf not a deck") == "pdf"
