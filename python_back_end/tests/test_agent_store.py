"""Validation tests for the agent-teammate store.

These cover the pure validators only — the CRUD functions need a live pool and
are exercised end-to-end instead. The validators are where a mistake is
invisible: a silently-dropped hard limit or an out-of-range budget does not
raise anything at write time, it just quietly widens what an autonomous agent
is allowed to do later.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.agents import store  # noqa: E402


# ─── names ───────────────────────────────────────────────────────────────────


def test_clean_name_accepts_kebab_case():
    assert store.clean_name("scout") == "scout"
    assert store.clean_name("  Research-Buddy  ") == "research-buddy"


@pytest.mark.parametrize("bad", ["", "  ", "9lives", "Has Space", "trailing-", "-leading", "a" * 41])
def test_clean_name_rejects_bad_handles(bad):
    with pytest.raises(store.ValidationError):
        store.clean_name(bad)


# ─── engine ──────────────────────────────────────────────────────────────────


def test_clean_engine_defaults_to_auto():
    assert store.clean_engine(None) == "auto"
    assert store.clean_engine("") == "auto"


def test_clean_engine_rejects_unknown_runner():
    with pytest.raises(store.ValidationError):
        store.clean_engine("gpt-in-a-box")


# ─── avatar ──────────────────────────────────────────────────────────────────


def test_clean_avatar_keeps_mascot_and_tint():
    assert store.clean_avatar({"mascot": "Claw", "tint": "#7C5CFF"}) == {
        "mascot": "claw",
        "tint": "#7c5cff",
    }


def test_clean_avatar_rejects_non_hex_tint():
    with pytest.raises(store.ValidationError):
        store.clean_avatar({"tint": "javascript:alert(1)"})


def test_clean_avatar_rejects_unknown_mascot():
    with pytest.raises(store.ValidationError):
        store.clean_avatar({"mascot": "dragon"})


# ─── autonomy: the four hard limits ──────────────────────────────────────────


def test_cleared_limits_accepts_only_the_four_hard_limits():
    got = store.clean_autonomy({"cleared_limits": ["send", "send", "delete"]})
    assert got["cleared_limits"] == ["send", "delete"]


def test_cleared_limits_rejects_invented_permission():
    # Dropping it silently would read to the user as if it had been granted.
    with pytest.raises(store.ValidationError):
        store.clean_autonomy({"cleared_limits": ["send", "wire_transfer"]})


def test_hard_limits_list_is_exactly_four():
    assert set(store.HARD_LIMITS) == {"sign_in", "pay", "send", "delete"}


def test_notify_channel_must_be_numeric():
    assert store.clean_autonomy({"notify_channel_id": " 123456 "})["notify_channel_id"] == "123456"
    with pytest.raises(store.ValidationError):
        store.clean_autonomy({"notify_channel_id": "#general"})


# ─── budget ──────────────────────────────────────────────────────────────────


def test_budget_rejects_values_over_the_ceiling():
    with pytest.raises(store.ValidationError):
        store.clean_budget({"max_minutes": 6000})


def test_budget_rejects_zero_and_negatives():
    for bad in (0, -1):
        with pytest.raises(store.ValidationError):
            store.clean_budget({"max_steps": bad})


def test_effective_budget_fills_defaults_and_ignores_junk():
    merged = store.effective_budget({"max_steps": 20, "max_minutes": "nope"})
    assert merged["max_steps"] == 20
    assert merged["max_minutes"] == store.BUDGET_DEFAULTS["max_minutes"]
    assert merged["max_child_runs"] == store.BUDGET_DEFAULTS["max_child_runs"]


def test_effective_budget_ignores_stored_value_over_ceiling():
    # A row written before a ceiling changed must not outrank the ceiling.
    merged = store.effective_budget({"max_minutes": 99999})
    assert merged["max_minutes"] == store.BUDGET_DEFAULTS["max_minutes"]


# ─── check-ins ───────────────────────────────────────────────────────────────


def test_check_ins_require_five_field_cron_and_prompt():
    ok = store.clean_check_ins([{"cron": "0 9 * * *", "prompt": "morning"}])
    assert ok == [{"cron": "0 9 * * *", "prompt": "morning"}]
    with pytest.raises(store.ValidationError):
        store.clean_check_ins([{"cron": "0 9 *", "prompt": "morning"}])
    with pytest.raises(store.ValidationError):
        store.clean_check_ins([{"cron": "0 9 * * *", "prompt": ""}])


def test_check_ins_capped():
    many = [{"cron": "0 9 * * *", "prompt": f"p{i}"} for i in range(9)]
    with pytest.raises(store.ValidationError):
        store.clean_check_ins(many)


# ─── keys ────────────────────────────────────────────────────────────────────


def test_keys_are_derived_from_id_not_name():
    # A rename must not orphan the teammate's saved logins or working tree.
    ws, browser = store.new_keys("11111111-2222-3333-4444-555555555555")
    assert ws == "agent-1111111122223333"
    assert browser == ws


# ─── text limits ─────────────────────────────────────────────────────────────


def test_clean_text_absent_stays_absent():
    assert store.clean_text(None, limit=10, field="job") is None


def test_clean_text_rejects_overlong():
    with pytest.raises(store.ValidationError):
        store.clean_text("x" * 11, limit=10, field="job")


# ─── the default assistant ───────────────────────────────────────────────────
# ensure_default_assistant is exercised against stand-ins for the row-level
# functions: what matters is which it calls, and what it does when the
# database says another call got there first.

import asyncio  # noqa: E402

import asyncpg  # noqa: E402


def _unique_violation():
    return asyncpg.UniqueViolationError("duplicate key value violates unique constraint")


def _fake_store(monkeypatch, *, default=None, create=None, claim=None):
    calls: dict = {"create": [], "claim": [], "delete": [], "list": 0, "promote": []}
    defaults = list(default) if isinstance(default, (list, tuple)) else [default]

    async def get_default(pool, user_id):
        return defaults.pop(0) if len(defaults) > 1 else defaults[0]

    async def create_agent(pool, user_id, fields):
        calls["create"].append(fields["name"])
        if callable(create):
            return create(fields)
        return {"id": "new-1", "name": fields["name"], "autonomy": fields.get("autonomy", {}),
                "is_default_assistant": False}

    async def claim_slot(pool, user_id, agent_id):
        calls["claim"].append(agent_id)
        if callable(claim):
            return claim(agent_id)
        return {"id": agent_id, "is_default_assistant": True, "autonomy": {}}

    async def delete_agent(pool, user_id, agent_id):
        calls["delete"].append(agent_id)
        return True

    async def list_teammates(pool, user_id, *, enabled_only=False):
        calls["list"] += 1
        return [{"id": "scout", "autonomy": {"cleared_limits": ["send"]}, "enabled": True}]

    async def set_default(pool, user_id, agent_id):
        calls["promote"].append(agent_id)
        return {"id": agent_id}

    monkeypatch.setattr(store, "get_default_assistant", get_default)
    monkeypatch.setattr(store, "create_agent", create_agent)
    monkeypatch.setattr(store, "_claim_default_slot", claim_slot)
    monkeypatch.setattr(store, "delete_agent", delete_agent)
    monkeypatch.setattr(store, "list_teammates", list_teammates)
    monkeypatch.setattr(store, "set_default_assistant", set_default)
    return calls


def test_an_explicit_enabled_default_is_used_as_is(monkeypatch):
    chosen = {"id": "chosen", "is_default_assistant": True, "autonomy": {"cleared_limits": ["pay"]}}
    calls = _fake_store(monkeypatch, default=chosen)
    assert asyncio.run(store.ensure_default_assistant("pool", 7)) is chosen
    assert calls["create"] == [] and calls["claim"] == []


def test_no_teammate_is_ever_promoted_a_fresh_one_is_made_instead(monkeypatch):
    # "scout" exists, enabled, with a cleared limit — and must stay untouched.
    calls = _fake_store(monkeypatch, default=None)
    got = asyncio.run(store.ensure_default_assistant("pool", 7))
    assert calls["list"] == 0 and calls["promote"] == []
    assert calls["create"] == ["Harvis"]
    assert calls["claim"] == ["new-1"]
    assert got["is_default_assistant"] is True and got["autonomy"] == {}


def test_the_fresh_default_carries_no_clearances():
    assert store.clean_autonomy(store.DEFAULT_ASSISTANT["autonomy"]) == {}
    assert store.clean_name(store.DEFAULT_ASSISTANT["name"]) == "harvis"
    for name in store._DEFAULT_NAMES:
        store.clean_name(name)  # every fallback handle is a legal one


def test_a_taken_handle_falls_back_to_the_next(monkeypatch):
    def create(fields):
        if fields["name"] == "Harvis":
            raise store.ValidationError("An agent named 'harvis' already exists.")
        return {"id": "new-2", "name": fields["name"], "autonomy": {}}

    calls = _fake_store(monkeypatch, default=None, create=create)
    got = asyncio.run(store.ensure_default_assistant("pool", 7))
    assert calls["create"] == ["Harvis", "harvis-assistant"]
    assert got["id"] == "new-2"


def test_losing_the_race_on_the_name_uses_the_winners_row(monkeypatch):
    winner = {"id": "theirs", "is_default_assistant": True}

    def create(fields):
        raise _unique_violation()

    calls = _fake_store(monkeypatch, default=[None, winner], create=create)
    assert asyncio.run(store.ensure_default_assistant("pool", 7)) is winner
    assert calls["claim"] == [] and calls["delete"] == []


def test_losing_the_race_on_the_default_slot_drops_the_spare_row(monkeypatch):
    winner = {"id": "theirs", "is_default_assistant": True}

    def claim(agent_id):
        raise _unique_violation()

    calls = _fake_store(monkeypatch, default=[None, winner], claim=claim)
    assert asyncio.run(store.ensure_default_assistant("pool", 7)) is winner
    assert calls["delete"] == ["new-1"]


def test_a_default_that_appeared_meanwhile_wins_without_an_error(monkeypatch):
    # The claim is conditional on "no default yet", so it updates nothing
    # rather than demoting the one another call just made.
    winner = {"id": "theirs", "is_default_assistant": True}
    calls = _fake_store(monkeypatch, default=[None, winner], claim=lambda _id: None)
    assert asyncio.run(store.ensure_default_assistant("pool", 7)) is winner
    assert calls["delete"] == ["new-1"]
