"""F7 leftovers: status/stats routes an anonymous caller could read.

All run against the real ``main.app`` (no lifespan, no DB).

* /api/research/stats and /api/research/health: host CPU/memory/disk and pipeline internals.
  No UI or script calls them, so they need a signed-in user.
* /api/tools/terminal/status: carried the Docker daemon's own error text. Needs a signed-in
  user, and only an admin gets the reason and probe detail.
* /onb-api/config: deliberately still anonymous. The vendored open-notebook UI's connection
  guard fetches it on boot, before anyone has signed in, and it must keep working. It is safe
  only because it returns fixed constants, so this pins that exact shape.
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOCKED = ["/api/research/stats", "/api/research/health", "/api/tools/terminal/status"]


@pytest.fixture(scope="module")
def main_mod():
    import main

    return main


@pytest.fixture
def client(main_mod, monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    return TestClient(main_mod.app, raise_server_exceptions=False)


@pytest.fixture
def signed_in(main_mod):
    """Make both auth dependencies in play (main's and auth_utils') accept X-Test-User."""
    import auth_utils

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(401, "Could not validate credentials")
        return {"id": int(uid), "username": f"user{uid}"}

    main_mod.app.dependency_overrides[main_mod.get_current_user] = fake_user
    main_mod.app.dependency_overrides[auth_utils.get_current_user] = fake_user
    yield
    main_mod.app.dependency_overrides.pop(main_mod.get_current_user, None)
    main_mod.app.dependency_overrides.pop(auth_utils.get_current_user, None)


@pytest.mark.parametrize("path", LOCKED)
def test_status_routes_refuse_anonymous(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/api/research/stats", "/api/research/health"])
def test_research_routes_work_for_a_signed_in_user(client, signed_in, path):
    r = client.get(path, headers={"X-Test-User": "2"})
    assert r.status_code == 200


def test_terminal_status_hides_docker_detail_from_non_admins(client, signed_in, monkeypatch):
    from workspace import terminal_routes

    async def fake_status(*, force_probe=False):
        return {"enabled": True, "ready": False, "available": False,
                "reason": "docker daemon: permission denied on /var/run/docker.sock",
                "probe": {"docker_host": "unix:///var/run/docker.sock"}}

    monkeypatch.setattr(terminal_routes, "terminal_status", fake_status)

    plain = client.get("/api/tools/terminal/status", headers={"X-Test-User": "2"})
    assert plain.status_code == 200
    assert plain.json() == {"enabled": True, "ready": False, "available": False}
    assert "docker" not in plain.text

    owner = client.get("/api/tools/terminal/status", headers={"X-Test-User": "1"})
    assert owner.status_code == 200
    assert "permission denied" in owner.json()["reason"]
    assert owner.json()["probe"]["docker_host"]


def test_onb_config_stays_anonymous_and_is_only_constants(client):
    r = client.get("/onb-api/config")
    assert r.status_code == 200
    assert r.json() == {"version": "harvis-onb", "latestVersion": None, "hasUpdate": False,
                        "dbStatus": {"connected": True}}
