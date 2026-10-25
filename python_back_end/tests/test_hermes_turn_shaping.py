"""Small shaping rules for Hermes turns: which render prompts a turn gets, how long a
spoken reply may run, and how a tool call written out as code is recovered."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import chat_completion  # noqa: E402
from plugins.hermes_ui.rest_voice import VOICE_DRAFT_MAX_TOKENS, VOICE_MAX_TOKENS, voice_max_tokens  # noqa: E402
from workspace.orchestration.tools import parse_tool_calls  # noqa: E402


def _systems(body):
    return "\n".join(m["content"] for m in body["messages"] if m["role"] == "system")


def test_a_hermes_turn_gets_the_house_tone_and_no_canvas_or_block_prompts():
    body = {"harvis_client": "hermes", "messages": [{"role": "user", "content": "hi"}]}
    chat_completion._inject_render_prompts(body)
    text = _systems(body)
    assert "You are Harvis, a direct assistant." in text
    assert "```canvas" not in text and ":::terminal" not in text


def test_any_other_client_still_gets_canvas_and_blocks():
    body = {"messages": [{"role": "user", "content": "hi"}]}
    chat_completion._inject_render_prompts(body)
    text = _systems(body)
    assert "canvas" in text and ":::terminal" in text


def test_a_hermes_turn_with_its_own_system_prompt_keeps_it_alone():
    body = {"harvis_client": "hermes",
            "messages": [{"role": "system", "content": "Be a pirate."}, {"role": "user", "content": "hi"}]}
    chat_completion._inject_render_prompts(body)
    assert _systems(body) == "Be a pirate."


def test_a_spoken_reply_stays_short_unless_text_for_the_chat_box_was_asked_for():
    assert voice_max_tokens("what's the weather like") == VOICE_MAX_TOKENS
    assert voice_max_tokens("") == VOICE_MAX_TOKENS
    assert voice_max_tokens("write a message to Sam saying I'm late") == VOICE_DRAFT_MAX_TOKENS
    assert voice_max_tokens("draft a grocery list") == VOICE_DRAFT_MAX_TOKENS
    assert voice_max_tokens("put that in my chat box") == VOICE_DRAFT_MAX_TOKENS
    assert voice_max_tokens("put the kettle on") == VOICE_MAX_TOKENS


def test_ordinary_questions_with_those_words_keep_the_short_cap():
    for q in ("what type of GPU do I have?", "my docker compose stack won't start, why?",
              "what's the right way to write a for loop in python?", "how do I type an em dash",
              "what did the draft say", "explain how to write unit tests", "who wrote Hamlet?"):
        assert voice_max_tokens(q) == VOICE_MAX_TOKENS, q


def test_polite_and_chained_asks_for_text_get_the_draft_cap():
    for q in ("can you write me a note for Sam", "please draft a reply", "Hey Harvis, jot down a list of chores",
              "ok. compose an email to my landlord", "type out a short message saying I'm late"):
        assert voice_max_tokens(q) == VOICE_DRAFT_MAX_TOKENS, q


def test_asks_with_a_recipient_a_count_or_a_longer_lead_in_get_the_draft_cap():
    for q in ("write John a quick text", "write Bob an email", "write me three bullet points",
              "write me 5 reasons to switch", "I need you to write a message to Sam",
              "I'd like you to draft a reply", "help me write a note to my landlord",
              "give me a todo list in the chat box", "write up a summary of this"):
        assert voice_max_tokens(q) == VOICE_DRAFT_MAX_TOKENS, q
    for q in ("the stack is down. compose up fails", "how do I compose up a stack", "what's in the chat history"):
        assert voice_max_tokens(q) == VOICE_MAX_TOKENS, q


def test_a_call_written_as_code_is_recovered_for_an_offered_tool():
    msg = {"content": 'write_file({"path": "a.txt", "content": "hi"})'}
    assert parse_tool_calls(msg, known=["write_file"]) == [
        {"id": None, "name": "write_file", "args": {"path": "a.txt", "content": "hi"}}]


def test_a_fenced_code_call_is_recovered_too():
    msg = {"content": '```python\nrun_command({"cmd": "ls"})\n```'}
    assert parse_tool_calls(msg, known=["run_command"])[0]["args"] == {"cmd": "ls"}


def test_code_that_is_not_an_offered_tool_or_not_the_whole_reply_is_left_alone():
    assert parse_tool_calls({"content": 'print({"a": 1})'}, known=["write_file"]) == []
    assert parse_tool_calls({"content": 'write_file({"path": "a"})'}, known=None) == []
    assert parse_tool_calls({"content": 'I would call write_file({"path": "a"}) next.'}, known=["write_file"]) == []
    assert parse_tool_calls({"content": "write_file({not json})"}, known=["write_file"]) == []
