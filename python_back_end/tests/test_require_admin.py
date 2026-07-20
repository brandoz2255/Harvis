"""Authorization tests for the server-side admin gate.

These exist because the gate they cover replaced *nothing* — before it, the only
thing between a signed-in non-admin and the admin/config surfaces was a
client-side route guard in the frontend. A silent regression here would not show
up in any UI test, because the UI would keep hiding the pages either way.
"""

import os
import sys

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat.authz import is_admin, make_require_admin, user_id_of  # noqa: E402


# ─── user_id_of: both user shapes in the codebase ────────────────────────────


class _Pydanticish:
    """Stands in for main.py's UserResponse (attribute access)."""

    def __init__(self, id):
        self.id = id


def test_user_id_of_accepts_dict_and_object():
    # The compat layer carries users as dicts, main.py as UserResponse objects.
    assert user_id_of({"id": 7}) == 7
    assert user_id_of(_Pydanticish(7)) == 7


def test_user_id_of_coerces_string_ids():
    # JWT subs are strings; a stringified id must not silently fail the check.
    assert user_id_of({"id": "3"}) == 3


def test_user_id_of_returns_none_for_unusable_input():
    assert user_id_of(None) is None
    assert user_id_of({}) is None
    assert user_id_of({"id": None}) is None
    assert user_id_of({"id": "not-a-number"}) is None


# ─── is_admin: fail-closed ───────────────────────────────────────────────────


def test_is_admin_defaults_to_first_registrant(monkeypatch):
    monkeypatch.delenv("HARVIS_OWUI_ADMIN_USER_IDS", raising=False)
    assert is_admin({"id": 1}) is True
    assert is_admin({"id": 2}) is False


def test_is_admin_honours_env_override(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "4,9")
    assert is_admin({"id": 4}) is True
    assert is_admin({"id": 9}) is True
    assert is_admin({"id": 1}) is False  # override REPLACES the default


def test_is_admin_fails_closed_on_unknown_id():
    # The whole point of a gate: when we cannot tell, the answer is no.
    assert is_admin(None) is False
    assert is_admin({}) is False
    assert is_admin({"id": "garbage"}) is False


# ─── require_admin as a live FastAPI dependency ──────────────────────────────


def _app_with(user):
    """Build a one-route app whose auth dependency returns `user`."""
    app = FastAPI()

    async def fake_current_user():
        if user is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="unauthenticated")
        return user

    require_admin = make_require_admin(fake_current_user)

    @app.post("/admin-only")
    async def admin_only(u=Depends(require_admin)):
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_admin_is_allowed(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    assert _app_with({"id": 1}).post("/admin-only").status_code == 200


def test_authenticated_non_admin_is_forbidden(monkeypatch):
    """The regression that matters most: a normal signed-in user must get 403."""
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    r = _app_with({"id": 2}).post("/admin-only")
    assert r.status_code == 403
    assert "dmin" in r.json()["detail"]  # names the reason, doesn't leak internals


def test_anonymous_is_unauthenticated_not_forbidden():
    """401 vs 403 is deliberate: 'who are you' precedes 'you may not'."""
    assert _app_with(None).post("/admin-only").status_code == 401


def test_gate_survives_object_shaped_users(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "5")
    assert _app_with(_Pydanticish(5)).post("/admin-only").status_code == 200
    assert _app_with(_Pydanticish(6)).post("/admin-only").status_code == 403


# ─── the specific routes this task was meant to close ────────────────────────


def test_rag_mutation_routes_declare_the_admin_gate():
    """Every server-wide RAG mutation must carry the dependency.

    Asserted against the source rather than a live app because importing the
    real router pulls in the whole backend; this still fails loudly if someone
    adds a mutation route without the gate.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "..", "rag_corpus", "routes.py")).read()

    mutations = [
        '@router.post("/update-local"',
        '@router.post("/jobs/{job_id}/cancel"',
        '@router.post("/rebuild"',
        '@router.delete("/sources/{source}"',
        '@router.post("/sources/config"',
        '@router.put("/sources/config/{source_id}"',
        '@router.delete("/sources/config/{source_id}"',
        '@router.post("/sources/config/{source_id}/toggle"',
        '@router.post("/sources/config/reset"',
    ]
    for decorator in mutations:
        idx = src.find(decorator)
        assert idx != -1, f"route vanished: {decorator}"
        # the gate must appear within this decorator's own call
        end = src.index(")\n", idx)
        assert "Depends(require_admin)" in src[idx:end], f"UNGATED mutation: {decorator}"


def test_audio_config_update_is_admin_gated():
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "..", "main.py")).read()
    idx = src.find('@app.post("/api/v1/audio/config/update"')
    assert idx != -1
    window = src[idx : idx + 400]
    assert "Depends(require_admin)" in window
    assert "Depends(get_current_user)" not in window
