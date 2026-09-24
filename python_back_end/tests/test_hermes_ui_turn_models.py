"""Settings ▸ Model made real: fallback models, mixture of agents, the chat note,
the curator pin, and the routes the Settings/Profiles pages call.

chat.stream_turn, the database and the network are replaced with in-memory seams;
no key is real and nothing leaves the process.
"""
import asyncio
import copy
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import chat, learn, profiles, providers, rest, rest_harvis, settings_store, store  # noqa: E402
from plugins.hermes_ui import turn_models as tm  # noqa: E402

USER = {"id": 7}
TURN = [{"role": "user", "content": "hi"}]


def run(coro):
    return asyncio.run(coro)


async def drain(agen):
    return [item async for item in agen]


class FakeRequest:
    def __init__(self, body=None):
        self._body = body or {}
        self.query_params = {}
        self.headers = {}
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=None))

    async def json(self):
        return self._body


@pytest.fixture
def section(monkeypatch):
    data: dict = {}

    async def read_section(pool, uid):
        return copy.deepcopy(data)

    async def write_patch(pool, uid, patch):
        data.update(copy.deepcopy(patch))
        return copy.deepcopy(data)

    monkeypatch.setattr(settings_store, "read_section", read_section)
    monkeypatch.setattr(settings_store, "write_patch", write_patch)
    return data


@pytest.fixture
def endpoints(monkeypatch):
    """The user's custom endpoints (fake keys only)."""
    rows = {"groq-me": {"id": "groq-me", "base_url": "http://fake/v1", "model": "m-default",
                        "api_key": "fake-key"}}

    async def resolve_endpoint(pool, uid, endpoint_id):
        return copy.deepcopy(rows.get(endpoint_id))

    monkeypatch.setattr(providers, "resolve_endpoint", resolve_endpoint)
    return rows


@pytest.fixture
def calls(monkeypatch):
    """Scripted chat.stream_turn: behaviour per model id; records every call."""
    seen: list[dict] = []
    script: dict = {}

    async def stream_turn(token, messages, model="", endpoint=None, mode="", effort="", origin="", extra=None):
        seen.append({"messages": copy.deepcopy(messages), "model": model, "endpoint": endpoint,
                     "mode": mode, "effort": effort})
        behaviour = script.get(model, [("text", f"answer from {model}")])
        for item in behaviour:
            if isinstance(item, Exception):
                raise item
            yield item

    monkeypatch.setattr(chat, "stream_turn", stream_turn)
    return SimpleNamespace(seen=seen, script=script)


def texts(items):
    return "".join(v for k, v in items if k == "text")


def notes(items):
    return "".join(v for k, v in items if k == "reasoning")


# ── fallbacks ───────────────────────────────────────────────────────────────

def test_a_failure_before_any_answer_hands_over_to_the_next_fallback(calls, endpoints):
    calls.script["main"] = [chat.ChatError("model not found")]
    calls.script["fb1"] = [RuntimeError("503 from upstream")]
    config = {"fallback_providers": [{"provider": "harvis", "model": "fb1"},
                                     {"provider": "groq-me", "model": "fb2"}]}

    items = run(drain(tm.stream(None, 7, "tok", TURN, "main", None, "chat", "high", "", config=config)))

    assert texts(items) == "answer from fb2"
    assert "main failed (model not found). Trying fallback fb1." in notes(items)
    assert "fb1 failed (503 from upstream). Trying fallback fb2 (groq-me)." in notes(items)
    last = calls.seen[-1]
    assert last["endpoint"]["base_url"] == "http://fake/v1" and last["endpoint"]["model"] == "fb2"
    assert last["effort"] == ""  # a fallback model may not take the main model's effort level


def test_a_model_that_fails_after_answering_is_not_retried(calls):
    calls.script["main"] = [("text", "half an ans"), RuntimeError("connection reset")]
    config = {"fallback_providers": [{"provider": "harvis", "model": "fb1"}]}

    with pytest.raises(RuntimeError, match="connection reset"):
        run(drain(tm.stream(None, 7, "tok", TURN, "main", None, "chat", "", "", config=config)))
    assert [c["model"] for c in calls.seen] == ["main"]


def test_no_fallbacks_means_the_original_error(calls):
    calls.script["main"] = [chat.ChatError("model not found")]
    with pytest.raises(chat.ChatError, match="model not found"):
        run(drain(tm.stream(None, 7, "tok", TURN, "main", None, "chat", "", "", config={})))


def test_every_model_failing_says_which_was_last(calls):
    calls.script["main"] = [chat.ChatError("down")]
    calls.script["fb1"] = [chat.ChatError("also down")]
    config = {"fallback_providers": [{"provider": "harvis", "model": "fb1"}]}
    with pytest.raises(chat.ChatError, match="every model failed; last was fb1: also down"):
        run(drain(tm.stream(None, 7, "tok", TURN, "main", None, "chat", "", "", config=config)))


# ── the chat note ───────────────────────────────────────────────────────────

def test_personality_and_local_time_go_first_but_not_into_a_bot_chat(calls):
    config = {"display": {"personality": "pirate"}, "timezone": "America/Los_Angeles"}
    run(drain(tm.stream(None, 7, "tok", TURN, "main", None, "chat", "", "", config=config)))
    note = calls.seen[0]["messages"][0]
    assert note["role"] == "system" and "Captain Harvis" in note["content"]
    assert "(America/Los_Angeles)" in note["content"]

    run(drain(tm.stream(None, 7, "tok", TURN, "main", None, "chat", "", "", config=config, bot=True)))
    assert calls.seen[1]["messages"] == TURN


def test_a_users_own_personality_wins_and_bad_timezones_are_ignored():
    config = {"display": {"personality": "pirate"}, "agent": {"personalities": {"pirate": "Talk like Ahab."}},
              "timezone": "Mars/Olympus"}
    assert tm.system_note(config) == {"role": "system", "content": "Talk like Ahab."}
    at = datetime(2026, 9, 23, 21, 0, tzinfo=timezone.utc)
    assert tm.time_text({"timezone": "UTC"}, at) == "The user's local time is Wednesday 2026-09-23 21:00 (UTC)."
    assert tm.system_note({}) is None


# ── mixture of agents ───────────────────────────────────────────────────────

PRESET = {"enabled": True, "aggregator": {"provider": "harvis", "model": "agg"},
          "reference_models": [{"provider": "harvis", "model": "ref1"}, {"provider": "groq-me", "model": "ref2"},
                               {"provider": "harvis", "model": "off", "enabled": False}]}


def test_moa_asks_every_reference_then_streams_the_aggregator(calls, section, endpoints):
    section[tm.MOA_KEY] = {"presets": {"team": PRESET}}
    calls.script["ref2"] = [RuntimeError("rate limited")]
    turn = [{"role": "system", "content": "house rules"}, *TURN]

    items = run(drain(tm.stream(None, 7, "tok", turn, "moa:team", None, "chat", "", "", config={})))

    assert sorted(c["model"] for c in calls.seen[:2]) == ["ref1", "ref2"]
    assert all(c["mode"] == "chat" for c in calls.seen[:2])
    agg = calls.seen[-1]
    assert agg["model"] == "agg"
    assert agg["messages"][0] == {"role": "system", "content": "house rules"}
    assert agg["messages"][1]["content"].startswith(tm.AGGREGATOR_SYSTEM_PROMPT)
    assert "1. answer from ref1" in agg["messages"][1]["content"]
    assert agg["messages"][2:] == TURN
    assert texts(items) == "answer from agg"
    assert "Reference ref2 (groq-me) failed: rate limited" in notes(items)
    assert "off" not in [c["model"] for c in calls.seen]


def test_moa_with_no_answering_reference_falls_back(calls, section, endpoints):
    section[tm.MOA_KEY] = {"presets": {"team": PRESET}}
    calls.script["ref1"] = [RuntimeError("down")]
    calls.script["ref2"] = [RuntimeError("down")]
    config = {"fallback_providers": [{"provider": "harvis", "model": "fb1"}]}

    items = run(drain(tm.stream(None, 7, "tok", TURN, "moa:team", None, "chat", "", "", config=config)))

    assert texts(items) == "answer from fb1"
    assert "Mixture of agents 'team' failed (no reference model answered)" in notes(items)


def test_an_unknown_preset_is_a_clear_error(section):
    with pytest.raises(chat.ChatError, match="preset 'gone' is not set up"):
        run(tm.moa_preset(None, 7, "moa:gone"))


def test_ready_presets_show_up_as_a_mixture_of_agents_group(monkeypatch, section):
    section[tm.MOA_KEY] = {"presets": {"team": PRESET, "empty": {"aggregator": {"model": "agg"}}}}

    async def resolve_model(pool, uid):
        return "gemma4:e2b"

    async def harvis_models(token):
        return [{"id": "gemma4:e2b", "owned_by": "ollama"}]

    async def list_endpoints(pool, uid):
        return [], None

    async def thinking_models():
        return frozenset()

    monkeypatch.setattr(store, "resolve_model", resolve_model)
    monkeypatch.setattr(rest, "_harvis_models", harvis_models)
    monkeypatch.setattr(rest, "thinking_models", thinking_models)
    monkeypatch.setattr(providers, "list_endpoints", list_endpoints)

    options = run(rest.build_model_options(None, 7, "tok"))
    moa = next(p for p in options["providers"] if p["slug"] == "moa")
    assert moa["models"] == ["moa:team"] and moa["name"] == "Mixture of agents" and moa["auth_type"] == "moa"
    assert options["provider"] == "ollama"


# ── endpoints, curator pin, routes ──────────────────────────────────────────

def test_picking_a_model_out_of_an_endpoint_group_sticks(monkeypatch):
    saved = {providers.ENDPOINTS_KEY: [{"id": "local-ollama", "model": "a", "models": ["a", "b"]}]}

    async def read(pool, uid):
        return copy.deepcopy(saved)

    async def write(pool, uid, section):
        saved.clear()
        saved.update(section)

    monkeypatch.setattr(providers, "_read_section", read)
    monkeypatch.setattr(providers, "_write_section", write)
    run(providers.activate_endpoint(None, 7, "local-ollama", "b"))
    assert saved[providers.ACTIVE_KEY] == "local-ollama" and saved["model"] == "b"
    run(providers.activate_endpoint(None, 7, "local-ollama", "not-listed"))
    assert saved["model"] == "b"


def test_the_curator_pin_is_only_honoured_for_local_models(section):
    assert run(learn.curator_model(None, 7)) == ""
    section["auxiliary_models"] = {"curator": {"provider": "ollama", "model": "gemma4:e2b"}}
    assert run(learn.curator_model(None, 7)) == "gemma4:e2b"
    section["auxiliary_models"] = {"curator": {"provider": "groq-me", "model": "llama"}}
    assert run(learn.curator_model(None, 7)) == ""
    section["auxiliary_models"] = {"curator": {"provider": "harvis", "model": "kimi-k2:cloud"}}
    assert run(learn.curator_model(None, 7)) == ""


def test_omniroute_row_carries_the_users_own_endpoint(monkeypatch):
    mine = {"id": "omniroute", "name": "OmniRoute", "base_url": "http://my-box:20129/v1", "model": "x",
            "models": ["x"], "api_key_enc": "ciphertext"}

    async def list_endpoints(pool, uid):
        return [mine], "omniroute"

    async def auth_status(pool, uid, engine):
        return {"saved": False, "verified": False, "auth_mode": "api_key", "last_error": None}

    monkeypatch.setattr(providers, "list_endpoints", list_endpoints)
    monkeypatch.setattr(rest_harvis, "_auth_status", auth_status)
    request = FakeRequest()
    request.app.state.pg_pool = object()
    rows = {r["id"]: r for r in run(rest_harvis.free_providers(request, USER))["providers"]}
    omni = rows["omniroute"]
    assert omni["key_optional"] and omni["endpoint_id"] == "omniroute"
    assert omni["endpoint"]["base_url"] == "http://my-box:20129/v1" and omni["endpoint"]["is_current"]
    assert "api_key" not in omni["endpoint"] and "api_key_enc" not in omni["endpoint"]
    assert all(r["endpoint"] is None for k, r in rows.items() if k != "omniroute")


def test_profile_page_routes_answer_instead_of_404():
    assert run(profiles.profiles_projects_tree(USER)) == {"projects": [], "active_id": None,
                                                          "scoped_session_ids": []}
    body = run(profiles.profiles_session_pull_requests(FakeRequest({"ids": ["a", 2]}), USER))
    assert body == {"pull_requests": {}, "scanned": ["a", "2"]}
