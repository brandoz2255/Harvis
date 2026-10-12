"""Quiz, flashcards and mind map: tolerant parsing, one retry, a plain error at the end."""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from onb_compat import studio_generate as sg  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_fences_think_blocks_and_prose_are_stripped():
    raw = '<think>hmm</think>Here you go:\n```json\n{"cards": [{"front": "a", "back": "b"}]}\n```'
    assert sg.parse_json_lenient(raw) == {"cards": [{"front": "a", "back": "b"}]}


def test_truncated_output_keeps_the_complete_items():
    raw = '{"cards": [{"front": "a", "back": "b"}, {"front": "c", "back": "d"}, {"front": "e", "ba'
    data = sg.parse_json_lenient(raw)
    assert [c["front"] for c in data["cards"]] == ["a", "c"]


def test_truncated_quiz_in_the_middle_of_a_string():
    raw = '{"questions": [{"q": "One?", "options": ["a", "b"], "answer": 1, "explanation": "x"}, {"q": "Two?", "options": ["a'
    assert len(sg._normalize_quiz(sg.parse_json_lenient(raw))) == 1


@pytest.mark.parametrize("raw", ["", "no json at all", "{"])
def test_garbage_parses_to_nothing_not_an_exception(raw):
    assert not sg.parse_json_lenient(raw)


def test_bare_list_is_accepted_for_cards():
    title, shaped = sg._shape("flashcards", sg.parse_json_lenient('[{"term": "t", "definition": "d"}]'))
    assert shaped["cards"] == [{"front": "t", "back": "d"}] and "1 cards" in title


def test_mindmap_is_normalised_capped_and_titled():
    data = {
        "title": "Cells",
        "branches": [{"label": "Organelles", "children": [{"label": "Nucleus", "children": [{"label": "DNA"}]}, "Ribosome"]}, {"label": ""}],
    }
    tree = sg._normalize_mindmap(data)
    assert tree["title"] == "Cells"
    assert tree["children"][0]["children"][1] == {"label": "Ribosome", "children": []}
    assert tree["children"][0]["children"][0]["children"][0]["label"] == "DNA"
    assert len(tree["children"]) == 1  # the empty label is dropped


def test_mindmap_node_budget_is_enforced():
    big = {"title": "T", "children": [{"label": f"b{i}", "children": [{"label": f"c{i}{j}"} for j in range(10)]} for i in range(20)]}

    def count(n):
        return 1 + sum(count(c) for c in n["children"])

    tree = sg._normalize_mindmap(big)
    assert sum(count(c) for c in tree["children"]) <= sg.MAX_MAP_NODES


def test_mindmap_without_branches_is_unusable():
    assert sg._normalize_mindmap({"title": "T", "children": []}) == {}


def test_generate_retries_once_then_succeeds(monkeypatch):
    replies = ["I cannot do that.", json.dumps({"title": "T", "children": [{"label": "A"}]})]
    seen = []

    async def fake_ask(prompt, schema, model, url, temperature):
        seen.append(temperature)
        return replies.pop(0)

    monkeypatch.setattr(sg, "_ask", fake_ask)
    title, content = run(sg.generate_structured("mindmap", "some source", "gemma3:4b", "http://x"))
    assert content["tree"]["children"][0]["label"] == "A" and len(seen) == 2 and seen[1] > seen[0]


def test_generate_gives_a_plain_error_after_two_misses(monkeypatch):
    async def fake_ask(*a, **k):
        return "{}"

    monkeypatch.setattr(sg, "_ask", fake_ask)
    with pytest.raises(sg.StudioError) as err:
        run(sg.generate_structured("quiz", "some source", "tiny:1b", "http://x"))
    assert "tiny:1b" in str(err.value) and "quiz" in str(err.value)


def test_quiz_options_and_answer_are_coerced():
    q = sg._normalize_quiz({"questions": [{"question": "Q?", "A": "x", "B": "y", "C": "z", "answer": "B", "rationale": "because"}]})
    assert q == [{"q": "Q?", "options": ["x", "y", "z"], "answer": 1, "explanation": "because"}]
