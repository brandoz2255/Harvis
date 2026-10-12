"""Pairing succeeds on the helper but saving the node fails: the helper is now paired
with a token the hub lost, and the admin cannot retry until the helper is re-run with
--repair. The error must say so, and the log must say it without the token."""

from __future__ import annotations

import logging

import pytest

from plugins.inference_nodes import store
# Fixtures are imported by name so pytest registers them in this module.
from tests.test_inference_node_pairing import (  # noqa: F401
    PIN, TOKEN, _clean, helper, make_client, pool, post,
)


def _failing_upsert(exc):
    async def _boom(*a, **k):
        raise exc
    return _boom


def test_save_failure_tells_the_admin_to_run_the_helper_with_repair(helper, pool, monkeypatch, caplog):
    monkeypatch.setattr(store, "upsert_node", _failing_upsert(RuntimeError(f"db down, row had {TOKEN}")))
    with caplog.at_level(logging.ERROR):
        r = post(make_client(pool))
    assert r.status_code == 500
    body = r.json()
    detail = body["detail"]
    assert "--repair" in detail and "harvis_node.py" in detail and "still paired" in detail
    assert "192.168.4.50:11437" in detail
    assert body["needs_repair"] is True
    # the helper really was paired, which is the whole problem
    assert any(path == "/harvis-node/pair" for _, path, _ in helper.calls)
    # neither secret reaches the browser or the log
    assert TOKEN not in r.text and PIN not in r.text
    assert "paired but could not be saved" in caplog.text and "--repair" in caplog.text
    assert TOKEN not in caplog.text and PIN not in caplog.text
    assert "***" in caplog.text            # scrubbed, not dropped


def test_a_spec_the_registry_rejects_after_pairing_gets_the_same_instruction(helper, pool, monkeypatch):
    import plugins.inference_nodes.routes as routes

    def _bad_spec(**kw):
        raise ValueError("bad spec")
    monkeypatch.setattr(routes, "NodeSpec", _bad_spec)
    r = post(make_client(pool))
    assert r.status_code == 500 and "--repair" in r.json()["detail"]
    assert pool.rows == {}


def test_success_path_is_unchanged(helper, pool):
    r = post(make_client(pool))
    assert r.status_code == 200 and "lab-pc-a" in pool.rows
