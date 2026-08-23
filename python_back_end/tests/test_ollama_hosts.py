"""Which host has a model, and what an unanswered host means.

Runs in the backend container (`python_back_end/tests` is not bind-mounted, so
`docker cp` this in). No network: every test seeds the probe cache directly, which is
also the honest way to exercise the case that matters — a host that did not answer.

The distinction under test throughout is *absent* (a host answered and does not have
the tag) versus *unknown* (nobody could say). Collapsing those is what let a laptop-only
check call the user's own model uninstalled.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from owui_compat import ollama_hosts as oh


@pytest.fixture(scope="module")
def loop():
    """The repo's async convention — `pytest-asyncio` is not installed and
    `--strict-markers` would reject its marker (see tests/test_cad_store.py)."""
    lp = asyncio.new_event_loop()
    try:
        yield lp
    finally:
        lp.close()


LAPTOP = "http://host.docker.internal:11434"
RIG = "http://192.168.20.58:11434"


def seed(*, laptop_up=True, rig_up=True, laptop_tags=None, rig_tags=None,
         rig_last_good=None):
    """Install a probe result without probing, and freeze the TTL so nothing re-probes."""
    states = {
        "laptop": oh.HostState(
            name="laptop", base_url=LAPTOP, label="Ollama",
            reachable=laptop_up,
            tags=set(laptop_tags or []) if laptop_up else set(),
            last_good_tags=set(laptop_tags or []),
            error=None if laptop_up else "ConnectTimeout",
        ),
        "desktop": oh.HostState(
            name="desktop", base_url=RIG, label="Desktop 5080",
            reachable=rig_up,
            tags=set(rig_tags or []) if rig_up else set(),
            last_good_tags=set(rig_last_good if rig_last_good is not None else (rig_tags or [])),
            error=None if rig_up else "ConnectTimeout",
        ),
    }
    oh._cache.clear()
    oh._cache.update(states)
    oh._cache_at = time.time()


@pytest.fixture(autouse=True)
def clean_cache():
    yield
    oh._cache.clear()
    oh._cache_at = 0.0


def test_a_v1_base_url_is_probed_at_the_root():
    """An OpenAI-compatible base points at the same daemon; `/v1/api/tags` is a 404."""
    assert oh._clean("http://x:11434/v1/") == "http://x:11434"
    assert oh._clean("http://x:11434/") == "http://x:11434"
    assert oh._clean("") == ""


def test_a_desktop_url_equal_to_the_laptop_is_one_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.setenv("DESKTOP_OLLAMA_URL", LAPTOP + "/")
    assert [h[0] for h in oh.configured_hosts()] == ["laptop"]

    monkeypatch.setenv("DESKTOP_OLLAMA_URL", RIG)
    assert [h[0] for h in oh.configured_hosts()] == ["laptop", "desktop"]


def test_a_desktop_preferred_model_goes_to_the_rig_even_when_both_have_it(loop):
    """gemma4 spills off the laptop's 8 GB card into CPU; a network hop beats that."""
    seed(laptop_tags=["gemma4:12b", "qwen3:4b"], rig_tags=["gemma4:12b"])
    assert loop.run_until_complete(oh.resolve("gemma4:12b")) == (RIG, "desktop-preferred")


def test_an_ordinary_model_prefers_the_laptop(loop):
    seed(laptop_tags=["qwen3:4b"], rig_tags=["qwen3:4b"])
    assert loop.run_until_complete(oh.resolve("qwen3:4b")) == (LAPTOP, "laptop")


def test_a_rig_only_model_resolves_to_the_rig(loop):
    seed(laptop_tags=["qwen3:4b"], rig_tags=["hermes4:14b-q5"])
    assert loop.run_until_complete(oh.resolve("hermes4:14b-q5")) == (RIG, "desktop")


def test_absent_means_every_host_answered_and_none_has_it(loop):
    seed(laptop_tags=["qwen3:4b"], rig_tags=["gemma4:12b"])
    assert loop.run_until_complete(oh.resolve("does-not-exist:1b")) == (None, "absent")


def test_unknown_is_not_absent_when_a_host_is_down(loop):
    """The failure a caller must never treat as 'not installed' — substituting a
    different model here is how a user's own selection got silently overridden."""
    seed(laptop_tags=["qwen3:4b"], rig_up=False, rig_last_good=["gemma4:12b"])
    assert loop.run_until_complete(oh.resolve("gemma4:12b")) == (None, "unknown")
    assert loop.run_until_complete(oh.resolve("does-not-exist:1b")) == (None, "unknown")


def test_a_reachable_hosts_model_still_resolves_while_the_other_is_down(loop):
    seed(laptop_tags=["qwen3:4b"], rig_up=False, rig_last_good=["gemma4:12b"])
    assert loop.run_until_complete(oh.resolve("qwen3:4b")) == (LAPTOP, "laptop")


def test_available_is_the_union_and_is_None_when_nothing_answered(loop):
    seed(laptop_tags=["qwen3:4b"], rig_tags=["gemma4:12b"])
    assert loop.run_until_complete(oh.available()) == {"qwen3:4b", "gemma4:12b"}

    seed(laptop_up=False, rig_up=False, laptop_tags=["qwen3:4b"], rig_last_good=["gemma4:12b"])
    assert loop.run_until_complete(oh.available()) is None, (
        "an empty set would read as 'you have no models installed'"
    )


def test_unreachable_models_names_the_tags_and_the_host(loop):
    seed(laptop_tags=["qwen3:4b"], rig_up=False,
         rig_last_good=["gemma4:12b", "hermes4:14b-q5"])
    out = loop.run_until_complete(oh.unreachable_models())
    assert [t for t, _ in out] == ["gemma4:12b", "hermes4:14b-q5"]
    assert all(st.label == "Desktop 5080" and st.error == "ConnectTimeout" for _, st in out)


def test_a_tag_a_live_host_also_serves_is_not_called_unreachable(loop):
    """granite4.1:8b sits on both boxes. The rig being asleep does not take it away."""
    seed(laptop_tags=["granite4.1:8b"], rig_up=False,
         rig_last_good=["granite4.1:8b", "gemma4:12b"])
    assert [t for t, _ in loop.run_until_complete(oh.unreachable_models())] == ["gemma4:12b"]


def test_an_empty_model_name_never_resolves(loop):
    seed(laptop_tags=["qwen3:4b"], rig_tags=["gemma4:12b"])
    assert loop.run_until_complete(oh.resolve("")) == (None, "absent")
    assert loop.run_until_complete(oh.resolve("   ")) == (None, "absent")


def test_invalidate_expires_the_ttl_but_keeps_what_the_hosts_last_served():
    seed(laptop_tags=["qwen3:4b"], rig_tags=["gemma4:12b"])
    oh.invalidate()
    assert oh._cache_at == 0.0
    assert oh._cache["desktop"].last_good_tags == {"gemma4:12b"}
