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
RIG = "http://192.168.5.58:11434"


def seed(*, laptop_up=True, rig_up=True, laptop_tags=None, rig_tags=None,
         rig_last_good=None):
    """Install a probe result without probing, and freeze the TTL so nothing re-probes."""
    states = {
        oh.LOCAL: oh.HostState(
            name=oh.LOCAL, base_url=LAPTOP, label="Ollama",
            reachable=laptop_up,
            tags=set(laptop_tags or []) if laptop_up else set(),
            last_good_tags=set(laptop_tags or []),
            error=None if laptop_up else "ConnectTimeout",
        ),
        "desktop": oh.HostState(
            name="desktop", base_url=RIG, label="Second machine",
            prefer=oh.DESKTOP_PREFERRED_PREFIXES,
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
    monkeypatch.delenv("HARVIS_OLLAMA_HOSTS", raising=False)
    assert [h[0] for h in oh.configured_hosts()] == [oh.LOCAL]

    monkeypatch.setenv("DESKTOP_OLLAMA_URL", RIG)
    assert [h[0] for h in oh.configured_hosts()] == [oh.LOCAL, "desktop"]


def test_a_desktop_preferred_model_goes_to_the_rig_even_when_both_have_it(loop):
    """gemma4 spills off the laptop's 8 GB card into CPU; a network hop beats that."""
    seed(laptop_tags=["gemma4:12b", "qwen3:4b"], rig_tags=["gemma4:12b"])
    assert loop.run_until_complete(oh.resolve("gemma4:12b")) == (RIG, "desktop-preferred")


def test_an_ordinary_model_prefers_the_laptop(loop):
    seed(laptop_tags=["qwen3:4b"], rig_tags=["qwen3:4b"])
    assert loop.run_until_complete(oh.resolve("qwen3:4b")) == (LAPTOP, oh.LOCAL)


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
    assert loop.run_until_complete(oh.resolve("qwen3:4b")) == (LAPTOP, oh.LOCAL)


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
    assert all(st.label == "Second machine" and st.error == "ConnectTimeout" for _, st in out)


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


# ── Any number of machines, of any kind ─────────────────────────────────────────────

STUDIO = "http://10.0.0.20:11434"
LAB = "https://lab-gpu.example:11434"


def seed_many(*, local=(), studio=(), lab=(), lab_up=True, studio_prefer=()):
    def st(name, url, label, tags, up=True, prefer=()):
        return oh.HostState(
            name=name, base_url=url, label=label, prefer=tuple(prefer), reachable=up,
            tags=set(tags) if up else set(), last_good_tags=set(tags),
            error=None if up else "ConnectTimeout",
        )
    oh._cache.clear()
    oh._cache.update({
        oh.LOCAL: st(oh.LOCAL, LAPTOP, "Ollama", local),
        "studio": st("studio", STUDIO, "Mac Studio", studio, prefer=studio_prefer),
        "lab": st("lab", LAB, "Lab GPU", lab, up=lab_up),
    })
    oh._cache_at = time.time()


def test_hosts_env_takes_any_number_of_named_machines(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.delenv("DESKTOP_OLLAMA_URL", raising=False)
    monkeypatch.setenv(
        "HARVIS_OLLAMA_HOSTS",
        f"studio={STUDIO}/v1|label=Mac Studio|prefer=llama3.3+Gemma4, lab={LAB}",
    )
    hosts = oh.configured_hosts()
    assert [(h.name, h.base_url, h.label) for h in hosts] == [
        (oh.LOCAL, LAPTOP, "Ollama"),
        ("studio", STUDIO, "Mac Studio"),
        ("lab", LAB, "lab"),
    ]
    assert hosts[1].prefer == ("llama3.3", "gemma4")
    assert hosts[2].prefer == ()


def test_hosts_env_accepts_json(monkeypatch):
    monkeypatch.setenv(
        "HARVIS_OLLAMA_HOSTS",
        '[{"name": "studio", "url": "%s", "label": "Mac Studio", "prefer": ["llama3.3"]}]' % STUDIO,
    )
    [studio] = [h for h in oh.configured_hosts() if h.name == "studio"]
    assert studio.prefer == ("llama3.3",) and studio.label == "Mac Studio"


@pytest.mark.parametrize("raw", [
    "Bad Name=http://x:11434",          # spaces / capitals in the name
    "local=http://x:11434",             # cannot shadow this machine
    "studio=ftp://x:11434",             # not http(s)
    "studio",                           # no URL at all
    "[not json",
])
def test_a_bad_hosts_entry_is_skipped_not_fatal(monkeypatch, raw):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.delenv("DESKTOP_OLLAMA_URL", raising=False)
    monkeypatch.setenv("HARVIS_OLLAMA_HOSTS", raw + f", lab={LAB}" if not raw.startswith("[") else raw)
    names = [h.name for h in oh.configured_hosts()]
    assert names[0] == oh.LOCAL and "local" not in names[1:]
    assert all(n in (oh.LOCAL, "lab") for n in names)


def test_the_same_machine_listed_twice_is_one_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.setenv("DESKTOP_OLLAMA_URL", STUDIO)
    monkeypatch.setenv("HARVIS_OLLAMA_HOSTS", f"studio={STUDIO}|label=Mac Studio, again={LAPTOP}")
    assert [h.name for h in oh.configured_hosts()] == [oh.LOCAL, "studio"]


def test_the_legacy_desktop_host_takes_its_label_from_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.delenv("HARVIS_OLLAMA_HOSTS", raising=False)
    monkeypatch.setenv("DESKTOP_OLLAMA_URL", RIG)
    monkeypatch.setenv("DESKTOP_OLLAMA_LABEL", "Mac Studio")
    assert oh.configured_hosts()[1].label == "Mac Studio"
    monkeypatch.delenv("DESKTOP_OLLAMA_LABEL")
    label = oh.configured_hosts()[1].label
    assert label == "Second machine" and "192.168" not in label


def test_this_machine_keeps_a_model_it_has_unless_another_prefers_it(loop):
    seed_many(local=["qwen3:4b", "llama3.3:70b"], studio=["qwen3:4b", "llama3.3:70b"],
              studio_prefer=("llama3.3",))
    assert loop.run_until_complete(oh.resolve("qwen3:4b")) == (LAPTOP, oh.LOCAL)
    assert loop.run_until_complete(oh.resolve("llama3.3:70b")) == (STUDIO, "studio-preferred")


def test_a_model_goes_to_the_first_machine_that_has_it(loop):
    seed_many(local=["qwen3:4b"], studio=["gpt-oss:120b"], lab=["gpt-oss:120b", "qwen3:235b"])
    assert loop.run_until_complete(oh.resolve("gpt-oss:120b")) == (STUDIO, "studio")
    assert loop.run_until_complete(oh.resolve("qwen3:235b")) == (LAB, "lab")


def test_a_third_machine_being_down_is_unknown_not_absent(loop):
    seed_many(local=["qwen3:4b"], studio=["gpt-oss:120b"], lab=["qwen3:235b"], lab_up=False)
    assert loop.run_until_complete(oh.resolve("qwen3:235b")) == (None, "unknown")
    out = loop.run_until_complete(oh.unreachable_models())
    assert [(t, st.label) for t, st in out] == [("qwen3:235b", "Lab GPU")]


def test_route_never_probes_a_single_machine_install(loop, monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.delenv("HARVIS_OLLAMA_HOSTS", raising=False)
    monkeypatch.delenv("DESKTOP_OLLAMA_URL", raising=False)

    async def boom(**_):
        raise AssertionError("a single-machine install must not probe")

    monkeypatch.setattr(oh, "snapshot", boom)
    assert loop.run_until_complete(oh.route("anything:1b", "http://mine:11434/v1/")) == (
        "http://mine:11434/v1", oh.LOCAL, "single")


def test_route_keeps_the_callers_ollama_unless_another_machine_should_serve(loop, monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.setenv("HARVIS_OLLAMA_HOSTS", f"studio={STUDIO}|label=Mac Studio, lab={LAB}")
    monkeypatch.delenv("DESKTOP_OLLAMA_URL", raising=False)
    seed_many(local=["qwen3:4b"], studio=["gpt-oss:120b"], lab=["qwen3:235b"], lab_up=False)
    mine = LAPTOP + "/v1"   # the saved provider is this install's own Ollama
    run = loop.run_until_complete
    assert run(oh.route("qwen3:4b", mine)) == (mine, oh.LOCAL, oh.LOCAL)
    assert run(oh.route("gpt-oss:120b", mine)) == (STUDIO, "studio", "studio")
    assert run(oh.route("qwen3:235b", mine)) == (mine, oh.LOCAL, "unknown")
    assert oh.host_label("studio") == "Mac Studio"


def test_route_never_moves_a_users_own_ollama_to_an_operator_machine(loop, monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.setenv("HARVIS_OLLAMA_HOSTS", f"studio={STUDIO}")
    monkeypatch.delenv("DESKTOP_OLLAMA_URL", raising=False)
    seed_many(studio=["gpt-oss:120b"])
    theirs = "https://their-ollama.example:11434"
    assert loop.run_until_complete(oh.route("gpt-oss:120b", theirs)) == (theirs, oh.LOCAL, "custom")


@pytest.mark.parametrize("asked", ["qwen3", "Qwen3", "QWEN3:LATEST", "qwen3:latest"])
def test_a_name_ollama_would_serve_counts_as_installed(asked):
    st = oh.HostState(name=oh.LOCAL, base_url=LAPTOP, label="Ollama", reachable=True,
                      tags={"qwen3:latest", "hf.co/org/model:q4"})
    assert st.has(asked)
    assert not st.has("qwen3:4b")
    assert st.has("HF.co/org/model:Q4") and not st.has("hf.co/org/model")


def test_legacy_desktop_repeated_in_hosts_env_is_dropped_with_one_warning(monkeypatch, caplog):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.setenv("HARVIS_OLLAMA_HOSTS", f"desktop={RIG}")
    monkeypatch.setenv("DESKTOP_OLLAMA_URL", RIG)
    monkeypatch.setattr(oh, "_warned_dupe", [])
    with caplog.at_level("WARNING", logger=oh.logger.name):
        hosts = oh.configured_hosts()
        oh.configured_hosts()
    assert [h.name for h in hosts] == [oh.LOCAL, "desktop"] and hosts[1].prefer == ()
    assert sum("DESKTOP_OLLAMA_URL" in r.message for r in caplog.records) == 1


def test_desktop_equal_to_this_machine_is_not_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("OLLAMA_URL", LAPTOP)
    monkeypatch.delenv("HARVIS_OLLAMA_HOSTS", raising=False)
    monkeypatch.setenv("DESKTOP_OLLAMA_URL", LAPTOP + "/v1")
    monkeypatch.setattr(oh, "_warned_dupe", [])
    with caplog.at_level("WARNING", logger=oh.logger.name):
        assert [h.name for h in oh.configured_hosts()] == [oh.LOCAL]
    assert not caplog.records
