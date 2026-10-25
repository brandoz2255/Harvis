"""Themes: the same palette and fonts reach the pptx theme XML, the PDF css and the docx styles."""

import io
import os
import re
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docx import Document  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches  # noqa: E402

from plugins.hermes_ui import docs_pdf  # noqa: E402
from plugins.hermes_ui.docs_chips import ACCENT, DARK, INK  # noqa: E402
from plugins.hermes_ui.docs_export import to_docx, to_pptx  # noqa: E402
from plugins.hermes_ui.docs_parse import parse_harvis_doc  # noqa: E402
from plugins.hermes_ui.docs_theme import (  # noqa: E402
    DEFAULT_THEME, PRESETS, THEME_NAMES, classify_slide, get_theme, normalize_theme_name)
from plugins.hermes_ui.docs_blocks import parse_blocks  # noqa: E402

DECK_BODY = """# Quarterly Review
Where we are
---
## Part one
---
## Two views
### Before
- Manual steps
- Slow handoffs
### After
- One pipeline
- Same-day releases
---
## Results
**42%**
fewer incidents
**3x**
faster deploys
---
## Plain slide
- A point
- Another point
"""


def deck(theme: str | None = None, body: str = DECK_BODY) -> str:
    line = f"theme: {theme}\n" if theme is not None else ""
    return f"---\nkind: deck\ntitle: Quarterly Review\n{line}---\n{body}"


def _zip_text(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(name).decode("utf-8")


def _theme_xml(pptx: bytes) -> str:
    return _zip_text(pptx, "ppt/theme/theme1.xml")


def test_there_are_at_least_four_presets_and_the_default_is_the_old_palette():
    assert len(THEME_NAMES) >= 4
    assert DEFAULT_THEME.name == "harvis"
    assert (DEFAULT_THEME.ink, DEFAULT_THEME.dark, DEFAULT_THEME.accent) == (INK, DARK, ACCENT)
    for preset in PRESETS.values():
        for value in (preset.ink, preset.ground, preset.dark, preset.accent, preset.card, preset.line):
            assert re.fullmatch(r"[0-9A-F]{6}", value), (preset.name, value)


@pytest.mark.parametrize("raw,name", [("Paper", "paper"), ('"slate"', "slate"), ("ember  # note", "ember"),
                                      ("neon", "harvis"), ("", "harvis"), (None, "harvis")])
def test_theme_names_normalise_and_unknown_names_fall_back(raw, name):
    assert get_theme(raw).name == name


def test_normalize_theme_name():
    assert normalize_theme_name(" 'Paper' ") == "paper"
    assert normalize_theme_name(None) == ""


def test_the_header_theme_is_parsed():
    assert parse_harvis_doc(deck("Paper")).theme == "paper"
    assert parse_harvis_doc(deck()).theme == ""
    assert parse_harvis_doc(deck("neon")).theme == "neon"


@pytest.mark.parametrize("name", THEME_NAMES)
def test_every_preset_exports_a_16x9_deck_with_its_own_colours_and_fonts(name):
    preset = PRESETS[name]
    data = to_pptx(deck(name))
    xml = _theme_xml(data)
    assert f'<a:srgbClr val="{preset.accent}"/>' in xml
    assert f'<a:srgbClr val="{preset.dark}"/>' in xml
    assert re.search(rf'<a:majorFont><a:latin typeface="{re.escape(preset.heading_font)}"', xml)
    assert re.search(rf'<a:minorFont><a:latin typeface="{re.escape(preset.body_font)}"', xml)
    prs = Presentation(io.BytesIO(data))
    assert (prs.slide_width, prs.slide_height) == (Inches(13.333), Inches(7.5))
    for part in (prs.slide_master, *prs.slide_layouts):
        for shape in part.shapes:
            assert shape.left is None or shape.left + shape.width <= prs.slide_width + 10, (name, shape.name)
    assert len(prs.slides) == 5


def test_an_unknown_theme_exports_like_the_default():
    default = to_pptx(deck())
    unknown = to_pptx(deck("no-such-theme"))
    assert _theme_xml(unknown) == _theme_xml(default)


def test_a_deck_with_no_theme_key_has_the_same_structure_as_an_explicit_harvis_one():
    plain = Presentation(io.BytesIO(to_pptx(deck())))
    named = Presentation(io.BytesIO(to_pptx(deck("harvis"))))
    def shape_kinds(prs):
        return [[(s.shape_type, s.has_text_frame and s.text_frame.text) for s in slide.shapes] for slide in prs.slides]
    assert shape_kinds(plain) == shape_kinds(named)
    assert [s.slide_layout.name for s in plain.slides] == [s.slide_layout.name for s in named.slides]


def test_the_stock_thumbnail_is_gone_from_the_pptx_and_docx():
    for data in (to_pptx(deck()), to_docx("---\nkind: doc\ntitle: T\n---\n## A\nx")):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            assert not [n for n in z.namelist() if "thumbnail" in n.lower()]
            assert "thumbnail" not in z.read("_rels/.rels").decode().lower()


def test_slides_use_a_section_a_two_column_and_a_big_number_layout():
    prs = Presentation(io.BytesIO(to_pptx(deck())))
    names = [s.slide_layout.name for s in prs.slides]
    assert len(set(names)) >= 4                       # title, section, columns, stats (title only), content
    texts = [" ".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame) for s in prs.slides]
    assert "Before" in texts[2] and "After" in texts[2]
    assert "42%" in texts[3] and "fewer incidents" in texts[3] and "3x" in texts[3]


def test_a_content_slide_has_no_accent_bar_unless_the_theme_asks():
    assert DEFAULT_THEME.decor is False
    content = Presentation(io.BytesIO(to_pptx(deck()))).slides[4]
    assert not [s for s in content.shapes if s.shape_type == 1 and s.height < Inches(0.1)]   # no auto-shape strip


def test_sparse_slides_get_bigger_text_than_dense_ones():
    from plugins.hermes_ui.docs_theme import body_size
    assert body_size(2, 40) >= 28
    assert body_size(8, 500) <= 22


def test_classify_slide():
    assert classify_slide([], True).kind == "section"
    assert classify_slide(parse_blocks("**42%**\nfewer incidents")).kind == "stats"
    assert classify_slide(parse_blocks("### A\n- x\n### B\n- y")).kind == "columns"
    assert classify_slide(parse_blocks("- one\n- two")).kind == "content"


def _kind(body: str):
    return classify_slide(parse_blocks(body), True, body)


@pytest.mark.parametrize("body", [
    "**$1.2M** raised from **3** investors",
    "**42%** fewer incidents than in **2023**",
    "**2024** was the year we doubled revenue and hired **40** engineers",
])
def test_a_figure_inside_a_sentence_does_not_split_it_into_two_cards(body):
    assert _kind(body).kind == "content"
    assert classify_slide(parse_blocks(body)).kind == "content"       # without the raw body too


def test_each_source_line_with_a_leading_figure_is_its_own_card():
    kind = _kind("**42%** fewer incidents\n**3x** faster deploys\n**$1.2M**\nraised")
    assert kind.kind == "stats"
    assert [("".join(r.text for r in n), "".join(r.text for r in c)) for n, c in kind.groups] == [
        ("42%", "fewer incidents"), ("3x", "faster deploys"), ("$1.2M", "raised")]


def test_a_figure_line_and_its_caption_line_make_one_card():
    kind = _kind("**42%**\nfewer incidents")
    assert kind.kind == "stats" and len(kind.groups) == 1


def test_a_sentence_with_a_mid_line_figure_exports_as_one_content_slide():
    text = deck(body="# T\n---\n## Raise\n**$1.2M** raised from **3** investors\n")
    prs = Presentation(io.BytesIO(to_pptx(text)))
    texts = [s.text_frame.text for s in prs.slides[1].shapes if s.has_text_frame]
    assert any("raised from" in x and "investors" in x for x in texts)
    assert not any(x.strip() == "$1.2M" for x in texts)               # no separate big-number card
    html = docs_pdf.build_html(parse_harvis_doc(text), "T")
    assert 'class="stat"' not in html


def test_the_pdf_deck_uses_the_theme_colours_and_fonts():
    paper = PRESETS["paper"]
    css = docs_pdf._deck_css(paper)
    assert f"#{paper.dark}" in css or f"#{paper.ground}" in css
    assert f"#{paper.accent}" in css
    assert "Georgia" in docs_pdf._heading_font(paper)
    # a light-title theme puts the cover on the ground colour, the harvis one on dark
    assert f"#{DEFAULT_THEME.dark}" in docs_pdf._deck_css(DEFAULT_THEME)
    assert docs_pdf._deck_css(DEFAULT_THEME) != css


def test_the_pdf_of_a_themed_deck_renders():
    data = docs_pdf.build_pdf(parse_harvis_doc(deck("slate")), "Quarterly Review")
    assert data.startswith(b"%PDF")


# ---- docx ---------------------------------------------------------------------------------------------------------

FOUR = "---\nkind: doc\ntitle: Report\n---\n" + "\n".join(f"## Part {i}\nText {i}\n" for i in range(4))
TWO = "---\nkind: doc\ntitle: Report\n---\n## One\nx\n## Two\ny\n"


def test_the_docx_has_a_page_number_field_in_the_footer():
    data = to_docx(TWO)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        footers = [z.read(n).decode() for n in z.namelist() if n.startswith("word/footer")]
    assert footers and any(" PAGE " in f for f in footers)


def test_the_docx_gets_a_table_of_contents_field_from_four_sections_up():
    assert " TOC " in _zip_text(to_docx(FOUR), "word/document.xml")
    assert " TOC " not in _zip_text(to_docx(TWO), "word/document.xml")


def test_a_horizontal_rule_is_a_bordered_paragraph_not_dashes():
    data = to_docx("---\nkind: doc\ntitle: T\n---\n## A\nbefore\n\n---\n\nafter\n")
    xml = _zip_text(data, "word/document.xml")
    assert "<w:pBdr>" in xml and 'w:val="single"' in xml
    texts = [p.text for p in Document(io.BytesIO(data)).paragraphs]
    assert "---" not in texts and not any(set(t) == {"-"} and t for t in texts)


def test_the_docx_theme_reaches_the_theme_part_and_the_heading_style():
    data = to_docx("---\nkind: doc\ntitle: T\ntheme: ember\n---\n## A\nx\n")
    ember = PRESETS["ember"]
    xml = _zip_text(data, "word/theme/theme1.xml")
    assert f'<a:srgbClr val="{ember.accent}"/>' in xml
    assert Document(io.BytesIO(data)).styles["Normal"].font.name == ember.body_font


# ---- polish: links, column size, the rule, big-number labels, closing slides -----------------------------------------

def _link_deck(theme: str) -> str:
    return deck(theme, "# T\n---\n## Links\nsee [the docs](https://example.com) now\n")


@pytest.mark.parametrize("name", THEME_NAMES)
def test_a_link_is_the_same_colour_in_the_pptx_the_pdf_and_the_docx(name):
    theme = PRESETS[name]
    pptx = to_pptx(_link_deck(name))
    assert f'<a:hlink><a:srgbClr val="{theme.accent2}"/></a:hlink>' in _theme_xml(pptx)
    slide = _zip_text(pptx, "ppt/slides/slide2.xml")
    assert re.search(rf'<a:srgbClr val="{theme.accent2}"/>.*?hlinkClick|hlinkClick.*?<a:srgbClr val="{theme.accent2}"/>',
                     slide, re.S)
    assert f"a {{ color: #{theme.accent2};" in docs_pdf.build_html(parse_harvis_doc(_link_deck(name)), "T")
    docx = to_docx(f"---\nkind: doc\ntitle: T\ntheme: {name}\n---\n## A\n[x](https://example.com)\n")
    assert f'<w:color w:val="{theme.accent2}"/><w:u' in _zip_text(docx, "word/document.xml")


def test_two_column_text_starts_at_the_same_size_in_the_pptx_and_the_pdf():
    from plugins.hermes_ui.docs_theme import COLUMN_MAX, COLUMN_MIN, column_size
    sparse = deck(body="# T\n---\n## Two\n### A\n- one\n### B\n- two\n")
    assert column_size(classify_slide(parse_blocks("### A\n- one\n### B\n- two")).groups) == COLUMN_MAX
    html = docs_pdf.build_html(parse_harvis_doc(sparse), "T")
    assert f'class="cols" style="font-size:{COLUMN_MAX}pt"' in html
    pptx = Presentation(io.BytesIO(to_pptx(sparse)))
    sizes = {r.font.size.pt for sh in pptx.slides[1].placeholders if sh.placeholder_format.idx in (1, 2)
             for p in sh.text_frame.paragraphs for r in p.runs}
    assert sizes == {float(COLUMN_MAX)}
    dense = "\n".join(f"- {'word ' * 12}{i}" for i in range(8))
    groups = classify_slide(parse_blocks(f"### A\n{dense}\n### B\n{dense}")).groups
    assert column_size(groups) == COLUMN_MIN


def test_the_docx_rule_uses_the_theme_line_colour():
    for name in ("paper", "slate"):
        data = to_docx(f"---\nkind: doc\ntitle: T\ntheme: {name}\n---\n## A\nbefore\n\n---\n\nafter\n")
        assert f'w:bottom w:val="single" w:sz="6" w:space="1" w:color="{PRESETS[name].line}"' in _zip_text(
            data, "word/document.xml")


@pytest.mark.parametrize("label", ["42%", "$1.2M", "3x", "120", "4.5/5", "1,200", "-3%", "99.9%", "120 ms", "3 weeks", "10K", "2GB", "120ms"])
def test_a_label_that_is_a_figure_makes_a_big_number(label):
    assert _kind(f"**{label}** fewer incidents").kind == "stats"


@pytest.mark.parametrize("body", [
    "**Q3** revenue grew 12% year over year",
    "**Step 1:** Install\n**Step 2:** Configure\n**Step 3:** Run",
    "**FY24** plan is approved",
    "**Phase 2** starts on Monday",
    "**2FA** is now required for every admin account",
    "**3D** printing cut prototype cost in half",
    "**5G** rollout starts in March",
    "**1st** place at the regional finals",
    "**3am** is when the backup job runs",
])
def test_a_label_that_only_contains_a_digit_is_not_a_big_number(body):
    assert _kind(body).kind == "content"


def _closing_deck(last_title: str) -> str:
    return deck(body=f"# T\n---\n## Part one\n---\n## Body\n- x\n---\n## {last_title}\n")


@pytest.mark.parametrize("last", ["Questions?", "Thank you", "Thank you!"])
def test_a_closing_slide_is_the_title_alone_with_no_number_in_the_pptx_and_the_pdf(last):
    prs = Presentation(io.BytesIO(to_pptx(_closing_deck(last))))
    final = prs.slides[-1]
    assert final.slide_layout.name == "Title Only"
    assert [sh.text_frame.text for sh in final.shapes if sh.has_text_frame] == [last]
    html = docs_pdf.build_html(parse_harvis_doc(_closing_deck(last)), "T")
    assert f'<section class="slide closing"><h1>{last}</h1></section>' in html
    assert html.count('class="kicker"') == 1                           # only "Part one" is numbered, and it is 01
    assert 'class="kicker">01<' in html


def test_a_title_ending_in_a_question_mark_is_closing_wherever_it_sits_and_other_empty_slides_stay_dividers():
    assert classify_slide([], True, "", "Why now?", False).kind == "closing"
    assert classify_slide([], True, "", "**Ready?**", False).kind == "closing"
    assert classify_slide([], True, "", "Part two", False).kind == "section"
    assert classify_slide([], True, "", "Part two", True).kind == "closing"
    assert classify_slide([], False, "", "", True).kind == "content"
    text = deck(body="# T\n---\n## Part one\n---\n## Why now?\n---\n## Part two\n---\n## Body\n- x\n")
    names = [s.slide_layout.name for s in Presentation(io.BytesIO(to_pptx(text))).slides]
    assert names == ["Title Slide", "Section Header", "Title Only", "Section Header", "Title and Content"]
    kickers = [sh.text_frame.text for s in Presentation(io.BytesIO(to_pptx(text))).slides for sh in s.shapes
               if sh.has_text_frame and re.fullmatch(r"\d\d", sh.text_frame.text)]
    assert kickers == ["01", "02"]
