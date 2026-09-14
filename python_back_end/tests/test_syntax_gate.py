"""The gate that would have caught the dead Asteroids page.

A Build turn wrote an index.html whose <script> opened `(() => {` on line 2 and
never closed it. Every tool call succeeded, the diff was clean, the turn reported
"Done." — and the browser parsed none of it, so the START GAME button only played
its CSS :active animation. Nothing in the stack noticed.

Two properties matter here and they pull against each other:

  * it must FLAG real breakage (the `must_flag` cases), and
  * it must NEVER flag working code (the far longer `must_not_flag` list),

because a false alarm fails a build that works, while a missed defect costs only
what was already lost. Every ambiguity in the checker resolves to silence, and
the `/` cases below are why: in JS a slash is either division or a regex, and a
regex full of braces read as division corrupts the whole scan.
"""

from __future__ import annotations

import pytest

from workspace.orchestration.syntax_gate import (
    check_files,
    check_links,
    check_source,
    missing_refs,
)

# ── Broken. Each of these must produce a defect message. ────────────────────────
MUST_FLAG = [
    ("app.js", "(() => {\n  const x = 1;\n  console.log(x);\n", "unclosed IIFE"),
    ("app.js", "function go() {\n  return 1;\n", "unclosed function"),
    ("app.js", "const a = 1;\n}\n", "stray close"),
    ("app.js", "function f() { if (a) { }\n", "crossed brackets"),
    ("data.json", '{"a": 1,}\n', "trailing comma in JSON"),
    ("run.py", "def f(:\n    pass\n", "bad Python"),
    (
        "index.html",
        "<html><body><script>\n(() => {\n  const s = 1;\n</script></body></html>",
        "unclosed script IIFE",
    ),
]

# ── Working. Each of these must be silent. ──────────────────────────────────────
MUST_NOT_FLAG = [
    ("app.js", "(() => {\n  const x = 1;\n})();\n", "closed IIFE"),
    ("app.js", "const re = /a{1,3}/g;\nconst t = re.test('aa');\n", "regex with braces"),
    ("app.js", "const re = /[{]/g;\nconsole.log(re);\n", "brace inside a class"),
    ("app.js", "function f(a) {\n  return /a{1}/.test(a);\n}\n", "regex after return"),
    ("app.js", 'const q = `"${y.replace(/"/g, \'""\')}"`;\n', "regex inside a template"),
    ("app.js", "const t = `a${`b${c}`}d`;\n", "nested template"),
    ("app.js", "const r = a / b / c;\nconst s = (x) / 2;\n", "division chain"),
    ("app.js", "// it's fine\nconst a = 1;\n", "apostrophe in a comment"),
    ("app.js", "const re = /[\"']/g;\nconst a = 1;\n", "quotes inside a class"),
    (
        "index.html",
        "<html><body><script>\n(() => { const s = 1; })();\n</script></body></html>",
        "good inline script",
    ),
    (
        "index.html",
        '<html><body><script src="game.js"></script></body></html>',
        "external script only",
    ),
    (
        "index.html",
        '<html><body><script type="application/json">{"a": 1}</script></body></html>',
        "JSON in a script tag",
    ),
    ("data.json", '{"a": [1, 2], "b": {"c": null}}\n', "good JSON"),
    ("App.jsx", "export default function App() {\n  return <div>hi</div>;\n}\n", "JSX"),
    ("notes.txt", "{{{ unbalanced but not code\n", "unknown extension"),
]


@pytest.mark.parametrize("rel,src,why", MUST_FLAG, ids=[c[2] for c in MUST_FLAG])
def test_flags_what_cannot_run(rel, src, why):
    assert check_source(rel, src), f"{why}: unparseable source reported clean"


@pytest.mark.parametrize("rel,src,why", MUST_NOT_FLAG, ids=[c[2] for c in MUST_NOT_FLAG])
def test_never_flags_working_code(rel, src, why):
    err = check_source(rel, src)
    assert err is None, f"{why}: working source was flagged — {err}"


def test_the_real_asteroids_failure_names_the_line():
    """The message has to be actionable: which line opened, and never closed."""
    src = "<html><body><script>\n(() => {\n" + "  const x = 1;\n" * 40 + "</script></body></html>"
    err = check_source("index.html", src)
    assert err and "line 2" in err and "never closed" in err, err


def test_check_files_maps_only_the_broken_ones():
    out = check_files({
        "good.js": "const a = 1;\n",
        "bad.js": "function f() {\n",
        "readme.md": "{{{\n",
    })
    assert list(out) == ["bad.js"]


def test_a_checker_that_throws_stays_silent():
    """Never break a build over the checker itself."""
    class Exploding(str):
        def __len__(self):  # exercised by the size guard
            raise RuntimeError("boom")

    assert check_source("app.js", Exploding("const a = 1;")) is None


# ── Dangling local references ──────────────────────────────────────────────────
# The other way to ship a dead page, and the one the multi-file prompt made more
# likely: index.html links styles.css and game.js, both correct, and neither was
# ever written. The browser renders the canvas, 404s the rest in silence, and the
# page does nothing.

_LINKED = (
    '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head>'
    '<body><canvas id="c"></canvas><script src="game.js"></script></body></html>'
)


def test_missing_siblings_are_flagged():
    out = check_links({"index.html": _LINKED}, known={"index.html"})
    assert "styles.css" in out["index.html"] and "game.js" in out["index.html"]


def test_present_siblings_are_silent():
    files = {"index.html": _LINKED, "styles.css": "body{}", "game.js": "const a=1;"}
    assert check_links(files, known=set(files)) == {}


def test_a_file_known_but_not_snapshotted_still_counts_as_written():
    """`known` carries paths whose bodies were too big or too binary to collect.
    Reporting those as missing would fail a build over the collector's own cap."""
    out = check_links({"index.html": _LINKED}, known={"index.html", "styles.css", "game.js"})
    assert out == {}


@pytest.mark.parametrize(
    "ref",
    [
        "https://cdn.example.com/x.js",
        "//cdn.example.com/x.js",
        "data:text/javascript,void%200",
    ],
)
def test_remote_references_are_never_reported(ref):
    """Only local files can be "never written". A CDN URL is someone else's."""
    html = f'<html><body><script src="{ref}"></script></body></html>'
    assert check_links({"index.html": html}, known={"index.html"}) == {}


def test_a_missing_image_is_not_a_defect():
    """A missing <img> degrades a page that still works. Failing a build over one
    is the false alarm this module refuses to raise."""
    html = '<html><body><img src="hero.png"><script>const a=1;</script></body></html>'
    assert check_links({"index.html": html}, known={"index.html"}) == {}


def test_missing_refs_counts_each_target_separately():
    """The repair loop's progress metric. One page short of two files must read as
    TWO defects, or a round that writes one of them looks like no progress at all
    and the loop stops with the page still dead."""
    two = missing_refs({"index.html": _LINKED}, known={"index.html"})
    assert two == {"index.html": ["styles.css", "game.js"]}
    after = missing_refs(
        {"index.html": _LINKED, "styles.css": "body{}"},
        known={"index.html", "styles.css"},
    )
    assert sum(map(len, after.values())) < sum(map(len, two.values()))
