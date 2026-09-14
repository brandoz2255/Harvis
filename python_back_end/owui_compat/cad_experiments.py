"""Disposable experiments (HE-8) — where a repair is allowed to fail.

The arithmetic this gate exists for: revisions are immutable and ``seq`` only ever
goes up, so before this module every repair attempt cost the project a permanent
revision whether or not it produced anything. That is how a session ends with eight
revisions, seven builds and no part — the failure that motivated ``_precheck`` in the
first place. An experiment absorbs the attempts and hands back **at most one**
revision, at the end, and only if something worked.

Four properties, and each one is structural rather than a rule somebody has to
remember:

**The answer key is not reachable from inside.** ``design_spec`` here is a copy of the
base revision's spec, frozen at open time and hashed. :func:`record_attempt` takes
geometry and parameters and nothing else — there is no column an attempt could write a
spec into. "An experiment may not weaken the DesignSpec or widen a tolerance" is
therefore a fact about the schema. ``spec_sha256`` is the check on top of that: it
catches a frozen copy edited out of band, and a base revision that changed underneath.

**A failed experiment cannot move the head.** Promotion inserts the revision with the
experiment's ``created_by``, which is ``ai`` for every repair loop, and
:func:`cad_store.is_proposal` has always kept an AI-authored revision off the head.
Nothing new enforces this; the existing rule is simply now the only path.

**A failed experiment leaves nothing behind.** :func:`abandon` unlinks the experiment's
build files and deletes their rows in one transaction. The experiment row itself stays,
closed, because "we tried this and it did not work" is a fact worth keeping and it
costs a few hundred bytes.

**Nothing here touches the real history.** There is no ``UPDATE cad_revisions`` and no
``UPDATE cad_projects`` in this module except the one that advances ``next_seq`` at
promotion — the same statement, under the same row lock, that an ordinary append uses.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid

from . import cad_store

logger = logging.getLogger(__name__)

OPEN = "open"
PROMOTED = "promoted"
ABANDONED = "abandoned"

# How many attempts one experiment may hold. A ceiling rather than a target: the
# caller says how many rounds it intends to run and this only stops a loop that has
# lost track of itself. The repair budget itself lives in `cad_agent.MAX_REPAIRS` and
# is HE-9's to raise.
MAX_ATTEMPTS_CEILING = int(os.getenv("HARVIS_CAD_EXPERIMENT_ATTEMPTS", "5"))


class ExperimentClosed(cad_store.CadStoreError):
    """The experiment has already been promoted or abandoned.

    409 rather than 404, and deliberately not silent: a loop that keeps writing to a
    closed experiment is a loop that thinks it is still repairing something.
    """

    def __init__(self, experiment_id: str, status: str):
        super().__init__(
            "experiment_closed",
            f"this experiment is {status}; open a new one to try again",
            status=409,
            extra={"experiment_id": experiment_id, "status": status},
        )


class AttemptsExhausted(cad_store.CadStoreError):
    def __init__(self, experiment_id: str, attempts: int, cap: int):
        super().__init__(
            "attempts_exhausted",
            f"this experiment has used all {cap} of its attempts",
            status=409,
            extra={"experiment_id": experiment_id, "attempts": attempts,
                   "max_attempts": cap},
        )


class NotPromotable(cad_store.CadStoreError):
    """The experiment produced nothing a revision could honestly be made from."""

    def __init__(self, code: str, message: str, extra: dict | None = None):
        super().__init__(code, message, status=409, extra=extra)


def spec_digest(spec: dict | None) -> str:
    """The frozen spec's fingerprint.

    ``sort_keys`` and no whitespace, so the digest is a property of the spec's content
    rather than of how a particular round-trip through JSONB chose to print it — the
    same canonicalisation ``canonical_source_hash`` already uses for documents.
    """
    return hashlib.sha256(
        json.dumps(spec or {}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _row(row) -> dict:
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]),
        "base_revision_id": str(row["base_revision_id"]),
        "status": row["status"],
        "reason": row["reason"],
        "attempts": int(row["attempts"]),
        "max_attempts": int(row["max_attempts"]),
        # The frozen copy travels with the experiment so a repair prompt can quote the
        # thing it is being measured against without a second query — and so a reader
        # can see that it is a copy.
        "design_spec": cad_store._jsonb(row["design_spec"]) or {},
        "spec_sha256": row["spec_sha256"],
        "cadir": cad_store._jsonb(row["cadir"]) if row["cadir"] else None,
        "parameters": cad_store._jsonb(row["parameters"]) or {},
        "created_by": row["created_by"],
        "promoted_revision_id": (str(row["promoted_revision_id"])
                                 if row["promoted_revision_id"] else None),
        "closed_reason": row["closed_reason"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "closed_at": row["closed_at"].isoformat() if row["closed_at"] else None,
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

async def get_experiment(pool, experiment_id: str, user_id: int) -> dict | None:
    """Ownership in the WHERE clause, like every other read in this lane."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT e.* FROM cad_experiments e "
            "JOIN cad_projects p ON p.id = e.project_id "
            "WHERE e.id=$1 AND p.user_id=$2",
            uuid.UUID(str(experiment_id)), int(user_id),
        )
    return _row(row) if row else None


async def list_experiments(pool, project_id: str, user_id: int,
                           limit: int = 50) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT e.* FROM cad_experiments e "
            "JOIN cad_projects p ON p.id = e.project_id "
            "WHERE e.project_id=$1 AND p.user_id=$2 "
            "ORDER BY e.created_at DESC LIMIT $3",
            uuid.UUID(str(project_id)), int(user_id), max(1, min(int(limit), 200)),
        )
    return [_row(r) for r in rows]


async def open_experiment_of(pool, base_revision_id: str) -> dict | None:
    """The open experiment on a revision, if one is running.

    There is at most one — the partial unique index says so. A second repair loop on
    the same revision would be two writers on one working copy, and the loser's
    attempts would silently disappear into the winner's.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cad_experiments WHERE base_revision_id=$1 AND status='open'",
            uuid.UUID(str(base_revision_id)),
        )
    return _row(row) if row else None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

async def open_experiment(pool, project_id: str, user_id: int, base_revision_id: str,
                          *, reason: str = "", max_attempts: int | None = None,
                          created_by: str = "ai") -> dict:
    """Branch off a revision. Returns ``{}`` when the revision is not the caller's.

    The working copy starts as a byte-for-byte copy of the base — same CadIR, same
    parameters — so the first attempt edits what the user is actually looking at rather
    than a reconstruction of it.
    """
    cap = MAX_ATTEMPTS_CEILING if max_attempts is None else int(max_attempts)
    cap = max(1, min(cap, MAX_ATTEMPTS_CEILING))
    async with pool.acquire() as conn:
        base = await conn.fetchrow(
            "SELECT r.* FROM cad_revisions r JOIN cad_projects p ON p.id = r.project_id "
            "WHERE r.id=$1 AND r.project_id=$2 AND p.user_id=$3",
            uuid.UUID(str(base_revision_id)), uuid.UUID(str(project_id)), int(user_id),
        )
        if not base:
            return {}
        spec = cad_store._jsonb(base["design_spec"]) or {}
        cadir = cad_store._jsonb(base["cadir"]) if base["cadir"] else None
        params = cad_store._jsonb(base["parameters"]) or {}
        eid = uuid.uuid4()
        row = await conn.fetchrow(
            "INSERT INTO cad_experiments "
            "(id, project_id, base_revision_id, reason, max_attempts, design_spec, "
            " spec_sha256, cadir, parameters, created_by) "
            "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8::jsonb,$9::jsonb,$10) "
            # An open experiment already exists on this revision — the partial unique
            # index catches the race the read above cannot. The loser gets the running
            # one rather than an error, because two callers asking to repair the same
            # revision want the same thing.
            "ON CONFLICT DO NOTHING RETURNING *",
            eid, uuid.UUID(str(project_id)), base["id"], (reason or "")[:500], cap,
            json.dumps(spec), spec_digest(spec),
            json.dumps(cadir) if cadir is not None else None,
            json.dumps(params), (created_by or "ai")[:32],
        )
        if row is None:
            row = await conn.fetchrow(
                "SELECT * FROM cad_experiments "
                "WHERE base_revision_id=$1 AND status='open'", base["id"])
    if row is None:  # the conflicting row closed between the insert and the re-read
        raise cad_store.CadStoreError(
            "experiment_race", "the experiment could not be opened", status=409)
    return _row(row)


async def record_attempt(pool, experiment_id: str, user_id: int, *,
                         cadir: dict | None, parameters: dict | None = None,
                         note: str = "") -> dict:
    """Write one repair round into the working copy and count it.

    Takes geometry and parameters. It does not take a spec, and that absence is the
    enforcement described in the module docstring — an attempt has no way to move the
    target it is being measured against.

    One transaction under ``FOR UPDATE``, so two rounds racing cannot both read
    ``attempts = 2`` and both write 3.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT e.* FROM cad_experiments e "
                "JOIN cad_projects p ON p.id = e.project_id "
                "WHERE e.id=$1 AND p.user_id=$2 FOR UPDATE OF e",
                uuid.UUID(str(experiment_id)), int(user_id),
            )
            if not row:
                return {}
            if row["status"] != OPEN:
                raise ExperimentClosed(str(row["id"]), row["status"])
            if int(row["attempts"]) >= int(row["max_attempts"]):
                raise AttemptsExhausted(str(row["id"]), int(row["attempts"]),
                                        int(row["max_attempts"]))
            out = await conn.fetchrow(
                "UPDATE cad_experiments SET attempts = attempts + 1, "
                " cadir = COALESCE($2::jsonb, cadir), "
                " parameters = COALESCE($3::jsonb, parameters), "
                " reason = CASE WHEN $4 = '' THEN reason ELSE $4 END, "
                " updated_at = NOW() "
                "WHERE id=$1 RETURNING *",
                row["id"],
                json.dumps(cadir) if cadir is not None else None,
                json.dumps(parameters) if parameters is not None else None,
                (note or "")[:500],
            )
    return _row(out)


async def create_experiment_build(pool, experiment_id: str, user_id: int) -> dict:
    """A build row for the current working copy. Returns ``{}`` if not the caller's.

    ``revision_id`` is the base revision, because that is honestly what this is an
    attempt at, and because artifacts, quota, the reaper and the render binding all key
    on it. ``experiment_id`` is what keeps it out of the history — see the migration
    comment in ``cad_store``.

    No idempotency key: an experiment build is always a fresh attempt, and the attempt
    counter is the thing that bounds them.
    """
    async with pool.acquire() as conn:
        exp = await conn.fetchrow(
            "SELECT e.* FROM cad_experiments e "
            "JOIN cad_projects p ON p.id = e.project_id "
            "WHERE e.id=$1 AND p.user_id=$2",
            uuid.UUID(str(experiment_id)), int(user_id),
        )
        if not exp:
            return {}
        if exp["status"] != OPEN:
            raise ExperimentClosed(str(exp["id"]), exp["status"])
        row = await conn.fetchrow(
            "INSERT INTO cad_builds (id, revision_id, status, started_at, experiment_id) "
            "VALUES ($1, $2, 'running', NOW(), $3) RETURNING *",
            uuid.uuid4(), exp["base_revision_id"], exp["id"],
        )
    return cad_store._row_build(row)


async def promote(pool, experiment_id: str, user_id: int, build_id: str) -> dict:
    """Turn a working experiment into one real revision. Returns that revision.

    Five refusals, each with its own code because each has a different next step:

    ``experiment_closed``
        Already promoted or abandoned. A second promotion would mint a second revision
        from the same work.
    ``no_geometry``
        The named build did not succeed, or belongs to a different experiment. There is
        nothing to promote.
    ``conformance_failed``
        The build measured wrong against the frozen spec. This is the refusal the gate
        exists for and it is **not** overridable here — an experiment that failed its
        own answer key has no business becoming history. A person may still accept a
        failing *revision* with ``acknowledge_conformance``; that decision belongs to
        them, at the head, not to a repair loop.
    ``spec_drift``
        The frozen spec no longer hashes to what was recorded, or no longer matches the
        base revision. Something changed the target mid-experiment, so no verdict taken
        against it can be trusted.
    ``nothing_built``
        The working copy has no CadIR. Nothing was ever authored.

    ``unverified`` promotes. It is the common grade for anything the regex extractor
    could not state a check for, and refusing it would make experiments useless on
    exactly the parts that need them most. The promoted revision is a *proposal* —
    ``created_by`` is the experiment's, which is ``ai`` for every repair loop — so
    :func:`cad_store.is_proposal` keeps the head where it is and a person still decides.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            exp = await conn.fetchrow(
                "SELECT e.* FROM cad_experiments e "
                "JOIN cad_projects p ON p.id = e.project_id "
                "WHERE e.id=$1 AND p.user_id=$2 FOR UPDATE OF e",
                uuid.UUID(str(experiment_id)), int(user_id),
            )
            if not exp:
                return {}
            if exp["status"] != OPEN:
                raise ExperimentClosed(str(exp["id"]), exp["status"])

            build = await conn.fetchrow(
                "SELECT * FROM cad_builds WHERE id=$1 AND experiment_id=$2",
                uuid.UUID(str(build_id)), exp["id"],
            )
            if build is None or build["status"] != "succeeded":
                raise NotPromotable(
                    "no_geometry",
                    "that build did not succeed inside this experiment, so there is "
                    "no geometry to promote",
                    {"experiment_id": str(exp["id"]), "build_id": str(build_id),
                     "build_status": build["status"] if build else None},
                )
            if build["conformance_status"] == "failed":
                report = cad_store._jsonb(build["conformance"]) or {}
                raise NotPromotable(
                    "conformance_failed",
                    (report.get("summary")
                     or "this attempt does not match what was asked for"),
                    {"experiment_id": str(exp["id"]), "build_id": str(build["id"]),
                     "conformance": report},
                )

            frozen = cad_store._jsonb(exp["design_spec"]) or {}
            base = await conn.fetchrow(
                "SELECT * FROM cad_revisions WHERE id=$1", exp["base_revision_id"])
            base_spec = cad_store._jsonb(base["design_spec"]) if base else None
            if (spec_digest(frozen) != exp["spec_sha256"]
                    or spec_digest(base_spec or {}) != exp["spec_sha256"]):
                raise NotPromotable(
                    "spec_drift",
                    "the design spec this experiment was measured against has "
                    "changed, so its verdict cannot be trusted",
                    {"experiment_id": str(exp["id"])},
                )

            cadir = cad_store._jsonb(exp["cadir"]) if exp["cadir"] else None
            if not cadir:
                raise NotPromotable(
                    "nothing_built",
                    "this experiment has no geometry of its own to promote",
                    {"experiment_id": str(exp["id"])},
                )

            # From here it is an ordinary append, under the project's own row lock, so
            # a promotion and a hand edit racing for `next_seq` resolve the way two
            # hand edits already do.
            proj = await conn.fetchrow(
                "SELECT * FROM cad_projects WHERE id=$1 FOR UPDATE", exp["project_id"])
            seq = int(proj["next_seq"])
            spec = {
                # The frozen copy, never the experiment's working state — there is no
                # working state for it to be.
                "design_spec": frozen,
                "cadir": cadir,
                "parameters": cad_store._jsonb(exp["parameters"]) or {},
                "source_kind": base["source_kind"] if base else "recipe",
                "recipe_name": base["recipe_name"] if base else None,
                "created_by": exp["created_by"],
                "model_provider": base["model_provider"] if base else None,
                "model_name": base["model_name"] if base else None,
            }
            accepted = not cad_store.is_proposal(spec)
            rev = await cad_store._insert_revision(
                conn, exp["project_id"], exp["base_revision_id"], seq, spec,
                accepted=accepted,
            )
            head = proj["head_revision"]
            await conn.execute(
                "UPDATE cad_projects SET head_revision=$1, next_seq=$2, updated_at=NOW() "
                "WHERE id=$3",
                uuid.UUID(rev["id"]) if accepted else head, seq + 1, proj["id"],
            )
            # The winning build joins the revision it produced, so the promoted
            # revision has geometry the moment it exists rather than needing a rebuild
            # of work that already ran.
            await conn.execute(
                "UPDATE cad_builds SET revision_id=$1, experiment_id=NULL WHERE id=$2",
                uuid.UUID(rev["id"]), build["id"],
            )
            await conn.execute(
                "UPDATE cad_experiments SET status=$1, promoted_revision_id=$2, "
                " closed_reason='promoted', closed_at=NOW(), updated_at=NOW() "
                "WHERE id=$3",
                PROMOTED, uuid.UUID(rev["id"]), exp["id"],
            )
            # Everything the experiment tried and discarded. Collected inside the
            # transaction, removed after it — file IO does not belong in a lock that
            # is holding up `next_seq` for the whole project.
            losers = [r["id"] for r in await conn.fetch(
                "SELECT id FROM cad_builds WHERE experiment_id=$1", exp["id"])]

    await _discard_builds(pool, losers)
    return rev


async def _discard_builds(pool, build_ids: list) -> int:
    """Remove a set of experiment builds, files first. The rows are the only record of
    where the files are, so the order is not a preference."""
    if not build_ids:
        return 0
    await cad_store._unlink_build_files(pool, build_ids)
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM cad_builds WHERE id = ANY($1::uuid[])", build_ids)
    return len(build_ids)


async def abandon(pool, experiment_id: str, user_id: int,
                  reason: str = "") -> dict:
    """Close a failed experiment and remove what it made. Returns the closed row.

    The builds go — rows and files both — because they are attempts at geometry nobody
    will ever look at again, and each one holds a STEP and a mesh against the user's
    quota. The experiment row stays: "this was tried and it did not work" is the one
    durable thing a failed experiment is worth.

    Files are unlinked before the rows, because the rows are the only record of where
    the files are.
    """
    async with pool.acquire() as conn:
        exp = await conn.fetchrow(
            "SELECT e.* FROM cad_experiments e "
            "JOIN cad_projects p ON p.id = e.project_id "
            "WHERE e.id=$1 AND p.user_id=$2",
            uuid.UUID(str(experiment_id)), int(user_id),
        )
        if not exp:
            return {}
        if exp["status"] != OPEN:
            return _row(exp)
        builds = await conn.fetch(
            "SELECT id FROM cad_builds WHERE experiment_id=$1", exp["id"])

    doomed = [b["id"] for b in builds]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE cad_experiments SET status=$1, closed_reason=$2, "
            " closed_at=NOW(), updated_at=NOW() "
            # The status guard is the latch: a promotion that landed between the read
            # and this write must not be rewritten into an abandonment.
            "WHERE id=$3 AND status='open' RETURNING *",
            ABANDONED, (reason or "abandoned")[:500], exp["id"],
        )
    if row is None:  # it closed under us; leave its builds alone and report the truth
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM cad_experiments WHERE id=$1", exp["id"])
        return _row(row)
    await _discard_builds(pool, doomed)
    logger.info("cad experiment %s abandoned after %d attempt(s), %d build(s) removed",
                exp["id"], int(exp["attempts"]), len(doomed))
    return _row(row)
