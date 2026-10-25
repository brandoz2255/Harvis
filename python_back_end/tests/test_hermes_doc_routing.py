"""Document requests stay out of agent mode, and /deck /doc /sheet /pdf force a document."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat.doc_bridge import detect_doc_kind  # noqa: E402
from plugins.hermes_ui import chat, ws_slash  # noqa: E402


@pytest.mark.parametrize("text", ["set up a slideshow for the standup", "set up a spreadsheet for my budget"])
def test_document_asks_that_open_with_set_up_are_not_agent_mode(text):
    assert detect_doc_kind(text) is not None
    assert chat.requested_mode(text) is None


@pytest.mark.parametrize("text", [
    "install comfyui", "can you set up this repo", "use an agent to fix the tests",
    "install excel", "can you install a pdf reader",
    "install comfyui and write me a doc on how to use it",
    "clone the repo and make a spreadsheet of the open issues",
    "install ollama, then make me a cheat sheet for its commands",
    "set up a google sheet integration",
    "set up a google sheets connector",
    "set up this repo and make a deck about it",
])
def test_real_agent_asks_keep_agent_mode(text):
    assert chat.requested_mode(text) == "agent"


@pytest.mark.parametrize("text", [
    "set up a word document for my essay",
    "set up a slideshow about how to install linux",
    "set up a slideshow for the standup and make it short",
])
def test_a_set_up_that_is_only_a_file_stays_auto(text):
    assert chat.requested_mode(text) is None


@pytest.mark.parametrize("text", [
    "set up a presentation on api design", "set up a deck on our mcp servers",
    "set up a report on our server costs", "set up a slideshow about browser extensions for my class",
    "set up slides on dev environments", "set up a spreadsheet to track our api costs",
    "can you set up a powerpoint about rest apis",
    "set up a deck with three sections: overview, install, and troubleshooting",
    "set up a presentation comparing git merge, clone and fork",
    "set up a doc on setup, install and clone steps",
    "set up a spreadsheet listing our repos", "set up a deck that explains our api",
    "set up a pdf summarizing the environments", "set up a spreadsheet tracking server uptime",
    "set up a server costs spreadsheet",
])
def test_a_document_topic_or_section_list_does_not_trip_the_agent_veto(text):
    assert detect_doc_kind(text) is not None
    assert chat.requested_mode(text) is None


@pytest.mark.parametrize("text", [
    "set up a google sheet integration for my team", "set up a google sheets connector with oauth",
    "set up comfyui and install it", "set up a doc, install comfyui",
    "set up the sheets api", "set up an mcp server for our slides",
])
def test_narrowed_vetoes_still_keep_agent_mode(text):
    assert chat.requested_mode(text) == "agent"


def test_other_modes_are_untouched_by_the_document_check():
    assert chat.requested_mode("just answer, no tools") == "chat"
    assert chat.requested_mode("hello there") is None


class _Conn(ws_slash.SlashMethods):
    pass


def _run(cmd: str, arg: str = ""):
    return asyncio.run(_Conn()._run_command(None, [], ws_slash.canonical(cmd), arg))


FILE_CASES = [
    ("/deck", "deck"), ("/slides", "deck"), ("/ppt", "deck"), ("/powerpoint", "deck"),
    ("/doc", "doc"), ("/word", "doc"),
    ("/sheet", "sheet"), ("/excel", "sheet"),
    ("/pdf", "pdf"),
]


@pytest.mark.parametrize("cmd,kind", FILE_CASES)
def test_file_commands_send_a_request_the_detector_matches(cmd, kind):
    out = _run(cmd, "the water cycle")
    assert out["type"] == "send"
    assert out["message"].endswith("about: the water cycle")
    assert out["notice"].startswith("Making a ")
    assert detect_doc_kind(out["message"]) == kind


def test_deck_message_wording_is_exact():
    out = _run("/deck", "cats")
    assert out["message"] == "Make a slide deck about: cats"
    assert out["notice"] == "Making a slide deck."


@pytest.mark.parametrize("cmd", [c for c, _ in FILE_CASES])
def test_file_commands_need_a_topic(cmd):
    assert _run(cmd, "") == {"output": f"Usage: {ws_slash.canonical(cmd)} <topic>"}


def test_a_code_word_in_the_topic_still_makes_a_deck():
    out = _run("/deck", "docker networking")
    assert detect_doc_kind(out["message"]) == "deck"


def test_catalog_help_and_popover_list_the_file_commands():
    cat = ws_slash.catalog()
    names = {pair[0].split()[0] for pair in cat["pairs"]}
    assert {"/deck", "/doc", "/sheet", "/pdf"} <= names
    section = next(c for c in cat["categories"] if c["name"] == "Make a file")
    assert [p[0].split()[0] for p in section["pairs"]] == ["/deck", "/doc", "/sheet", "/pdf"]
    assert cat["canon"]["/ppt"] == "/deck" and cat["canon"]["/excel"] == "/sheet"
    assert "/deck - Make a slide deck" in ws_slash.help_text()
    assert "/deck" in [i["text"] for i in ws_slash.complete("/de", [])["items"]]
    assert "/deck" in [i["text"] for i in ws_slash.complete("/sl", [])["items"]]


@pytest.mark.parametrize("cmd", [c for c, _ in FILE_CASES])
@pytest.mark.parametrize("topic", ["a team of agents", "multi-agent systems: a team of agents",
                                   "using multiple agents", "just answer questions", "use the browser"])
def test_mode_words_in_a_file_command_topic_do_not_change_the_mode(cmd, topic):
    out = _run(cmd, topic)
    assert out["type"] == "send"
    assert chat.requested_mode(out["message"]) is None
    assert detect_doc_kind(out["message"]) is not None


def test_the_same_topic_typed_without_the_command_keeps_its_mode():
    assert chat.requested_mode("a team of agents") == "orchestrate"
    assert chat.requested_mode("use a team of agents to build a site") == "orchestrate"
