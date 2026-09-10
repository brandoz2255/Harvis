"""plugins.inference_nodes — registry parsing, the thinking policy, and resolution.

No network: ``probe`` is exercised by seeding its cache the way the Ollama-hosts
tests do, so what is under test is the contract (absent vs unknown, priority order,
URL ownership) and not a socket.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.inference_nodes import control, moe, policy, probe, provision, registry  # noqa: E402
from plugins.inference_nodes.types import NodeSpec, NodeState  # noqa: E402


@pytest.fixture(scope="module")
def loop():
    lp = asyncio.new_event_loop()
    yield lp
    lp.close()


@pytest.fixture(autouse=True)
def _clean_probe(monkeypatch):
    probe._cache.clear()
    probe._cache_at = 0.0
    probe._lock = asyncio.Lock()
    monkeypatch.delenv(registry.ENV_VAR, raising=False)
    monkeypatch.delenv("HARVIS_NODE_THINKING", raising=False)
    yield
    probe._cache.clear()
    probe._cache_at = 0.0


def _seed(*states: NodeState) -> None:
    for st in states:
        probe._cache[st.spec.name] = st
    probe._cache_at = time.time()


# ── registry ────────────────────────────────────────────────────────────────

def test_parse_env_shorthand(monkeypatch):
    monkeypatch.setenv("FT_TOKEN", "s3cret")
    raw = (
        "freetoken=http://host.docker.internal:1919/v1|dialect=openai|label=FreeToken (laptop)"
        "|hw=RTX 5070 8GB|token_env=FT_TOKEN, rig=http://10.0.0.5:8000|priority=10"
    )
    specs = registry.parse_env(raw)
    assert [s.name for s in specs] == ["freetoken", "rig"]
    ft, rig = specs
    assert ft.base_url == "http://host.docker.internal:1919"      # /v1 stripped
    assert ft.chat_url == "http://host.docker.internal:1919/v1/chat/completions"
    assert ft.label == "FreeToken (laptop)"
    assert ft.hardware == "RTX 5070 8GB"
    assert ft.token == "s3cret"
    assert ft.headers()["Authorization"] == "Bearer s3cret"
    assert ft.public()["has_token"] is True and "token" not in ft.public()
    assert rig.priority == 10 and rig.label == "rig" and rig.token == ""


def test_parse_env_json_and_bad_entries():
    raw = '[{"name":"a","base_url":"http://a:1","hardware":"x"},{"name":"bad","base_url":"ftp://no"}]'
    specs = registry.parse_env(raw)
    assert [s.name for s in specs] == ["a"]
    assert registry.parse_env("") == [] and registry.parse_env(None) == []
    assert registry.parse_env("nonsense") == []
    assert registry.parse_env("x=http://ok:1,junk,y=not-a-url") and len(registry.parse_env("x=http://ok:1,junk,y=not-a-url")) == 1


def test_spec_validation():
    with pytest.raises(ValueError):
        NodeSpec(name="n", base_url="http://x", dialect="grpc")
    with pytest.raises(ValueError):
        NodeSpec(name="", base_url="http://x")


def test_configured_nodes_env_only_sorted(loop, monkeypatch):
    monkeypatch.setenv(registry.ENV_VAR, "b=http://b:1|priority=5, a=http://a:1|priority=5, off=http://c:1|enabled=false")
    specs = loop.run_until_complete(registry.configured_nodes(None))
    assert [s.name for s in specs] == ["a", "b"]


# ── policy ──────────────────────────────────────────────────────────────────

def test_policy_auto_turns_thinking_off_for_tools_and_small_budgets():
    assert policy.shape_body({"messages": [], "tools": [{}]})["chat_template_kwargs"] == {"enable_thinking": False}
    assert policy.shape_body({"messages": [], "max_tokens": 64})["chat_template_kwargs"] == {"enable_thinking": False}
    assert policy.shape_body({"messages": [], "metadata": {"task": "title_generation"}})["chat_template_kwargs"] == {"enable_thinking": False}


def test_policy_auto_leaves_plain_chat_to_the_model():
    out = policy.shape_body({"messages": [], "stream": True})
    assert "chat_template_kwargs" not in out


def test_policy_respects_explicit_caller_choice(monkeypatch):
    body = {"messages": [], "tools": [{}], "chat_template_kwargs": {"enable_thinking": True}}
    assert policy.shape_body(body)["chat_template_kwargs"] == {"enable_thinking": True}
    assert "chat_template_kwargs" not in policy.shape_body({"messages": [], "reasoning_effort": "none"})
    monkeypatch.setenv("HARVIS_NODE_THINKING", "off")
    assert policy.shape_body({"messages": []})["chat_template_kwargs"] == {"enable_thinking": False}
    monkeypatch.setenv("HARVIS_NODE_THINKING", "on")
    assert policy.shape_body({"messages": [], "tools": [{}]})["chat_template_kwargs"] == {"enable_thinking": True}


def test_policy_drops_ollama_only_keys_and_maps_max_completion_tokens():
    body = {"messages": [], "options": {"num_ctx": 1}, "keep_alive": "5m", "format": "json",
            "max_completion_tokens": 2000, "stream_options": {"include_usage": True}}
    out = policy.shape_body(body)
    assert "options" not in out and "keep_alive" not in out and "format" not in out
    assert out["max_tokens"] == 2000 and "max_completion_tokens" not in out
    assert out["stream_options"] == {"include_usage": True}      # OpenAI key, kept
    assert body["options"] == {"num_ctx": 1}                      # input untouched


# ── probe / resolve ─────────────────────────────────────────────────────────

def test_resolve_present_absent_unknown(loop):
    ft = NodeSpec(name="ft", base_url="http://ft:1919", label="FreeToken")
    rig = NodeSpec(name="rig", base_url="http://rig:8000", priority=10)
    _seed(
        NodeState(spec=ft, reachable=True, models={"Qwen3.6-35B"}, ctx={"Qwen3.6-35B": 262144}),
        NodeState(spec=rig, reachable=False, error="ConnectError", last_good_models={"gemma4:26b"}),
    )
    st, why = loop.run_until_complete(probe.resolve("Qwen3.6-35B"))
    assert st is not None and st.spec.name == "ft" and why == "ft"
    st, why = loop.run_until_complete(probe.resolve("gemma4:26b"))
    assert st is None and why == "unknown:rig"
    st, why = loop.run_until_complete(probe.resolve("nope"))
    assert st is None and why == "absent"
    assert loop.run_until_complete(probe.resolve("")) == (None, "absent")


def test_resolve_prefers_lower_priority(loop):
    a = NodeSpec(name="a", base_url="http://a:1", priority=100)
    b = NodeSpec(name="b", base_url="http://b:1", priority=1)
    _seed(NodeState(spec=a, reachable=True, models={"m"}), NodeState(spec=b, reachable=True, models={"m"}))
    st, why = loop.run_until_complete(probe.resolve("m"))
    assert why == "b"


def test_resolve_with_no_nodes(loop):
    _seed()   # sets the timestamp with an empty cache → no probe, no nodes
    assert loop.run_until_complete(probe.resolve("m")) == (None, "no-nodes")


def test_unreachable_models_and_node_for_url(loop):
    ft = NodeSpec(name="ft", base_url="http://ft:1919/")
    down = NodeSpec(name="down", base_url="http://down:1")
    _seed(
        NodeState(spec=ft, reachable=True, models={"x"}),
        NodeState(spec=down, reachable=False, last_good_models={"x", "y"}),
    )
    assert loop.run_until_complete(probe.unreachable_models()) == [("y", probe._cache["down"])]
    assert probe.node_for_url("http://ft:1919/v1/chat/completions") is ft
    assert probe.node_for_url("http://ft:1919") is ft
    assert probe.node_for_url("http://ft:19190/v1/chat/completions") is None
    assert probe.node_for_url("http://host.docker.internal:11434/v1/chat/completions") is None
    assert probe.node_for_url("") is None


def test_node_for_url_falls_back_to_env_before_any_probe(monkeypatch):
    monkeypatch.setenv(registry.ENV_VAR, "ft=http://ft:1919")
    assert probe.node_for_url("http://ft:1919/v1/chat/completions").name == "ft"


# ── task-gen on a node (title / tags fallback while Ollama cannot load) ─────────


def _reachable(name, models, priority=100):
    spec = NodeSpec(name=name, base_url=f"http://{name}:1919", priority=priority)
    st = NodeState(spec=spec, reachable=True, models=set(models))
    st.last_good_models = set(models)
    return st


def test_node_complete_uses_first_reachable_node_thinking_off(loop, monkeypatch):
    from plugins.inference_nodes import taskgen

    probe._cache.update({
        "down": NodeState(spec=NodeSpec(name="down", base_url="http://down:1", priority=1)),
        "ft": _reachable("ft", {"Qwen3.6-35B-A3B-NVFP4"}, priority=50),
    })
    probe._cache_at = time.time()
    seen = {}

    async def fake_post(spec, body, timeout):
        seen["spec"] = spec
        seen["body"] = body
        return "  Docker Layer Caching\n"

    monkeypatch.setattr(taskgen, "_post", fake_post)
    out = loop.run_until_complete(taskgen.complete("Message: docker caching\nTitle:", max_tokens=24))
    assert out == "Docker Layer Caching"
    assert seen["spec"].name == "ft"
    assert seen["body"]["model"] == "Qwen3.6-35B-A3B-NVFP4"
    assert seen["body"]["stream"] is False
    assert seen["body"]["max_tokens"] == 24
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_node_complete_none_when_no_node_answers(loop, monkeypatch):
    from plugins.inference_nodes import taskgen

    probe._cache.update({"ft": _reachable("ft", {"m"})})
    probe._cache_at = time.time()

    async def boom(spec, body, timeout):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(taskgen, "_post", boom)
    assert loop.run_until_complete(taskgen.complete("x")) is None
    assert loop.run_until_complete(taskgen.complete("   ")) is None


def test_node_complete_none_with_no_nodes(loop):
    from plugins.inference_nodes import taskgen

    probe._cache_at = time.time()  # empty cache, fresh TTL → no probe, no nodes
    assert loop.run_until_complete(taskgen.complete("x")) is None


def test_kv_capacity_caps_the_paper_context():
    assert probe.kv_capacity({"kv": {"total_pages": 4098, "page_size": 1}}) == 4098
    assert probe.kv_capacity({"kv": {"total_pages": 256, "page_size": 16}}) == 4096
    assert probe.kv_capacity({"kv": {}}) is None
    assert probe.kv_capacity(None) is None
    assert probe.kv_capacity({"kv": {"total_pages": 0}}) is None


def test_policy_turns_thinking_off_when_the_cache_leaves_no_room(monkeypatch):
    monkeypatch.setenv("HARVIS_NODE_CHARS_PER_TOKEN", "1")
    big = {"model": "m", "messages": [{"role": "user", "content": "x" * 3300}]}
    small = {"model": "m", "messages": [{"role": "user", "content": "x" * 300}]}
    assert policy.decide_thinking(big, "auto", ctx_cap=4098) is False
    assert policy.decide_thinking(small, "auto", ctx_cap=4098) is None
    assert policy.decide_thinking(big, "auto", ctx_cap=None) is None
    # An explicit caller choice still wins.
    big["chat_template_kwargs"] = {"enable_thinking": True}
    assert policy.decide_thinking(big, "auto", ctx_cap=4098) is None


def test_shape_body_reads_the_probed_cache_size(monkeypatch):
    monkeypatch.setenv("HARVIS_NODE_CHARS_PER_TOKEN", "1")
    spec = NodeSpec(name="ft", base_url="http://ft:1919")
    st = NodeState(spec=spec, reachable=True, models={"m"}, ctx={"m": 4098})
    probe._cache["ft"] = st
    body = {"model": "m", "messages": [{"role": "user", "content": "x" * 3300}]}
    out = policy.shape_body(body, spec)
    assert out["chat_template_kwargs"] == {"enable_thinking": False}
    st.ctx["m"] = 262144
    out = policy.shape_body(body, spec)
    assert "chat_template_kwargs" not in out


# --- provision -------------------------------------------------------------------
# The generated script is what a second machine actually runs, so the things worth
# pinning down are that it is valid bash, that it leaves no placeholder behind, and
# that it does not carry this laptop's tuning numbers to a bigger card.


def _bash_syntax_ok(script: str) -> bool:
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        return subprocess.run(["bash", "-n", path], capture_output=True).returncode == 0
    finally:
        os.unlink(path)


def test_provision_script_is_valid_bash_with_nothing_left_unsubstituted():
    script = provision.render_script(node_name="rig1", port=2020, host="127.0.0.1")
    assert "@@" not in script
    assert "Node: rig1" in script and "127.0.0.1:2020" in script
    assert "reverse_proxy 127.0.0.1:$FT_PORT" in script  # Caddy braces survived
    assert ":2021 {" in script  # token proxy sits one port up
    assert _bash_syntax_ok(script)


def test_provision_script_sizes_the_target_box_instead_of_copying_ours():
    script = provision.render_script()
    # No FT_* tuning value is hardcoded into the env file the script writes; each one
    # comes from the measurement block.
    for var in ("FT_MEMORY_RATIO", "FT_KV_RESERVE", "FT_MAX_RUNNING", "FT_MOE_THREADS"):
        assert f"{var}=$A_" in script
    assert "nvidia-smi --query-gpu=memory.total,memory.used" in script
    assert "# (nothing pinned by the operator" in script


def test_provision_script_appends_only_the_pins_it_was_given():
    script = provision.render_script(memory_ratio=0.85, max_running=4)
    assert "# pinned by the operator" in script
    assert "FT_MEMORY_RATIO=0.85" in script
    assert "FT_MAX_RUNNING=4" in script
    assert "FT_KV_RESERVE=None" not in script
    assert "FT_MOE_THREADS=None" not in script
    assert _bash_syntax_ok(script)


def test_provision_sizing_block_matches_the_measured_laptop_settings():
    """The inlined arithmetic is a copy of scripts/freetoken/autotune.sh. Run it."""
    import subprocess
    import textwrap

    script = provision.render_script()
    body = script.split("eval \"$(./venv/bin/python - ", 1)[1].split("<<'PY'\n", 1)[1]
    sizing = body.split("\nPY\n", 1)[0]
    # 8151 MiB card, 30 GB RAM, 8 physical cores, 21 GB checkpoint: this laptop, whose
    # ratio 0.90 / kv 16384 / prefill 2048 were measured to survive a grounded prompt.
    out = subprocess.run(
        ["python3", "-c", textwrap.dedent(sizing), "8151", "30000", "8", "21000"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    got = dict(line.split("=", 1) for line in out.stdout.strip().splitlines())
    assert got["A_RATIO"] == "0.89"
    assert got["A_KV"] == "16384"
    assert got["A_PREFILL"] == "2048"
    assert got["A_RUNNING"] == "2"
    assert got["A_THREADS"] == "6"
    assert "RAM is workable but not roomy" in got["A_WARN"]

    # A 24 GB card must not inherit the laptop's numbers.
    out = subprocess.run(
        ["python3", "-c", textwrap.dedent(sizing), "24564", "128000", "24", "21000"],
        capture_output=True,
        text=True,
    )
    big = dict(line.split("=", 1) for line in out.stdout.strip().splitlines())
    assert big["A_PREFILL"] == "8192"
    assert big["A_KV"] == "32768"
    assert big["A_RUNNING"] == "4"


# --- control: the power channel -------------------------------------------------
#
# The channel is two JSON files in a shared directory, so it is testable without a
# host, a systemd bus or a container: point CONTROL_DIR at a tmpdir and play both
# sides. What is under test is the contract the settings pane depends on — "no agent"
# must never read as "node is off", and "loading" must never read as "on".


@pytest.fixture
def control_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "CONTROL_DIR", str(tmp_path / "ctl"))
    return tmp_path / "ctl"


def _agent_says(control_dir, state, *, want_at=0.0, error=None):
    """Stand in for the host agent writing status.json."""
    import json
    control_dir.mkdir(parents=True, exist_ok=True)
    (control_dir / control.STATUS).write_text(json.dumps({
        "state": state, "applied_at": time.time(),
        "last_desired_at": want_at, "error": error, "unit": "freetoken.service",
    }))


def test_serving_waits_for_the_checkpoint_not_just_the_socket():
    """FreeToken answers /v1/models while still loading; /health is the honest signal."""
    assert control.serving({"status": "loading", "phase": "other"}) is False
    assert control.serving({"status": "ok", "maintenance": "serving"}) is True
    assert control.serving({"status": "ok", "maintenance": "draining"}) is False
    # A node with no /health at all (vLLM, llama-server) is taken at its word.
    assert control.serving({}) is True
    assert control.serving(None) is True


def test_power_state_without_an_agent_says_uncontrollable_not_off(control_dir):
    out = control.power_state()
    assert out["controllable"] is False
    assert out["running"] is False
    assert "install-user-units.sh" in out["hint"]


def test_request_round_trips_through_the_shared_directory(control_dir):
    rec = control.request("off", by="tester", reason="unit test")
    assert rec["state"] == "off"
    got = control.desired()
    assert got["state"] == "off" and got["by"] == "tester"
    # No leftover half-written file: the write is a rename, not a truncate-in-place.
    assert not (control_dir / (control.DESIRED + ".tmp")).exists()
    with pytest.raises(ValueError):
        control.request("reboot")


def test_power_state_reports_loading_separately_from_running(control_dir):
    _agent_says(control_dir, "active")
    loading = NodeState(spec=NodeSpec(name="freetoken", base_url="http://x:1919"))
    loading.reachable = True
    loading.health = {"status": "loading"}
    out = control.power_state(loading)
    assert out["running"] is False and out["loading"] is True

    ready = NodeState(spec=NodeSpec(name="freetoken", base_url="http://x:1919"))
    ready.reachable = True
    ready.health = {"status": "ok", "maintenance": "serving"}
    out = control.power_state(ready)
    assert out["running"] is True and out["loading"] is False
    assert out["controllable"] is True and out["unit_state"] == "active"


def test_agent_stale_only_after_the_grace_period(control_dir):
    now = time.time()
    _agent_says(control_dir, "active", want_at=now)
    control.request("on")
    # Just asked: the agent has not had time to answer, so this is not staleness.
    assert control.power_state()["agent_stale"] is False
    _agent_says(control_dir, "inactive", want_at=0.0)
    assert control._stale(control.agent_status(), now - control.AGENT_STALE_S - 5) is True


# --- moe: which installed models are sparse ------------------------------------


def _show(family="qwen35moe", total=256, active=8, params="35.1B"):
    info = {f"{family}.block_count": 48}
    if total is not None:
        info[f"{family}.expert_count"] = total
        info[f"{family}.expert_used_count"] = active
    return {"model_info": info, "details": {"parameter_size": params, "family": family}}


def test_expert_info_reads_gguf_metadata_not_the_model_name():
    ex = moe.expert_info(_show())
    assert ex == {"total": 256, "active": 8, "family": "qwen35moe"}
    assert moe.expert_info(_show("gptoss", 32, 4, "20.9B"))["total"] == 32
    # Dense: no expert keys at all, and the "1 expert" spelling some checkpoints use.
    assert moe.expert_info(_show("llama", None, None, "8.0B")) is None
    assert moe.expert_info(_show("llama", 1, 1, "8.0B")) is None
    assert moe.expert_info({}) is None


def test_param_and_active_param_counts():
    assert moe.param_count(_show()) == 35.1e9
    assert moe.param_count({"details": {"parameter_size": "nonsense"}}) is None
    # 8 of 256 experts: roughly 1.1B active, the reason this runs on an 8 GB card.
    assert moe.active_params(_show()) == pytest.approx(35.1e9 * 8 / 256)
    assert moe.active_params(_show("llama", None, None, "8.0B")) is None


def test_verdict_separates_worth_a_node_from_dense_and_already_served():
    big = _show()
    kind, why = moe.verdict("qwen3.6-35b", moe.expert_info(big), moe.param_count(big),
                            set(), True)
    assert kind == "node_would_help" and "8 of 256" in why

    kind, _ = moe.verdict("qwen3.6-35b", moe.expert_info(big), moe.param_count(big),
                          {"qwen3.6-35b"}, True)
    assert kind == "served_by_node"

    dense = _show("llama", None, None, "8.0B")
    kind, _ = moe.verdict("llama3.1:8b", moe.expert_info(dense), moe.param_count(dense),
                          set(), True)
    assert kind == "dense"

    # Sparse but small: Ollama handles it, so a node is not the answer.
    small = _show("gptoss", 32, 4, "3.0B")
    kind, _ = moe.verdict("tiny-moe", moe.expert_info(small), moe.param_count(small),
                          set(), True)
    assert kind == "fits_anyway"
