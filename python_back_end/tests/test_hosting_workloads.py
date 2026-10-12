"""The admin cluster panel: services, pods, warnings and log tails from a faked
Kubernetes API. Nothing opens a socket and no cluster is needed."""
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hosting import cluster, workloads  # noqa: E402
from plugins.hosting.cluster import NodeListError  # noqa: E402

K8S = {"KUBERNETES_SERVICE_HOST": "10.43.0.1", "HARVIS_K8S_NAMESPACE": "harvis"}


def deployment(name, *, replicas=1, ready=1, app=None, image="ghcr.io/x/harvis-backend:1.5"):
    return {
        "metadata": {"name": name},
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": {"app": app or name}},
            "template": {"spec": {"containers": [{"name": name, "image": image}]}},
        },
        "status": {"readyReplicas": ready, "updatedReplicas": ready},
    }


def pod(name, app, *, ready=True, restarts=0, waiting=None, node="n1"):
    state = {"waiting": {"reason": waiting}} if waiting else {"running": {}}
    return {
        "metadata": {"name": name, "labels": {"app": app}},
        "spec": {"nodeName": node, "containers": [{"name": app}]},
        "status": {
            "phase": "Running",
            "startTime": "2026-10-12T10:00:00Z",
            "containerStatuses": [{"ready": ready, "restartCount": restarts, "state": state,
                                   "lastState": {"terminated": {"finishedAt": "2026-10-12T11:00:00Z"}} if restarts else {}}],
        },
    }


def event(reason, name, message, last="2026-10-12T11:00:00Z", count=1):
    return {"reason": reason, "message": message, "count": count, "lastTimestamp": last,
            "involvedObject": {"kind": "Pod", "name": name}, "metadata": {}}


def fake(objects, fail=None):
    def fetch(path, what):
        if fail and fail in path:
            raise NodeListError(f"the backend's service account is not allowed to {what}")
        for key, items in objects.items():
            if path.endswith(key) or f"{key}?" in path:
                return {"items": items}
        return {"items": []}
    return fetch


def test_docker_mode_reports_nothing_and_calls_nothing():
    def boom(*_a):
        raise AssertionError("must not call the API under docker")
    out = workloads.describe_workloads({}, boom)
    assert out["mode"] == "docker" and out["services"] == [] and out["error"] is None


def test_services_get_their_own_pods_and_a_state():
    out = workloads.describe_workloads(K8S, fake({
        "deployments": [deployment("backend"), deployment("ollama", ready=0), deployment("voice", replicas=0, ready=0)],
        "pods": [pod("backend-a", "backend", restarts=2), pod("ollama-b", "ollama", ready=False, waiting="CrashLoopBackOff", restarts=7),
                 pod("db-backup-x", "db-backup")],
        "events": [],
    }))
    by = {s["name"]: s for s in out["services"]}
    assert [s["name"] for s in out["services"]] == ["backend", "ollama", "voice"]
    assert by["backend"]["state"] == "ready" and by["backend"]["restarts"] == 2
    assert by["backend"]["images"] == [{"name": "backend", "tag": "1.5"}]
    assert by["ollama"]["state"] == "down" and by["ollama"]["pods"][0]["reason"] == "CrashLoopBackOff"
    assert by["voice"]["state"] == "stopped" and by["voice"]["pods"] == []
    assert [p["name"] for p in out["unmatched_pods"]] == ["db-backup-x"]
    assert "labels" not in json.dumps(out) and "selector" not in json.dumps(out)


def test_ready_but_crash_looping_is_degraded():
    out = workloads.describe_workloads(K8S, fake({
        "deployments": [deployment("web", replicas=2, ready=2)],
        "pods": [pod("web-1", "web"), pod("web-2", "web", waiting="CrashLoopBackOff")],
    }))
    assert out["services"][0]["state"] == "degraded"


def test_partial_readiness_is_degraded():
    out = workloads.describe_workloads(K8S, fake({"deployments": [deployment("web", replicas=3, ready=1)], "pods": []}))
    assert out["services"][0]["state"] == "degraded"


def test_events_newest_first_and_redacted():
    out = workloads.describe_workloads(K8S, fake({
        "deployments": [], "pods": [],
        "events": [event("BackOff", "a", "old", last="2026-10-12T09:00:00Z"),
                   event("Failed", "b", "pull failed password=hunter2hunter2", last="2026-10-12T12:00:00Z", count=4)],
    }))
    assert [e["reason"] for e in out["events"]] == ["Failed", "BackOff"]
    assert out["events"][0]["object"] == "pod/b" and out["events"][0]["count"] == 4
    assert "hunter2" not in json.dumps(out)


def test_missing_events_permission_keeps_the_services():
    out = workloads.describe_workloads(K8S, fake({"deployments": [deployment("backend")], "pods": []}, fail="events"))
    assert [s["name"] for s in out["services"]] == ["backend"]
    assert "not allowed to list events" in out["events_error"] and out["error"] is None


def test_missing_pods_permission_is_a_plain_error():
    out = workloads.describe_workloads(K8S, fake({"deployments": [deployment("backend")]}, fail="/pods"))
    assert out["services"] == [] and "list pods" in out["error"]


def test_unexpected_exception_is_scrubbed():
    def fetch(path, what):
        raise RuntimeError("secret-token-XYZ leaked")
    out = workloads.describe_workloads(K8S, fetch)
    assert "secret-token-XYZ" not in json.dumps(out) and "RuntimeError" in out["error"]


@pytest.mark.parametrize("name", ["../secrets", "a/b", "UPPER", "", "x" * 300, "pod;rm"])
def test_logs_refuse_names_that_are_not_dns_labels(name):
    with pytest.raises(NodeListError):
        workloads.pod_logs(name, environ=K8S, fetch_text=lambda *a: "")


def test_logs_refuse_under_docker():
    with pytest.raises(NodeListError):
        workloads.pod_logs("backend-a", environ={}, fetch_text=lambda *a: "")


def test_logs_path_is_pinned_to_our_namespace_and_redacted():
    seen = {}

    def fetch_text(path, what, params):
        seen.update(path=path, params=params)
        return ("ok line\nDATABASE_URL=postgresql://pguser:pgpassword@pgsql:5432/database\n"
                "Authorization: Bearer abcdefghijklmnop123\ntoken=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig\n")

    out = workloads.pod_logs("backend-a", "backend", environ=K8S, previous=True, fetch_text=fetch_text)
    assert seen["path"] == "/api/v1/namespaces/harvis/pods/backend-a/log"
    assert seen["params"]["container"] == "backend" and seen["params"]["previous"] == "true"
    assert seen["params"]["tailLines"] == workloads.LOG_TAIL_LINES
    text = "\n".join(out["lines"])
    assert out["lines"][0] == "ok line"
    for leaked in ("pgpassword", "abcdefghijklmnop123", "eyJhbGciOiJIUzI1NiJ9"):
        assert leaked not in text


def test_api_get_never_surfaces_the_token(tmp_path):
    token = tmp_path / "token"
    token.write_text("sa-secret-token-XYZ")

    def handler(request):
        assert request.headers["Authorization"] == "Bearer sa-secret-token-XYZ"
        return httpx.Response(403, text="forbidden for sa-secret-token-XYZ")

    with pytest.raises(NodeListError) as err:
        cluster.api_get("/api/v1/namespaces/harvis/pods", "list pods", K8S, token_path=str(token),
                        ca_path=str(tmp_path / "none"), transport=httpx.MockTransport(handler))
    assert "sa-secret-token-XYZ" not in str(err.value) and "list pods" in str(err.value)


def test_api_get_text_mode(tmp_path):
    token = tmp_path / "token"
    token.write_text("t")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="line1\nline2"))
    assert cluster.api_get("/x", "read pod logs", K8S, token_path=str(token), ca_path=str(tmp_path / "none"),
                           transport=transport, as_text=True) == "line1\nline2"
