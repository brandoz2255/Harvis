"""Sandbox folders map to host paths in Kubernetes mode too.

A sandbox is a sibling Docker container bound to the session folder by its HOST
path. In Docker mode the backend learns that path by inspecting its own
container; as a pod it has none, so the manifest generator passes the table in
HARVIS_HOST_MOUNTS (scripts/k8s/k8s_extras.extra_env).
"""

import asyncio
import json

from workspace.terminal_container import WorkspaceTerminalManager


class _NoDocker:
    class containers:
        @staticmethod
        def get(_cid):
            raise AssertionError("must not inspect a container when the table is given")


def _manager():
    m = WorkspaceTerminalManager.__new__(WorkspaceTerminalManager)
    m._client = _NoDocker()
    m._own_mounts = None
    return m


def test_pod_uses_the_mount_table_it_was_given(monkeypatch):
    monkeypatch.setenv("HARVIS_HOST_MOUNTS", json.dumps([
        {"Destination": "/data/artifacts", "Source": "/var/lib/docker/volumes/harvis_artifact_data/_data"},
        {"Destination": "/var/run/docker.sock", "Source": "/var/run/docker.sock"},
    ]))
    path = asyncio.run(_manager().host_path_of("/data/artifacts/sessions/u1/s1"))
    assert path == "/var/lib/docker/volumes/harvis_artifact_data/_data/sessions/u1/s1"


def test_a_folder_outside_every_mount_is_still_refused(monkeypatch):
    monkeypatch.setenv("HARVIS_HOST_MOUNTS", json.dumps([
        {"Destination": "/data/artifacts", "Source": "/var/lib/docker/volumes/harvis_artifact_data/_data"},
    ]))
    try:
        asyncio.run(_manager().host_path_of("/app/secrets"))
    except RuntimeError as exc:
        assert "no backend mount covers" in str(exc)
    else:
        raise AssertionError("an unmapped path must fail closed")


def test_a_malformed_table_is_refused_in_words(monkeypatch):
    monkeypatch.setenv("HARVIS_HOST_MOUNTS", "{not json")
    try:
        asyncio.run(_manager().host_path_of("/data/artifacts/x"))
    except RuntimeError as exc:
        assert "HARVIS_HOST_MOUNTS" in str(exc)
    else:
        raise AssertionError("a malformed table must fail closed")


def test_vibecode_run_sandbox_uses_the_table_too(monkeypatch):
    from owui_compat import workspace_sandbox as ws

    monkeypatch.setenv("HARVIS_HOST_MOUNTS", json.dumps([
        {"Destination": "/data/artifacts", "Source": "/var/lib/docker/volumes/harvis_artifact_data/_data"},
    ]))
    monkeypatch.delenv("HARVIS_VIBECODE_HOST_ARTIFACT_ROOT", raising=False)
    monkeypatch.setattr(ws, "_host_root_cache", None)
    assert ws._resolve_mount_root(_NoDocker()) == (
        "/data/artifacts", "/var/lib/docker/volumes/harvis_artifact_data/_data")
