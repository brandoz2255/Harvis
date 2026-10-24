"""The abilities note: what this install can do, told to the chat model once per turn.

It exists because a plain chat turn gives the model no tools, so a request the wording
detector missed was answered "I can't make files". These tests pin what the note may
say, where it may go, and that it never lists a feature that is switched off.
"""

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import chat_abilities, chat_completion  # noqa: E402
from owui_compat.chat_abilities import NOTE_HEADING, Ability, inject_abilities, render_note  # noqa: E402
from owui_compat.doc_bridge import DOC_PROMPT_MARKER, detect_doc_kind, doc_system_prompt  # noqa: E402
from owui_compat.system_prompt import core_text, inject_core  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    """Each test starts from the built-in entries and gets them back afterwards."""
    monkeypatch.setattr(chat_abilities, "_ABILITIES", list(chat_abilities._ABILITIES))
    monkeypatch.setattr(chat_abilities, "_cache", None)
    monkeypatch.delenv("HARVIS_CHAT_ABILITIES", raising=False)


def _chat(text="hello", system="be nice"):
    return {"messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}


def test_note_leaves_out_a_feature_that_is_off(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_IMAGE_GENERATION", "false")
    note = render_note()
    image = next(a for a in chat_abilities.abilities() if a.id == "image")
    assert not image.available()
    assert image.summary not in note and image.example_phrase not in note
    for entry in chat_abilities.abilities():
        if not entry.available():
            assert entry.summary not in note


def test_note_lists_image_generation_once_it_is_on(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_IMAGE_GENERATION", "true")
    assert "image generation" in render_note()


def test_note_never_lists_an_entry_whose_check_raises():
    def boom():
        raise RuntimeError("probe failed")

    chat_abilities.register(Ability("flaky", "flaky thing", "do the flaky thing", boom))
    assert "flaky thing" not in render_note()


def test_note_stays_under_900_chars_even_with_everything_on(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_IMAGE_GENERATION", "true")
    note = render_note()
    assert 500 < len(note) < 900


def test_note_stays_under_900_chars_when_other_modules_register_more(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_IMAGE_GENERATION", "true")
    chat_abilities.register(Ability("schedule", "scheduled reminders", "remind me every morning at 8 to check email"))
    chat_abilities.register(Ability("memory", "remembering and forgetting", "remember that I like tea"))
    note = render_note()
    assert len(note) < 900
    assert "scheduled reminders" in note and "remembering and forgetting" in note


def test_note_says_the_things_the_model_must_do():
    note = render_note()
    assert "not tool calls you can see" in note
    assert "never offer only an outline or script" in note
    # No /deck command exists until P0-B lands; the note must not send users to it.
    assert "/deck" not in note
    assert "make me a <deck|document|spreadsheet|PDF> about" in note
    assert "Posters, flyers, logos and video are not supported" in note


def test_note_is_cached_until_the_set_of_features_changes(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_IMAGE_GENERATION", "false")
    first = render_note()
    assert render_note() is first
    monkeypatch.setenv("HARVIS_OWUI_IMAGE_GENERATION", "true")
    assert render_note() is not first


def test_register_adds_an_entry_and_replaces_one_with_the_same_id():
    chat_abilities.register(Ability("schedule", "scheduled reminders", "remind me at 8"))
    assert "scheduled reminders" in render_note()
    chat_abilities.register(Ability("schedule", "timed reminders", "remind me at 9"))
    note = render_note()
    assert "timed reminders" in note and "scheduled reminders" not in note
    assert sum(1 for a in chat_abilities.abilities() if a.id == "schedule") == 1


def test_inject_appends_to_the_first_system_message():
    body = _chat()
    inject_abilities(body)
    first = body["messages"][0]["content"]
    assert first.startswith("be nice") and NOTE_HEADING in first
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_inject_adds_a_system_message_when_the_turn_has_none():
    body = {"messages": [{"role": "user", "content": "hi"}]}
    inject_abilities(body)
    assert body["messages"][0]["role"] == "system" and NOTE_HEADING in body["messages"][0]["content"]


def test_not_injected_on_a_document_turn():
    body = _chat("make me a slide deck about volcanoes")
    body["messages"].insert(1, {"role": "system", "content": doc_system_prompt("deck")})
    before = copy.deepcopy(body)
    inject_abilities(body)
    assert body == before


def test_not_injected_on_a_plain_voice_turn():
    body = _chat()
    body["harvis_plain"] = True
    before = copy.deepcopy(body)
    inject_abilities(body)
    assert body == before


def test_switch_turns_it_off(monkeypatch):
    monkeypatch.setenv("HARVIS_CHAT_ABILITIES", "0")
    body = _chat()
    inject_abilities(body)
    assert body["messages"][0]["content"] == "be nice"


def test_injection_is_idempotent_across_a_grounded_retry_copy():
    body = _chat()
    inject_abilities(body)
    retry_copy = copy.deepcopy(body)
    inject_abilities(retry_copy)
    assert retry_copy == body
    assert body["messages"][0]["content"].count(NOTE_HEADING) == 1


def test_a_malformed_body_is_left_alone():
    for body in ({}, {"messages": None}, {"messages": []}, {"messages": ["x"]}):
        inject_abilities(body)


def test_the_core_still_ends_up_first_after_the_note():
    body = _chat()
    chat_completion._inject_block_vocabulary(body)
    inject_abilities(body)
    inject_core(body["messages"])
    first = body["messages"][0]["content"]
    assert first.startswith(core_text())
    assert NOTE_HEADING in first and "fenced block" in first


def test_strip_note_cuts_only_the_note():
    body = _chat()
    chat_completion._inject_block_vocabulary(body)
    inject_abilities(body)
    with_note = body["messages"][0]["content"]
    stripped = chat_abilities.strip_note(with_note)
    assert NOTE_HEADING not in stripped and stripped.startswith("be nice")
    assert "fenced block" in stripped  # the vocabulary before it is untouched
    assert chat_abilities.strip_note("no note here") == "no note here"


def test_every_entry_has_a_phrase_and_the_ones_with_a_cheap_bridge_trigger_it():
    for entry in chat_abilities.abilities():
        assert entry.example_phrase.strip() and entry.summary.strip()
    by_id = {a.id: a for a in chat_abilities.abilities()}

    assert detect_doc_kind(by_id["docs"].example_phrase) is not None

    from owui_compat.research_bridge import research_query
    assert research_query(by_id["research"].example_phrase)

    from plugins.agents.browse import is_browse_request
    assert is_browse_request(by_id["browse"].example_phrase)

    from owui_compat.image_bridge import _IMAGE_NL_RE
    assert _IMAGE_NL_RE.search(by_id["image"].example_phrase)


def test_agent_example_is_read_as_an_agent_request():
    pytest.importorskip("plugins.hermes_ui.chat")
    from plugins.hermes_ui.chat import requested_mode

    agent = next(a for a in chat_abilities.abilities() if a.id == "agent")
    assert requested_mode(agent.example_phrase) == "agent"


def test_connector_example_reads_as_a_connector_request():
    from types import SimpleNamespace

    from owui_compat.chat_tools_gate import gate

    connectors = next(a for a in chat_abilities.abilities() if a.id == "connectors")
    cfg = SimpleNamespace(server_name="github", url="")
    match = gate(connectors.example_phrase, [cfg])
    assert match is not None and match.read_cue
