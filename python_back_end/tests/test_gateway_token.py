"""The shared gateway token: HARVIS_GATEWAY_TOKEN wins, the OpenClaw-era names
still work, and every reader goes through gateway_token.py."""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import gateway_token  # noqa: E402

ALL = ("HARVIS_GATEWAY_TOKEN", "OPENCLAW_GATEWAY_TOKEN",
       "OPENCLAW_GATEWAY_TOKEN_BUNDLED", "OPENCLAW_FALLBACK_TOKEN")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ALL:
        monkeypatch.delenv(name, raising=False)


def test_nothing_set_is_empty():
    assert gateway_token.gateway_token() == ""
    assert gateway_token.bundled_gateway_token() == ""
    assert gateway_token.fallback_gateway_token() == ""


def test_legacy_name_alone_still_works(monkeypatch):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "old")
    assert gateway_token.gateway_token() == "old"
    assert gateway_token.fallback_gateway_token() == "old"


def test_new_name_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "old")
    monkeypatch.setenv("HARVIS_GATEWAY_TOKEN", "new")
    assert gateway_token.gateway_token() == "new"


def test_empty_new_name_falls_back(monkeypatch):
    monkeypatch.setenv("HARVIS_GATEWAY_TOKEN", "")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "old")
    assert gateway_token.gateway_token() == "old"


def test_explicit_fallback_token_beats_shared(monkeypatch):
    monkeypatch.setenv("HARVIS_GATEWAY_TOKEN", "new")
    monkeypatch.setenv("OPENCLAW_FALLBACK_TOKEN", "failover")
    assert gateway_token.fallback_gateway_token() == "failover"


def test_gateway_auth_accepts_new_name_only(monkeypatch):
    monkeypatch.setenv("HARVIS_GATEWAY_TOKEN", "new")
    from workspace import gateway_auth
    importlib.reload(gateway_auth)
    assert gateway_auth._is_bundled_token("new")
    assert not gateway_auth._is_bundled_token("other")


def test_gateway_auth_accepts_legacy_name_only(monkeypatch):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "old")
    from workspace import gateway_auth
    importlib.reload(gateway_auth)
    assert gateway_auth._is_bundled_token("old")
