"""Two tags of the same model on different PAIR nodes share load: a lone request
keeps the tag the user picked, a concurrent one spills to the other tag."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace import model_pool  # noqa: E402

A, B = "qwen3.8:27b-mtp-q4_K_M", "qwen3.8:27b-q4_K_M"


def test_unpooled_model_passes_through(monkeypatch):
    monkeypatch.setenv("HARVIS_MODEL_POOLS", f"{A},{B}")
    with model_pool.lease("gemma4:e4b") as m:
        assert m == "gemma4:e4b"


def test_lone_request_keeps_its_tag(monkeypatch):
    monkeypatch.setenv("HARVIS_MODEL_POOLS", f"{A},{B}")
    with model_pool.lease(B) as m:
        assert m == B
    with model_pool.lease(A) as m:
        assert m == A


def test_concurrent_requests_split(monkeypatch):
    monkeypatch.setenv("HARVIS_MODEL_POOLS", f"{A},{B}")
    with model_pool.lease(A) as m1, model_pool.lease(A) as m2, \
            model_pool.lease(A) as m3, model_pool.lease(A) as m4:
        assert sorted([m1, m2, m3, m4]) == sorted([A, A, B, B])
    # All released: the next lone request is back on the picked tag.
    with model_pool.lease(A) as m:
        assert m == A


def test_no_pools_configured(monkeypatch):
    monkeypatch.delenv("HARVIS_MODEL_POOLS", raising=False)
    with model_pool.lease(A) as m1, model_pool.lease(A) as m2:
        assert m1 == m2 == A


def test_never_swaps_to_a_tag_the_upstream_lacks(monkeypatch):
    # The PAIR router is closed: the request goes to this machine's Ollama, which holds A only.
    monkeypatch.setenv("HARVIS_MODEL_POOLS", f"{A},{B}")
    with model_pool.lease(A, {A}) as m1, model_pool.lease(A, {A}) as m2:
        assert m1 == m2 == A


def test_swaps_when_the_upstream_serves_both(monkeypatch):
    monkeypatch.setenv("HARVIS_MODEL_POOLS", f"{A},{B}")
    with model_pool.lease(A, {A, B}) as m1, model_pool.lease(A, {A, B}) as m2:
        assert sorted([m1, m2]) == sorted([A, B])
