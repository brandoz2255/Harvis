"""Live check of the persistent workspace terminal volume (F19 regression).

A brand-new named volume used to mount /workspace as 0:0, so the unprivileged terminal
user got "Permission denied": Docker's copy-up reset the volume root to the image
directory's owner after _own_volume had chowned it. This spawns real throwaway
containers through terminal_container's own code path and writes as uid 1001.

Skipped unless a Docker daemon is reachable and the terminal base image is already
local (nothing is pulled). Every volume, container and network it makes is named
vrfy2* and removed afterwards.
"""

import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

docker = pytest.importorskip("docker")

import workspace.terminal_container as tc  # noqa: E402


def _client():
    try:
        client = docker.from_env()
        client.ping()
        client.images.get(tc._BASE_IMAGE)
        return client
    except Exception:
        return None


_CLIENT = _client()
pytestmark = pytest.mark.skipif(_CLIENT is None, reason="needs a Docker daemon and the terminal base image locally")


@pytest.fixture
def lab(monkeypatch):
    tag = "vrfy2" + uuid.uuid4().hex[:8]
    net = _CLIENT.networks.create(f"{tag}-net", driver="bridge", internal=True)
    monkeypatch.setattr(tc, "_NETWORK", net.name)
    monkeypatch.setattr(tc, "_PERSISTENT", True)
    made: list[str] = []

    def manager():
        m = tc.WorkspaceTerminalManager.__new__(tc.WorkspaceTerminalManager)
        m._client = _CLIENT
        m._terminals = {}
        m._own_mounts = []
        m._container_name = lambda w: f"{tag}-term-{w}"
        m._volume_name = lambda w: f"{tag}-vol-{w}"
        made.append(tag)
        return m

    yield tag, manager
    for c in _CLIENT.containers.list(all=True, filters={"name": tag}):
        c.remove(force=True, v=True)
    for v in _CLIENT.volumes.list(filters={"name": tag}):
        v.remove(force=True)
    net.remove()


def _as_terminal_user(tag, ws):
    c = _CLIENT.containers.get(f"{tag}-term-{ws}")
    code, out = c.exec_run(["sh", "-c", "touch /workspace/ok && mkdir /workspace/d && echo WRITE_OK; stat -c %u:%g /workspace"])
    return code, out.decode()


def test_a_brand_new_volume_is_writable_by_the_terminal_user(lab):
    tag, manager = lab
    asyncio.run(manager()._spawn("fresh"))
    code, out = _as_terminal_user(tag, "fresh")
    assert code == 0 and "WRITE_OK" in out, out
    assert out.strip().endswith("1001:1001"), out


def test_a_legacy_root_owned_volume_with_files_is_handed_over(lab):
    tag, manager = lab
    vol = f"{tag}-vol-legacy"
    _CLIENT.volumes.create(vol)
    _CLIENT.containers.run(tc._BASE_IMAGE, ["sh", "-c", "mkdir -p /workspace/old && echo hi > /workspace/old/f && chmod 700 /workspace/old"],
                           user="0", network_mode="none", remove=True, volumes={vol: {"bind": "/workspace", "mode": "rw"}})
    asyncio.run(manager()._spawn("legacy"))
    code, out = _as_terminal_user(tag, "legacy")
    assert code == 0 and "WRITE_OK" in out, out
    c = _CLIENT.containers.get(f"{tag}-term-legacy")
    code, out = c.exec_run(["sh", "-c", "cat /workspace/old/f"])
    assert code == 0 and out.decode().strip() == "hi"
