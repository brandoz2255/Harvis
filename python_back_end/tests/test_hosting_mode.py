"""Hosting-mode detection, the /api/capabilities/hosting payload, and the
service-health wording that follows it. The Kubernetes API is faked with
httpx.MockTransport; nothing opens a socket and no cluster is needed."""
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import setup_flow  # noqa: E402
from plugins.hosting import cluster  # noqa: E402
from plugins.hosting import describe_hosting, hosting_mode, profile_not_enabled_reason  # noqa: E402

DOCKER_WORDING = "compose profile 'voice' is not enabled"
K8S_WORDING = (
    "not deployed in this cluster — add 'voice' to COMPOSE_PROFILES in .env "
    "and re-run ./install.sh --k8s"
)


def fake_node(name, *, ready=True, roles=(), gpus=None, cpu="8", memory="16384000Ki", version="v1.31.2+k3s1"):
    labels = {f"node-role.kubernetes.io/{r}": "true" for r in roles}
    allocatable = {"cpu": cpu, "memory": memory}
    if gpus is not None:
        allocatable["nvidia.com/gpu"] = str(gpus)
    return {
        "metadata": {"name": name, "labels": labels},
        "status": {
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "allocatable": allocatable,
            "capacity": {"cpu": cpu, "memory": memory},
            "nodeInfo": {"kubeletVersion": version},
        },
    }


def no_nodes():
    return []


# ─── Mode detection --------------------------------------------------------------


def test_default_is_docker():
    out = describe_hosting({}, no_nodes, docker_socket_path="/nonexistent/docker.sock")
    assert (out["mode"], out["detected_by"]) == ("docker", "default")
    assert out["namespace"] is None
    assert out["nodes"] == [] and out["nodes_error"] is None
    assert out["gpu"] == {"available": False, "count": 0}
    assert out["lan_models"] == {"enabled": False, "url": None}
    assert out["docker_socket"] is False
    assert out["commands"] == {
        "enable": "./install.sh --k8s",
        "disable": "./install.sh --k8s-off",
        "status": "./install.sh --k8s-status",
        "join": "./install.sh --k8s-join-command",
    }


def test_override_env_wins_both_ways():
    assert hosting_mode({"HARVIS_HOSTING_MODE": "kubernetes"}) == ("kubernetes", "override")
    assert hosting_mode({"HARVIS_HOSTING_MODE": "K8s"}) == ("kubernetes", "override")
    # A pod told to behave as docker is docker, detected by override.
    assert hosting_mode({"HARVIS_HOSTING_MODE": "docker", "KUBERNETES_SERVICE_HOST": "10.43.0.1"}) == ("docker", "override")
    # A typo is not trusted; the cluster signal still counts.
    assert hosting_mode({"HARVIS_HOSTING_MODE": "kubernets", "KUBERNETES_SERVICE_HOST": "10.43.0.1"}) == ("kubernetes", "cluster")


def test_cluster_env_detection_and_namespace():
    env = {"KUBERNETES_SERVICE_HOST": "10.43.0.1", "KUBERNETES_SERVICE_PORT": "443"}
    out = describe_hosting(env, no_nodes)
    assert (out["mode"], out["detected_by"], out["namespace"]) == ("kubernetes", "cluster", "harvis")
    out = describe_hosting({**env, "HARVIS_K8S_NAMESPACE": "lab"}, no_nodes)
    assert out["namespace"] == "lab"


def test_docker_gpu_and_lan_models_come_from_env():
    out = describe_hosting({"HARVIS_GPU_RUNTIME": "nvidia", "HARVIS_LAN_MODELS_URL": "http://192.168.8.100:31434"}, no_nodes)
    assert out["gpu"] == {"available": True, "count": 0}
    assert out["lan_models"] == {"enabled": True, "url": "http://192.168.8.100:31434"}


# ─── Node parsing ----------------------------------------------------------------


def test_node_parsing_from_fake_list():
    nodes = [
        fake_node("pi5-master", roles=("control-plane", "master"), gpus=0, cpu="4", memory="8192000Ki"),
        fake_node("rig-4090", ready=False, gpus=1, cpu="16", memory="67108864Ki", version="v1.31.2+k3s2"),
        fake_node("pi4-worker", memory="4Gi"),
    ]
    out = describe_hosting({"KUBERNETES_SERVICE_HOST": "10.43.0.1"}, lambda: nodes)
    assert out["nodes_error"] is None
    master, rig, pi4 = out["nodes"]
    assert master == {
        "name": "pi5-master", "ready": True, "roles": ["control-plane", "master"],
        "gpus": 0, "cpu": "4", "memory_gib": 7.8, "version": "v1.31.2+k3s1",
    }
    assert rig["ready"] is False and rig["gpus"] == 1 and rig["memory_gib"] == 64.0
    assert rig["roles"] == [] and rig["version"] == "v1.31.2+k3s2"
    assert pi4["memory_gib"] == 4.0
    assert out["gpu"] == {"available": True, "count": 1}


def test_stripped_node_object_does_not_break_listing():
    out = describe_hosting({"KUBERNETES_SERVICE_HOST": "10.43.0.1"}, lambda: [{"metadata": {"name": "bare"}}])
    assert out["nodes"] == [{
        "name": "bare", "ready": False, "roles": [], "gpus": 0, "cpu": "", "memory_gib": 0.0, "version": "",
    }]


# ─── Failure paths ---------------------------------------------------------------


def test_fetch_failure_sets_nodes_error_and_never_raises():
    def boom():
        raise cluster.NodeListError("the Kubernetes API answered HTTP 403")

    out = describe_hosting({"KUBERNETES_SERVICE_HOST": "10.43.0.1"}, boom)
    assert out["nodes"] == []
    assert out["nodes_error"] == "the Kubernetes API answered HTTP 403"
    assert out["gpu"] == {"available": False, "count": 0}

    def unexpected():
        raise ValueError("garbage from the api")

    out = describe_hosting({"KUBERNETES_SERVICE_HOST": "10.43.0.1"}, unexpected)
    assert out["nodes"] == [] and "garbage" in out["nodes_error"]


def test_fetch_failure_on_docker_is_never_attempted():
    def boom():
        raise AssertionError("must not list nodes under docker")

    out = describe_hosting({}, boom)
    assert out["nodes"] == [] and out["nodes_error"] is None


def _real_fetch(tmp_path, handler, *, with_token=True):
    token_path = tmp_path / "token"
    if with_token:
        token_path.write_text("sa-secret-token-XYZ\n")
    # A non-default port, so the URL assertion proves the port is honoured
    # (httpx drops a literal :443 when rendering the URL).
    env = {"KUBERNETES_SERVICE_HOST": "10.43.0.1", "KUBERNETES_SERVICE_PORT": "6443"}
    return env, lambda: cluster.list_nodes_uncached(
        env,
        token_path=str(token_path),
        ca_path=str(tmp_path / "missing-ca.crt"),
        transport=httpx.MockTransport(handler),
    )


def test_token_is_sent_but_never_appears_in_output(tmp_path):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"items": [fake_node("n1")]})

    env, fetch = _real_fetch(tmp_path, handler)
    out = describe_hosting(env, fetch)
    assert seen["auth"] == "Bearer sa-secret-token-XYZ"
    assert seen["url"] == "https://10.43.0.1:6443/api/v1/nodes"
    assert [n["name"] for n in out["nodes"]] == ["n1"]
    assert "sa-secret-token-XYZ" not in json.dumps(out)


def test_api_error_body_echoing_the_token_is_not_surfaced(tmp_path):
    def handler(request):
        # A hostile or chatty API server that reflects the header back.
        return httpx.Response(403, text=f"forbidden for {request.headers.get('authorization')}")

    env, fetch = _real_fetch(tmp_path, handler)
    out = describe_hosting(env, fetch)
    assert out["nodes"] == []
    assert "HTTP 403" in out["nodes_error"] and "RBAC" in out["nodes_error"]
    assert "sa-secret-token-XYZ" not in json.dumps(out)


def test_missing_token_file_is_a_plain_reason(tmp_path):
    env, fetch = _real_fetch(tmp_path, lambda r: httpx.Response(200, json={"items": []}), with_token=False)
    out = describe_hosting(env, fetch)
    assert out["nodes_error"].startswith("no service-account token at ")


def test_connection_error_is_a_plain_reason(tmp_path):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    env, fetch = _real_fetch(tmp_path, handler)
    out = describe_hosting(env, fetch)
    assert out["nodes_error"] == "could not reach the Kubernetes API at 10.43.0.1:6443 (ConnectError)"


def test_cached_fetch_reuses_result_for_30s(monkeypatch):
    calls = []

    def fake_list(*args, **kwargs):
        calls.append(1)
        return [fake_node("n1")]

    monkeypatch.setattr(cluster, "list_nodes_uncached", fake_list)
    cluster.reset_cache()
    try:
        assert cluster.fetch_cluster_nodes()[0]["metadata"]["name"] == "n1"
        cluster.fetch_cluster_nodes()
        assert len(calls) == 1
    finally:
        cluster.reset_cache()


def test_cached_fetch_remembers_a_failure(monkeypatch):
    def fake_list(*args, **kwargs):
        raise cluster.NodeListError("boom")

    monkeypatch.setattr(cluster, "list_nodes_uncached", fake_list)
    cluster.reset_cache()
    try:
        with pytest.raises(cluster.NodeListError):
            cluster.fetch_cluster_nodes()
        monkeypatch.setattr(cluster, "list_nodes_uncached", lambda *a, **k: [])
        with pytest.raises(cluster.NodeListError, match="boom"):
            cluster.fetch_cluster_nodes()
    finally:
        cluster.reset_cache()


def test_cached_fetch_scrubs_and_remembers_an_unexpected_error(monkeypatch):
    def fake_list(*args, **kwargs):
        raise OSError("ca.crt: Bearer leaked-token-in-message")

    monkeypatch.setattr(cluster, "list_nodes_uncached", fake_list)
    cluster.reset_cache()
    try:
        with pytest.raises(cluster.NodeListError) as first:
            cluster.fetch_cluster_nodes()
        assert str(first.value) == "listing nodes failed (OSError)"
        monkeypatch.setattr(cluster, "list_nodes_uncached", lambda *a, **k: [])
        with pytest.raises(cluster.NodeListError, match=r"\(OSError\)"):
            cluster.fetch_cluster_nodes()
    finally:
        cluster.reset_cache()


# ─── Health wording --------------------------------------------------------------


def _docker_env(monkeypatch):
    monkeypatch.delenv("HARVIS_HOSTING_MODE", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)


def test_health_wording_under_docker_is_unchanged(monkeypatch):
    _docker_env(monkeypatch)
    assert profile_not_enabled_reason("voice") == DOCKER_WORDING
    assert setup_flow._not_installed_reason("tts") == f"not installed — {DOCKER_WORDING}"


def test_health_wording_switches_under_kubernetes(monkeypatch):
    _docker_env(monkeypatch)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.43.0.1")
    assert profile_not_enabled_reason("voice") == K8S_WORDING
    assert setup_flow._not_installed_reason("tts") == K8S_WORDING

    _docker_env(monkeypatch)
    monkeypatch.setenv("HARVIS_HOSTING_MODE", "kubernetes")
    assert setup_flow._not_installed_reason("tts-service") == K8S_WORDING
