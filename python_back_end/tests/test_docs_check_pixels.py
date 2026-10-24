"""Pixel checks on page images: blank pages, hard-to-read text and content at the page edge, on synthetic PNGs."""

import base64
import io
import os
import sys

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import docs_check_pixels as px, docs_preview, rest_docs  # noqa: E402
from plugins.hermes_ui.docs_check import page_label  # noqa: E402
from tests.test_docs_preview import BASE, DECK, client, who  # noqa: E402,F401 - client and who are fixtures

W, H = 800, 450
LABEL = page_label("pptx")


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def page(bars=(), *, bg="white", color="black", size=(W, H)) -> bytes:
    """A page with a bar of ``color`` for each (x0, y0, x1, y1): a line of text as far as the checks can tell."""
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    for box in bars:
        draw.rectangle(box, fill=color)
    return png(img)


def text_block(color="black", x0=80, x1=720):
    return [(x0, 60 + 40 * i, x1, 74 + 40 * i) for i in range(8)]


def run(*pages, **kw):
    return px.check_pixels(list(pages), LABEL, **kw)


def said(issues):
    return " | ".join(f"{i['severity']} {i['where']}: {i['message']}" for i in issues)


def test_a_page_of_dark_text_on_white_is_clean():
    assert run(page(text_block())) == []
    stats = px.check_page(page(text_block()))
    assert stats["contrast"] > 10 and stats["touching"] == []


def test_a_light_page_on_a_dark_theme_is_clean():
    assert run(page(text_block(), bg=(15, 23, 42), color=(240, 244, 250))) == []


def test_a_blank_page_is_an_error():
    issues = run(page(), page(text_block()))
    assert [(i["severity"], i["where"]) for i in issues] == [("error", "slide 1")], said(issues)
    assert "blank" in issues[0]["message"]


def test_a_transparent_page_counts_as_blank_paper():
    issues = run(png(Image.new("RGBA", (W, H), (0, 0, 0, 0))))
    assert [i["severity"] for i in issues] == ["error"]


def test_a_nearly_blank_page_is_a_warning_except_a_short_last_page():
    little = page([(100, 100, 140, 106)])
    assert [(i["severity"], i["where"]) for i in run(little)] == [("warn", "slide 1")]
    assert run(page(text_block()), little, last_may_be_short=True) == []
    assert run(little, page(text_block()), last_may_be_short=True)[0]["where"] == "slide 1"
    assert [i["severity"] for i in run(page(), last_may_be_short=True)] == ["error"]


def test_pale_text_on_white_is_a_warning_and_nearly_invisible_text_an_error():
    pale = run(page(text_block(), color=(208, 208, 208)))
    assert [i["severity"] for i in pale] == ["warn"] and "hard to read" in pale[0]["message"], said(pale)
    faint = run(page(text_block(), color=(224, 224, 224)))
    assert [i["severity"] for i in faint] == ["error"], said(faint)


def test_dark_text_on_a_dark_background_is_flagged():
    issues = run(page(text_block(), bg=(30, 30, 30), color=(60, 60, 60)))
    assert issues and "hard to read" in issues[0]["message"], said(issues)


def test_a_soft_tinted_card_behind_dark_text_is_not_low_contrast():
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((60, 40, 740, 410), fill=(226, 232, 240))
    for box in text_block():
        draw.rectangle(box, fill="black")
    assert run(png(img)) == []


def chart_page(label="black", rules=(222, 222, 230)):
    """A chart-like page: pale one-pixel gridlines and axes across it, short labels beside them, two bars."""
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    for y in range(100, 360, 50):
        draw.line((60, y, 740, y), fill=rules)
        draw.rectangle((24, y - 6, 40, y + 6), fill=label)                    # an axis number
    draw.line((60, 100, 60, 350), fill=rules)
    draw.line((740, 100, 740, 350), fill=rules)
    draw.rectangle((140, 160, 220, 350), fill=(20, 160, 150))
    draw.rectangle((220, 260, 300, 350), fill=(50, 110, 220))
    for x in (130, 330, 530):                                                 # a category label under the axis
        for k in range(6):
            draw.rectangle((x + 14 * k, 366, x + 14 * k + 9, 380), fill=label)
    return png(img)


def test_pale_gridlines_do_not_decide_the_contrast_of_the_labels():
    # Measured on the writer's own rendered bar chart: the gridlines made up most of the edge pixels and a page of
    # dark labels on white read as about 1.4 to 1.
    assert run(chart_page()) == []
    assert px.check_page(chart_page())["contrast"] > 10


def test_pale_labels_next_to_gridlines_are_still_flagged():
    issues = run(chart_page(label=(220, 220, 220)))
    assert [i["severity"] for i in issues] == ["error"] and "hard to read" in issues[0]["message"], said(issues)


def test_content_at_the_page_edge_is_a_warning_on_that_side():
    left = run(page([(0, 100, 300, 114)] + text_block()))
    assert len(left) == 1 and left[0]["severity"] == "warn" and "left" in left[0]["message"], said(left)
    bottom = run(page(text_block() + [(100, H - 8, 500, H)]))
    assert len(bottom) == 1 and "bottom" in bottom[0]["message"], said(bottom)


def test_a_flat_colour_that_runs_off_the_page_is_not_content_at_the_edge():
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 30, H), fill=(30, 60, 120))
    for box in text_block():
        draw.rectangle(box, fill="black")
    assert run(png(img)) == []


def test_a_thumbnail_and_a_broken_image_are_skipped():
    assert run(png(Image.new("RGB", (40, 30), "red")), b"not an image", b"") == []


def test_only_the_first_twenty_pages_are_read():
    pages = [page(text_block())] * 20 + [page()]
    assert run(*pages) == []


def test_contrast_ratio_matches_the_standard():
    assert px.contrast_ratio(0, 255) == pytest.approx(21.0, rel=0.01)
    assert px.contrast_ratio(255, 255) == pytest.approx(1.0)
    assert px.contrast_ratio(119, 255) == pytest.approx(4.48, rel=0.02)         # #777 on white


# ---- the check route --------------------------------------------------------------------------

@pytest.fixture()
def sandbox(monkeypatch):
    """A renderer that draws a blank first page and a page of text, at a real page size."""
    async def fake(data, ext, max_pages=20):
        pages = [{"png_b64": base64.b64encode(p).decode(), "width": W, "height": H, "text": t}
                 for p, t in ((page(), "Status deck"), (page(text_block()), "Plan Ship it"))]
        return {"ok": True, "pages": pages, "page_count": 2}

    monkeypatch.setattr(docs_preview, "render_pages", fake)
    docs_preview.cache.clear()
    yield
    docs_preview.cache.clear()


def test_the_check_route_adds_the_pixel_findings_beside_the_text_ones(client, sandbox):
    body = client.post(f"{BASE}/check", json={"source": DECK}).json()
    assert body["checked"]["render"] is True
    blank = [i for i in body["issues"] if "blank" in i["message"]]
    assert [(i["severity"], i["where"]) for i in blank] == [("error", "slide 1")]
    assert body["issues"][0]["severity"] == "error"


def test_a_crash_in_the_pixel_check_never_fails_the_route(client, sandbox, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("pillow fell over")

    monkeypatch.setattr(rest_docs, "check_pixels", boom)
    r = client.post(f"{BASE}/check", json={"source": DECK})
    assert r.status_code == 200 and r.json()["checked"]["render"] is True
