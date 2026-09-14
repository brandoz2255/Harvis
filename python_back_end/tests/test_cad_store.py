"""Gate 3: the CAD persistence store, against the real database.

Not stubs. Every claim this gate makes is a claim about Postgres — that ``next_seq``
is atomic under concurrency, that a composite FK refuses a cross-project parent, that
an idempotency key collapses two retries into one build, that a CASCADE from ``users``
reaches all four tables. A mocked pool would agree with whatever the test asserted and
prove none of it.

The suite creates one throwaway user, does everything under it, and deletes it in a
``finally`` — which also exercises the cascade. Artifacts go to a tmpdir, never the
real store.

Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_cad_store.py -q
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import tempfile
import uuid

import asyncpg
import pytest

from owui_compat import cad_store

DATABASE_URL = os.getenv("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="no DATABASE_URL — the store has nothing to talk to")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tmp_artifacts():
    with tempfile.TemporaryDirectory(prefix="cad-test-") as d:
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
    """A live pool, the schema applied, and two throwaway users.

    Two, not one: half of what this gate promises is that user B cannot see user A's
    rows, and that is not testable with a single identity.
    """
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
                    f"cadtest-{tag}-{nonce}", f"cadtest-{tag}-{nonce}@invalid.test", "x",
                ))
        return pool, ids[0], ids[1]

    pool, ua, ub = loop.run_until_complete(setup())
    try:
        yield {"pool": pool, "user_a": ua, "user_b": ub, "loop": loop}
    finally:
        async def teardown():
            async with pool.acquire() as conn:
                # The cascade is the cleanup. If cad_projects did NOT reference
                # users(id), this would leave rows behind — which the assertion below
                # would catch, so the teardown doubles as the FK test.
                await conn.execute("DELETE FROM users WHERE id = ANY($1::int[])", [ua, ub])
                left = await conn.fetchval(
                    "SELECT COUNT(*) FROM cad_projects WHERE user_id = ANY($1::int[])",
                    [ua, ub])
            await pool.close()
            return left
        left = loop.run_until_complete(teardown())
        assert left == 0, "deleting the user left cad_projects rows behind"


def run(env, coro):
    return env["loop"].run_until_complete(coro)


async def _project(env, title="Test part", user=None, with_revision=True):
    return await cad_store.create_project(
        env["pool"], user if user is not None else env["user_a"], title,
        conversation_id=None,
        revision={"recipe_name": "helmet_hanger_v1",
                  "parameters": {"arm_len_mm": 90}} if with_revision else None,
    )


# ---------------------------------------------------------------------------
# Revisions are facts
# ---------------------------------------------------------------------------

def test_the_only_update_to_a_revision_is_the_acceptance_latch():
    """Immutability is enforced by the absence of the code, so assert the absence.

    A comment saying "insert only" is not a constraint. This is the closest thing to
    one short of a database trigger, and it fails the moment someone adds the UPDATE
    that a comment would have quietly permitted.

    Gate 7C-2 added exactly one, and the test narrowed rather than disappeared. What
    the table promises is that *what a revision says* never changes — its design spec,
    its document, its parameters, its author. ``accepted_at`` says nothing about the
    revision's content; it records that a person later agreed to it, and it moves in
    one direction only. So the assertion is now the precise thing: every
    ``UPDATE cad_revisions`` in this module must set that column and nothing else.
    """
    src = inspect.getsource(cad_store)
    sets = re.findall(r"UPDATE cad_revisions SET (\w+)=", src)
    assert sets, "the acceptance latch is missing entirely"
    assert set(sets) == {"accepted_at"}, (
        f"a revision's content was made mutable: {sorted(set(sets))}")


def test_project_and_first_revision_land_together(env):
    p = run(env, _project(env))
    assert p["revision"]["seq"] == 1
    assert p["head_revision"] == p["revision"]["id"]
    assert p["next_seq"] == 2
    assert p["revision"]["parent_id"] is None


def test_an_imported_revision_carries_its_provenance_and_an_authored_one_does_not(env):
    """Gate 8B. The column exists so an imported part can answer "where did this come
    from", and the answer has to survive the round trip through JSONB rather than
    living only in the request that created it.

    The second half matters as much as the first: a recipe revision must come back
    with ``provenance`` null, because the field's presence is how a client tells an
    imported body from an authored one without parsing ``source_kind``. A default of
    ``{}`` would make every part look imported.
    """
    prov = {"source": "attachment", "name": "bracket.stp", "kind": "step",
            "bytes": 4096, "sha256": "a" * 64, "file_id": None}
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Imported bracket", conversation_id=None,
        revision={"source_kind": "import", "recipe_name": "bracket",
                  "parameters": {}, "created_by": "user", "provenance": prov}))

    back = run(env, cad_store.get_revision(env["pool"], p["revision"]["id"],
                                           env["user_a"]))
    assert back["source_kind"] == "import"
    assert back["provenance"] == prov
    # An upload is something a person did, so it is accepted, not proposed — and the
    # head moved to it. A part that arrived as a proposal would need accepting before
    # it could be seen, which is not what uploading a file means.
    assert back["accepted_at"] is not None
    assert p["head_revision"] == p["revision"]["id"]

    authored = run(env, _project(env, title="Authored part"))
    assert authored["revision"]["provenance"] is None


def test_a_revision_chains_to_the_head(env):
    p = run(env, _project(env))
    r2 = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"],
        {"recipe_name": "helmet_hanger_v1", "parameters": {"arm_len_mm": 120}},
        base_revision_id=p["revision"]["id"]))
    assert r2["seq"] == 2
    assert r2["parent_id"] == p["revision"]["id"]

    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] == r2["id"]
    assert fresh["next_seq"] == 3


def test_a_stale_base_is_a_conflict_not_a_silent_fork(env):
    """Two clients editing rev 1: the second must be told, not branched."""
    p = run(env, _project(env))
    first = p["revision"]["id"]
    run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"], {"parameters": {"arm_len_mm": 100}},
        base_revision_id=first))

    with pytest.raises(cad_store.StaleRevision) as e:
        run(env, cad_store.create_revision(
            env["pool"], p["id"], env["user_a"], {"parameters": {"arm_len_mm": 111}},
            base_revision_id=first))
    assert e.value.status == 409
    assert e.value.extra["base_revision_id"] == first
    assert e.value.extra["head_revision"] != first

    # And nothing was written: a 409 that half-committed would be worse than no check.
    revs = run(env, cad_store.list_revisions(env["pool"], p["id"], env["user_a"]))
    assert [r["seq"] for r in revs] == [2, 1]


def test_concurrent_appends_do_not_collide_on_seq(env):
    """The row lock, not the unique index, is what has to hold.

    Eight appends fired at once. If ``next_seq`` were read outside the lock they would
    either duplicate a seq or fail on the unique constraint; either outcome is a bug,
    and this is the only test that can tell.
    """
    p = run(env, _project(env))

    async def race():
        return await asyncio.gather(*[
            cad_store.create_revision(
                env["pool"], p["id"], env["user_a"], {"parameters": {"n": i}})
            for i in range(8)
        ], return_exceptions=True)

    out = run(env, race())
    errors = [r for r in out if isinstance(r, Exception)]
    assert not errors, f"concurrent appends raised: {errors}"
    seqs = sorted(r["seq"] for r in out)
    assert seqs == list(range(2, 10)), seqs

    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["next_seq"] == 10
    assert fresh["head_revision"] in {r["id"] for r in out}


def test_a_parent_from_another_project_is_refused(env):
    """The composite FK. A plain parent_id reference would accept this."""
    p1 = run(env, _project(env))
    p2 = run(env, _project(env, title="Other"))

    async def cross():
        async with env["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO cad_revisions (id, project_id, parent_id, seq, parameters) "
                "VALUES ($1,$2,$3,$4,'{}'::jsonb)",
                uuid.uuid4(), uuid.UUID(p1["id"]),
                uuid.UUID(p2["revision"]["id"]), 99,
            )

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        run(env, cross())


# ---------------------------------------------------------------------------
# Builds
# ---------------------------------------------------------------------------

def test_an_idempotency_key_returns_the_first_build(env):
    p = run(env, _project(env))
    rid = p["revision"]["id"]
    b1, made1 = run(env, cad_store.create_build(env["pool"], rid, env["user_a"], "k-1"))
    b2, made2 = run(env, cad_store.create_build(env["pool"], rid, env["user_a"], "k-1"))
    assert made1 is True and made2 is False
    assert b1["id"] == b2["id"]


def test_no_key_means_every_call_is_a_new_attempt(env):
    """NULLs are distinct in a unique index, and that is the behaviour we want: a
    caller who sent no key asked for a fresh build."""
    p = run(env, _project(env))
    rid = p["revision"]["id"]
    b1, _ = run(env, cad_store.create_build(env["pool"], rid, env["user_a"], None))
    b2, _ = run(env, cad_store.create_build(env["pool"], rid, env["user_a"], None))
    assert b1["id"] != b2["id"]


def test_the_same_key_on_a_different_revision_is_a_different_build(env):
    p = run(env, _project(env))
    r2 = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"], {"parameters": {}}))
    b1, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"], "shared"))
    b2, made = run(env, cad_store.create_build(
        env["pool"], r2["id"], env["user_a"], "shared"))
    assert made is True and b1["id"] != b2["id"]


def test_a_failed_build_records_why(env):
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    run(env, cad_store.fail_build(env["pool"], b["id"], "too_complex", "over the cap"))
    got = run(env, cad_store.get_build(env["pool"], b["id"], env["user_a"]))
    assert got["status"] == "failed"
    assert got["error_code"] == "too_complex"
    assert got["artifacts"] == []


def test_a_cancelled_build_is_cancelled_not_failed(env):
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    run(env, cad_store.fail_build(env["pool"], b["id"], "build_cancelled", "cancelled"))
    got = run(env, cad_store.get_build(env["pool"], b["id"], env["user_a"]))
    assert got["status"] == "cancelled"


def test_cancel_is_recorded_even_before_the_engine_answers(env):
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    run(env, cad_store.request_cancel(env["pool"], b["id"]))

    async def flag():
        async with env["pool"].acquire() as conn:
            return await conn.fetchval(
                "SELECT cancel_requested FROM cad_builds WHERE id=$1", uuid.UUID(b["id"]))
    assert run(env, flag()) is True


# ---------------------------------------------------------------------------
# Artifacts: rows and bytes together
# ---------------------------------------------------------------------------

def _finish(env, project_id, build_id, blobs=None, user=None, conformance=None):
    blobs = blobs or {"stl": b"solid test\nendsolid test\n", "step": b"ISO-10303-21;\n"}
    return run(env, cad_store.finish_build(
        env["pool"], build_id, user if user is not None else env["user_a"], project_id,
        artifacts=blobs,
        refs=[{"format": f, "media_type": f"model/{f}"} for f in blobs],
        validation={"brep_valid": True, "volume_mm3": 20622.6902},
        duration_ms=284, peak_rss_bytes=123456,
        # Defaults to None so every pre-7C caller keeps meaning what it meant: a build
        # with no DesignSpec to grade against, which is not a pass and not a failure.
        conformance=conformance,
    ))


def test_a_finished_build_has_rows_and_bytes(env, tmp_artifacts):
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    done = _finish(env, p["id"], b["id"])

    assert done["status"] == "succeeded"
    assert done["duration_ms"] == 284
    assert done["validation"]["brep_valid"] is True
    assert {a["format"] for a in done["artifacts"]} == {"stl", "step"}

    for a in done["artifacts"]:
        full = run(env, cad_store.get_artifact(env["pool"], a["id"], env["user_a"]))
        path = cad_store.resolve_storage_key(
            env["user_a"], p["id"], full["storage_key"])
        assert path and os.path.isfile(path)
        with open(path, "rb") as fh:
            blob = fh.read()
        assert len(blob) == a["size_bytes"]
        import hashlib
        assert hashlib.sha256(blob).hexdigest() == a["sha256"]


def test_storage_key_never_appears_in_a_listed_artifact(env):
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    done = _finish(env, p["id"], b["id"])
    for a in done["artifacts"]:
        assert "storage_key" not in a


def test_rebuilding_the_same_format_replaces_it(env):
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    _finish(env, p["id"], b["id"], {"stl": b"first"})
    done = _finish(env, p["id"], b["id"], {"stl": b"second-longer"})
    stl = [a for a in done["artifacts"] if a["format"] == "stl"]
    assert len(stl) == 1
    assert stl[0]["size_bytes"] == len(b"second-longer")


def test_a_key_pointing_outside_its_project_resolves_to_nothing(env):
    p = run(env, _project(env))
    assert cad_store.resolve_storage_key(
        env["user_a"], p["id"], "../../../etc/passwd") is None
    assert cad_store.resolve_storage_key(
        env["user_a"], p["id"], f"{env['user_b']}/x/y/part.stl") is None


# ---------------------------------------------------------------------------
# Quotas
# ---------------------------------------------------------------------------

def test_quota_refuses_before_a_byte_is_written(env, tmp_artifacts, monkeypatch):
    monkeypatch.setenv("CAD_PROJECT_QUOTA_BYTES", "64")
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))

    with pytest.raises(cad_store.QuotaExceeded) as e:
        _finish(env, p["id"], b["id"], {"stl": b"x" * 200})
    assert e.value.status == 413
    assert e.value.extra["scope"] == "project"

    # The refusal has to be total: no row, and nothing on disk under that build.
    got = run(env, cad_store.get_build(env["pool"], b["id"], env["user_a"]))
    assert got["artifacts"] == []
    assert not os.path.isdir(os.path.join(
        tmp_artifacts, "cad", str(env["user_a"]), p["id"], b["id"]))


def test_usage_is_counted_per_user_and_per_project(env):
    p1 = run(env, _project(env))
    p2 = run(env, _project(env, title="Second"))
    for proj in (p1, p2):
        b, _ = run(env, cad_store.create_build(
            env["pool"], proj["revision"]["id"], env["user_a"]))
        _finish(env, proj["id"], b["id"], {"stl": b"y" * 100})

    per_project = run(env, cad_store.usage_bytes(env["pool"], env["user_a"], p1["id"]))
    total = run(env, cad_store.usage_bytes(env["pool"], env["user_a"]))
    assert per_project == 100
    assert total >= 200
    # Another user's bytes are not on this user's bill.
    assert run(env, cad_store.usage_bytes(env["pool"], env["user_b"])) == 0


# ---------------------------------------------------------------------------
# Cross-user isolation — 404 shaped as None, never another user's row
# ---------------------------------------------------------------------------

def test_another_users_project_is_simply_absent(env):
    p = run(env, _project(env))
    assert run(env, cad_store.get_project(env["pool"], p["id"], env["user_b"])) is None
    assert run(env, cad_store.list_revisions(
        env["pool"], p["id"], env["user_b"])) == []
    assert run(env, cad_store.get_revision(
        env["pool"], p["revision"]["id"], env["user_b"])) is None


def test_another_users_build_and_artifact_are_absent(env):
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    done = _finish(env, p["id"], b["id"])
    aid = done["artifacts"][0]["id"]

    assert run(env, cad_store.get_build(env["pool"], b["id"], env["user_b"])) is None
    assert run(env, cad_store.get_artifact(env["pool"], aid, env["user_b"])) is None


def test_another_user_cannot_build_someone_elses_revision(env):
    p = run(env, _project(env))
    build, made = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_b"]))
    assert build == {} and made is False


# ---------------------------------------------------------------------------
# Retention and the reaper
# ---------------------------------------------------------------------------

def test_retention_keeps_the_newest_and_drops_the_rest(env, monkeypatch):
    monkeypatch.setenv("CAD_RETAINED_BUILDS_PER_REVISION", "2")
    p = run(env, _project(env))
    rid = p["revision"]["id"]
    ids = []
    for i in range(4):
        b, _ = run(env, cad_store.create_build(env["pool"], rid, env["user_a"]))
        _finish(env, p["id"], b["id"], {"stl": bytes([65 + i]) * 10})
        ids.append(b["id"])

    dropped = run(env, cad_store.enforce_retention(env["pool"], rid))
    assert dropped == 2
    surviving = [i for i in ids
                 if run(env, cad_store.get_build(env["pool"], i, env["user_a"]))]
    assert surviving == ids[-2:]


def test_retention_never_drops_a_failed_build(env, monkeypatch):
    """A failure holds no bytes and its error is the record of what went wrong.
    Counting it toward the cap would delete the diagnosis of a repeated failure."""
    monkeypatch.setenv("CAD_RETAINED_BUILDS_PER_REVISION", "1")
    p = run(env, _project(env))
    rid = p["revision"]["id"]
    failed, _ = run(env, cad_store.create_build(env["pool"], rid, env["user_a"]))
    run(env, cad_store.fail_build(env["pool"], failed["id"], "too_complex", "no"))
    ok, _ = run(env, cad_store.create_build(env["pool"], rid, env["user_a"]))
    _finish(env, p["id"], ok["id"], {"stl": b"z" * 10})

    run(env, cad_store.enforce_retention(env["pool"], rid))
    assert run(env, cad_store.get_build(env["pool"], failed["id"], env["user_a"]))
    assert run(env, cad_store.get_build(env["pool"], ok["id"], env["user_a"]))


def test_the_reaper_clears_files_no_row_claims(env, tmp_artifacts):
    """The crash-between-write-and-insert case, and the CASCADE case."""
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    done = _finish(env, p["id"], b["id"], {"stl": b"kept"})

    orphan_dir = os.path.join(tmp_artifacts, "cad", str(env["user_a"]), p["id"], "ghost")
    os.makedirs(orphan_dir, exist_ok=True)
    orphan = os.path.join(orphan_dir, "part.stl")
    with open(orphan, "wb") as fh:
        fh.write(b"nobody claims this")

    dry = run(env, cad_store.reap_orphans(env["pool"], dry_run=True))
    assert dry["orphans"] >= 1 and dry["removed"] == 0
    assert os.path.isfile(orphan), "a dry run removed a file"

    wet = run(env, cad_store.reap_orphans(env["pool"], dry_run=False))
    assert wet["removed"] >= 1
    assert not os.path.exists(orphan)

    # And the claimed file survived — a reaper that clears everything is not a reaper.
    kept = run(env, cad_store.get_artifact(
        env["pool"], done["artifacts"][0]["id"], env["user_a"]))
    assert cad_store.resolve_storage_key(env["user_a"], p["id"], kept["storage_key"])


def test_the_reaper_reports_rows_whose_bytes_are_gone_and_does_not_delete_them(env):
    """A row without its file is damage that already happened. Deleting the row would
    destroy the only evidence; the count is what surfaces it."""
    p = run(env, _project(env))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    done = _finish(env, p["id"], b["id"], {"stl": b"about to vanish"})
    art = run(env, cad_store.get_artifact(
        env["pool"], done["artifacts"][0]["id"], env["user_a"]))
    os.unlink(cad_store.resolve_storage_key(env["user_a"], p["id"], art["storage_key"]))

    out = run(env, cad_store.reap_orphans(env["pool"], dry_run=False))
    assert out["missing_files"] >= 1
    still = run(env, cad_store.get_artifact(
        env["pool"], done["artifacts"][0]["id"], env["user_a"]))
    assert still is not None


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

def test_measurements_are_none_until_something_builds(env):
    p = run(env, _project(env))
    assert run(env, cad_store.latest_measurements(
        env["pool"], p["revision"]["id"])) is None

    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    run(env, cad_store.fail_build(env["pool"], b["id"], "too_complex", "no"))
    assert run(env, cad_store.latest_measurements(
        env["pool"], p["revision"]["id"])) is None, "a failed build is not a measurement"

    ok, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    _finish(env, p["id"], ok["id"], {"stl": b"m"})
    got = run(env, cad_store.latest_measurements(env["pool"], p["revision"]["id"]))
    assert got["volume_mm3"] == 20622.6902


# ---------------------------------------------------------------------------
# Proposals and acceptance (Gate 7C-2)
#
# One sentence is what all of this is for: a failed proposal must not become the
# project head. The gate exists because a build can be flawless and still be the
# wrong part — a 30 mm cube with a 10 mm bore came out 35 mm with no hole in it,
# watertight, valid, one solid, and reported as "build succeeded".
#
# So the head moves for exactly one reason: a person said so.
# ---------------------------------------------------------------------------

def _proposal(**over):
    """A revision the model authored. ``created_by`` is the whole distinction."""
    spec = {"recipe_name": None, "source_kind": "cadir", "created_by": "ai",
            "parameters": {}, "cadir": {"schema_version": "0.1", "operations": []}}
    spec.update(over)
    return spec


FAILED = {"schema_version": "0.1", "status": "failed",
          "summary": "bounding box measured 30 × 35 × 35 mm, asked for 30 × 30 × 30 mm",
          "checks": [{"id": "bbox_set", "status": "failed", "label": "overall size",
                      "expected": "30 × 30 × 30 mm", "measured": "30 × 35 × 35 mm"}]}
PASSED = {"schema_version": "0.1", "status": "passed", "summary": "all 2 checks passed",
          "checks": []}


def test_a_generated_project_has_no_head_until_someone_accepts(env):
    """The empty head is the point, not an oversight.

    A project whose only revision is the model's proposal has nothing accepted in it,
    and saying so is more honest than pointing the head at work no one has looked at.
    """
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Generated cube", revision=_proposal()))
    assert p["head_revision"] is None
    assert p["revision"]["state"] == "proposal"
    assert p["revision"]["accepted_at"] is None
    assert p["revision"]["seq"] == 1, "a proposal is still a real revision in the history"


def test_a_user_authored_revision_is_accepted_on_arrival(env):
    """Nothing changed for the lane that was already working.

    Sliders and recipes are the user's own edits; asking someone to accept the thing
    they just typed would be a gate that teaches people to click through gates.
    """
    p = run(env, _project(env))
    assert p["head_revision"] == p["revision"]["id"]
    assert p["revision"]["state"] == "accepted"
    assert p["revision"]["accepted_at"] is not None


def test_a_proposal_appended_to_a_head_leaves_that_head_alone(env):
    p = run(env, _project(env))
    head = p["revision"]["id"]
    prop = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"], _proposal(),
        base_revision_id=head))

    assert prop["seq"] == 2 and prop["parent_id"] == head
    assert prop["state"] == "proposal"
    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] == head, "the model moved the head"
    # seq advanced even though the head did not: the proposal is in the history and
    # can be built, inspected and compared. It is only not what the next edit builds on.
    assert fresh["next_seq"] == 3


def test_a_proposal_can_be_repaired_by_editing_it(env):
    """The bounded repair, which the head-only staleness check used to forbid.

    A model that proposed a wrong part and is told to fix it has exactly one honest
    base: its own proposal. That revision never became the head, so comparing the base
    against the head alone answered `stale_revision` — on a generated project, where
    the head is NULL, it refused every repair there was.
    """
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Generated cube", revision=_proposal()))
    wrong = p["revision"]["id"]
    assert p["head_revision"] is None

    fixed = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"], _proposal(), base_revision_id=wrong))
    assert fixed["seq"] == 2
    assert fixed["parent_id"] == wrong, "the repair chains to what it repaired"
    assert fixed["state"] == "proposal"

    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] is None, "repairing a proposal accepts nothing"

    # And the check still catches the fork it exists for: the superseded proposal is
    # no longer a base anyone may edit from.
    with pytest.raises(cad_store.StaleRevision):
        run(env, cad_store.create_revision(
            env["pool"], p["id"], env["user_a"], _proposal(), base_revision_id=wrong))


def test_a_failed_build_does_not_wedge_the_next_edit(env):
    """The third honest base, and the wedge that made it necessary.

    A revision a person authored becomes the head the instant it is inserted — before
    its build has run. When that build then fails, the head and the newest revision both
    name a revision with no geometry, while the workspace goes on showing the last one
    that built, exactly as it should. Checking the base against only those two answered
    ``stale_revision`` to every edit made from the view the user was actually looking at,
    and the reload the UI offers in response returns the identical state. One failed
    build ended parameter editing for the project.
    """
    p = run(env, _project(env))
    good = p["revision"]["id"]
    b, _ = run(env, cad_store.create_build(env["pool"], good, env["user_a"]))
    _finish(env, p["id"], b["id"])

    broken = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"],
        {"recipe_name": "helmet_hanger_v1", "parameters": {"arm_len_mm": 999}},
        base_revision_id=good))
    bb, _ = run(env, cad_store.create_build(env["pool"], broken["id"], env["user_a"]))
    run(env, cad_store.fail_build(env["pool"], bb["id"], "export_failed",
                                  "the operation produced no geometry"))

    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] == broken["id"], "head still names the failed revision"

    ws = run(env, cad_store.workspace_snapshot(env["pool"], p["id"], env["user_a"]))
    assert ws["displayed"]["revision_id"] == good, "§3: the good geometry stays on screen"

    # The edit the panel sends when the user drags a slider on what they can see.
    fixed = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"],
        {"recipe_name": "helmet_hanger_v1", "parameters": {"arm_len_mm": 120}},
        base_revision_id=ws["displayed"]["revision_id"]))
    assert fixed["seq"] == 3
    assert fixed["parent_id"] == good, "it chains to what was on screen, not to the wreck"

    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] == fixed["id"], "and the head recovers by itself"

    # The check still catches what it exists for: a base older than all three is a fork.
    older = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"], {"parameters": {"arm_len_mm": 130}},
        base_revision_id=fixed["id"]))
    with pytest.raises(cad_store.StaleRevision):
        run(env, cad_store.create_revision(
            env["pool"], p["id"], env["user_a"], {"parameters": {"arm_len_mm": 140}},
            base_revision_id=broken["id"]))
    assert older["seq"] == 4


def test_an_unbuilt_proposal_cannot_be_accepted(env):
    """There is no geometry yet, so there is nothing this could be agreeing to."""
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Unbuilt", revision=_proposal()))
    with pytest.raises(cad_store.NotAcceptable) as e:
        run(env, cad_store.accept_revision(
            env["pool"], p["id"], p["revision"]["id"], env["user_a"]))
    assert e.value.code == "not_built"
    assert e.value.status == 409, "recoverable — build it and try again"


def test_a_failed_proposal_does_not_become_the_head(env):
    """The gate, stated as a test.

    The build succeeded. The geometry is sound. It is the wrong part, and the refusal
    carries the checks that say which dimension missed, because a 409 that only says
    "no" leaves the user with nothing to repair.
    """
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Wrong cube", revision=_proposal()))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    done = _finish(env, p["id"], b["id"], conformance=FAILED)

    # Both verdicts, recorded separately and neither overwriting the other.
    assert done["status"] == "succeeded"
    assert done["conformance_status"] == "failed"
    assert done["conformance"]["checks"][0]["measured"] == "30 × 35 × 35 mm"

    with pytest.raises(cad_store.NotAcceptable) as e:
        run(env, cad_store.accept_revision(
            env["pool"], p["id"], p["revision"]["id"], env["user_a"]))
    assert e.value.code == "conformance_failed"
    assert e.value.extra["conformance"]["checks"], "the refusal dropped its evidence"

    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] is None


def test_a_person_may_accept_a_mismatch_but_only_by_saying_so(env):
    """The override exists, and it is not reachable by accident.

    A checker that cannot be argued with traps the user; an override that happens
    silently is the thing this gate was built to stop. So it takes an explicit flag,
    which is one deliberate act rather than a second click in the same place.
    """
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Accepted anyway", revision=_proposal()))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    _finish(env, p["id"], b["id"], conformance=FAILED)

    rev = run(env, cad_store.accept_revision(
        env["pool"], p["id"], p["revision"]["id"], env["user_a"],
        acknowledge_conformance=True))
    assert rev["state"] == "accepted"

    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] == p["revision"]["id"]
    # The build's verdict is untouched by the acceptance. A person overrode it; that
    # does not make the part measure differently, and the record has to keep saying so.
    build = run(env, cad_store.get_build(env["pool"], b["id"], env["user_a"]))
    assert build["conformance_status"] == "failed"


def test_a_conforming_proposal_still_waits_for_a_person(env):
    """Passing is not accepting.

    The checks only cover what the DesignSpec stated. Everything it did not state —
    which is most of a part — is exactly what a person is being asked to look at.
    """
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Right cube", revision=_proposal()))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    _finish(env, p["id"], b["id"], conformance=PASSED)

    mid = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert mid["head_revision"] is None, "a passing grade moved the head by itself"

    rev = run(env, cad_store.accept_revision(
        env["pool"], p["id"], p["revision"]["id"], env["user_a"]))
    assert rev["state"] == "accepted"
    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] == p["revision"]["id"]


def test_an_ungraded_build_is_acceptable_because_unverified_is_not_a_failure(env):
    """A recipe build states no checkable dimensions, and must not be trapped by that.

    Only ``failed`` blocks. ``unverified`` means the spec said nothing measurable —
    an absence of evidence, which is not evidence of a wrong part.
    """
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Ungraded", revision=_proposal()))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    done = _finish(env, p["id"], b["id"])
    assert done["conformance"] is None and done["conformance_status"] is None

    rev = run(env, cad_store.accept_revision(
        env["pool"], p["id"], p["revision"]["id"], env["user_a"]))
    assert rev["state"] == "accepted"


def test_accepting_twice_is_the_same_as_accepting_once(env):
    """A double-click and a retried request are one act, and the latch is what says so."""
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Twice", revision=_proposal()))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    _finish(env, p["id"], b["id"], conformance=PASSED)

    first = run(env, cad_store.accept_revision(
        env["pool"], p["id"], p["revision"]["id"], env["user_a"]))
    second = run(env, cad_store.accept_revision(
        env["pool"], p["id"], p["revision"]["id"], env["user_a"]))
    assert second["accepted_at"] == first["accepted_at"], "the latch moved twice"


def test_accepting_a_revision_older_than_the_head_is_refused(env):
    """The head does not move backwards; restore moves forward instead.

    Rewinding it would leave every newer revision parented to something that is no
    longer the head — the same reason restore appends rather than rewinds.
    """
    p = run(env, _project(env))
    stale = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"], _proposal(),
        base_revision_id=p["revision"]["id"]))
    b, _ = run(env, cad_store.create_build(
        env["pool"], stale["id"], env["user_a"]))
    _finish(env, p["id"], b["id"], conformance=PASSED)

    # A later user edit moves the head past the proposal while it sat there.
    newer = run(env, cad_store.create_revision(
        env["pool"], p["id"], env["user_a"], {"parameters": {"arm_len_mm": 140}}))
    assert newer["seq"] > stale["seq"]

    with pytest.raises(cad_store.NotAcceptable) as e:
        run(env, cad_store.accept_revision(
            env["pool"], p["id"], stale["id"], env["user_a"]))
    assert e.value.code == "stale_proposal"
    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] == newer["id"]


def test_another_user_cannot_accept_your_proposal(env):
    """Absent, not forbidden — the same answer every other cross-user read gives."""
    p = run(env, cad_store.create_project(
        env["pool"], env["user_a"], "Mine", revision=_proposal()))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], env["user_a"]))
    _finish(env, p["id"], b["id"], conformance=PASSED)

    assert run(env, cad_store.accept_revision(
        env["pool"], p["id"], p["revision"]["id"], env["user_b"])) == {}
    fresh = run(env, cad_store.get_project(env["pool"], p["id"], env["user_a"]))
    assert fresh["head_revision"] is None


# ===========================================================================
# The router
#
# Two of Gate 3's promises are route-level and cannot be shown from the store:
# a cross-user request 404s, and ``storage_key`` never reaches a response body.
# These mount the real router on a bare app — no ``main``, so no Discord client,
# no model probes — with its own pool and its own pair of throwaway users.
#
# ``fab_cad.execute`` is stubbed here, and only here. The engine is proven by the
# cad-engine suite's 103 tests; what is unproven is the wiring around it, and a
# stub is what lets the build path be driven to completion deterministically.
# ===========================================================================

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from owui_compat import cad_router, fab_cad


class _User:
    def __init__(self, uid: int):
        self.id = uid
        self.username = f"u{uid}"
        self.email = f"u{uid}@invalid.test"
        self.avatar = None


async def _fake_execute(params, recipe=None, formats=None, build_id=None, **kw):
    blobs = {f: f"{f}:{recipe}:{sorted(params.items())}".encode() for f in (formats or ["stl"])}
    return {
        "meta": {"recipe": recipe},
        "artifacts": blobs,
        "artifact_refs": [{"format": f, "media_type": cad_router.MEDIA_TYPES.get(f, "")}
                          for f in blobs],
        "validation": {"brep_valid": True, "volume_mm3": 1234.5, "duration_ms": 7},
        "params": params,
        "build_id": build_id,
    }


@pytest.fixture(scope="module")
def client(tmp_artifacts):
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=6)
        async with pool.acquire() as conn:
            for stmt in cad_store.CAD_SCHEMA_SQL:
                await conn.execute(stmt)
            for tag in ("r1", "r2"):
                nonce = uuid.uuid4().hex[:12]
                state.setdefault("users", []).append(await conn.fetchval(
                    "INSERT INTO users (username, email, password) "
                    "VALUES ($1,$2,$3) RETURNING id",
                    f"cadrt-{tag}-{nonce}", f"cadrt-{tag}-{nonce}@invalid.test", "x"))
        app.state.pg_pool = pool
        yield
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE id = ANY($1::int[])",
                               state["users"])
        await pool.close()

    app = FastAPI(lifespan=lifespan)

    def get_current_user(request: Request):
        raw = request.headers.get("X-Test-User")
        if not raw:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return _User(int(raw))

    cad_router.register_cad_routes(app.router, get_current_user)

    old_flag = os.environ.get("HARVIS_ADAPTIVE_CAD_ENABLED")
    old_exec = fab_cad.execute
    os.environ["HARVIS_ADAPTIVE_CAD_ENABLED"] = "1"
    fab_cad.execute = _fake_execute
    try:
        with TestClient(app) as c:
            c.user_a, c.user_b = state["users"]
            yield c
    finally:
        fab_cad.execute = old_exec
        if old_flag is None:
            os.environ.pop("HARVIS_ADAPTIVE_CAD_ENABLED", None)
        else:
            os.environ["HARVIS_ADAPTIVE_CAD_ENABLED"] = old_flag


def _as(client, uid):
    return {"X-Test-User": str(uid)}


def _build_a_part(client, uid, title="Routed part"):
    """Create a project, kick a revision build, and wait for it to land."""
    p = client.post("/api/cad/projects", headers=_as(client, uid),
                    json={"title": title}).json()
    r = client.post(f"/api/cad/projects/{p['id']}/revisions", headers=_as(client, uid),
                    json={"base_revision_id": p["revision"]["id"],
                          "params": {"arm_len_mm": 95}, "formats": ["stl", "step"]})
    assert r.status_code == 202, r.text
    bid = r.json()["build_id"]
    for _ in range(100):
        b = client.get(f"/api/cad/builds/{bid}", headers=_as(client, uid)).json()
        if b["status"] not in ("queued", "running"):
            return p, b
    raise AssertionError("the build never reached a terminal status")


def test_the_flag_is_the_gate_not_the_ui(client):
    """With the flag off every gated route is indistinguishable from a backend that
    never had the lane. Capability stays reachable — a 404 there would defeat the
    only endpoint whose job is to say whether the lane exists."""
    os.environ["HARVIS_ADAPTIVE_CAD_ENABLED"] = ""
    try:
        assert client.get("/api/cad/projects", headers=_as(client, client.user_a)
                          ).status_code == 404
        cap = client.get("/api/cad/capability", headers=_as(client, client.user_a))
        assert cap.status_code == 200
        assert cap.json()["enabled"] is False
    finally:
        os.environ["HARVIS_ADAPTIVE_CAD_ENABLED"] = "1"


def test_capability_reports_the_engine_it_actually_probed(client):
    body = client.get("/api/cad/capability", headers=_as(client, client.user_a)).json()
    assert body["enabled"] is True
    assert body["units"] == "mm"
    assert "helmet_hanger_v1" in body["recipes"]
    assert isinstance(body["engine_reachable"], bool)
    assert body["quota"]["user_limit_bytes"] > 0


def test_a_build_runs_end_to_end_through_the_routes(client):
    p, b = _build_a_part(client, client.user_a)
    assert b["status"] == "succeeded", b
    assert {a["format"] for a in b["artifacts"]} == {"stl", "step"}
    assert b["validation"]["brep_valid"] is True

    art = b["artifacts"][0]
    got = client.get(f"/api/cad/builds/{b['id']}/artifacts/{art['id']}",
                     headers=_as(client, client.user_a))
    assert got.status_code == 200
    assert len(got.content) == art["size_bytes"]
    assert got.headers["x-content-type-options"] == "nosniff"


def test_storage_key_never_reaches_a_response_body(client):
    p, b = _build_a_part(client, client.user_a, title="Leak check")
    for url in (f"/api/cad/projects",
                f"/api/cad/projects/{p['id']}",
                f"/api/cad/builds/{b['id']}"):
        r = client.get(url, headers=_as(client, client.user_a))
        assert r.status_code == 200
        assert "storage_key" not in r.text
        assert "/data/artifacts" not in r.text


def test_every_cross_user_read_is_a_404(client):
    p, b = _build_a_part(client, client.user_a, title="Private")
    art = b["artifacts"][0]["id"]
    other = _as(client, client.user_b)
    for url in (f"/api/cad/projects/{p['id']}",
                f"/api/cad/builds/{b['id']}",
                f"/api/cad/builds/{b['id']}/artifacts/{art}",
                f"/api/cad/projects/{p['id']}/compare?a={p['revision']['id']}"
                f"&b={p['revision']['id']}"):
        assert client.get(url, headers=other).status_code == 404, url
    assert client.post(f"/api/cad/projects/{p['id']}/revisions", headers=other,
                       json={"base_revision_id": p["revision"]["id"]}
                       ).status_code == 404
    # And user B's project list does not contain it either — a 404 on the direct
    # read means nothing if the listing leaks the same row.
    ids = [x["id"] for x in client.get("/api/cad/projects", headers=other
                                       ).json()["projects"]]
    assert p["id"] not in ids


def test_a_stale_base_revision_is_a_409_carrying_both_ids(client):
    p = client.post("/api/cad/projects", headers=_as(client, client.user_a),
                    json={"title": "Conflict"}).json()
    first = p["revision"]["id"]
    client.post(f"/api/cad/projects/{p['id']}/revisions",
                headers=_as(client, client.user_a),
                json={"base_revision_id": first})
    r = client.post(f"/api/cad/projects/{p['id']}/revisions",
                    headers=_as(client, client.user_a),
                    json={"base_revision_id": first})
    assert r.status_code == 409
    # Both sides of the conflict travel with it, so the UI can name what it is
    # about to overwrite rather than saying "please refresh".
    err = r.json()["detail"]
    assert err["error_code"] == "stale_revision"
    assert err["base_revision_id"] == first
    assert err["head_revision"] != first


def test_a_garbage_id_is_not_found_not_a_500(client):
    for url in ("/api/cad/projects/not-a-uuid",
                "/api/cad/builds/not-a-uuid",
                "/api/cad/builds/not-a-uuid/artifacts/also-not"):
        assert client.get(url, headers=_as(client, client.user_a)).status_code == 404


def test_an_unknown_recipe_or_format_is_refused_before_any_work(client):
    a = _as(client, client.user_a)
    assert client.post("/api/cad/projects", headers=a,
                       json={"title": "x", "recipe": "../../etc/passwd"}
                       ).status_code == 400
    p = client.post("/api/cad/projects", headers=a, json={"title": "x"}).json()
    assert client.post(f"/api/cad/projects/{p['id']}/revisions", headers=a,
                       json={"base_revision_id": p["revision"]["id"],
                             "formats": ["exe"]}).status_code == 400
    # Sent as raw bytes, because no conforming JSON encoder will emit a bare NaN —
    # which is exactly why it has to be tested this way. This is the payload that
    # hung the worker before Gate 1A, and it must now die at the backend's edge.
    raw = ('{"base_revision_id": "%s", "params": {"arm_len_mm": NaN}}'
           % p["revision"]["id"])
    r = client.post(f"/api/cad/projects/{p['id']}/revisions",
                    headers={**a, "Content-Type": "application/json"}, content=raw)
    assert r.status_code in (400, 422), r.text


def test_an_idempotency_key_does_not_start_a_second_build(client):
    a = _as(client, client.user_a)
    p = client.post("/api/cad/projects", headers=a, json={"title": "Retry"}).json()
    body = {"base_revision_id": p["revision"]["id"], "idempotency_key": "same"}
    r1 = client.post(f"/api/cad/projects/{p['id']}/revisions", headers=a, json=body)
    rev = r1.json()["revision_id"]
    r2 = client.post(f"/api/cad/projects/{p['id']}/revisions", headers=a,
                     json={"base_revision_id": rev, "idempotency_key": "same"})
    # Second call targets the NEW head, so it is a different revision and a real
    # build. The key only collapses retries of the SAME intent.
    assert r2.status_code == 202
    assert r2.json()["build_id"] != r1.json()["build_id"]


def test_restore_moves_forward_and_never_rewinds_the_head(client):
    a = _as(client, client.user_a)
    p = client.post("/api/cad/projects", headers=a, json={"title": "History"}).json()
    first = p["revision"]["id"]
    second = client.post(f"/api/cad/projects/{p['id']}/revisions", headers=a,
                         json={"base_revision_id": first,
                               "params": {"arm_len_mm": 130}}).json()["revision_id"]
    r = client.post(f"/api/cad/projects/{p['id']}/revisions/{first}/restore",
                    headers=a, json={})
    assert r.status_code == 202
    third = r.json()["revision_id"]
    assert third not in (first, second)

    proj = client.get(f"/api/cad/projects/{p['id']}", headers=a).json()
    assert proj["head_revision"] == third
    assert [x["seq"] for x in proj["revisions"]] == [3, 2, 1]


def test_a_revision_route_answers_which_kind_of_revision_it_made(client):
    """The 202 says ``state``, because the caller cannot infer it.

    A client that read 202 as "this is now the project" would draw the wrong thing for
    every model-authored part. Nothing on this route can produce a proposal — there is
    deliberately no ``created_by`` in the request body, so a client can never declare
    its own edit to be the model's work or the model's work to be a person's — but the
    field is on every answer so the chat lane's proposals and this lane's edits are read
    the same way.
    """
    a = _as(client, client.user_a)
    p = client.post("/api/cad/projects", headers=a, json={"title": "Stated"}).json()
    r = client.post(f"/api/cad/projects/{p['id']}/revisions", headers=a,
                    json={"base_revision_id": p["revision"]["id"],
                          "params": {"arm_len_mm": 100}})
    assert r.status_code == 202
    assert r.json()["state"] == "accepted"
    assert r.json()["created"] is True


def test_accepting_an_accepted_revision_changes_nothing(client):
    """A no-op, not an error. The route is safe to call from a UI that cannot always
    know whether the thing on screen still needs accepting."""
    a = _as(client, client.user_a)
    p = client.post("/api/cad/projects", headers=a, json={"title": "Already"}).json()
    rid = p["revision"]["id"]
    r = client.post(f"/api/cad/projects/{p['id']}/revisions/{rid}/accept", headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "accepted"
    proj = client.get(f"/api/cad/projects/{p['id']}", headers=a).json()
    assert proj["head_revision"] == rid


def test_accept_is_absent_for_everyone_but_the_owner(client):
    a, b = _as(client, client.user_a), _as(client, client.user_b)
    p = client.post("/api/cad/projects", headers=a, json={"title": "Not yours"}).json()
    rid = p["revision"]["id"]
    assert client.post(f"/api/cad/projects/{p['id']}/revisions/{rid}/accept",
                       headers=b).status_code == 404
    # A revision id that is not a UUID is the same answer as one that does not exist:
    # telling those apart would say whether an id is well-formed, which is a fact about
    # someone else's project.
    assert client.post(f"/api/cad/projects/{p['id']}/revisions/not-a-uuid/accept",
                       headers=a).status_code == 404


def test_a_row_that_outlived_its_bytes_answers_410_not_404(client):
    """404 would read as 'no such artifact', which is a different and less honest
    thing than 'the metadata is here and the bytes are not'."""
    p, b = _build_a_part(client, client.user_a, title="Vanishing")
    art = b["artifacts"][0]

    # Resolve the key the way the route does, then delete the file underneath it.
    async def _key():
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            row = await cad_store.get_artifact(pool, art["id"], client.user_a)
            return row["storage_key"], row["project_id"]
        finally:
            await pool.close()

    lp = asyncio.new_event_loop()
    try:
        sk, pid = lp.run_until_complete(_key())
    finally:
        lp.close()
    os.unlink(cad_store.resolve_storage_key(client.user_a, pid, sk))

    r = client.get(f"/api/cad/builds/{b['id']}/artifacts/{art['id']}",
                   headers=_as(client, client.user_a))
    assert r.status_code == 410
    assert r.json()["detail"]["error_code"] == "artifact_missing"


def test_the_reaper_is_admin_only_and_says_nothing_to_anyone_else(client):
    r = client.post("/api/cad/maintenance/reap?dry_run=1",
                    headers=_as(client, client.user_a))
    assert r.status_code == 404


def test_compare_reports_both_parameter_and_measurement_differences(client):
    a = _as(client, client.user_a)
    p = client.post("/api/cad/projects", headers=a,
                    json={"title": "Diff", "params": {"arm_len_mm": 90}}).json()
    r2 = client.post(f"/api/cad/projects/{p['id']}/revisions", headers=a,
                     json={"base_revision_id": p["revision"]["id"],
                           "params": {"arm_len_mm": 130}}).json()
    out = client.get(f"/api/cad/projects/{p['id']}/compare"
                     f"?a={p['revision']['id']}&b={r2['revision_id']}", headers=a)
    assert out.status_code == 200
    body = out.json()
    assert body["parameters"]["arm_len_mm"] == {"a": 90, "b": 130}
    # Revision A was never built. Its measurements are absent rather than empty, and
    # the diff itself is None rather than {} — "not measured" and "measured
    # identical" must not render as the same thing.
    assert body["a"]["measurements"] is None
    assert body["measurements"] is None


# ---------------------------------------------------------------------------
# UX-D: a selection the client names, and the store re-reads
# ---------------------------------------------------------------------------

_MANIFEST = {
    "nodes": [
        {"node_id": "node_body_1", "parent_id": None, "label": "bottle_body",
         "kind": "body", "status": "valid", "selectable": True,
         "glb_pick_key": "node_body_1"},
        {"node_id": "node_feat_1", "parent_id": "node_body_1", "label": "neck taper",
         "kind": "feature", "status": "valid", "selectable": False,
         "glb_pick_key": None, "cadir_operation_id": "op_3"},
    ]
}


def _selectable_project(env, user=None):
    """A project whose head revision has a built scene manifest to select from."""
    p = run(env, _project(env, title="Selectable", user=user))
    b, _ = run(env, cad_store.create_build(
        env["pool"], p["revision"]["id"], user if user is not None else env["user_a"]))
    run(env, cad_store.finish_build(
        env["pool"], b["id"], user if user is not None else env["user_a"], p["id"],
        artifacts={"glb": b"glTF-ish"},
        refs=[{"format": "glb", "media_type": "model/gltf-binary"}],
        validation={"brep_valid": True},
        scene_manifest=_MANIFEST,
    ))
    return p


def _resolve(env, p, node_id, user=None, revision_id=None):
    return run(env, cad_store.resolve_selection(
        env["pool"], user if user is not None else env["user_a"], p["id"],
        revision_id or p["revision"]["id"], node_id))


def test_a_valid_selection_resolves_to_the_stores_own_words(env):
    """The whole point of the round trip: every human-readable field comes from here.

    A client that sent ``label: "the mounting boss"`` for this node would still get
    "bottle_body" back, because the label is read from the manifest the build wrote.
    """
    p = _selectable_project(env)
    got = _resolve(env, p, "node_body_1")
    assert got is not None
    assert got["label"] == "bottle_body"
    assert got["kind"] == "body"
    assert got["status"] == "valid"
    assert got["selectable"] is True
    assert got["project_title"] == "Selectable"
    assert got["revision_seq"] == 1
    # A feature carries the one field that lets a model edit precisely.
    assert _resolve(env, p, "node_feat_1")["cadir_operation_id"] == "op_3"


def test_another_users_selection_resolves_to_nothing(env):
    """404-shaped, not 403-shaped: user B learns nothing about whether it exists."""
    p = _selectable_project(env)
    assert _resolve(env, p, "node_body_1", user=env["user_b"]) is None


def test_a_node_that_is_not_in_this_manifest_resolves_to_nothing(env):
    """A stale chip — the workspace rebuilt and the slot moved — names nothing.

    This is what stops a selection from silently retargeting a different body that
    happens to occupy the old id's place.
    """
    p = _selectable_project(env)
    assert _resolve(env, p, "node_gone_9") is None


def test_a_revision_from_another_project_resolves_to_nothing(env):
    """Ownership of the revision is not enough; it must belong to *this* project."""
    mine = _selectable_project(env)
    other = _selectable_project(env)
    assert _resolve(env, mine, "node_body_1",
                    revision_id=other["revision"]["id"]) is None


def test_a_revision_with_no_build_resolves_to_nothing(env):
    """No build means no manifest, and a manifest is the only source of node names."""
    p = run(env, _project(env, title="Never built"))
    assert _resolve(env, p, "node_body_1") is None


def test_malformed_ids_resolve_to_nothing_without_touching_the_database(env):
    """Garbage in the ids is a client bug, not a 500."""
    p = _selectable_project(env)
    assert run(env, cad_store.resolve_selection(
        env["pool"], env["user_a"], "not-a-uuid",
        p["revision"]["id"], "node_body_1")) is None
    assert run(env, cad_store.resolve_selection(
        env["pool"], env["user_a"], p["id"], "not-a-uuid", "node_body_1")) is None
    assert _resolve(env, p, "") is None
    assert _resolve(env, p, None) is None


# ---------------------------------------------------------------------------
# Cancelling a turn (#144)
#
# The guard exists because the runner drops its task handle a moment before it writes
# the outcome. A cancel arriving in that gap finds nothing to interrupt, and an
# unguarded write would stamp "cancelled" over a turn that had already succeeded.
# ---------------------------------------------------------------------------

def test_cancelling_a_running_job_moves_the_row(env):
    job = run(env, cad_store.create_job(env["pool"], env["user_a"], "probe"))
    assert run(env, cad_store.cancel_job_if_running(env["pool"], job["id"])) is True
    row = run(env, cad_store.get_job(env["pool"], job["id"], env["user_a"]))
    assert row["status"] == "cancelled"
    assert row["phase"] == "cancelled"
    assert row["finished_at"] is not None


def test_cancelling_a_finished_job_does_not_rewrite_it(env):
    """The race this closes: a turn that succeeded must not read as cancelled."""
    job = run(env, cad_store.create_job(env["pool"], env["user_a"], "probe"))
    run(env, cad_store.update_job(env["pool"], job["id"], status="succeeded",
                                  phase="done"))
    assert run(env, cad_store.cancel_job_if_running(env["pool"], job["id"])) is False
    row = run(env, cad_store.get_job(env["pool"], job["id"], env["user_a"]))
    assert row["status"] == "succeeded"


def test_cancelling_a_job_id_that_is_not_a_uuid_is_not_an_error(env):
    assert run(env, cad_store.cancel_job_if_running(env["pool"], "not-a-uuid")) is False


# ---------------------------------------------------------------------------
# Queueing a turn behind the one already running (UX-G)
#
# The queue itself is memory — a waiting turn's lane and tool context are live Python
# objects and cannot be written to a row. The *row* is what makes a waiting turn real:
# it can be named, watched and stopped before it has begun, which is the whole
# difference between a queued turn and a message the browser is holding on to.
# ---------------------------------------------------------------------------

CONV = "conv-uxg"


def _job(env, *, conversation_id=CONV, queued=False, user=None):
    return run(env, cad_store.create_job(
        env["pool"], user if user is not None else env["user_a"], "probe",
        conversation_id=conversation_id, queued=queued))


def _drop(env, *jobs):
    async def go():
        async with env["pool"].acquire() as conn:
            await conn.execute("DELETE FROM cad_jobs WHERE id = ANY($1::uuid[])",
                               [uuid.UUID(str(j["id"])) for j in jobs])
    run(env, go())


def test_a_queued_turn_is_a_row_of_its_own_not_a_quiet_running_one(env):
    j = _job(env, queued=True)
    assert j["status"] == "queued"
    assert j["phase"] == "queued"
    assert j["conversation_id"] == CONV
    _drop(env, j)


def test_the_conversation_is_on_the_row_because_a_cancel_has_to_find_the_queue(env):
    j = _job(env)
    assert j["conversation_id"] == CONV
    assert run(env, cad_store.get_job(
        env["pool"], j["id"], env["user_a"]))["conversation_id"] == CONV
    _drop(env, j)


def test_the_turn_in_flight_is_the_oldest_of_running_and_waiting(env):
    first = _job(env)
    second = _job(env, queued=True)
    active = run(env, cad_store.find_active_job(env["pool"], env["user_a"], CONV))
    assert active["id"] == first["id"], "the running turn is the one in front"
    run(env, cad_store.update_job(env["pool"], first["id"], status="succeeded",
                                  phase="done"))
    active = run(env, cad_store.find_active_job(env["pool"], env["user_a"], CONV))
    assert active["id"] == second["id"], "the waiting turn moves up when the first ends"
    _drop(env, first, second)


def test_a_finished_conversation_has_no_turn_in_flight(env):
    j = _job(env)
    run(env, cad_store.update_job(env["pool"], j["id"], status="succeeded", phase="done"))
    assert run(env, cad_store.find_active_job(env["pool"], env["user_a"], CONV)) is None
    _drop(env, j)


def test_another_conversation_and_another_user_are_not_in_front_of_you(env):
    mine = _job(env, conversation_id="conv-other")
    theirs = _job(env, user=env["user_b"])
    assert run(env, cad_store.find_active_job(env["pool"], env["user_a"], CONV)) is None
    _drop(env, mine, theirs)


def test_a_turn_with_no_conversation_never_queues_behind_anything(env):
    """Discord and the recipe lane pass no conversation, and must not serialise."""
    j = _job(env, conversation_id=None)
    assert run(env, cad_store.find_active_job(env["pool"], env["user_a"], None)) is None
    assert run(env, cad_store.has_running_job(env["pool"], env["user_a"], None)) is False
    assert run(env, cad_store.count_waiting_jobs(env["pool"], env["user_a"], None)) == 0
    _drop(env, j)


def test_waiting_is_not_running(env):
    """The distinction the enqueue race depends on: if nothing is *running*, the
    turn that just joined the queue has to start itself, because the turn it thought
    was ahead of it has already finished and drained an empty queue."""
    waiting = _job(env, queued=True)
    assert run(env, cad_store.find_active_job(
        env["pool"], env["user_a"], CONV))["id"] == waiting["id"]
    assert run(env, cad_store.has_running_job(env["pool"], env["user_a"], CONV)) is False
    running = _job(env)
    assert run(env, cad_store.has_running_job(env["pool"], env["user_a"], CONV)) is True
    _drop(env, waiting, running)


def test_only_the_waiting_are_counted(env):
    running = _job(env)
    a, b = _job(env, queued=True), _job(env, queued=True)
    assert run(env, cad_store.count_waiting_jobs(env["pool"], env["user_a"], CONV)) == 2
    _drop(env, running, a, b)


def test_a_waiting_turn_is_claimed_once_and_only_once(env):
    j = _job(env, queued=True)
    assert run(env, cad_store.claim_queued_job(env["pool"], j["id"])) is True
    row = run(env, cad_store.get_job(env["pool"], j["id"], env["user_a"]))
    assert (row["status"], row["phase"]) == ("running", "starting")
    assert run(env, cad_store.claim_queued_job(env["pool"], j["id"])) is False, \
        "a second drain must not restart a turn already running"
    _drop(env, j)


def test_a_turn_stopped_while_waiting_is_never_started(env):
    """The one outcome a queue must not produce: a model asked to do work the user
    has already called off."""
    j = _job(env, queued=True)
    assert run(env, cad_store.cancel_job_if_running(env["pool"], j["id"])) is True
    assert run(env, cad_store.claim_queued_job(env["pool"], j["id"])) is False
    assert run(env, cad_store.get_job(
        env["pool"], j["id"], env["user_a"]))["status"] == "cancelled"
    _drop(env, j)


def test_claiming_a_job_id_that_is_not_a_uuid_is_not_an_error(env):
    assert run(env, cad_store.claim_queued_job(env["pool"], "not-a-uuid")) is False


def test_the_reaper_ends_turns_the_server_walked_out_on(env):
    """A turn only leaves `running` because its own task writes the outcome. A backend
    that stops mid-turn leaves a row claiming to be in progress forever — a spinner
    that outlives the work it describes."""
    old_running, old_waiting = _job(env), _job(env, queued=True)
    fresh = _job(env)

    async def backdate_and_reap():
        async with env["pool"].acquire() as conn:
            await conn.execute(
                "UPDATE cad_jobs SET created_at = NOW() - INTERVAL '40 minutes' "
                "WHERE id = ANY($1::uuid[])",
                [uuid.UUID(str(old_running["id"])), uuid.UUID(str(old_waiting["id"]))])
            await conn.execute(cad_store.REAP_STRANDED_CAD_JOBS_SQL)

    run(env, backdate_and_reap())
    for stranded in (old_running, old_waiting):
        row = run(env, cad_store.get_job(env["pool"], stranded["id"], env["user_a"]))
        assert row["status"] == "failed"
        assert row["error_code"] == "job_stranded"
        assert row["finished_at"] is not None
    assert run(env, cad_store.get_job(
        env["pool"], fresh["id"], env["user_a"]))["status"] == "running", \
        "a turn started minutes ago is a live turn, not a stranded one"
    _drop(env, old_running, old_waiting, fresh)


# ---------------------------------------------------------------------------
# HE-7: render recipes share the `variant` column, and QC guards the write
# ---------------------------------------------------------------------------

def test_render_presets_cover_every_recipe():
    """A recipe id is stored as a render's ``variant``, so the allowlist on the write
    has to admit it or a recipe capture is refused as "not a camera preset"."""
    from owui_compat import cad_render_recipes
    assert set(cad_render_recipes.RECIPE_IDS) <= set(cad_store.RENDER_PRESETS)
    assert not set(cad_render_recipes.RECIPE_IDS) & set(cad_store.CAMERA_PRESETS), \
        "sharing one uniqueness constraint, a collision would silently overwrite"
    for recipe_id in cad_render_recipes.RECIPE_IDS:
        assert cad_store._RENDER_LABELS.get(recipe_id), \
            "a render with no label reads as a blank row in the timeline"


def _mask(paint) -> bytes:
    import io
    import numpy as np
    from PIL import Image
    px = np.zeros((60, 80, 3), dtype=np.uint8)
    paint(px)
    out = io.BytesIO()
    Image.fromarray(px, mode="RGB").save(out, format="PNG")
    return out.getvalue()


_RECIPE = {
    "recipe_id": "ev_overview",
    "mask_palette": {"node_a": "#FF0000"},
    "expected_visible_parts": ["node_a"],
    "rotationally_symmetric": False,
    "exempt_from_similarity": False,
}


def test_a_blank_mask_stops_the_write_before_any_bytes_reach_disk():
    """The one QC finding that refuses a picture, raised as a store error so it takes
    the same path as the size ceiling and the source-digest check — a caller cannot
    reach the write without passing it."""
    pytest.importorskip("PIL")
    with pytest.raises(cad_store.CadStoreError) as e:
        cad_store._render_qc(_mask(lambda px: None), _RECIPE, {})
    assert e.value.code == "render_rejected"


def test_a_good_mask_contributes_evidence_and_nothing_else():
    pytest.importorskip("PIL")
    blob = _mask(lambda px: px[10:50, 10:70].__setitem__(slice(None), (255, 0, 0)))
    meta = cad_store._render_qc(blob, _RECIPE, {})
    assert meta["recipe_id"] == "ev_overview"
    assert meta["visible_parts"] == ["node_a"]
    assert isinstance(meta["dhash"], int)
    assert meta["qc"] == [], "a well-framed picture of what was asked for has no findings"
    assert meta["disclaimer"]


def test_no_mask_stores_the_render_unmeasured_rather_than_refusing_it():
    """A client that has not learned the second pass, or a build with more bodies than
    mask colours, still produces a real picture of a real build."""
    assert cad_store._render_qc(None, _RECIPE, {}) == {}
    assert cad_store._render_qc(b"whatever", None, {}) == {}
    assert cad_store._render_qc(b"whatever", {"mask_palette": {}}, {}) == {}


def test_bytes_that_are_not_a_png_are_a_400_not_a_crash():
    pytest.importorskip("PIL")
    with pytest.raises(cad_store.CadStoreError) as e:
        cad_store._render_qc(b"GIF89a" + b"\x00" * 60, _RECIPE, {})
    assert e.value.status == 400
