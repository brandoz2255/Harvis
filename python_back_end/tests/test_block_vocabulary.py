"""The content-block prompt must not turn code into terminal blocks."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import chat_completion  # noqa: E402


def test_code_is_told_to_stay_in_ordinary_fenced_blocks():
    text = chat_completion._BLOCK_VOCABULARY
    assert "ALWAYS go in an ordinary markdown fenced block" in text
    assert "Never replace code with a description" in text


def test_terminal_blocks_are_reserved_for_real_tool_output():
    text = chat_completion._BLOCK_VOCABULARY
    terminal = next(line for line in text.splitlines() if ":::terminal" in line)
    assert "ONLY output that a tool" in terminal and "never for code" in terminal.lower()
    assert "status=running" not in text  # the old prompt invited a fake running shell around any snippet


def test_vocabulary_is_appended_to_the_system_message():
    body = {"messages": [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}]}
    chat_completion._inject_block_vocabulary(body)
    assert body["messages"][0]["content"].startswith("be nice") and "fenced block" in body["messages"][0]["content"]
