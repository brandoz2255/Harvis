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

def test_the_store_has_no_update_path_for_revisions():
    """Immutability is enforced by the absence of the code, so assert the absence.

    A comment saying "insert only" is not a constraint. This is the closest thing to
    one short of a database trigger, and it fails the moment someone adds the UPDATE
    that a comment would have quietly permitted.
    """
    src = inspect.getsource(cad_store).lower()
    assert "update cad_revisions" not in src


def test_project_and_first_revision_land_together(env):
    p = run(env, _project(env))
    assert p["revision"]["seq"] == 1
    assert p["head_revision"] == p["revision"]["id"]
    assert p["next_seq"] == 2
    assert p["revision"]["parent_id"] is None


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

def _finish(env, project_id, build_id, blobs=None, user=None):
    blobs = blobs or {"stl": b"solid test\nendsolid test\n", "step": b"ISO-10303-21;\n"}
    return run(env, cad_store.finish_build(
        env["pool"], build_id, user if user is not None else env["user_a"], project_id,
        artifacts=blobs,
        refs=[{"format": f, "media_type": f"model/{f}"} for f in blobs],
        validation={"brep_valid": True, "volume_mm3": 20622.6902},
        duration_ms=284, peak_rss_bytes=123456,
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
