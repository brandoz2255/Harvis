"""Deep research started from a chat message, and followed into the Hermes reply."""
import asyncio

import pytest

from owui_compat import research_bridge as rb
from plugins.hermes_ui import chat, research_follow


@pytest.mark.parametrize(
    "message, query",
    [
        ("/research quantum dot solar cells", "quantum dot solar cells"),
        ("deep research on the history of the Mojave Desert", "the history of the Mojave Desert"),
        ("Can you do a deep research into Kubernetes network policies", "Kubernetes network policies"),
        ("write me a research report on WiFi CSI sensing", "write me a research report on WiFi CSI sensing"),
        ("research lithium supply chains in depth", "research lithium supply chains in depth"),
    ],
)
def test_explicit_asks_start_research(message, query):
    assert rb.research_query(message) == query


@pytest.mark.parametrize(
    "message",
    [
        "what is deep research?",
        "how does deep research work?",
        "I did some research yesterday",
        "summarise this research paper",
        "/research",
        "",
    ],
)
def test_ordinary_chat_is_not_research(message):
    assert rb.research_query(message) is None


def test_prior_run_is_found_in_the_marker_or_the_report_link():
    history = [
        {"role": "user", "content": "deep research solar"},
        {"role": "assistant", "content": 'report … research `rp-0123456789ab`'},
        {"role": "user", "content": "dig deeper into perovskites"},
    ]
    assert rb.prior_research_id(history) == "rp-0123456789ab"
    assert rb.prior_research_id(history[-1:]) is None


def test_follow_up_continues_only_related_or_explicit_asks():
    assert rb.continues("dig deeper into perovskites", "solar cells")
    assert rb.continues("perovskite solar cell efficiency", "perovskite solar cell stability")
    assert not rb.continues("medieval castle architecture", "perovskite solar cell stability")


class _Handler:
    def __init__(self, data):
        self.data = data

    def _get_session_json(self, _sid):
        return self.data


def test_prior_context_hands_over_report_findings_and_urls():
    data = {"owner": "7", "status": "done", "query": "solar cells", "raw_report": "R",
            "raw_findings": [{"f": 1}], "sources": [{"url": "https://a"}, {"url": "https://b"}]}
    prior = rb._prior_context(_Handler(data), "rp-0123456789ab", "7", "expand on solar cells")
    assert prior == {"prior_report": "R", "prior_findings": [{"f": 1}], "prior_urls": {"https://a", "https://b"}}
    # Someone else's research never leaks into this user's run.
    assert rb._prior_context(_Handler(data), "rp-0123456789ab", "8", "expand on solar cells") == {}


def test_marker_is_what_the_facade_recognises():
    marker = rb._marker("rp-0123456789ab", 'a "quoted" <topic>', None)
    assert chat.research_marker(marker) == "rp-0123456789ab"
    assert chat.run_marker(marker) is None
    assert "&quot;quoted&quot;" in marker


def test_progress_lines_read_like_a_log():
    assert research_follow.progress_line({"phase": "planning"}) == "Planning the research"
    line = research_follow.progress_line({"phase": "searching", "round": 2, "queries": ["a", "b"], "total_sources": 5})
    assert line == "Round 2: searching “b” (5 sources so far)"
    assert research_follow.progress_line({"phase": "reading", "url": "https://x", "title": "X"}) == "Reading X"
    assert research_follow.progress_line({}) == ""


def test_report_links_its_page_and_lists_missing_sources():
    text = research_follow.report_text(
        "rp-0123456789ab", "# Findings\nbody", [{"url": "https://a", "title": "A"}, {"url": "https://b"}],
        "http://localhost:9000",
    )
    assert "[Open the report page](http://localhost:9000/hermes/#/research?id=rp-0123456789ab)" in text
    assert "- [A](https://a)" in text and "- [https://b](https://b)" in text
    assert "rp-0123456789ab" in text


def test_stream_turn_follows_the_research_marker(monkeypatch):
    marker = rb._marker("rp-0123456789ab", "topic", None)

    async def fake_completion(*_args):
        yield "research", chat.research_marker(marker)

    async def fake_follow(token, research_id, origin):
        yield "reasoning", f"{token}:{research_id}:{origin}"
        yield "text", "REPORT"

    monkeypatch.setattr(chat, "_stream_completion", fake_completion)
    monkeypatch.setattr(chat, "follow_research", fake_follow)

    async def collect():
        return [item async for item in chat.stream_turn("tok", [], origin="http://o")]

    assert asyncio.run(collect()) == [("reasoning", "tok:rp-0123456789ab:http://o"), ("text", "REPORT")]
