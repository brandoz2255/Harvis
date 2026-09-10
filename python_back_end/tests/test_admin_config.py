"""Resolution tests for the instance-wide admin settings.

The module under test states its own rule: a control that cannot change the
thing it names is worse than no control. These tests hold that rule to the
DEV_MODE key specifically, because its failure mode is silent in both
directions — a stale True leaves experimental panels on a machine an operator
meant to hand over, and a stale False makes a developer's panels vanish with no
error anywhere. Neither shows up in a UI test, because the UI just renders
whatever the boot payload says.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import config as owui_config  # noqa: E402
from owui_compat.admin_config import (  # noqa: E402
    _DEV_MODE_KEY,
    _SIGNUP_KEY,
    dev_mode_enabled,
    dev_mode_enabled_via_pool,
    load_admin_config,
)


class _Conn:
    """Minimal asyncpg-shaped connection over a dict of stored rows."""

    def __init__(self, stored: dict | None = None, raises: bool = False):
        self._stored = stored or {}
        self._raises = raises

    async def fetch(self, _query, keys):
        if self._raises:
            raise RuntimeError("relation \"instance_settings\" does not exist")
        return [{"key": k, "value": v} for k, v in self._stored.items() if k in keys]


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *_):
                return False

        return _Ctx()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("HARVIS_DEV_MODE", raising=False)
    monkeypatch.delenv("HARVIS_OWUI_ENABLE_SIGNUP", raising=False)


# ─── defaults ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_mode_defaults_on_so_an_upgrade_loses_nothing():
    # Pre-1.0 default. If this ever flips to False, the existing installs that
    # rely on the Inference Nodes panel lose it on a pull with no message.
    cfg = await load_admin_config(_Conn())
    assert cfg["DEV_MODE"] is True


@pytest.mark.asyncio
async def test_env_can_turn_dev_mode_off_without_a_database(monkeypatch):
    monkeypatch.setenv("HARVIS_DEV_MODE", "false")
    cfg = await load_admin_config(_Conn())
    assert cfg["DEV_MODE"] is False


# ─── stored value wins ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stored_row_beats_the_env_default(monkeypatch):
    # The switch is the value an admin last chose on purpose; .env is only the
    # default for an instance nobody has touched.
    monkeypatch.setenv("HARVIS_DEV_MODE", "true")
    cfg = await load_admin_config(_Conn({_DEV_MODE_KEY: "false"}))
    assert cfg["DEV_MODE"] is False


@pytest.mark.asyncio
async def test_blank_row_is_treated_as_unset_not_as_false(monkeypatch):
    # TEXT column: an empty string is "never written", not "off".
    monkeypatch.setenv("HARVIS_DEV_MODE", "true")
    cfg = await load_admin_config(_Conn({_DEV_MODE_KEY: "   "}))
    assert cfg["DEV_MODE"] is True


@pytest.mark.asyncio
async def test_the_two_keys_do_not_bleed_into_each_other():
    # One round trip fetches both; a mis-keyed row would silently swap them.
    cfg = await load_admin_config(
        _Conn({_SIGNUP_KEY: "false", _DEV_MODE_KEY: "true"})
    )
    assert cfg["ENABLE_SIGNUP"] is False
    assert cfg["DEV_MODE"] is True


# ─── failure modes ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_cold_database_falls_back_to_env_not_to_off():
    # /api/config is boot-critical. A DB blip must not blank the panels of
    # someone mid-session.
    cfg = await load_admin_config(_Conn(raises=True))
    assert cfg["DEV_MODE"] is True


@pytest.mark.asyncio
async def test_via_pool_survives_no_pool_at_all(monkeypatch):
    monkeypatch.setenv("HARVIS_DEV_MODE", "false")
    assert await dev_mode_enabled_via_pool(None) is False


@pytest.mark.asyncio
async def test_via_pool_reads_the_stored_row():
    pool = _Pool(_Conn({_DEV_MODE_KEY: "false"}))
    assert await dev_mode_enabled_via_pool(pool) is False


@pytest.mark.asyncio
async def test_dev_mode_enabled_matches_load_admin_config():
    conn = _Conn({_DEV_MODE_KEY: "false"})
    assert await dev_mode_enabled(conn) is False


# ─── the flag actually reaches the frontend ──────────────────────────────────


def test_build_config_publishes_the_resolved_flag():
    # This is the whole enforcement path: the panel gates on this key. If it
    # stops being emitted, the frontend falls back to "on" and the switch
    # becomes decorative — the exact failure admin_config exists to prevent.
    assert owui_config.build_config(dev_mode=False)["features"]["enable_dev_mode"] is False
    assert owui_config.build_config(dev_mode=True)["features"]["enable_dev_mode"] is True


def test_build_config_falls_back_to_env_when_told_nothing(monkeypatch):
    monkeypatch.setenv("HARVIS_DEV_MODE", "false")
    assert owui_config.build_config()["features"]["enable_dev_mode"] is False
