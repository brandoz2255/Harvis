"""Source markers in a model answer become numbered citations that each carry a quote."""
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks.citations import resolve_citations, snippet  # noqa: E402
from notebooks.rag_chat import RAGChatService  # noqa: E402


def chunks(n=3):
    return [
        SimpleNamespace(
            source_title=f"Doc {i}",
            score=0.9,
            chunk=SimpleNamespace(
                id=uuid4(), source_id=uuid4(), content=f"Passage {i} says something useful. " * 20, metadata={"paragraphs": [i]}
            ),
        )
        for i in range(1, n + 1)
    ]


@pytest.mark.parametrize(
    "marker",
    [
        "[SOURCE 2]",
        "[Source 2]",
        "[SOURCE 2, Para 3]",
        "[SOURCE 2: Para 3]",
        "[SOURCE 2, page 4]",
        "[S2]",
        "[2]",
        "【SOURCE 2】",
        "SOURCE 2",
        "[SOURCE: 2]",
    ],
)
def test_every_marker_form_resolves_to_chunk_two(marker):
    cs = chunks()
    text, cited, explicit = resolve_citations(f"The cell makes energy {marker}.", cs)
    assert explicit and cited == [cs[1]]
    assert text == "The cell makes energy [1]."


def test_markers_are_numbered_by_first_mention_and_repeats_share_a_number():
    cs = chunks()
    text, cited, _ = resolve_citations("A [SOURCE 3]. B [SOURCE 1]. C [SOURCE 3, Para 2].", cs)
    assert text == "A [1]. B [2]. C [1]."
    assert cited == [cs[2], cs[0]]


def test_several_sources_in_one_bracket():
    cs = chunks()
    text, cited, _ = resolve_citations("Both agree [SOURCE 1, SOURCE 2].", cs)
    assert text == "Both agree [1][2]." and cited == [cs[0], cs[1]]


def test_title_form_maps_to_the_source():
    cs = chunks()
    text, cited, _ = resolve_citations("As said [Source: Doc 3, Para 2].", cs)
    assert text == "As said [1]." and cited == [cs[2]]


def test_marker_outside_the_context_is_dropped_not_left_dangling():
    cs = chunks(2)
    text, cited, explicit = resolve_citations("Claim [SOURCE 9].", cs)
    assert explicit and cited == [] and "9" not in text


def test_ordinary_brackets_are_left_alone():
    text, cited, explicit = resolve_citations("Use list[int] and [see below] and [text](http://x).", chunks())
    assert text.startswith("Use list[int] and [see below]") and cited == [] and not explicit


def test_snippet_is_one_line_cut_at_a_word():
    s = snippet("alpha  beta\n\ngamma " * 40)
    assert "\n" not in s and s.endswith("…") and len(s) <= 241


def test_citations_always_carry_a_quote():
    svc = RAGChatService.__new__(RAGChatService)
    cs = chunks()
    text, cites = svc._resolve_answer("Yes [SOURCE 1, Para 2] and [SOURCE 3].", cs)
    assert [c.quote for c in cites] and all(c.quote and c.quote.startswith("Passage") for c in cites)
    assert text == "Yes [1] and [2]."


def test_uncited_answer_falls_back_to_top_passages_with_quotes():
    svc = RAGChatService.__new__(RAGChatService)
    text, cites = svc._resolve_answer("An answer with no markers.", chunks())
    assert len(cites) == 3 and all(c.quote for c in cites)
