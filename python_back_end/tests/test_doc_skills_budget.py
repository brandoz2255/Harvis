"""The doc skills carry design guidance, and that guidance stays inside what a small model can hold.

A 4B model at num_ctx 8192 loses grammar rules when the prompt grows, so each prompt has a fixed character budget
(the length it had before the Design sections were written, plus 1,200) and each SKILL.md stays under 100 lines.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import doc_bridge  # noqa: E402
from owui_compat.doc_bridge import DOC_PROMPT_MARKER, KINDS, doc_system_prompt, maybe_prepare_doc_turn  # noqa: E402
from owui_compat.doc_revision import MAX_NOTE_TITLE, PriorDoc, revision_note  # noqa: E402
from plugins.hermes_ui.docs_theme import THEME_NAMES  # noqa: E402

SKILLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "owui_compat", "doc_skills")

# len(doc_system_prompt(kind)) before the Design sections existed.
BASELINE = {"deck": 2398, "doc": 2212, "pdf": 2199, "sheet": 1827}
HEADROOM = 1200
MAX_SKILL_LINES = 100
MAX_DESIGN_LINES = 12
PROMPT_CAP = 3500  # the same ceiling tests/test_doc_revision.py holds revision prompts to


def _skill_text(kind):
    with open(os.path.join(SKILLS, kind, "SKILL.md"), encoding="utf-8") as fh:
        return fh.read()


def _design_lines(kind):
    """The lines of the 'Design' section: from its heading to the next blank line."""
    lines = _skill_text(kind).splitlines()
    start = lines.index("Design")
    end = next((i for i in range(start + 1, len(lines)) if not lines[i].strip()), len(lines))
    return lines[start:end]


def test_the_budget_table_covers_every_kind():
    assert set(BASELINE) == set(KINDS)


@pytest.mark.parametrize("kind", KINDS)
def test_a_skill_file_is_under_100_lines(kind):
    assert len(_skill_text(kind).splitlines()) < MAX_SKILL_LINES


@pytest.mark.parametrize("kind", KINDS)
def test_a_prompt_stays_within_its_budget(kind):
    assert len(doc_system_prompt(kind)) <= BASELINE[kind] + HEADROOM


@pytest.mark.parametrize("kind", KINDS)
def test_every_skill_has_a_short_design_section(kind):
    section = _design_lines(kind)
    assert 3 <= len(section) <= MAX_DESIGN_LINES
    assert "Design" in doc_system_prompt(kind)


@pytest.mark.parametrize("kind", KINDS)
def test_the_grammar_lines_survive_the_design_text(kind):
    prompt = doc_system_prompt(kind)
    assert DOC_PROMPT_MARKER in prompt
    assert "````harvis-doc" in prompt and "\n````\n" in prompt
    assert f"kind: {kind}" in prompt and "outline:" in prompt
    assert "<body>" in prompt and "Gotchas" in prompt and "Rules" in prompt
    assert prompt.rstrip().endswith("outside the block.")
    assert "No second block" in prompt
    # The design text comes after the example and the rules, so the grammar is read first.
    assert prompt.index("Rules") < prompt.index("Design")


def test_deck_guidance_covers_takeaways_length_variety_and_next_steps():
    design = "\n".join(_design_lines("deck"))
    assert "takeaway" in design
    assert "25 words" in design
    assert "two bullet-only slides in a row" in design
    for layout in ("cards", "chart", "timeline", "quadrant"):
        assert layout in design
    assert "next-steps" in design


def test_sheet_guidance_covers_units_assumptions_and_one_table():
    design = "\n".join(_design_lines("sheet"))
    assert "units" in design and "headers" in design
    assert "assumption" in design and "$B$" in design
    assert "One table per sheet" in design


@pytest.mark.parametrize("kind", ("doc", "pdf"))
def test_document_guidance_is_a_summary_first_then_real_headings(kind):
    design = "\n".join(_design_lines(kind))
    assert "Summary" in design
    assert "real heading" in design


@pytest.mark.parametrize("kind", ("deck", "doc", "pdf"))
def test_the_theme_line_names_every_preset(kind):
    design = "\n".join(_design_lines(kind))
    assert "theme:" in design
    for name in THEME_NAMES:
        assert name in design


def test_a_sheet_does_not_advertise_themes():
    assert "theme:" not in _skill_text("sheet")


@pytest.mark.parametrize("kind", KINDS)
def test_the_design_section_does_not_break_the_example_block(kind):
    """The one four-backtick block in the prompt is still the example, and the design text adds no second one."""
    prompt = doc_system_prompt(kind)
    assert len(re.findall(r"^````harvis-doc$", prompt, re.M)) == 1


def test_the_budget_is_measured_on_the_real_prompt_not_a_cached_copy(monkeypatch):
    monkeypatch.setattr(doc_bridge, "_skill_cache", {})
    for kind in KINDS:
        assert len(doc_system_prompt(kind)) <= BASELINE[kind] + HEADROOM


def _worst_revision_prompt(kind):
    """The longest prompt a revision or conversion into this kind can produce, over every prior kind and title length."""
    longest = 0
    for prior_kind in KINDS:
        for mode in ("revise", "convert"):
            if mode == "convert" and prior_kind == kind:
                continue
            for n in (0, 40, 100, MAX_NOTE_TITLE - 6, MAX_NOTE_TITLE - 1, MAX_NOTE_TITLE, MAX_NOTE_TITLE + 1):
                prior = PriorDoc(0, 0, 0, prior_kind, "T" * n, "")
                note = revision_note(mode, prior, kind, cut=True)
                longest = max(longest, len(doc_system_prompt(kind, note)))
    return longest


@pytest.mark.parametrize("kind", KINDS)
def test_the_worst_case_revision_prompt_stays_under_the_small_model_cap(kind):
    """The revision note quotes the title twice, so a long title is where the 3,500 cap in test_doc_revision breaks."""
    assert _worst_revision_prompt(kind) <= PROMPT_CAP


def test_a_long_titled_deck_revision_through_the_real_entry_point_stays_under_the_cap():
    title = "Q3 Security Review: " + "Findings and Next Steps " * 4
    title = title[:MAX_NOTE_TITLE].strip()
    doc = f"Here.\n\n````harvis-doc\n---\nkind: deck\ntitle: {title}\noutline:\n  - Title\n---\n# {title}\nSub\n````\n"
    body = {"messages": [
        {"role": "user", "content": "make a deck about the review"},
        {"role": "assistant", "content": doc},
        {"role": "user", "content": "make it shorter"},
    ]}
    assert maybe_prepare_doc_turn(body)
    system = [m["content"] for m in body["messages"] if m["role"] == "system"]
    assert system and len(system[0]) <= PROMPT_CAP
