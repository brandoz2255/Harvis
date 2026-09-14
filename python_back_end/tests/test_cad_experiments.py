"""HE-8: disposable experiments, against the real database.

The gate's whole promise is negative — *a failed repair round costs the project
nothing* — and a negative promise is only worth what its tests are. So each of the
six things a failed experiment must not do gets an assertion here, and four of them
assert against Postgres rather than against a mock, because the mechanism is a
constraint or a transaction rather than a branch in Python:

===============================  =========================================
must not …                       proved by
-------------------------------  -----------------------------------------
advance head                     head_revision / next_seq after abandon
mutate an accepted revision      the base revision's row, byte for byte
weaken the DesignSpec            no UPDATE in the module writes design_spec
widen a tolerance                the same absence — a tolerance lives in
                                 the spec, and there is no way in
modify protected geometry        the base's cadir after attempts + promote
leave orphans                    cad_builds after abandon and after promote
===============================  =========================================

Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_cad_experiments.py -q
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
import re
import tempfile
import uuid

import asyncpg
import pytest

from owui_compat import cad_experiments, cad_store

DATABASE_URL = os.getenv("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="no DATABASE_URL — the store has nothing to talk to")


DOC = {
    "schema_version": "0.1",
    "name": "jar",
    "units": "mm",
    "parameters": [{"name": "h", "value": 115}],
    "operations": [
        {"op_id": "body", "op": "cylinder", "radius": 20, "height": "h"},
    ],
}
SPEC = {
    "units": "mm",
    "checks": [{"id": "c1", "kind": "part_height", "nominal": 115.0,
                "tolerance": {"kind": "symmetric", "nominal": 115.0, "plus": 0.5,
                              "minus": 0.5, "unit": "mm"}}],
    "assumptions": [],
    "unknowns": [],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tmp_artifacts():
    with tempfile.TemporaryDirectory(prefix="cad-exp-") as d:
        old = os.environ.get("ARTIFACT_STORAGE_DIR")
        os.environ["ARTIFACT_STORAGE_DIR"] = d
        try:
            yield d
        finally:
            if old is None:
                os.environ.pop("ARTIFACT_STORAGE_DIR", None)
            else:
                os.environ["ARTIFACT_STORAGE_DIR"] = old


@pytest.fixture(scope="module")
def loop():
    lp = asyncio.new_event_loop()
    try:
        yield lp
    finally:
        lp.close()


@pytest.fixture(scope="module")
def env(loop, tmp_artifacts):
    async def setup():
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=6)
        async with pool.acquire() as conn:
            for stmt in cad_store.CAD_SCHEMA_SQL:
                await conn.execute(stmt)
            ids = []
            for tag in ("a", "b"):
                nonce = uuid.uuid4().hex[:12]
                ids.append(await conn.fetchval(
                    "INSERT INTO users (username, email, password) "
                    "VALUES ($1, $2, $3) RETURNING id",
                    f"expt-{tag}-{nonce}", f"expt-{tag}-{nonce}@invalid.test", "x"))
        return pool, ids[0], ids[1]

    pool, ua, ub = loop.run_until_complete(setup())
    try:
        yield {"pool": pool, "user_a": ua, "user_b": ub, "loop": loop}
    finally:
        async def teardown():
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM users WHERE id = ANY($1::int[])",
                                   [ua, ub])
                left = await conn.fetchval(
                    "SELECT COUNT(*) FROM cad_experiments e "
                    "JOIN cad_projects p ON p.id = e.project_id "
                    "WHERE p.user_id = ANY($1::int[])", [ua, ub])
            await pool.close()
            return left
        # The experiment table's own cascade, exercised by the cleanup: an experiment
        # must not outlive the project it branched inside.
        left = loop.run_until_complete(teardown())
        assert left == 0, "deleting the user left cad_experiments rows behind"


def run(env, coro):
    return env["loop"].run_until_complete(coro)


async def _project(env, user=None):
    return await cad_store.create_project(
        env["pool"], user if user is not None else env["user_a"], "Jar",
        conversation_id=None,
        revision={"source_kind": "cadir", "recipe_name": "jar",
                  "cadir": copy.deepcopy(DOC), "parameters": {"h": 115},
                  "design_spec": copy.deepcopy(SPEC), "created_by": "user"})


async def _open(env, project, **kw):
    return await cad_experiments.open_experiment(
        env["pool"], project["id"], env["user_a"], project["revision"]["id"], **kw)


async def _mark(env, build_id: str, status: str = "succeeded",
                conformance: str | None = "passed"):
    """Land a build the way the runner would, without running geometry.

    The experiment machinery only ever reads ``status`` and ``conformance_status`` off
    a build row, so writing those two directly tests the promotion rules rather than
    the engine — which has its own suite.
    """
    async with env["pool"].acquire() as conn:
        await conn.execute(
            "UPDATE cad_builds SET status=$1, conformance_status=$2, "
            " conformance=$3::jsonb, finished_at=NOW() WHERE id=$4",
            status, conformance,
            json.dumps({"status": conformance, "summary": "test"}),
            uuid.UUID(str(build_id)))


async def _build_ids_of(env, experiment_id: str) -> list[str]:
    async with env["pool"].acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM cad_builds WHERE experiment_id=$1",
            uuid.UUID(str(experiment_id)))
    return [str(r["id"]) for r in rows]


# ---------------------------------------------------------------------------
# Opening: a copy, and only one at a time
# ---------------------------------------------------------------------------

def test_an_experiment_starts_as_a_copy_of_the_revision_it_branched_from(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p, reason="height measured 111.2"))
    assert exp["status"] == "open"
    assert exp["cadir"] == DOC
    assert exp["parameters"] == {"h": 115}
    assert exp["design_spec"] == SPEC
    assert exp["attempts"] == 0
    assert exp["reason"] == "height measured 111.2"


def test_the_frozen_spec_is_hashed_at_open_time(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    assert exp["spec_sha256"] == cad_experiments.spec_digest(SPEC)


def test_a_second_open_on_the_same_revision_hands_back_the_running_one(env):
    """Two callers asking to repair one revision want the same experiment, not two.
    The partial unique index is what settles the race the read cannot."""
    p = run(env, _project(env))
    first = run(env, _open(env, p, reason="first"))
    second = run(env, _open(env, p, reason="second"))
    assert second["id"] == first["id"]
    assert second["reason"] == "first"


def test_another_users_revision_is_not_branchable(env):
    p = run(env, _project(env, user=env["user_b"]))
    got = run(env, cad_experiments.open_experiment(
        env["pool"], p["id"], env["user_a"], p["revision"]["id"]))
    assert got == {}


def test_max_attempts_cannot_exceed_the_operators_ceiling(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p, max_attempts=9999))
    assert exp["max_attempts"] == cad_experiments.MAX_ATTEMPTS_CEILING


# ---------------------------------------------------------------------------
# The answer key is unreachable from inside
# ---------------------------------------------------------------------------

def test_no_write_in_this_module_can_touch_the_frozen_spec(env):
    """"An experiment may not weaken the DesignSpec or widen a tolerance" is a
    property of the schema here, not a rule someone has to remember: after the INSERT
    that copies it, no statement in the module writes ``design_spec`` or
    ``spec_sha256``. A tolerance lives inside that spec, so the same absence covers
    both halves of the requirement.

    This test fails the moment an UPDATE is added that would let an attempt move its
    own target — which is the only way that could happen."""
    src = inspect.getsource(cad_experiments)
    for stmt in re.findall(r"UPDATE cad_experiments SET (.*?)WHERE", src, re.S):
        assert "design_spec" not in stmt, f"an update writes design_spec: {stmt!r}"
        assert "spec_sha256" not in stmt, f"an update writes spec_sha256: {stmt!r}"


def test_recording_an_attempt_takes_geometry_and_nothing_else(env):
    params = set(inspect.signature(cad_experiments.record_attempt).parameters)
    assert "cadir" in params and "parameters" in params
    assert not params & {"design_spec", "spec", "checks", "tolerance"}


def test_a_spec_edited_out_of_band_refuses_to_promote(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=DOC))
    build = run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_a"]))
    run(env, _mark(env, build["id"]))

    loosened = copy.deepcopy(SPEC)
    loosened["checks"][0]["tolerance"]["plus"] = 50.0
    run(env, _tamper(env, exp["id"], loosened))

    with pytest.raises(cad_experiments.NotPromotable) as e:
        run(env, cad_experiments.promote(
            env["pool"], exp["id"], env["user_a"], build["id"]))
    assert e.value.code == "spec_drift"


async def _tamper(env, experiment_id: str, spec: dict):
    async with env["pool"].acquire() as conn:
        await conn.execute(
            "UPDATE cad_experiments SET design_spec=$1::jsonb WHERE id=$2",
            json.dumps(spec), uuid.UUID(str(experiment_id)))


# ---------------------------------------------------------------------------
# Attempts are counted and bounded
# ---------------------------------------------------------------------------

def test_each_attempt_increments_the_counter_and_replaces_the_working_copy(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p, max_attempts=3))
    edited = copy.deepcopy(DOC)
    edited["operations"][0]["radius"] = 21
    out = run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=edited,
        parameters={"h": 116}, note="raised the wall"))
    assert out["attempts"] == 1
    assert out["cadir"]["operations"][0]["radius"] == 21
    assert out["parameters"] == {"h": 116}
    assert out["reason"] == "raised the wall"


def test_an_attempt_that_sends_no_geometry_keeps_the_working_copy(env):
    """A parameter-only repair round. COALESCE, not a null overwrite — otherwise the
    second round would build an experiment with no document at all."""
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=DOC))
    out = run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=None, parameters={"h": 120}))
    assert out["cadir"] == DOC
    assert out["parameters"] == {"h": 120}
    assert out["attempts"] == 2


def test_the_attempt_budget_is_a_hard_stop(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p, max_attempts=2))
    for _ in range(2):
        run(env, cad_experiments.record_attempt(
            env["pool"], exp["id"], env["user_a"], cadir=DOC))
    with pytest.raises(cad_experiments.AttemptsExhausted) as e:
        run(env, cad_experiments.record_attempt(
            env["pool"], exp["id"], env["user_a"], cadir=DOC))
    assert e.value.status == 409


def test_a_closed_experiment_refuses_further_work(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    run(env, cad_experiments.abandon(env["pool"], exp["id"], env["user_a"], "done"))
    with pytest.raises(cad_experiments.ExperimentClosed):
        run(env, cad_experiments.record_attempt(
            env["pool"], exp["id"], env["user_a"], cadir=DOC))
    with pytest.raises(cad_experiments.ExperimentClosed):
        run(env, cad_experiments.create_experiment_build(
            env["pool"], exp["id"], env["user_a"]))


# ---------------------------------------------------------------------------
# An experiment build is not part of the project's history
# ---------------------------------------------------------------------------

def test_an_experiment_build_is_invisible_to_every_history_query(env):
    """The one cost of keeping ``revision_id`` pointing at the base revision is that
    each query asking "what is the geometry of this revision" has to say
    ``experiment_id IS NULL``. Miss one and a failed attempt shows up in the user's
    workspace as if it were their part — so all of them are asserted at once."""
    p = run(env, _project(env))
    rid = p["revision"]["id"]
    exp = run(env, _open(env, p))
    run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=DOC))
    build = run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_a"]))
    run(env, _mark(env, build["id"], conformance="failed"))

    latest = run(env, cad_store.latest_builds_by_revision(
        env["pool"], p["id"], env["user_a"]))
    assert rid not in latest

    snap = run(env, cad_store.workspace_snapshot(
        env["pool"], p["id"], env["user_a"]))
    shown = json.dumps(snap, default=str)
    assert build["id"] not in shown

    acts = run(env, cad_store.project_activity(env["pool"], p["id"], env["user_a"]))
    assert build["id"] not in json.dumps(acts, default=str)

    assert run(env, cad_store.latest_scene_manifest(env["pool"], rid)) is None
    assert run(env, cad_store.latest_measurements(env["pool"], rid)) is None


def test_the_build_row_says_which_experiment_it_belongs_to(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    build = run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_a"]))
    assert build["experiment_id"] == exp["id"]
    assert build["revision_id"] == p["revision"]["id"]

    ordinary, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"], None))
    assert ordinary["experiment_id"] is None


# ---------------------------------------------------------------------------
# Abandoning: nothing is left behind, except the fact that it was tried
# ---------------------------------------------------------------------------

def test_a_failed_experiment_does_not_advance_head_or_burn_a_seq(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    for _ in range(2):
        run(env, cad_experiments.record_attempt(
            env["pool"], exp["id"], env["user_a"], cadir=DOC))
        b = run(env, cad_experiments.create_experiment_build(
            env["pool"], exp["id"], env["user_a"]))
        run(env, _mark(env, b["id"], status="failed", conformance=None))
    run(env, cad_experiments.abandon(
        env["pool"], exp["id"], env["user_a"], "two rounds, still short"))

    after = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert after["head_revision"] == p["head_revision"]
    assert after["next_seq"] == p["next_seq"]
    revs = run(env, cad_store.list_revisions(env["pool"], p["id"], env["user_a"]))
    assert len(revs) == 1


def test_abandoning_removes_the_builds_and_keeps_the_record(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=DOC))
    run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_a"]))
    assert len(run(env, _build_ids_of(env, exp["id"]))) == 1

    closed = run(env, cad_experiments.abandon(
        env["pool"], exp["id"], env["user_a"], "gave up"))
    assert closed["status"] == "abandoned"
    assert closed["closed_reason"] == "gave up"
    assert closed["attempts"] == 1  # the record of what was tried survives
    assert run(env, _build_ids_of(env, exp["id"])) == []


def test_abandoning_twice_is_not_an_error_and_changes_nothing(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    once = run(env, cad_experiments.abandon(env["pool"], exp["id"], env["user_a"], "a"))
    twice = run(env, cad_experiments.abandon(env["pool"], exp["id"], env["user_a"], "b"))
    assert twice["closed_reason"] == once["closed_reason"] == "a"


def test_abandoning_frees_the_revision_for_a_new_experiment(env):
    p = run(env, _project(env))
    first = run(env, _open(env, p))
    run(env, cad_experiments.abandon(env["pool"], first["id"], env["user_a"], "x"))
    second = run(env, _open(env, p))
    assert second["id"] != first["id"]
    assert second["status"] == "open"


# ---------------------------------------------------------------------------
# Promotion: at most one revision, and only for work that stood up
# ---------------------------------------------------------------------------

def _promoted(env, project, conformance="passed"):
    exp = run(env, _open(env, project))
    run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=DOC, parameters={"h": 115}))
    build = run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_a"]))
    run(env, _mark(env, build["id"], conformance=conformance))
    return exp, build


def test_a_passing_experiment_becomes_exactly_one_revision(env):
    p = run(env, _project(env))
    exp, build = _promoted(env, p)
    rev = run(env, cad_experiments.promote(
        env["pool"], exp["id"], env["user_a"], build["id"]))
    assert rev["seq"] == p["next_seq"]
    assert rev["parent_id"] == p["revision"]["id"]
    revs = run(env, cad_store.list_revisions(env["pool"], p["id"], env["user_a"]))
    assert len(revs) == 2


def test_a_promoted_repair_is_a_proposal_and_does_not_move_head(env):
    """``created_by`` is the experiment's, which is ``ai`` for every repair loop, so
    the rule Gate 7C-2 already wrote is what keeps the head where it is. No second
    enforcement mechanism was added, and this is the test that says so."""
    p = run(env, _project(env))
    exp, build = _promoted(env, p)
    rev = run(env, cad_experiments.promote(
        env["pool"], exp["id"], env["user_a"], build["id"]))
    assert rev["created_by"] == "ai"
    assert rev["accepted_at"] is None
    after = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert after["head_revision"] == p["revision"]["id"]


def test_the_winning_build_follows_its_revision_and_the_losers_are_gone(env):
    p = run(env, _project(env))
    exp = run(env, _open(env, p))
    run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=DOC))
    loser = run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_a"]))
    run(env, _mark(env, loser["id"], status="failed", conformance=None))
    run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=DOC))
    winner = run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_a"]))
    run(env, _mark(env, winner["id"]))

    rev = run(env, cad_experiments.promote(
        env["pool"], exp["id"], env["user_a"], winner["id"]))

    kept = run(env, cad_store.get_build(env["pool"], winner["id"], env["user_a"]))
    assert kept["revision_id"] == rev["id"]
    assert kept["experiment_id"] is None
    assert run(env, cad_store.get_build(
        env["pool"], loser["id"], env["user_a"])) is None
    assert run(env, _build_ids_of(env, exp["id"])) == []


def test_the_promoted_revision_has_geometry_immediately(env):
    p = run(env, _project(env))
    exp, build = _promoted(env, p)
    rev = run(env, cad_experiments.promote(
        env["pool"], exp["id"], env["user_a"], build["id"]))
    latest = run(env, cad_store.latest_builds_by_revision(
        env["pool"], p["id"], env["user_a"]))
    assert latest.get(rev["id"], {}).get("id") == build["id"]


def test_a_failed_conformance_is_refused_and_is_not_overridable_here(env):
    p = run(env, _project(env))
    exp, build = _promoted(env, p, conformance="failed")
    with pytest.raises(cad_experiments.NotPromotable) as e:
        run(env, cad_experiments.promote(
            env["pool"], exp["id"], env["user_a"], build["id"]))
    assert e.value.code == "conformance_failed"
    # And the refusal really did leave the project alone.
    after = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert after["next_seq"] == p["next_seq"]
    assert len(run(env, cad_store.list_revisions(
        env["pool"], p["id"], env["user_a"]))) == 1


def test_unverified_promotes(env):
    """The common grade for anything the regex extractor could not state a check for.
    Refusing it would make experiments useless on exactly the parts that need them."""
    p = run(env, _project(env))
    exp, build = _promoted(env, p, conformance="unverified")
    rev = run(env, cad_experiments.promote(
        env["pool"], exp["id"], env["user_a"], build["id"]))
    assert rev["seq"] == p["next_seq"]


def test_a_build_that_never_succeeded_has_nothing_to_promote(env):
    p = run(env, _project(env))
    exp, build = _promoted(env, p)
    run(env, _mark(env, build["id"], status="failed", conformance=None))
    with pytest.raises(cad_experiments.NotPromotable) as e:
        run(env, cad_experiments.promote(
            env["pool"], exp["id"], env["user_a"], build["id"]))
    assert e.value.code == "no_geometry"


def test_a_build_from_a_different_experiment_cannot_be_promoted(env):
    p = run(env, _project(env))
    exp, build = _promoted(env, p)
    other = run(env, _project(env))
    other_exp, other_build = _promoted(env, other)
    with pytest.raises(cad_experiments.NotPromotable) as e:
        run(env, cad_experiments.promote(
            env["pool"], exp["id"], env["user_a"], other_build["id"]))
    assert e.value.code == "no_geometry"


def test_promoting_twice_mints_only_one_revision(env):
    p = run(env, _project(env))
    exp, build = _promoted(env, p)
    run(env, cad_experiments.promote(
        env["pool"], exp["id"], env["user_a"], build["id"]))
    with pytest.raises(cad_experiments.ExperimentClosed):
        run(env, cad_experiments.promote(
            env["pool"], exp["id"], env["user_a"], build["id"]))
    assert len(run(env, cad_store.list_revisions(
        env["pool"], p["id"], env["user_a"]))) == 2


def test_another_users_experiment_is_not_found_by_any_call(env):
    p = run(env, _project(env))
    exp, build = _promoted(env, p)
    assert run(env, cad_experiments.get_experiment(
        env["pool"], exp["id"], env["user_b"])) is None
    assert run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_b"], cadir=DOC)) == {}
    assert run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_b"])) == {}
    assert run(env, cad_experiments.promote(
        env["pool"], exp["id"], env["user_b"], build["id"])) == {}
    assert run(env, cad_experiments.abandon(
        env["pool"], exp["id"], env["user_b"])) == {}


# ---------------------------------------------------------------------------
# The base revision, before and after
# ---------------------------------------------------------------------------

def test_nothing_an_experiment_does_reaches_the_revision_it_branched_from(env):
    """The strongest form of "must not mutate an accepted revision": the row is read
    whole before and after a full experiment life cycle, and compared."""
    p = run(env, _project(env))
    rid = p["revision"]["id"]
    before = run(env, cad_store.get_revision(env["pool"], rid, env["user_a"]))

    exp = run(env, _open(env, p))
    wrecked = copy.deepcopy(DOC)
    wrecked["operations"][0]["radius"] = 999
    run(env, cad_experiments.record_attempt(
        env["pool"], exp["id"], env["user_a"], cadir=wrecked, parameters={"h": 9}))
    b = run(env, cad_experiments.create_experiment_build(
        env["pool"], exp["id"], env["user_a"]))
    run(env, _mark(env, b["id"]))
    run(env, cad_experiments.promote(env["pool"], exp["id"], env["user_a"], b["id"]))

    after = run(env, cad_store.get_revision(env["pool"], rid, env["user_a"]))
    assert after == before
