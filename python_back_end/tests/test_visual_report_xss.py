"""The research report is served on the app origin: raw HTML in the markdown must not run."""
import pytest

from deep_research.visual_report import _md_to_html


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="fetch(\'/api/me\')">',
        "text <b onmouseover=alert(1)>x</b> text",
        "<div>\n<script>alert(1)</script>\n</div>",
        '<div markdown="1">\n<img src=x onerror=alert(1)>\n</div>',
        "<iframe src=//evil></iframe>",
    ],
)
def test_raw_html_is_escaped(payload):
    out = _md_to_html(payload)
    assert "<script" not in out
    assert "<img" not in out
    assert "<iframe" not in out
    assert "<b onmouseover" not in out


@pytest.mark.parametrize(
    "link",
    [
        "[x](javascript:alert(document.domain))",
        "[x](JaVaScRiPt:alert(1))",
        "[x](java&#x09;script:alert(1))",
        "[x](data:text/html;base64,PHNjcmlwdD4=)",
        "[x](vbscript:msgbox(1))",
        "![x](javascript:alert(1))",
    ],
)
def test_unsafe_url_schemes_are_dropped(link):
    out = _md_to_html(link).lower()
    assert "javascript:" not in out
    assert "vbscript:" not in out
    assert "data:text" not in out
    assert "java&#" not in out


def test_normal_markdown_still_renders():
    out = _md_to_html(
        "## Heading\n\nSee [docs](https://example.com/a?b=1) and https://example.org/x and "
        "[mail](mailto:a@b.co), [top](#heading).\n\n```python\nprint('<hi>')\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n"
    )
    assert '<h2 id="heading">Heading</h2>' in out
    assert 'target="_blank" rel="noopener noreferrer" href="https://example.com/a?b=1"' in out
    assert 'href="https://example.org/x"' in out
    assert 'href="mailto:a@b.co"' in out
    assert 'href="#heading"' in out
    assert "<table>" in out
    assert "&lt;hi&gt;" in out


# --- attr_list: python-markdown "extra" let markdown set ANY attribute -------------

ATTR_LIST_PAYLOADS = [
    "![c](https://nonexistent.invalid/x.png){: onerror=\"fetch('/api/auth/me?PWNED')\" }",
    "![c](https://nonexistent.invalid/x.png){: onerror=PWNED }",
    "## Heading {: onclick=PWNED }",
    "Para text\n{: onclick=PWNED style=\"background:url(PWNED)\" }",
    "[x](https://example.com){: onmouseover=PWNED formaction=PWNED }",
    "[x](https://example.com){: formaction=javascript:PWNED }",
    "![x](https://a.invalid/x.png){: srcset=\"javascript:PWNED 1x\" }",
    "![x](https://a.invalid/x.png){: style=\"x:PWNED\" onload=PWNED }",
    "| a | b |\n|---|---|\n| 1 | 2 |\n{: onclick=PWNED }",
    "```python {: onclick=PWNED }\nx=1\n```",
    "term\n:   definition {: onclick=PWNED }",
]


def _tags_carrying_marker(page_html):
    from bs4 import BeautifulSoup

    bad = []
    for tag in BeautifulSoup(page_html, "html.parser").find_all(True):
        if tag.name == "meta":  # og/description text is escaped text, not markup
            continue
        for name, value in tag.attrs.items():
            text = " ".join(value) if isinstance(value, list) else str(value)
            if "PWNED" in text:
                bad.append((tag.name, name, text))
    return bad


@pytest.mark.parametrize("payload", ATTR_LIST_PAYLOADS)
def test_attr_list_cannot_set_attributes_md_to_html(payload):
    assert _tags_carrying_marker(_md_to_html(payload)) == []


@pytest.mark.parametrize("payload", ATTR_LIST_PAYLOADS)
def test_attr_list_cannot_set_attributes_end_to_end(payload):
    from deep_research.visual_report import generate_visual_report

    page = generate_visual_report(
        "q", "# Title\n\n## Intro\n\n" + payload + "\n\n## Next\n\nbody\n", sources=[]
    )
    assert _tags_carrying_marker(page) == []


def test_sanitizer_strips_event_handlers_even_if_extension_returns():
    from deep_research.visual_report import _sanitize_report_html

    out = _sanitize_report_html(
        '<img src="https://a/x.png" onerror="PWNED" srcset="PWNED" style="PWNED" alt="k">'
        '<h2 onclick="PWNED" id="h">t</h2><p style="x" class="c">p</p>'
        '<a href="https://a" formaction="PWNED" onmouseover="PWNED" title="t">l</a>'
        "<script>PWNED</script><iframe src=\"https://a\"></iframe>"
        '<td colspan="2" onclick="PWNED">c</td>'
    )
    assert "PWNED" not in out
    assert 'alt="k"' in out and 'id="h"' in out and 'class="c"' in out
    assert 'colspan="2"' in out and 'href="https://a"' in out and 'title="t"' in out
    assert "<script" not in out and "<iframe" not in out


def test_sources_list_drops_non_http_urls():
    from deep_research.visual_report import generate_visual_report

    page = generate_visual_report(
        "q",
        "# T\n\n## A\n\nbody\n",
        sources=[
            {"url": "javascript:alert(1)", "title": "bad"},
            {"url": "https://ok.example/a", "title": "good"},
        ],
    )
    assert "javascript:" not in page.lower()
    assert 'href="https://ok.example/a"' in page
