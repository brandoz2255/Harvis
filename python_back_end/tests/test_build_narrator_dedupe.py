"""`_dedupe` must never reshape fenced content.

The user asked for an ASCII tree, watched it stream in with its shape intact, and read
it back left-aligned with lines missing. The stream is the model's own text; the
transcript goes through here, where two rules were quietly destructive to anything
whitespace-significant: `[ \\t]+ → " "` flattened every indent, and "the same line twice
in a row is a repeat" deleted real rows of a drawing.
"""

from __future__ import annotations

from workspace.build_narrator import _dedupe, compose_build_analysis

TREE = "\n".join([
    "```text",
    "       /\\",
    "      /**\\",
    "     /****\\",
    "    /******\\",
    "      ||",
    "      ||",
    "  ____||____",
    " /__________\\",
    "```",
])


def test_fenced_indentation_survives():
    out = _dedupe("Here is your tree:\n\n" + TREE)
    for line in TREE.split("\n"):
        assert line in out, f"lost: {line!r}"


def test_fenced_repeated_lines_survive():
    """`      ||` twice in a row is the trunk, not an engine stutter."""
    assert _dedupe(TREE).count("      ||") == 2


def test_prose_still_collapses_and_dedupes():
    assert _dedupe("Done.   Done.") == "Done."
    assert _dedupe("a\na\nb") == "a\nb"
    assert _dedupe("ragged     spacing here") == "ragged spacing here"


def test_whole_string_double_still_folds():
    body = "The build finished and every test passed cleanly."
    assert _dedupe(body + " " + body) == body


def test_unterminated_fence_is_preserved():
    """A streaming tail has no closing fence yet — do not mangle it mid-flight."""
    partial = "Here:\n```text\n       /\\\n      /**\\"
    out = _dedupe(partial)
    assert "       /\\" in out and "      /**\\" in out


def test_tilde_fences_too():
    out = _dedupe("~~~\n    indented\n    indented\n~~~")
    assert out.count("    indented") == 2


def test_narrator_end_to_end_keeps_the_drawing():
    out = compose_build_analysis(
        task_brief="make an ascii tree in a text block",
        engine_label="Harvis Agent",
        raw_summary="Here's your ASCII tree:\n\n" + TREE,
        changed_files=[],
        file_count=0,
    )
    assert "     /****\\" in out
    assert out.count("      ||") == 2
