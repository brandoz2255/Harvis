"""The "Harvis default" model: how it is picked, retried, filtered and shown.

Network, database and the model list are replaced with in-memory seams; nothing leaves the process.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402
import setup_flow  # noqa: E402
from owui_compat import ollama_hosts  # noqa: E402
from plugins.hermes_ui import providers, rest, sessions, settings_store, store  # noqa: E402
from plugins.models import resolver  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def fresh_resolver(monkeypatch):
    monkeypatch.setattr(main, "_RESOLVED_DEFAULT_MODEL", None)
    monkeypatch.setattr(main, "_DEFAULT_MODEL_PROBED_AT", float("-inf"))
    monkeypatch.setattr(main, "DEFAULT_MODEL", "")
    monkeypatch.setattr(main, "LOCAL_OLLAMA_MODELS_CACHE", set())


class FakeClient:
    """httpx.Client replacement: answers /api/tags from ``tags`` or raises when it is None."""

    calls: list = []

    def __init__(self, tags):
        self.tags = tags

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        FakeClient.calls.append(url)
        if self.tags is None:
            raise OSError("unreachable")
        if url.endswith("/api/tags"):
            return SimpleNamespace(status_code=200, json=lambda: {"models": [{"name": n} for n in self.tags]})
        return SimpleNamespace(status_code=404, json=lambda: {})


def _serve(monkeypatch, tags):
    FakeClient.calls = []
    monkeypatch.setattr("httpx.Client", FakeClient(tags))


# ---- resolve_default_model -------------------------------------------------------

def test_local_cache_skips_embedders_that_sort_first(fresh_resolver):
    main.LOCAL_OLLAMA_MODELS_CACHE.update({"bge-m3:latest", "nomic-embed-text:latest", "qwen3:4b"})
    assert main.resolve_default_model() == "qwen3:4b"


def test_provider_probe_skips_embedders_and_cloud(fresh_resolver, monkeypatch):
    _serve(monkeypatch, ["nomic-embed-text:latest", "kimi-k2:cloud", "gemma3:4b"])
    assert main.resolve_default_model() == "gemma3:4b"


def test_empty_probe_is_retried_after_the_window_not_latched(fresh_resolver, monkeypatch):
    _serve(monkeypatch, [])
    assert main.resolve_default_model() == ""
    probes = len(FakeClient.calls)
    assert probes > 0
    # Inside the window nothing is probed again.
    assert main.resolve_default_model() == ""
    assert len(FakeClient.calls) == probes
    # A model pulled after boot is found once the window has passed.
    monkeypatch.setattr(main, "_DEFAULT_MODEL_PROBED_AT", main.time.monotonic() - main._DEFAULT_MODEL_RETRY_S - 1)
    _serve(monkeypatch, ["qwen3:4b"])
    assert main.resolve_default_model() == "qwen3:4b"
    # A found model is cached: no further probing.
    FakeClient.calls = []
    assert main.resolve_default_model() == "qwen3:4b"
    assert FakeClient.calls == []


def test_clear_cache_resets_the_resolver_but_not_the_routing_cache(fresh_resolver, monkeypatch):
    main.LOCAL_OLLAMA_MODELS_CACHE.add("qwen3:4b")
    assert main.resolve_default_model() == "qwen3:4b"
    monkeypatch.setattr(main, "DEFAULT_MODEL", "")
    run(main.clear_models_cache(current_user=None))
    assert main._RESOLVED_DEFAULT_MODEL is None
    assert main._DEFAULT_MODEL_PROBED_AT == float("-inf")
    assert main.LOCAL_OLLAMA_MODELS_CACHE == {"qwen3:4b"}


def test_clear_cache_restores_the_pin(fresh_resolver, monkeypatch):
    monkeypatch.setattr(main, "DEFAULT_MODEL", "pinned:1b")
    monkeypatch.setattr(main, "_RESOLVED_DEFAULT_MODEL", "something-else")
    run(main.clear_models_cache(current_user=None))
    assert main.resolve_default_model() == "pinned:1b"


def test_pin_reads_either_env_name(monkeypatch):
    src = open(main.__file__).read()
    line = next(ln for ln in src.splitlines() if ln.startswith("DEFAULT_MODEL = "))
    for env, want in (
        ({"HARVIS_DEFAULT_MODEL": "a:1b", "HARVIS_DEFAULT_LOCAL_MODEL": "b:1b"}, "a:1b"),
        ({"HARVIS_DEFAULT_MODEL": " ", "HARVIS_DEFAULT_LOCAL_MODEL": "b:1b"}, "b:1b"),
        ({"HARVIS_DEFAULT_LOCAL_MODEL": " b:1b "}, "b:1b"),
        ({}, ""),
    ):
        for key in ("HARVIS_DEFAULT_MODEL", "HARVIS_DEFAULT_LOCAL_MODEL"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        scope = {"os": os}
        exec(line, scope)
        assert scope["DEFAULT_MODEL"] == want, env


def test_compose_passes_the_pin(monkeypatch):
    here = os.path.dirname(__file__)
    for root in (os.path.join(here, "..", ".."), "/app/.."):
        path = os.path.join(root, "docker-compose.yaml")
        if os.path.exists(path):
            text = open(path).read()
            assert 'HARVIS_DEFAULT_MODEL: "${HARVIS_DEFAULT_MODEL:-}"' in text
            return
    pytest.skip("docker-compose.yaml is not mounted here")


# ---- sessions.harvis_default_model ------------------------------------------------

def test_harvis_default_model_is_async_and_runs_the_resolver_off_the_loop(monkeypatch):
    seen = {}

    def resolver_fn():
        import threading
        seen["thread"] = threading.current_thread() is not threading.main_thread()
        return "qwen3:4b"

    monkeypatch.setattr(main, "resolve_default_model", resolver_fn)
    assert asyncio.iscoroutinefunction(sessions.harvis_default_model)
    assert run(sessions.harvis_default_model()) == "qwen3:4b"
    assert seen["thread"] is True


def test_harvis_default_model_falls_back_to_other_ollama_hosts(monkeypatch):
    async def available(**kw):
        return {"nomic-embed-text:latest", "kimi:cloud", "gemma3:4b", "qwen3:4b"}

    monkeypatch.setattr(main, "resolve_default_model", lambda: "")
    monkeypatch.setattr(ollama_hosts, "available", available)
    assert run(sessions.harvis_default_model()) == "gemma3:4b"


def test_harvis_default_model_is_empty_when_nothing_answers(monkeypatch):
    async def available(**kw):
        return None

    monkeypatch.setattr(main, "resolve_default_model", lambda: "")
    monkeypatch.setattr(ollama_hosts, "available", available)
    assert run(sessions.harvis_default_model()) == ""


def _stub_create(monkeypatch, saved):
    async def resolve_model(pool, uid):
        return saved

    async def default(*a):
        return "fallback:1b"

    monkeypatch.setattr(store, "resolve_model", resolve_model)
    monkeypatch.setattr(sessions, "harvis_default_model", default)


def test_create_uses_the_saved_model_then_the_default(monkeypatch):
    _stub_create(monkeypatch, "saved:7b")
    assert run(sessions.create(None, 1)).model == "saved:7b"
    _stub_create(monkeypatch, "")
    assert run(sessions.create(None, 1)).model == "fallback:1b"


def test_create_skip_saved_ignores_a_model_that_is_gone(monkeypatch):
    _stub_create(monkeypatch, "ghost:1b")
    assert run(sessions.create(None, 1, skip_saved=True)).model == "fallback:1b"
    assert run(sessions.create(None, 1, bot={"id": "b1"}, skip_saved=True)).model == "fallback:1b"


# ---- model picker: stale default, status ------------------------------------------

def _picker(monkeypatch, current, rows):
    async def resolve_model(pool, uid):
        return current

    async def harvis_models(token, refresh=False):
        return rows

    async def list_endpoints(pool, uid):
        return [], None

    async def thinking_models():
        return frozenset()

    async def get_key(pool, uid, key, default):
        return {}

    monkeypatch.setattr(store, "resolve_model", resolve_model)
    monkeypatch.setattr(rest, "_harvis_models", harvis_models)
    monkeypatch.setattr(rest, "thinking_models", thinking_models)
    monkeypatch.setattr(providers, "list_endpoints", list_endpoints)
    monkeypatch.setattr(settings_store, "get_key", get_key)
    return run(rest.build_model_options(None, 7, "tok"))


def test_picker_shows_harvis_default_when_the_saved_model_is_gone(monkeypatch):
    options = _picker(monkeypatch, "ghost:1b", [{"id": "qwen3:4b", "owned_by": "ollama"}])
    assert options["model"] == "harvis-default"
    assert options["providers"][0]["slug"] == "harvis"


def test_picker_keeps_an_installed_saved_model(monkeypatch):
    options = _picker(monkeypatch, "qwen3:4b", [{"id": "qwen3:4b", "owned_by": "ollama"}])
    assert options["model"] == "qwen3:4b"


def test_picker_keeps_the_saved_model_when_the_list_cannot_be_read(monkeypatch):
    options = _picker(monkeypatch, "qwen3:4b", [])
    assert options["model"] == "qwen3:4b"


def test_picker_leaves_out_models_whose_host_is_down(monkeypatch):
    rows = [{"id": "qwen3:4b", "owned_by": "ollama"},
            {"id": "rig:7b", "owned_by": "ollama-desktop",
             "harvis": {"status": "unreachable", "host": "rig", "reason": "Rig is not answering"}}]
    options = _picker(monkeypatch, "rig:7b", rows)
    offered = {m for p in options["providers"] for m in p["models"]}
    assert "rig:7b" not in offered and "qwen3:4b" in offered
    assert options["model"] == "harvis-default"  # a saved model on a dead host is not started on


def test_picker_serves_the_last_list_when_a_read_fails(monkeypatch):
    rest._last_rows.pop(7, None)
    _picker(monkeypatch, "", [{"id": "qwen3:4b", "owned_by": "ollama"}])

    async def broken(token, refresh=False):
        raise TimeoutError("slow host")

    monkeypatch.setattr(rest, "_harvis_models", broken)
    options = run(rest.build_model_options(None, 7, "tok"))
    assert options["degraded"] is False
    assert "qwen3:4b" in {m for p in options["providers"] for m in p["models"]}


def test_picker_reports_an_unreadable_list_instead_of_an_empty_success(monkeypatch):
    rest._last_rows.pop(7, None)
    _picker(monkeypatch, "", [])

    async def broken(token, refresh=False):
        raise TimeoutError("slow host")

    monkeypatch.setattr(rest, "_harvis_models", broken)
    rest._last_rows.pop(7, None)
    assert run(rest.build_model_options(None, 7, "tok"))["degraded"] is True
    with pytest.raises(rest.HTTPException) as exc:
        run(rest.model_options(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=None)),
                                               headers={}, cookies={}), user={"id": 7}))
    assert exc.value.status_code == 503


def test_picker_refresh_reaches_the_backend_list(monkeypatch):
    seen = {}

    async def harvis_models(token, refresh=False):
        seen["refresh"] = refresh
        return [{"id": "qwen3:4b", "owned_by": "ollama"}]

    _picker(monkeypatch, "", [])
    monkeypatch.setattr(rest, "_harvis_models", harvis_models)
    run(rest.build_model_options(None, 7, "tok", refresh=True))
    assert seen == {"refresh": True}


def test_status_counts_only_this_users_running_sessions(monkeypatch):
    live = {
        "a": SimpleNamespace(running=True, user_id=7),
        "b": SimpleNamespace(running=False, user_id=7),
        "c": SimpleNamespace(running=True, user_id=8),
    }
    monkeypatch.setattr(sessions, "_LIVE", live)
    monkeypatch.setattr(rest.ops, "install", lambda: None)
    monkeypatch.setattr(rest.ops, "capabilities", lambda user: {})
    body = run(rest.status(user={"id": 7}))
    assert body["active_sessions"] == 1


# ---- plugins.models.resolver --------------------------------------------------------

def test_resolver_tag_list_leaves_out_embedders(monkeypatch):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"models": [{"name": "nomic-embed-text:latest"}, {"name": "bge-m3:latest"},
                                         {"name": "qwen3:4b"}]})

    monkeypatch.setattr(resolver.httpx, "AsyncClient", Client)
    assert run(resolver.list_ollama_models(ollama_url="http://x:11434")) == ["qwen3:4b"]


# ---- /api/health/services ------------------------------------------------------------

class _Conn:
    async def fetchval(self, q):
        return 1


class _Pool:
    def acquire(self):
        class _Ctx:
            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *a):
                return False

        return _Ctx()


def _health(monkeypatch, dead=()):
    urls: list[str] = []

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            urls.append(url)
            if any(d in url for d in dead):
                raise OSError("connection refused")
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    monkeypatch.setattr(main.app.state, "pg_pool", _Pool(), raising=False)
    return run(main.health_services()), urls


def test_health_services_reports_voice_onnx_and_sandbox(monkeypatch):
    monkeypatch.delenv("CODE_EXECUTOR_URL", raising=False)
    body, urls = _health(monkeypatch)
    assert body["status"] == "healthy"
    assert body["services"]["voice-onnx"]["status"] == "up"
    assert body["services"]["sandbox"]["status"] == "up"
    assert "http://voice-onnx:8000/health" in urls
    assert "http://sandbox:8080/health" in urls


def test_health_services_probes_voice_onnx_even_when_speech_points_elsewhere(monkeypatch):
    monkeypatch.setenv("HARVIS_TTS_URL", "https://speech.example/v1")
    _, urls = _health(monkeypatch)
    assert "http://voice-onnx:8000/health" in urls
    assert not any("speech.example" in u for u in urls)


@pytest.mark.parametrize("service,host", [("voice-onnx", "voice-onnx"), ("sandbox", "sandbox:8080")])
def test_health_services_flags_a_dead_default_service(monkeypatch, service, host):
    monkeypatch.delenv("CODE_EXECUTOR_URL", raising=False)
    body, _ = _health(monkeypatch, dead=(host,))
    assert body["services"][service]["status"] == "down"
    assert body["status"] == "degraded"


# ---- setup_flow: Notebooks enable command ------------------------------------------------

def _notebooks_command(monkeypatch, mode_env):
    for key in ("HARVIS_HOSTING_MODE", "KUBERNETES_SERVICE_HOST"):
        monkeypatch.delenv(key, raising=False)
    for key, value in mode_env.items():
        monkeypatch.setenv(key, value)

    async def probe():
        return {"ready": False, "skipped": True, "reason": "off", "probe": "GET x"}

    monkeypatch.setattr(setup_flow, "_probe_notebooks", probe)
    router = setup_flow.create_setup_router(get_current_user=lambda: None, require_admin=lambda: None)
    route = next(r for r in router.routes if getattr(r, "path", "") == "/api/capabilities/notebooks")
    return run(route.endpoint(_user=None))["enable"]["command"]


def test_notebooks_enable_command_is_compose_on_docker(monkeypatch):
    assert _notebooks_command(monkeypatch, {}) == "docker compose --profile notebooks up -d"


def test_notebooks_enable_command_is_the_installer_on_k8s(monkeypatch):
    command = _notebooks_command(monkeypatch, {"HARVIS_HOSTING_MODE": "kubernetes"})
    assert "COMPOSE_PROFILES" in command and "./install.sh --k8s" in command
    assert "docker compose" not in command


# ---- /api/models: sources probed together ----------------------------------------------

def test_model_list_waits_for_the_slowest_source_not_the_sum(monkeypatch):
    import time as _time

    import plugins.inference_nodes as nodes
    from owui_compat import ollama_hosts

    async def slow_hosts(**kw):
        await asyncio.sleep(0.4)
        return {}

    async def slow_nodes(**kw):
        await asyncio.sleep(0.4)
        return {}

    async def none(**kw):
        return []

    monkeypatch.setattr(ollama_hosts, "snapshot", slow_hosts)
    monkeypatch.setattr(ollama_hosts, "unreachable_models", none)
    monkeypatch.setattr(nodes, "snapshot", slow_nodes)
    monkeypatch.setattr(nodes, "unreachable_models", none)
    monkeypatch.delenv("LLAMA_URL", raising=False)
    monkeypatch.delenv("VLLM_URL", raising=False)
    monkeypatch.setattr(main, "EXTERNAL_OLLAMA_URL", "")
    monkeypatch.setattr(main, "_models_cache", {"data": None, "timestamp": 0})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=None)))
    start = _time.monotonic()
    out = run(main.list_models(request, SimpleNamespace(id=7)))
    assert out == {"models": []}
    assert _time.monotonic() - start < 0.7


def test_model_list_with_a_host_down_is_rebuilt_sooner(monkeypatch):
    monkeypatch.setattr(main, "_models_cache", {"data": None, "timestamp": 0})
    main._set_cached_models({"models": []}, ttl=main._MODELS_DEGRADED_TTL)
    main._models_cache["timestamp"] -= main._MODELS_DEGRADED_TTL + 1
    assert main._get_cached_models() is None
    main._set_cached_models({"models": []})
    main._models_cache["timestamp"] -= main._MODELS_DEGRADED_TTL + 1
    assert main._get_cached_models() == {"models": []}


def test_a_users_cloud_models_never_reach_the_shared_cache(monkeypatch):
    cached = {"models": [{"name": "qwen3:4b", "status": "available"}]}
    monkeypatch.setattr(main, "_models_cache", {"data": cached, "timestamp": main.time.time(), "ttl": 60})

    async def get_user_api_key(pool, uid, provider):
        return {"api_key": "k"} if provider == "moonshot" else None

    monkeypatch.setattr(main, "get_user_api_key", get_user_api_key)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))
    out = run(main.list_models(request, SimpleNamespace(id=7)))
    assert "kimi-k2.5" in {m["name"] for m in out["models"]}
    assert [m["name"] for m in cached["models"]] == ["qwen3:4b"]


def test_thinking_capabilities_do_not_reprobe_a_dead_ollama_on_every_open(monkeypatch):
    from plugins.hermes_ui import models as hm

    calls = []

    class Dead:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls.append(url)
            raise ConnectionError("no route")

    monkeypatch.setattr(hm.httpx, "AsyncClient", Dead)
    monkeypatch.setattr(hm, "_thinking", (0.0, frozenset()))
    assert run(hm.thinking_models()) == frozenset()
    assert run(hm.thinking_models()) == frozenset()
    assert len(calls) == 1
