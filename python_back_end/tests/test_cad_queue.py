"""UX-G: the per-conversation queue in front of the CAD authoring lane.

A second CAD message sent while a turn is still authoring used to start a second turn
against the same project. Two models proposing revisions over each other leaves no way
to say afterwards which one the user meant, so the follow-up waits instead.

What is under test here is the ordering half — the memory that decides what runs next.
The row half (queued state, the claim guard, the reaper) is tested against a live
database in ``test_cad_store.py``; these tests need no database at all, and the store
is stubbed so that the ordering can be exercised on its own.
"""
from __future__ import annotations

import asyncio

import pytest

from owui_compat import cad_jobs


@pytest.fixture(autouse=True)
def empty_queues():
    """Each test starts with nothing waiting, and leaves nothing behind."""
    cad_jobs._queued.clear()
    cad_jobs._queued_in.clear()
    yield
    cad_jobs._queued.clear()
    cad_jobs._queued_in.clear()


@pytest.fixture
def started(monkeypatch):
    """Record what would have been started, without starting a model."""
    calls: list[dict] = []

    def fake_start(pool, job_id, description, *, lane, ctx, conversation_id=None):
        calls.append({"job_id": job_id, "description": description,
                      "conversation_id": conversation_id})
        return None

    monkeypatch.setattr(cad_jobs, "start_job", fake_start)
    return calls


@pytest.fixture
def claims(monkeypatch):
    """Control which rows are still claimable, the way a cancel would."""
    state = {"claimable": set(), "asked": []}

    async def fake_claim(pool, job_id):
        state["asked"].append(str(job_id))
        return str(job_id) in state["claimable"]

    monkeypatch.setattr(cad_jobs.cad_store, "claim_queued_job", fake_claim)
    return state


def _enqueue(job_id, conv="conv-1"):
    return cad_jobs.enqueue(None, job_id, f"make {job_id}", lane=object(),
                            ctx=object(), conversation_id=conv)


def test_a_waiting_turn_knows_its_place_in_line():
    assert _enqueue("a") == 1
    assert _enqueue("b") == 2
    assert _enqueue("c") == 3


def test_conversations_do_not_wait_on_each_other():
    assert _enqueue("a", "conv-1") == 1
    assert _enqueue("b", "conv-2") == 1, "another chat's turn is not in front of you"


def test_a_waiting_turn_can_be_taken_out_of_the_line():
    _enqueue("a")
    _enqueue("b")
    assert cad_jobs.dequeue("a") is True
    assert cad_jobs.dequeue("a") is False, "twice is not twice as cancelled"
    assert cad_jobs.dequeue("never-queued") is False
    assert [e["job_id"] for e in cad_jobs._queued["conv-1"]] == ["b"]


def test_emptying_a_queue_leaves_no_entry_behind():
    """The dicts are keyed by conversation and live for the process; a queue that
    empties has to disappear, not linger as an empty list per chat ever used."""
    _enqueue("a")
    cad_jobs.dequeue("a")
    assert "conv-1" not in cad_jobs._queued
    assert cad_jobs._queued_in == {}


def test_draining_starts_the_oldest_waiting_turn(started, claims):
    _enqueue("a")
    _enqueue("b")
    claims["claimable"] = {"a", "b"}

    assert asyncio.run(cad_jobs.drain(None, "conv-1")) == "a"
    assert [c["job_id"] for c in started] == ["a"]
    assert started[0]["conversation_id"] == "conv-1", \
        "the started turn must be able to hand off to the one behind it"
    assert [e["job_id"] for e in cad_jobs._queued["conv-1"]] == ["b"]


def test_draining_an_empty_queue_starts_nothing(started, claims):
    assert asyncio.run(cad_jobs.drain(None, "conv-1")) is None
    assert started == []


def test_a_turn_stopped_while_waiting_is_skipped_not_started(started, claims):
    """The one outcome a queue must not produce: a model asked to do work the user
    has already called off. The row is re-read at the front of the line, not trusted
    from when it joined."""
    _enqueue("cancelled")
    _enqueue("wanted")
    claims["claimable"] = {"wanted"}

    assert asyncio.run(cad_jobs.drain(None, "conv-1")) == "wanted"
    assert [c["job_id"] for c in started] == ["wanted"]
    assert claims["asked"] == ["cancelled", "wanted"]


def test_a_queue_of_nothing_but_cancelled_turns_drains_to_nothing(started, claims):
    _enqueue("x")
    _enqueue("y")
    claims["claimable"] = set()

    assert asyncio.run(cad_jobs.drain(None, "conv-1")) is None
    assert started == []
    assert "conv-1" not in cad_jobs._queued


def test_a_store_that_errors_skips_the_turn_rather_than_wedging_the_queue(
        started, monkeypatch):
    """A claim that raises must not leave every later turn waiting forever behind
    the one row the database could not answer for."""
    async def boom(pool, job_id):
        if str(job_id) == "bad":
            raise RuntimeError("connection reset")
        return True

    monkeypatch.setattr(cad_jobs.cad_store, "claim_queued_job", boom)
    _enqueue("bad")
    _enqueue("good")

    assert asyncio.run(cad_jobs.drain(None, "conv-1")) == "good"
    assert [c["job_id"] for c in started] == ["good"]


def test_draining_twice_cannot_start_the_same_turn_twice(started, claims):
    """Both the finishing turn's hand-off and the enqueuing request can call drain,
    and they race by design. The entry leaves the queue before anything is awaited,
    so the second caller finds an empty line; the row's claim guard is the backstop
    for the case this test cannot reach — a second process draining the same chat."""
    _enqueue("a")
    claims["claimable"] = {"a"}

    async def both():
        first, second = await asyncio.gather(cad_jobs.drain(None, "conv-1"),
                                             cad_jobs.drain(None, "conv-1"))
        return first, second

    first, second = asyncio.run(both())
    assert {first, second} == {"a", None}
    assert [c["job_id"] for c in started] == ["a"]
