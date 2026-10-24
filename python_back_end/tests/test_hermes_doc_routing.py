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


@pytest.mark.parametrize("text", ["install comfyui", "can you set up this repo", "use an agent to fix the tests"])
def test_real_agent_asks_keep_agent_mode(text):
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
