"""Limits of the rich exports: legal shape sizes, slide bounds, control characters, tall figures, huge inputs."""

import os
import re
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import docs_pdf  # noqa: E402
from plugins.hermes_ui.docs_blocks import parse_blocks  # noqa: E402
from plugins.hermes_ui.docs_export import export_doc  # noqa: E402
from plugins.hermes_ui.docs_parse import parse_harvis_doc  # noqa: E402
from plugins.hermes_ui.docs_rich import parse_chart, parse_flow, parse_quadrant, rich_as_rows  # noqa: E402
from plugins.hermes_ui.docs_svg import svg_markup  # noqa: E402
from tests.test_docs_rich import CARDS, QUADRANT, TABLE, TIMELINE, _docx, _inside, _prs, _texts, deck, fence  # noqa: E402


def plain_of(blocks):
    return "".join(r.text for b in blocks for r in b.runs)


def _bullets(n: int) -> str:
    return "\n".join(f"- point {i}" for i in range(n))


GEOMETRY_CASES = {
    "bullets and a quadrant": "## A\n" + _bullets(6) + "\n\n" + fence("quadrant", QUADRANT),
    "bullets and three timelines": "## A\n" + _bullets(6) + "\n\n" + "\n".join([fence("timeline", TIMELINE)] * 3),
    "sixty cards": "## A\n" + fence("cards", "\n".join(f"c{i} | h{i} | detail {i}" for i in range(60))),
    "thirty tables": "## A\n" + "\n\n".join([TABLE] * 30),
    "bullets and cards": "## A\n" + _bullets(5) + "\n\n" + fence("cards", CARDS),
}


@pytest.mark.parametrize("name", GEOMETRY_CASES)
def test_layouts_are_sized_right_without_the_final_clamp(name, monkeypatch):
    """The clamp is a safety net; the layouts themselves must already give every shape a legal size."""
    from plugins.hermes_ui import docs_pptx

    monkeypatch.setattr(docs_pptx, "clamp_to_slide", lambda *_a, **_k: None)
    prs = _prs(deck(GEOMETRY_CASES[name]))
    for slide in prs.slides:
        _inside(prs, slide)


def test_extra_cards_and_figures_become_a_more_line():
    prs = _prs(deck(GEOMETRY_CASES["sixty cards"], GEOMETRY_CASES["thirty tables"]))
    assert "… 48 more" in _texts(prs.slides[1])
    assert "… 27 more not shown" in _texts(prs.slides[2])


def test_control_characters_do_not_break_any_export():
    bad = "a\x01b"
    assert plain_of(parse_blocks(f"hello{bad} `c{bad}` there")) == "helloab cab there"
    pptx = deck(f"## C\n" + fence("chart", f"{bad}: 1\nc: 2") + f"\n- hello{bad}", fence("cards", f"{bad} | x | y"))
    assert len(_prs(pptx).slides) == 3
    doc = f"---\nkind: doc\ntitle: D{bad}\n---\n## S{bad}\nhello{bad} [l{bad}](https://a.example/{bad})\n\n" + fence("cards", f"{bad} | x")
    assert any(p.text == "helloab l" or "helloab" in p.text for p in _docx(doc).paragraphs)
    assert export_doc(doc, "pdf").data.startswith(b"%PDF")


def test_a_flow_back_edge_is_listed_once_in_the_fallback_table():
    f = parse_flow("a -> b -> c -> a")
    assert f.back_edges == [("c", "a")] and f.edges == [("a", "b"), ("b", "c"), ("c", "a")]
    assert rich_as_rows("flow", f) == [["From", "To"], ["a", "b"], ["b", "c"], ["c", "a"]]


def test_a_quadrant_cell_says_how_many_items_were_really_left_out():
    q = parse_quadrant("A: " + ", ".join(f"item{i}" for i in range(20)) + "\nB: x\nC: y\nD: z")
    svg = svg_markup("quadrant", q, 640)
    shown = svg.count("• item")
    assert 0 < shown < 20 and f"… +{20 - shown} more" in svg


def test_a_tall_figure_in_a_document_pdf_is_scaled_to_the_page():
    import pypdfium2

    src = ("---\nkind: doc\ntitle: D\n---\n## S\nIntro.\n\n"
           + fence("timeline", "\n".join(f"ROW{i:02d} | Oct {i + 1} | Oct {i + 2}" for i in range(30))) + "\n\nAFTERMARK")
    html = docs_pdf.build_html(parse_harvis_doc(src), "D")
    assert float(re.search(r'<svg[^>]* height="([\d.]+)"', html).group(1)) <= docs_pdf.DOC_FIT[1]
    pdf = pypdfium2.PdfDocument(export_doc(src, "pdf").data)
    text = "".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    assert all(f"ROW{i:02d}" in text for i in range(30)) and "AFTERMARK" in text


def test_a_long_series_legend_wraps_inside_the_figure():
    names = ", ".join(f"A series with a long name {i}" for i in range(6))
    svg = svg_markup("chart", parse_chart(f"series: {names}\nx: 1, 2, 3, 4, 5, 6"), 640)
    xs = [float(m) for m in re.findall(r'<text x="([\d.]+)"', svg)]
    assert max(xs) <= 640


def test_huge_inputs_export_in_seconds_not_minutes():
    def took(fn) -> float:
        t0 = time.time()
        fn()
        return time.time() - t0

    rows = "\n".join(f"row {i},val {i},Done" for i in range(8000))
    assert took(lambda: export_doc(deck("## D\n" + fence("csv", "a,b,c\n" + rows)), "pptx")) < 15
    assert took(lambda: export_doc(deck("## D\n" + _bullets(8000)), "pptx")) < 15
    assert took(lambda: parse_flow("\n".join(f"n{i} -> n{i + 1}" for i in range(6000)))) < 5
    assert took(lambda: export_doc(f"---\nkind: doc\ntitle: D\n---\n## S\n" + fence("csv", "a,b,c\n" + rows[:20000]), "docx")) < 20
