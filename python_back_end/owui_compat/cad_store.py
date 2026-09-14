"""Gate 3 persistence for the local CAD lane: projects, immutable revisions, build
attempts, and artifact metadata.

Four tables and one rule that shapes all of them: **a revision is a fact, a build is
an attempt.** Revision rows are inserted and never updated — they record what the
user asked for. Build rows carry the mutable status of trying to make it, and a
revision can be built many times (a retry, a re-export in another format, a rebuild
after an engine fix) without its history changing underneath.

**Bytes are not in Postgres.** ``cad_artifacts`` holds size, media type, sha256 and
an opaque ``storage_key``; the files live under ``$ARTIFACT_STORAGE_DIR/cad/...``,
the same volume the Adaptive Space lane already writes to. A STEP or 3MF in ``BYTEA``
would land in the WAL and in every backup, which is exactly the cost the storage work
this repo just finished was undoing.

``storage_key`` never leaves the server. Callers address artifacts by their row id
and the route streams the bytes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from . import cad_render_qc, cad_render_recipes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# One statement per table so a failure names the table that failed.
#
# The FK to users(id) is a deliberate deviation. `adaptive_spaces` uses a bare
# `user_id INTEGER NOT NULL` with no reference, and matching that convention would
# have been the low-friction choice — but this lane writes FILES keyed by user id,
# and an orphaned project whose owner no longer exists is an artifact directory
# nothing will ever reclaim. users.id is `SERIAL PRIMARY KEY`, so INTEGER is the
# matching type and the cascade is well-defined.
CREATE_CAD_PROJECTS_SQL = """
CREATE TABLE IF NOT EXISTS cad_projects (
    id              UUID PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT,
    title           TEXT NOT NULL,
    head_revision   UUID,
    next_seq        INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cad_projects_user
    ON cad_projects(user_id, updated_at DESC);
"""

# IMMUTABLE. Insert only — there is no UPDATE path for this table anywhere in this
# module, and that absence is the enforcement.
#
# The composite FK is the point of the redundant `UNIQUE (project_id, id)`: a plain
# `parent_id REFERENCES cad_revisions(id)` would happily accept a parent from another
# user's project, which is a cross-tenant edge in the history graph.
CREATE_CAD_REVISIONS_SQL = """
CREATE TABLE IF NOT EXISTS cad_revisions (
    id             UUID PRIMARY KEY,
    project_id     UUID NOT NULL REFERENCES cad_projects(id) ON DELETE CASCADE,
    parent_id      UUID,
    seq            INTEGER NOT NULL,
    design_spec    JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_kind    TEXT NOT NULL DEFAULT 'recipe',
    recipe_name    TEXT,
    cadir          JSONB,
    parameters     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by     TEXT NOT NULL DEFAULT 'user',
    model_provider TEXT,
    model_name     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, seq),
    UNIQUE (project_id, id),
    FOREIGN KEY (project_id, parent_id)
        REFERENCES cad_revisions(project_id, id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_cad_revisions_project
    ON cad_revisions(project_id, seq DESC);
"""

# MUTABLE. One row per attempt.
#
# `idempotency_key` is UNIQUE per revision rather than globally: the same client
# retry token against a different revision is a different intent, and a global
# unique index would make one user's key collide with another's.
CREATE_CAD_BUILDS_SQL = """
CREATE TABLE IF NOT EXISTS cad_builds (
    id               UUID PRIMARY KEY,
    revision_id      UUID NOT NULL REFERENCES cad_revisions(id) ON DELETE CASCADE,
    status           TEXT NOT NULL DEFAULT 'queued',
    idempotency_key  TEXT,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    duration_ms      INTEGER,
    peak_rss_bytes   BIGINT,
    validation       JSONB,
    error_code       TEXT,
    error_detail     TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (revision_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_cad_builds_rev
    ON cad_builds(revision_id, created_at DESC);
"""

CREATE_CAD_ARTIFACTS_SQL = """
CREATE TABLE IF NOT EXISTS cad_artifacts (
    id          UUID PRIMARY KEY,
    build_id    UUID NOT NULL REFERENCES cad_builds(id) ON DELETE CASCADE,
    format      TEXT NOT NULL,
    media_type  TEXT NOT NULL,
    size_bytes  BIGINT NOT NULL,
    sha256      CHAR(64) NOT NULL,
    storage_key TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (build_id, format)
);
CREATE INDEX IF NOT EXISTS idx_cad_artifacts_build ON cad_artifacts(build_id);
"""

# Gate 7C-2. A revision is either a PROPOSAL or ACCEPTED, and only an accepted one
# may be the project head.
#
# This is a one-way latch on an otherwise insert-only table, not a status column, and
# the difference matters. `cad_revisions` records what was asked for and nothing here
# rewrites any of that — `accepted_at` goes from NULL to a timestamp exactly once and
# can never go back, which is why the UPDATE that sets it carries
# `WHERE accepted_at IS NULL`. A mutable `state` column would have re-opened the table
# to edits and made "what did this revision say" a question with a history.
#
# The backfill runs inside the existence test rather than as its own idempotent
# statement, and that is the whole reason for the DO block: every revision that
# existed before this column did was the head under the old rules, and re-running a
# bare `UPDATE ... WHERE accepted_at IS NULL` on the next restart would silently
# accept every proposal made since — turning the boot sequence into the thing that
# approves the model's work.
MIGRATE_CAD_REVISION_ACCEPTANCE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'cad_revisions' AND column_name = 'accepted_at'
    ) THEN
        ALTER TABLE cad_revisions ADD COLUMN accepted_at TIMESTAMPTZ;
        UPDATE cad_revisions SET accepted_at = created_at;
    END IF;
END $$;
"""

# The build's verdict on whether it made the REQUESTED part, kept beside the
# validation report that says whether it made a valid one. Two columns because they
# answer two questions: `validation` has always said "this solid is watertight,
# manifold and one piece", and every word of that was true of the 30 mm cube that
# came out 35 mm with no hole in it.
#
# `conformance_status` is denormalised out of the JSON deliberately — acceptance is
# decided on it, and deciding a state transition by digging into a JSONB blob makes
# the rule invisible to anyone reading the table.
MIGRATE_CAD_BUILD_CONFORMANCE_SQL = """
ALTER TABLE cad_builds ADD COLUMN IF NOT EXISTS conformance JSONB;
ALTER TABLE cad_builds ADD COLUMN IF NOT EXISTS conformance_status TEXT;
"""

# Gate 8B. Where an imported revision's geometry came from: the file's own name, its
# digest, its size, and which reader parsed it.
#
# It lives on the revision rather than the build because it describes the *source*,
# and the source is the one thing about an import that never changes. A recipe
# revision can be rebuilt from its row; an import revision cannot — the bytes were
# never ours to keep — so without this column an imported part has no honest answer
# to "where did this come from", which is the question an imported part attracts most.
#
# The parser's verdict on that file (exact or mesh, how many solids it yielded) is
# recorded separately, in the build's `validation` blob, and deliberately so: that is
# what one attempt made of the file, and a later engine with a different reader could
# legitimately make something else of the same bytes.
MIGRATE_CAD_REVISION_PROVENANCE_SQL = """
ALTER TABLE cad_revisions ADD COLUMN IF NOT EXISTS provenance JSONB;
"""

# UX-2. The one index the project-scoped design timeline needs.
#
# `cad_jobs` was indexed for "this user's recent jobs" and nothing else, because UX-0
# only ever read a job by its own id. The activity panel asks the opposite question —
# every job that touched THIS project — and without this index that is a sequential
# scan of every authoring turn every user has ever run.
#
# Partial on purpose: a job spends its first seconds with `project_id` NULL (the model
# has not called `cad_create_project` yet), and those rows are exactly the ones this
# query can never match. Excluding them keeps the index to the rows it answers for.
MIGRATE_CAD_JOBS_PROJECT_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_cad_jobs_project
    ON cad_jobs(project_id, created_at) WHERE project_id IS NOT NULL;
"""

# UX-0. One row per *authoring turn* — the thing a cloud model does before any of the
# three tables above have a row to point at.
#
# It exists because of an ordering problem the rest of this schema does not have. In
# the recipe lane Harvis knows the project, the revision and the build before it
# answers, so the chat card can carry those ids from the first byte. In the authoring
# lane the model calls `cad_create_project` itself, several seconds in — so a card
# that must appear immediately has nothing to name. This row is minted first and is
# what the card names; the ids are filled in as the model discovers them.
#
# `project_id`, `revision_id` and `build_id` carry no foreign key on purpose. A job is
# the record of a turn that happened, and it stays true after the project it made has
# been deleted; a CASCADE would erase the only evidence that the turn ever ran.
#
# `activity` is the public design activity — tool names, verdicts, durations, safe
# errors. Never a prompt, a credential, a path or a storage key. It lives here rather
# than in a `cad_events` table because whether CAD gets its own event log or borrows
# the workspace one is still an open decision, and UX-0 has no business answering it.
CREATE_CAD_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS cad_jobs (
    id              UUID PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    phase           TEXT,
    description     TEXT NOT NULL DEFAULT '',
    provider        TEXT,
    model           TEXT,
    title           TEXT,
    project_id      UUID,
    revision_id     UUID,
    build_id        UUID,
    conformance     TEXT,
    error_code      TEXT,
    error_detail    TEXT,
    activity        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_cad_jobs_user ON cad_jobs(user_id, created_at DESC);
"""

# UX-3. Renders live in `cad_artifacts` beside the exports rather than in a table
# of their own.
#
# A render is the same kind of thing an export is — bytes on disk, owned by a build,
# addressed by row id, counted against the quota, swept by the same reaper — and the
# only reason it did not already fit is the `UNIQUE (build_id, format)` constraint,
# which assumed one file per format. That is true of STEP and STL and false of a
# render: a build has an iso view and a front view and a four-view sheet, all PNG.
#
# So the key gains a `variant`. An export's variant is the empty string, which is
# what every existing row gets; a render's variant is its camera preset. `meta`
# carries the render's binding — the sha256 of the geometry it depicts and the
# revision it came from — because a render of an older solid is not a render of this
# one, and the only way to know is to have written down which bytes were on screen.
MIGRATE_CAD_ARTIFACT_VARIANTS_SQL = """
ALTER TABLE cad_artifacts ADD COLUMN IF NOT EXISTS variant TEXT NOT NULL DEFAULT '';
ALTER TABLE cad_artifacts ADD COLUMN IF NOT EXISTS meta JSONB;
ALTER TABLE cad_artifacts DROP CONSTRAINT IF EXISTS cad_artifacts_build_id_format_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cad_artifacts_build_format_variant
    ON cad_artifacts(build_id, format, variant);
"""

# UX-A. The semantic tree the workspace's hierarchy panel draws, and the pick keys
# that tie its body rows to nodes inside the GLB.
#
# On the build and not the revision, unlike `provenance`, because it is a property of
# the *geometry* rather than of the source: which bodies came out, which operations ran
# and which their guards dropped, and — on a failure — which one broke. Two builds of
# the same revision at different parameters can legitimately differ here, and a column
# on the revision could only record one of them.
#
# Nullable and expected to be null on old rows. A build from before this column, or
# from an older engine image, has no tree, and the workspace says so rather than
# drawing an invented one.
MIGRATE_CAD_BUILD_SCENE_SQL = """
ALTER TABLE cad_builds ADD COLUMN IF NOT EXISTS scene_manifest JSONB;
"""

# HE-3. The numbers this build's geometry actually measured, with their provenance.
#
# On the build rather than the revision for the same reason `scene_manifest` is: a
# measurement is a property of the geometry that came out, and two builds of one
# revision at different parameters legitimately measure differently. A column on the
# revision could only record one of them and would silently pick the wrong one.
#
# Nullable, and null on every row from before this gate. That is not a gap to be
# filled with zeros — a build nobody measured has no measurements, and every check
# that wanted one grades `unverified`, which is what an absent number has always
# meant here.
MIGRATE_CAD_BUILD_MEASUREMENTS_SQL = """
ALTER TABLE cad_builds ADD COLUMN IF NOT EXISTS measurements JSONB;
"""

# HE-8. A disposable experiment: a mutable working branch off a revision, where a
# repair round may fail without costing the project a permanent revision.
#
# The whole table exists because of one arithmetic fact. Revisions are immutable and
# `seq` only ever goes up, so every repair attempt that ran against the real history
# burned a number whether or not it produced anything — which is how a session ends
# with eight revisions, seven builds and no part. An experiment absorbs those attempts
# and hands back at most one revision, at the end, only if something worked.
#
# **The frozen spec is a copy, and there is no column an attempt can write it into.**
# `design_spec` here is the base revision's spec, copied once at open time and hashed;
# `record_attempt` takes geometry and parameters and nothing else. That is what makes
# "an experiment may not weaken the DesignSpec or widen a tolerance" a property of the
# schema rather than a rule someone has to remember: the answer key is not reachable
# from inside the experiment. `spec_sha256` is the tamper check on top — it catches a
# frozen copy edited out of band, and a base revision that changed underneath.
#
# `base_revision_id` carries no ON DELETE CASCADE through a composite key the way
# `cad_revisions.parent_id` does, because the project-level cascade already covers it:
# an experiment cannot outlive its project, and within a project a revision is never
# deleted.
CREATE_CAD_EXPERIMENTS_SQL = """
CREATE TABLE IF NOT EXISTS cad_experiments (
    id                   UUID PRIMARY KEY,
    project_id           UUID NOT NULL REFERENCES cad_projects(id) ON DELETE CASCADE,
    base_revision_id     UUID NOT NULL REFERENCES cad_revisions(id) ON DELETE CASCADE,
    status               TEXT NOT NULL DEFAULT 'open',
    reason               TEXT NOT NULL DEFAULT '',
    attempts             INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL DEFAULT 3,
    design_spec          JSONB NOT NULL DEFAULT '{}'::jsonb,
    spec_sha256          CHAR(64) NOT NULL,
    cadir                JSONB,
    parameters           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by           TEXT NOT NULL DEFAULT 'ai',
    promoted_revision_id UUID,
    closed_reason        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at            TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_cad_experiments_project
    ON cad_experiments(project_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cad_experiments_open_base
    ON cad_experiments(base_revision_id) WHERE status = 'open';
"""

# HE-8. Which experiment a build belongs to, or NULL for a build of the real history.
#
# An experiment build keeps its `revision_id` pointing at the base revision, because
# that is honestly what it is an attempt at, and because everything the build machinery
# already does — artifacts, quota, the reaper, the render binding — keys on it and
# would otherwise need a second implementation for the experimental case.
#
# The cost of that choice is paid here, once: every query that asks "what is the
# geometry of this revision" now says `experiment_id IS NULL`. A failed experiment must
# not change what the workspace shows, what `accept_revision` grades, or what retention
# sweeps, and each of those is one clause. Old rows are NULL, which is correct with no
# backfill — nothing before this gate was an experiment.
MIGRATE_CAD_BUILD_EXPERIMENT_SQL = """
ALTER TABLE cad_builds ADD COLUMN IF NOT EXISTS experiment_id UUID;
CREATE INDEX IF NOT EXISTS idx_cad_builds_experiment
    ON cad_builds(experiment_id, created_at DESC) WHERE experiment_id IS NOT NULL;
"""

# CS-1. A CAD session: one project, one dedicated conversation, one restorable view.
#
# The session exists because a part is not a chat message. Authoring one takes many
# turns, produces a tree, a viewport, a code view and a history, and none of that fits
# beside a conversation about something else. So a CAD request opens its own room: a
# child conversation bound to a project, addressable by a URL, that a person can leave
# and come back to.
#
# `project_id` is nullable, and that is the ordering problem `cad_jobs` already
# documents rather than a missing constraint. The model calls `cad_create_project`
# itself, several seconds into the turn, so a session that must open *now* has no
# project to name yet. `job_id` is what carries it across that gap: the session binds
# its project the moment the job discovers one. A session without a project is a room
# whose part is still being made — it draws the turn and nothing else.
#
# `source_conversation_id` is the chat the request came from, kept so the header can
# offer the way back and so the card in that chat stays meaningful. It is nullable
# because the Discord and recipe lanes have no chat to return to.
#
# `view_state` is what makes "returning later" mean something: camera, selected part,
# revision, open file, active tab. Opaque JSON on purpose — it is a client's memory of
# where it was, never a source of authority. Nothing downstream reads it to decide what
# is true; the workspace snapshot does that.
CREATE_CAD_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS cad_sessions (
    id                     UUID PRIMARY KEY,
    user_id                INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id             UUID REFERENCES cad_projects(id) ON DELETE CASCADE,
    job_id                 UUID,
    source_conversation_id TEXT,
    cad_conversation_id    TEXT NOT NULL,
    title                  TEXT NOT NULL DEFAULT '',
    view_state             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cad_sessions_conversation
    ON cad_sessions(cad_conversation_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cad_sessions_project
    ON cad_sessions(project_id) WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cad_sessions_user
    ON cad_sessions(user_id, updated_at DESC);
"""

# UX-G. Not schema — a reaper, kept here because it has to run at the same moment the
# schema does and adding a second startup hook for one statement is worse.
#
# A turn only ever moves off ``running`` because the task that owns it writes the
# outcome, and a ``queued`` turn only ever starts because the process holding its queue
# entry drains it. Both of those live in memory, so a backend that stops mid-turn
# leaves rows that claim to be in progress and never will be: the workspace shows a
# spinner that outlives the work it describes.
#
# Age-bounded rather than "everything not running in *this* process", because that
# stronger sweep would be wrong the moment a second replica exists — a starting pod
# would strand the turns its sibling is actively running. Thirty minutes is far longer
# than any authoring turn the deadline chain permits, so nothing real is caught by it.
REAP_STRANDED_CAD_JOBS_SQL = """
UPDATE cad_jobs
   SET status='failed', phase='failed', error_code='job_stranded',
       error_detail='The server stopped before this turn finished.',
       finished_at=NOW()
 WHERE status IN ('running', 'queued')
   AND created_at < NOW() - INTERVAL '30 minutes';
"""

CAD_SCHEMA_SQL = (
    CREATE_CAD_PROJECTS_SQL,
    CREATE_CAD_REVISIONS_SQL,
    CREATE_CAD_BUILDS_SQL,
    CREATE_CAD_ARTIFACTS_SQL,
    MIGRATE_CAD_REVISION_ACCEPTANCE_SQL,
    MIGRATE_CAD_BUILD_CONFORMANCE_SQL,
    MIGRATE_CAD_REVISION_PROVENANCE_SQL,
    CREATE_CAD_JOBS_SQL,
    MIGRATE_CAD_JOBS_PROJECT_INDEX_SQL,
    MIGRATE_CAD_ARTIFACT_VARIANTS_SQL,
    MIGRATE_CAD_BUILD_SCENE_SQL,
    MIGRATE_CAD_BUILD_MEASUREMENTS_SQL,
    CREATE_CAD_SESSIONS_SQL,
    CREATE_CAD_EXPERIMENTS_SQL,
    MIGRATE_CAD_BUILD_EXPERIMENT_SQL,
    REAP_STRANDED_CAD_JOBS_SQL,
)

# ---------------------------------------------------------------------------
# Quotas and retention
#
# Numbers, not policy: the mechanism is what Gate 3 owes, and the operator sets the
# caps. They are checked BEFORE any byte is written, because a quota enforced after
# the write is a cleanup job wearing a quota's name.
# ---------------------------------------------------------------------------

def _int_env(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def user_quota_bytes() -> int:
    return _int_env("CAD_USER_QUOTA_BYTES", 2 * 1024 * 1024 * 1024)


def project_quota_bytes() -> int:
    return _int_env("CAD_PROJECT_QUOTA_BYTES", 512 * 1024 * 1024)


def retained_builds_per_revision() -> int:
    return _int_env("CAD_RETAINED_BUILDS_PER_REVISION", 5)


class CadStoreError(RuntimeError):
    """A refusal the route can turn into an honest status code."""

    def __init__(self, code: str, message: str, status: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra or {}


class QuotaExceeded(CadStoreError):
    def __init__(self, message: str, extra: dict | None = None):
        super().__init__("quota_exceeded", message, status=413, extra=extra)


class StaleRevision(CadStoreError):
    """The caller edited from a revision that is no longer the head.

    409 with both ids, so the UI can show a conflict. Silently forking instead would
    make the second editor's change look applied when it is on a branch nobody sees.
    """

    def __init__(self, base_revision_id: str, head_revision: str | None):
        super().__init__(
            "stale_revision",
            "this project moved on since the revision you edited",
            status=409,
            extra={"base_revision_id": base_revision_id, "head_revision": head_revision},
        )


class NotAcceptable(CadStoreError):
    """A proposal that may not be promoted to the project head yet.

    Three refusals share this class because they share a consequence — the head does
    not move — and a caller that wants to explain any of them to a user needs the same
    three fields. The ``code`` is what distinguishes them, and none of them is a
    permanent no: a proposal can be rebuilt, repaired, or accepted with the failure
    acknowledged.
    """

    def __init__(self, code: str, message: str, extra: dict | None = None):
        super().__init__(code, message, status=409, extra=extra)


# ---------------------------------------------------------------------------
# Storage layout
# ---------------------------------------------------------------------------

def artifact_root() -> str:
    return os.path.join(os.getenv("ARTIFACT_STORAGE_DIR", "/data/artifacts"), "cad")


def _build_dir(user_id: int, project_id: str, build_id: str) -> str:
    """Keyed by user first so a per-user sweep is one directory, and so the
    containment check below has a natural boundary to test against."""
    return os.path.join(artifact_root(), str(int(user_id)), str(project_id), str(build_id))


def resolve_storage_key(user_id: int, project_id: str, storage_key: str) -> str | None:
    """Turn a stored key into a real path, or ``None`` if it escapes its own project.

    The key is written by this module and is not caller-supplied, so this is defense
    in depth rather than the primary control — but it is the check that decides
    whether a database row can ever address a file outside its owner's tree, and a
    row is a thing an attacker with SQL access could write.
    """
    base = os.path.realpath(os.path.join(artifact_root(), str(int(user_id)), str(project_id)))
    real = os.path.realpath(os.path.join(artifact_root(), storage_key))
    if not (real == base or real.startswith(base + os.sep)):
        logger.warning("cad artifact key escaped its project dir; refusing")
        return None
    return real if os.path.isfile(real) else None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _row_project(row) -> dict:
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "conversation_id": row["conversation_id"],
        "head_revision": str(row["head_revision"]) if row["head_revision"] else None,
        "next_seq": int(row["next_seq"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _jsonb(v):
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except ValueError:
            return {}
    return v


def _row_revision(row) -> dict:
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]),
        "parent_id": str(row["parent_id"]) if row["parent_id"] else None,
        "seq": int(row["seq"]),
        "design_spec": _jsonb(row["design_spec"]),
        "source_kind": row["source_kind"],
        "recipe_name": row["recipe_name"],
        # The document itself, not a reference to it. A CadIR revision that returned
        # only its name would be unrestorable — there is no registry to look the name
        # up in, which is the entire difference between a document and a recipe.
        "cadir": _jsonb(row["cadir"]) if row["cadir"] is not None else None,
        "parameters": _jsonb(row["parameters"]),
        # Only an import has one. Null on every authored revision, and its presence is
        # how a client tells "this body came from a file somebody uploaded" from "this
        # body was built from a recipe or a document" without parsing `source_kind`.
        "provenance": (_jsonb(row.get("provenance"))
                       if row.get("provenance") is not None else None),
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "accepted_at": (row["accepted_at"].isoformat()
                        if row.get("accepted_at") else None),
        # Derived, never stored. One column and one reading of it, so a client cannot
        # be looking at a `state` that disagrees with the timestamp it was computed
        # from — and so the word every surface shows comes from here rather than from
        # each of them re-deciding what a null timestamp means.
        "state": "accepted" if row.get("accepted_at") else "proposal",
    }


def _row_build(row) -> dict:
    return {
        "id": str(row["id"]),
        "revision_id": str(row["revision_id"]),
        # HE-8. Set only on an attempt made inside a disposable experiment. A client
        # that sees one is looking at a trial, not at the project's history.
        "experiment_id": (str(row["experiment_id"])
                          if row.get("experiment_id") else None),
        "status": row["status"],
        "duration_ms": row["duration_ms"],
        "peak_rss_bytes": row["peak_rss_bytes"],
        "validation": _jsonb(row["validation"]),
        # Two verdicts, never merged. `validation` says the solid is well-formed;
        # `conformance` says it is the part that was asked for. A build can be
        # `succeeded` and `conformance_status: failed` at the same time, and that
        # combination is the whole reason this gate exists.
        "conformance": _jsonb(row["conformance"]) if row.get("conformance") else None,
        "conformance_status": row.get("conformance_status"),
        # UX-A. The tree, when this build produced one. Null on a build from before
        # the column existed and on one whose engine never reported a tree — the
        # workspace shows no hierarchy there rather than inventing a single body.
        "scene_manifest": (_jsonb(row["scene_manifest"])
                           if row.get("scene_manifest") else None),
        # HE-3. Typed measurements with provenance, or None on a build that took
        # none. Deliberately not defaulted to `[]`: an empty list would say "this
        # was measured and nothing was found", which is a different claim.
        "measurements": (_jsonb(row["measurements"])
                         if row.get("measurements") else None),
        "error_code": row["error_code"],
        "error_detail": row["error_detail"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
    }


def _row_artifact(row) -> dict:
    """Never includes ``storage_key``. A client that can name a path can probe for
    one, and there is nothing it could do with the value that the artifact route
    does not already do for it."""
    out = {
        "id": str(row["id"]),
        "format": row["format"],
        "media_type": row["media_type"],
        "size_bytes": int(row["size_bytes"]),
        "sha256": row["sha256"],
    }
    # Present only on renders. `meta` is written by this module — the camera preset,
    # the digest of the geometry the picture shows — never by the caller, so there is
    # nothing in it a client could have planted.
    variant = row["variant"] or ""
    if variant:
        out["variant"] = variant
        out["meta"] = _jsonb(row["meta"]) or {}
    return out


async def get_project(pool, project_id: str, user_id: int) -> dict | None:
    """Ownership is in the WHERE clause, not in a check after the read. A route that
    fetches first and compares second is one early return away from a leak."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cad_projects WHERE id=$1 AND user_id=$2",
            uuid.UUID(str(project_id)), int(user_id),
        )
    return _row_project(row) if row else None


async def list_projects(pool, user_id: int, limit: int = 50) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM cad_projects WHERE user_id=$1 "
            "ORDER BY updated_at DESC LIMIT $2",
            int(user_id), max(1, min(200, int(limit))),
        )
    return [_row_project(r) for r in rows]


async def list_revisions(pool, project_id: str, user_id: int, limit: int = 100) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT r.* FROM cad_revisions r JOIN cad_projects p ON p.id = r.project_id "
            "WHERE r.project_id=$1 AND p.user_id=$2 ORDER BY r.seq DESC LIMIT $3",
            uuid.UUID(str(project_id)), int(user_id), max(1, min(500, int(limit))),
        )
    return [_row_revision(r) for r in rows]


async def get_revision(pool, revision_id: str, user_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT r.* FROM cad_revisions r JOIN cad_projects p ON p.id = r.project_id "
            "WHERE r.id=$1 AND p.user_id=$2",
            uuid.UUID(str(revision_id)), int(user_id),
        )
    return _row_revision(row) if row else None


async def get_build(pool, build_id: str, user_id: int) -> dict | None:
    """Returns the build with its artifacts, or ``None`` for another user's build —
    the same answer as a build that does not exist, on purpose."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT b.* FROM cad_builds b "
            "JOIN cad_revisions r ON r.id = b.revision_id "
            "JOIN cad_projects p ON p.id = r.project_id "
            "WHERE b.id=$1 AND p.user_id=$2",
            uuid.UUID(str(build_id)), int(user_id),
        )
        if not row:
            return None
        arts = await conn.fetch(
            "SELECT * FROM cad_artifacts WHERE build_id=$1 ORDER BY variant, format",
            row["id"],
        )
    out = _row_build(row)
    # `artifacts` stays what it has always been: the exports. Renders are pictures of
    # the part, not the part, and a client that put them in the download row would
    # offer a PNG next to the STEP as though they were the same kind of thing.
    out["artifacts"] = [_row_artifact(a) for a in arts if not (a["variant"] or "")]
    out["renders"] = [_row_artifact(a) for a in arts if (a["variant"] or "")]
    return out


async def get_artifact(pool, artifact_id: str, user_id: int) -> dict | None:
    """The one read that returns ``storage_key`` — for the streaming route, which
    resolves it and never puts it in a response body."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT a.*, p.id AS project_id, p.user_id FROM cad_artifacts a "
            "JOIN cad_builds b ON b.id = a.build_id "
            "JOIN cad_revisions r ON r.id = b.revision_id "
            "JOIN cad_projects p ON p.id = r.project_id "
            "WHERE a.id=$1 AND p.user_id=$2",
            uuid.UUID(str(artifact_id)), int(user_id),
        )
    if not row:
        return None
    out = _row_artifact(row)
    out["storage_key"] = row["storage_key"]
    out["project_id"] = str(row["project_id"])
    return out


async def usage_bytes(pool, user_id: int, project_id: str | None = None) -> int:
    """Bytes recorded against a user, or one of their projects. Sums the rows rather
    than walking the directory: the rows are what quotas are enforced from and what
    the reaper reconciles to, and a `du` would count files the reaper has already
    orphaned."""
    sql = (
        "SELECT COALESCE(SUM(a.size_bytes), 0) FROM cad_artifacts a "
        "JOIN cad_builds b ON b.id = a.build_id "
        "JOIN cad_revisions r ON r.id = b.revision_id "
        "JOIN cad_projects p ON p.id = r.project_id "
        "WHERE p.user_id=$1"
    )
    args: list = [int(user_id)]
    if project_id is not None:
        sql += " AND p.id=$2"
        args.append(uuid.UUID(str(project_id)))
    async with pool.acquire() as conn:
        return int(await conn.fetchval(sql, *args) or 0)


async def latest_builds_by_revision(pool, project_id: str, user_id: int) -> dict:
    """The most recent build of every revision in one project, keyed by revision id.

    Gate 3 handed the client a build id only in the ``202`` that created it, so a
    reloaded page had no way to find the geometry of a revision it had not just
    built. One query for the whole project rather than a route per revision: the
    panel needs every revision's state to draw its version list at all, and N+1
    round trips to draw one list is not a design.

    The most recent build is returned whatever its status. A revision whose last
    build failed has to read as failed, not as the older success it superseded.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT ON (b.revision_id) b.* FROM cad_builds b "
            "JOIN cad_revisions r ON r.id = b.revision_id "
            "JOIN cad_projects p ON p.id = r.project_id "
            "WHERE r.project_id=$1 AND p.user_id=$2 AND b.experiment_id IS NULL "
            "ORDER BY b.revision_id, b.created_at DESC",
            uuid.UUID(str(project_id)), int(user_id),
        )
        if not rows:
            return {}
        arts = await conn.fetch(
            "SELECT * FROM cad_artifacts WHERE build_id = ANY($1::uuid[]) ORDER BY format",
            [r["id"] for r in rows],
        )
    by_build: dict = {}
    renders_by_build: dict = {}
    for a in arts:
        target = renders_by_build if (a["variant"] or "") else by_build
        target.setdefault(str(a["build_id"]), []).append(_row_artifact(a))
    out: dict = {}
    for r in rows:
        b = _row_build(r)
        b["artifacts"] = by_build.get(b["id"], [])
        b["renders"] = renders_by_build.get(b["id"], [])
        out[str(r["revision_id"])] = b
    return out


async def latest_scene_manifest(pool, revision_id: str) -> dict | None:
    """The scene manifest of a revision's most recent succeeded build, or ``None``.

    Succeeded, not merely most recent, because the only thing that reads this is the
    code view asking "which body is this part in the viewport" — and a failed build's
    manifest describes bodies it did not produce, so its node ids match nothing on
    screen. ``None`` then correctly means "this part has no body to point at yet".
    """
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT scene_manifest FROM cad_builds WHERE revision_id=$1 "
            "AND status='succeeded' AND experiment_id IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            uuid.UUID(str(revision_id)),
        )
    if row is None:
        return None
    out = _jsonb(row)
    return out if isinstance(out, dict) else None


async def latest_measurements(pool, revision_id: str) -> dict | None:
    """The validation report of a revision's most recent succeeded build, or ``None``.

    ``None`` means "never built successfully" and is deliberately not ``{}`` — compare
    has to be able to say "no measurements yet" rather than showing an empty diff that
    reads as "identical".
    """
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT validation FROM cad_builds WHERE revision_id=$1 "
            "AND status='succeeded' AND experiment_id IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            uuid.UUID(str(revision_id)),
        )
    if row is None:
        return None
    out = _jsonb(row)
    return out if isinstance(out, dict) else None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def is_proposal(spec: dict) -> bool:
    """Whether a revision lands as a proposal rather than at the head.

    One rule: **a revision the model authored is a proposal; a revision the user
    authored is not.** ``created_by`` already carried that distinction — Gate 3 wrote
    ``'ai'`` for generated revisions and ``'user'`` for everything else — and nothing
    was reading it.

    It is authorship, not the conformance verdict, that decides this, and the
    difference is deliberate. Grading happens after the revision exists, so a rule
    keyed on the verdict would have to demote a head that had already moved, and a
    head that can move backwards is not a head. Keying on authorship means the model's
    work is never the head until a person says so, whatever the grade turns out to be
    — which is the property the gate actually asked for.
    """
    return (spec.get("created_by") or "user") == "ai"


async def create_project(pool, user_id: int, title: str,
                         conversation_id: str | None = None,
                         revision: dict | None = None) -> dict:
    """A project and, optionally, its first revision — in one transaction.

    A project with no revisions is a state nothing else in this module expects, so
    the two are created together or not at all.

    A project whose first revision is a proposal has **no head**, and that is the
    correct state rather than a gap to paper over: nothing in it has been accepted
    yet. ``head_revision`` is null until someone accepts something.
    """
    project_id = uuid.uuid4()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO cad_projects (id, user_id, conversation_id, title) "
                "VALUES ($1, $2, $3, $4)",
                project_id, int(user_id), conversation_id, (title or "Untitled").strip()[:200],
            )
            first = None
            if revision is not None:
                accepted = not is_proposal(revision)
                first = await _insert_revision(conn, project_id, None, 1, revision,
                                               accepted=accepted)
                await conn.execute(
                    "UPDATE cad_projects SET head_revision=$1, next_seq=2, updated_at=NOW() "
                    "WHERE id=$2",
                    uuid.UUID(first["id"]) if accepted else None, project_id,
                )
            row = await conn.fetchrow("SELECT * FROM cad_projects WHERE id=$1", project_id)
    out = _row_project(row)
    out["revision"] = first
    return out


async def _insert_revision(conn, project_id, parent_id, seq: int, spec: dict,
                           accepted: bool = True) -> dict:
    rid = uuid.uuid4()
    row = await conn.fetchrow(
        "INSERT INTO cad_revisions "
        "(id, project_id, parent_id, seq, design_spec, source_kind, recipe_name, "
        " cadir, parameters, created_by, model_provider, model_name, accepted_at, "
        " provenance) "
        "VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8::jsonb,$9::jsonb,$10,$11,$12,"
        " CASE WHEN $13 THEN NOW() ELSE NULL END, $14::jsonb) "
        "RETURNING *",
        rid, project_id, parent_id, int(seq),
        json.dumps(spec.get("design_spec") or {}),
        (spec.get("source_kind") or "recipe")[:32],
        (spec.get("recipe_name") or None),
        json.dumps(spec["cadir"]) if spec.get("cadir") is not None else None,
        json.dumps(spec.get("parameters") or {}),
        (spec.get("created_by") or "user")[:32],
        spec.get("model_provider"), spec.get("model_name"),
        bool(accepted),
        json.dumps(spec["provenance"]) if spec.get("provenance") is not None else None,
    )
    return _row_revision(row)


async def create_revision(pool, project_id: str, user_id: int, spec: dict,
                          base_revision_id: str | None = None) -> dict:
    """Append a revision, advancing ``seq`` and ``head_revision`` atomically.

    The row lock is what makes ``next_seq`` a sequence rather than a suggestion. Two
    concurrent appends that both read ``next_seq = 4`` would either collide on the
    ``UNIQUE (project_id, seq)`` index or, without it, silently produce two revision
    4s; ``FOR UPDATE`` makes the second one wait and read 5.

    ``seq`` always advances; ``head_revision`` only advances for an accepted revision
    (see :func:`is_proposal`). A proposal is still appended to the history and can be
    built, inspected, compared and edited further. What it is not is the thing the next
    *parameter edit from the UI* builds from.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            proj = await conn.fetchrow(
                "SELECT * FROM cad_projects WHERE id=$1 AND user_id=$2 FOR UPDATE",
                uuid.UUID(str(project_id)), int(user_id),
            )
            if not proj:
                return {}

            head = str(proj["head_revision"]) if proj["head_revision"] else None
            # The newest revision is not always the head, because a proposal does not
            # move it. Checking the base against the head alone made a bounded repair
            # impossible: a model that proposed a wrong part and was told to fix it had
            # to edit its own proposal, and got `stale_revision` for doing exactly what
            # it was asked — on a fresh project the head was still NULL. Both the head
            # and the newest revision are honest bases for an edit; anything older is
            # the silent fork this check exists to catch.
            tip = await conn.fetchval(
                "SELECT id FROM cad_revisions WHERE project_id=$1 ORDER BY seq DESC "
                "LIMIT 1", proj["id"])
            tip = str(tip) if tip else None
            # The third honest base: the newest revision that actually produced geometry
            # — the one the workspace is showing. A user-authored revision becomes the
            # head the moment it is inserted, before its build has run, so a build that
            # then fails leaves both the head and the tip pointing at a revision with no
            # geometry. The viewport correctly keeps showing the last good one; without
            # this clause every edit made from that view came back `stale_revision`, and
            # the reload the UI offers returns the identical state. One failed build
            # wedged parameter editing permanently.
            shown = await conn.fetchval(
                "SELECT r.id FROM cad_revisions r JOIN cad_builds b "
                "ON b.revision_id = r.id AND b.status = 'succeeded' "
                "AND b.experiment_id IS NULL "
                "WHERE r.project_id=$1 ORDER BY r.seq DESC LIMIT 1", proj["id"])
            shown = str(shown) if shown else None
            if base_revision_id is not None and str(base_revision_id) not in {
                    r for r in (head, tip, shown) if r}:
                raise StaleRevision(str(base_revision_id), head)

            # A stated base is also the parent, so a repair chains to the proposal it
            # repairs instead of skipping back to the last accepted revision and
            # leaving the history claiming the two were never related. A caller that
            # states no base is appending to the head, which is right for restore and
            # for a fresh project.
            parent = str(base_revision_id) if base_revision_id is not None else head
            seq = int(proj["next_seq"])
            accepted = not is_proposal(spec)
            rev = await _insert_revision(
                conn, proj["id"],
                uuid.UUID(parent) if parent else None,
                seq, spec, accepted=accepted,
            )
            await conn.execute(
                "UPDATE cad_projects SET head_revision=$1, next_seq=$2, updated_at=NOW() "
                "WHERE id=$3",
                uuid.UUID(rev["id"]) if accepted
                else (uuid.UUID(head) if head else None),
                seq + 1, proj["id"],
            )
    return rev


async def accept_revision(pool, project_id: str, revision_id: str, user_id: int,
                          acknowledge_conformance: bool = False) -> dict:
    """Promote a proposal to the project head. The one-way latch, and its guards.

    Four things have to be true, and each refusal is its own code because each has a
    different next step for whoever hit it:

    ``not_built``
        The revision has no succeeded build. There is no geometry to accept, so there
        is nothing this could be agreeing to.
    ``conformance_failed``
        The build measured wrong against the frozen DesignSpec. This is the refusal
        the gate exists for. It is overridable — with ``acknowledge_conformance``,
        because a person is allowed to decide that a part which missed a stated
        dimension is still what they want, and the alternative is a lane that traps
        the user behind a checker that cannot be argued with. What is not allowed is
        it happening quietly: the caller has to say so in the request.
    ``stale_proposal``
        The revision is older than the current head. Accepting it would move the head
        backwards, which would leave the newer history pointing nowhere — the same
        reason ``restore`` creates a new revision instead of rewinding.
    already accepted
        Not an error. Returns the revision unchanged, so a double-click and a retried
        request are the same thing.

    Returns the revision, or ``{}`` when it is not the caller's or not in that project.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            proj = await conn.fetchrow(
                "SELECT * FROM cad_projects WHERE id=$1 AND user_id=$2 FOR UPDATE",
                uuid.UUID(str(project_id)), int(user_id),
            )
            if not proj:
                return {}
            rev = await conn.fetchrow(
                "SELECT * FROM cad_revisions WHERE id=$1 AND project_id=$2",
                uuid.UUID(str(revision_id)), proj["id"],
            )
            if not rev:
                return {}
            if rev["accepted_at"] is not None:
                return _row_revision(rev)

            build = await conn.fetchrow(
                "SELECT * FROM cad_builds WHERE revision_id=$1 "
                "AND experiment_id IS NULL ORDER BY created_at DESC LIMIT 1",
                rev["id"],
            )
            if build is None or build["status"] != "succeeded":
                raise NotAcceptable(
                    "not_built",
                    "this proposal has no successful build, so there is no geometry "
                    "to accept",
                    {"revision_id": str(rev["id"]),
                     "build_status": build["status"] if build else None},
                )
            if build["conformance_status"] == "failed" and not acknowledge_conformance:
                report = _jsonb(build["conformance"]) or {}
                raise NotAcceptable(
                    "conformance_failed",
                    (report.get("summary")
                     or "this build does not match what was asked for"),
                    {"revision_id": str(rev["id"]), "build_id": str(build["id"]),
                     "conformance": report},
                )

            head_seq = await conn.fetchval(
                "SELECT seq FROM cad_revisions WHERE id=$1", proj["head_revision"],
            ) if proj["head_revision"] else None
            if head_seq is not None and int(rev["seq"]) <= int(head_seq):
                raise NotAcceptable(
                    "stale_proposal",
                    "a newer revision is already the head of this project; restore "
                    "this one instead of accepting it",
                    {"revision_id": str(rev["id"]),
                     "head_revision": str(proj["head_revision"])},
                )

            # `WHERE accepted_at IS NULL` is the latch itself, not a nicety: it is what
            # makes a concurrent second accept a no-op rather than a second timestamp.
            row = await conn.fetchrow(
                "UPDATE cad_revisions SET accepted_at=NOW() "
                "WHERE id=$1 AND accepted_at IS NULL RETURNING *",
                rev["id"],
            )
            if row is None:  # someone else accepted it between the read and the write
                row = await conn.fetchrow(
                    "SELECT * FROM cad_revisions WHERE id=$1", rev["id"])
            else:
                await conn.execute(
                    "UPDATE cad_projects SET head_revision=$1, updated_at=NOW() "
                    "WHERE id=$2",
                    row["id"], proj["id"],
                )
    return _row_revision(row)


async def create_build(pool, revision_id: str, user_id: int,
                       idempotency_key: str | None = None) -> tuple[dict, bool]:
    """Return ``(build, created)``. A repeated idempotency key returns the FIRST
    build rather than starting a second one.

    Done as an ``ON CONFLICT DO NOTHING`` plus a re-read rather than a check-then-
    insert: two retries racing would both see no existing row and both insert, and
    the unique index is the only thing that can actually decide which one wins.
    """
    async with pool.acquire() as conn:
        owned = await conn.fetchval(
            "SELECT 1 FROM cad_revisions r JOIN cad_projects p ON p.id = r.project_id "
            "WHERE r.id=$1 AND p.user_id=$2",
            uuid.UUID(str(revision_id)), int(user_id),
        )
        if not owned:
            return {}, False

        bid = uuid.uuid4()
        row = await conn.fetchrow(
            "INSERT INTO cad_builds (id, revision_id, status, idempotency_key, started_at) "
            "VALUES ($1, $2, 'running', $3, NOW()) "
            "ON CONFLICT (revision_id, idempotency_key) DO NOTHING RETURNING *",
            bid, uuid.UUID(str(revision_id)), idempotency_key,
        )
        if row is not None:
            return _row_build(row), True

        existing = await conn.fetchrow(
            "SELECT * FROM cad_builds WHERE revision_id=$1 AND idempotency_key=$2",
            uuid.UUID(str(revision_id)), idempotency_key,
        )
    if existing is None:  # the conflicting row vanished; nothing sane to return
        raise CadStoreError("build_race", "the build could not be created", status=409)
    return _row_build(existing), False


async def fail_build(pool, build_id: str, code: str, detail: str,
                     scene_manifest: dict | None = None) -> None:
    """Record why a build did not produce geometry. ``detail`` is the sidecar's safe
    text — names and numbers, never a path, argv or host name.

    ``scene_manifest`` is the tree the engine was attempting, with the operation that
    broke marked. A failed build is when the workspace needs it most and is least able
    to derive it: there is no GLB, so without this the hierarchy panel goes blank at
    exactly the moment the user is asking which step went wrong. Written only when the
    engine sent one — a build that died before the geometry started has no tree, and
    an empty one would claim the part has no operations.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cad_builds SET status=$1, error_code=$2, error_detail=$3, "
            "scene_manifest=COALESCE($4::jsonb, scene_manifest), "
            "finished_at=NOW() WHERE id=$5",
            "cancelled" if code == "build_cancelled" else "failed",
            code, (detail or "")[:2000],
            json.dumps(scene_manifest) if scene_manifest else None,
            uuid.UUID(str(build_id)),
        )


async def request_cancel(pool, build_id: str) -> None:
    """Record the intent, separately from acting on it.

    The engine kill is best-effort over the network; this row is not. A cancel the
    engine never received still has to be visible to whatever reads the build next,
    or the user's click leaves no trace at all.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cad_builds SET cancel_requested=TRUE WHERE id=$1 "
            "AND status IN ('queued','running')",
            uuid.UUID(str(build_id)),
        )


async def check_quota(pool, user_id: int, project_id: str, incoming_bytes: int) -> None:
    """Refuse before a byte is written. Raises :class:`QuotaExceeded`."""
    if incoming_bytes <= 0:
        return
    u_cap, p_cap = user_quota_bytes(), project_quota_bytes()
    used_u = await usage_bytes(pool, user_id)
    if used_u + incoming_bytes > u_cap:
        raise QuotaExceeded(
            f"this would use {used_u + incoming_bytes} bytes against your {u_cap} byte limit",
            {"scope": "user", "used_bytes": used_u, "limit_bytes": u_cap},
        )
    used_p = await usage_bytes(pool, user_id, project_id)
    if used_p + incoming_bytes > p_cap:
        raise QuotaExceeded(
            f"this would use {used_p + incoming_bytes} bytes against this project's "
            f"{p_cap} byte limit",
            {"scope": "project", "used_bytes": used_p, "limit_bytes": p_cap},
        )


async def finish_build(pool, build_id: str, user_id: int, project_id: str,
                       artifacts: dict[str, bytes], refs: list[dict],
                       validation: dict, duration_ms: int | None = None,
                       peak_rss_bytes: int | None = None,
                       conformance: dict | None = None,
                       scene_manifest: dict | None = None,
                       measurements: list[dict] | None = None) -> dict:
    """Write the bytes, then the rows, then mark the build succeeded.

    Order matters and it is the unhappy path that decides it. Files first means a
    crash between the two leaves files with no rows — reclaimable, and the reaper
    does exactly that. Rows first would leave rows with no files: a build that reads
    as succeeded and 404s on every artifact, which no amount of sweeping can repair.

    The sha256 is recomputed here from the bytes about to be written, not copied from
    ``refs``. ``refs`` is what the engine said; this is what is on disk.
    """
    total = sum(len(b) for b in artifacts.values())
    await check_quota(pool, user_id, project_id, total)

    by_format = {r.get("format"): r for r in (refs or []) if isinstance(r, dict)}
    directory = _build_dir(user_id, project_id, build_id)
    os.makedirs(directory, exist_ok=True)

    written: list[dict] = []
    for fmt, blob in artifacts.items():
        path = os.path.join(directory, f"part.{fmt}")
        tmp = path + ".part"
        # Written to a temp name and renamed, so a reader can never see a file that
        # is still being filled — the rename is what publishes it.
        with open(tmp, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)
        written.append({
            "format": fmt,
            "media_type": (by_format.get(fmt) or {}).get("media_type")
                          or "application/octet-stream",
            "size_bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "storage_key": os.path.relpath(path, artifact_root()),
        })

    async with pool.acquire() as conn:
        async with conn.transaction():
            for w in written:
                await conn.execute(
                    "INSERT INTO cad_artifacts "
                    "(id, build_id, format, media_type, size_bytes, sha256, storage_key) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7) "
                    "ON CONFLICT (build_id, format, variant) DO UPDATE SET "
                    "media_type=EXCLUDED.media_type, size_bytes=EXCLUDED.size_bytes, "
                    "sha256=EXCLUDED.sha256, storage_key=EXCLUDED.storage_key",
                    uuid.uuid4(), uuid.UUID(str(build_id)), w["format"], w["media_type"],
                    w["size_bytes"], w["sha256"], w["storage_key"],
                )
            # `succeeded` still means what it always meant — the geometry ran and the
            # solid is sound — and the conformance columns are recorded beside it
            # rather than folded into it. A caller that only wants to know whether a
            # build produced a usable part reads `status`; a caller deciding whether
            # this may become the head reads `conformance_status`.
            await conn.execute(
                "UPDATE cad_builds SET status='succeeded', validation=$1::jsonb, "
                "duration_ms=$2, peak_rss_bytes=$3, conformance=$4::jsonb, "
                "conformance_status=$5, scene_manifest=$6::jsonb, "
                "measurements=$7::jsonb, finished_at=NOW() WHERE id=$8",
                json.dumps(validation or {}), duration_ms, peak_rss_bytes,
                json.dumps(conformance) if conformance else None,
                (conformance or {}).get("status"),
                # In the same statement as the artifact rows' transaction, so a
                # succeeded build never exists without the tree that describes the
                # GLB it just wrote — the two are read together on every workspace
                # load, and half of them is worse than neither.
                json.dumps(scene_manifest) if scene_manifest else None,
                # HE-3, in the same statement for the same reason the tree is: the
                # verdict and the numbers it was reached on are read together, and a
                # build that says `failed` with no measurement to point at is the
                # exact uninformative state this tranche exists to end.
                json.dumps(measurements) if measurements else None,
                uuid.UUID(str(build_id)),
            )
    return await get_build(pool, build_id, user_id)


# ---------------------------------------------------------------------------
# Renders (UX-3)
# ---------------------------------------------------------------------------
#
# A render is a picture of a build taken from a named camera, and it is produced by
# the viewport the user is already looking at — the same trusted three.js component
# that loaded the authorized GLB. Nothing renders server-side. That is a deliberate
# choice and not a shortcut: a headless GL stack in the backend image would be a new
# several-hundred-megabyte dependency, a second renderer that could disagree with the
# first, and a picture of something nobody ever saw. Capturing the canvas gives a
# render that is, by construction, exactly what was on screen.
#
# What that costs is honesty about availability: with no viewer attached, no render
# gets made. The tool surface says so rather than pretending otherwise.
#
# A render is never evidence of a dimension. It is bound to the build it depicts and
# to the sha256 of the geometry that was loaded when the shutter fired, so a render
# whose part has since been rebuilt can be recognised as stale instead of silently
# standing in for the new one.

CAMERA_PRESETS: tuple[str, ...] = (
    "iso", "front", "rear", "left", "right", "top", "bottom", "four_view",
)
# A render's `variant` is either a camera preset a person pressed, or a recipe id the
# server issued (HE-7). They share one column and one uniqueness constraint, which is
# what gives a re-capture last-write-wins, so they must never collide — asserted by
# `test_recipe_ids_never_collide_with_the_camera_presets_they_share_a_column_with`.
RENDER_PRESETS: tuple[str, ...] = CAMERA_PRESETS + cad_render_recipes.RECIPE_IDS
# How a preset reads in a sentence, for the timeline row a render gets (DE-10). A map
# rather than a `.title()`, because "four_view" and "iso" both come out wrong that way.
_RENDER_LABELS: dict[str, str] = {
    "iso": "Isometric view",
    "front": "Front view",
    "rear": "Rear view",
    "left": "Left view",
    "right": "Right view",
    "top": "Top view",
    "bottom": "Bottom view",
    "four_view": "Four-view sheet",
    cad_render_recipes.OVERVIEW: "Overview",
    cad_render_recipes.SECTION_CAVITY: "Cut view",
    cad_render_recipes.SEPARATION: "Parts",
    cad_render_recipes.CONTACT_SHEET: "Four views",
}
MAX_RENDER_BYTES = 4 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _render_qc(mask: bytes | None, recipe: dict | None,
               siblings: dict[str, int] | None) -> dict:
    """Measure the object-mask pass and return what belongs in the render's ``meta``.

    Raises :class:`CadStoreError` on the one finding that means "do not keep this
    picture" — a mask with no body in it at all. Every other finding is a warning that
    rides along with the stored render.

    No mask means no QC, and no QC means the render is stored unmeasured rather than
    refused. That is the honest outcome for a build with more bodies than mask colours
    (the recipe then ships without a palette) and for a client that has not learned to
    render the second pass yet — an unmeasured picture is not a bad one.
    """
    if not mask or not recipe:
        return {}
    palette = recipe.get("mask_palette") or {}
    if not palette:
        return {}
    try:
        report = cad_render_qc.mask_report(mask, palette)
    except cad_render_qc.RenderQcError as exc:
        raise CadStoreError("bad_render_mask", str(exc), status=400) from exc
    except Exception:
        # Pillow or numpy missing, a decode that fell over: the beauty pass is still a
        # real picture of a real build, so it is kept and simply not measured.
        logger.exception("cad_store: render QC failed, storing the render unmeasured")
        return {}

    findings = cad_render_qc.verdicts(
        report,
        expected_visible_parts=recipe.get("expected_visible_parts"),
        sibling_dhashes=siblings or {},
        rotationally_symmetric=bool(recipe.get("rotationally_symmetric")),
        exempt_from_similarity=bool(recipe.get("exempt_from_similarity")),
    )
    refusal = cad_render_qc.rejected(findings)
    if refusal:
        raise CadStoreError("render_rejected", refusal["detail"], status=422,
                            extra={"finding": refusal["code"]})

    return {
        "recipe_id": recipe.get("recipe_id") or "",
        "dhash": report["dhash"],
        "coverage": report["coverage"],
        "visible_parts": report["visible_parts"],
        "qc": findings,
        "disclaimer": cad_render_recipes.DISCLAIMER,
    }


async def save_render(pool, build_id: str, user_id: int, preset: str, blob: bytes,
                      source_sha256: str, label: str = "",
                      mask: bytes | None = None, recipe: dict | None = None,
                      siblings: dict[str, int] | None = None) -> dict:
    """Store one render of a build. Re-capturing a preset replaces the old picture.

    Validated here rather than at the route because this is the function that writes
    bytes to disk: the magic number, the size ceiling, the preset allowlist and the
    binding to a real export of this build are all conditions on the write, and a
    second caller must not be able to reach the write without them. HE-7's quality
    control joins them for the same reason — a picture QC rejects must not reach disk
    by a second path.

    ``mask`` is the object-mask pass for ``recipe``: flat per-body colour on black. It
    is QC input rather than a deliverable, so it is measured and discarded — what
    survives is its findings and its perceptual hash, in ``meta``. ``siblings`` maps
    this build's other stored recipes to their hashes, which is the only comparison in
    which "these two are the same view" says anything.

    **Nothing measured here can change a conformance verdict.** The worst QC can do is
    refuse to keep one picture; everything else is a warning stored beside a picture
    that is kept.
    """
    preset = str(preset or "").strip()
    if preset not in RENDER_PRESETS:
        raise CadStoreError("bad_preset", f"{preset!r} is not a camera preset", status=400,
                       extra={"presets": list(RENDER_PRESETS)})
    if not blob or not blob.startswith(_PNG_MAGIC):
        raise CadStoreError("bad_render", "a render must be a PNG", status=400)
    if len(blob) > MAX_RENDER_BYTES:
        raise CadStoreError("render_too_large",
                       f"a render may be at most {MAX_RENDER_BYTES} bytes", status=413)

    build = await get_build(pool, build_id, user_id)
    if not build:
        return {}
    # The digest of the geometry that was on screen has to match a file this build
    # actually produced. Without that check a render is just a PNG someone posted at
    # a build id, and the gallery would caption it with that build's measurements.
    source = str(source_sha256 or "").lower()
    depicted = next((a for a in build.get("artifacts") or [] if a["sha256"] == source), None)
    if not depicted:
        raise CadStoreError("render_source_mismatch",
                       "that geometry digest does not belong to this build", status=409)

    qc_meta = _render_qc(mask, recipe, siblings)

    project_id = await _project_of_build(pool, build_id)
    await check_quota(pool, user_id, project_id, len(blob))

    directory = _build_dir(user_id, project_id, build_id)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"view-{preset}.png")
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, path)

    meta = {
        "preset": preset,
        "revision_id": build.get("revision_id"),
        "source_sha256": source,
        "source_format": depicted["format"],
        "label": str(label or "")[:80],
    }
    if qc_meta:
        meta.update(qc_meta)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO cad_artifacts "
            "(id, build_id, format, media_type, size_bytes, sha256, storage_key, "
            " variant, meta) "
            "VALUES ($1,$2,'png','image/png',$3,$4,$5,$6,$7::jsonb) "
            "ON CONFLICT (build_id, format, variant) DO UPDATE SET "
            "size_bytes=EXCLUDED.size_bytes, sha256=EXCLUDED.sha256, "
            "storage_key=EXCLUDED.storage_key, meta=EXCLUDED.meta, "
            "created_at=NOW() "
            "RETURNING *",
            uuid.uuid4(), uuid.UUID(str(build_id)), len(blob),
            hashlib.sha256(blob).hexdigest(),
            os.path.relpath(path, artifact_root()), preset, json.dumps(meta),
        )
    return _row_artifact(row)


async def list_renders(pool, build_id: str, user_id: int) -> list[dict]:
    """Every render of one build, oldest preset first. Ownership is in the join."""
    try:
        bid = uuid.UUID(str(build_id))
    except ValueError:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT a.* FROM cad_artifacts a "
            "JOIN cad_builds b ON b.id = a.build_id "
            "JOIN cad_revisions r ON r.id = b.revision_id "
            "JOIN cad_projects p ON p.id = r.project_id "
            "WHERE a.build_id=$1 AND p.user_id=$2 AND a.variant <> '' "
            "ORDER BY a.created_at",
            bid, int(user_id),
        )
    return [_row_artifact(r) for r in rows]


async def _project_of_build(pool, build_id: str) -> str:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT r.project_id FROM cad_builds b "
            "JOIN cad_revisions r ON r.id = b.revision_id WHERE b.id=$1",
            uuid.UUID(str(build_id)),
        )
    return str(val)


# ---------------------------------------------------------------------------
# Retention and the reaper
# ---------------------------------------------------------------------------

async def _unlink_build_files(pool, build_ids: list) -> int:
    """Remove the files a set of builds owns, before their rows go. The rows are the
    only record of where the files are, so this cannot be done afterwards."""
    if not build_ids:
        return 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT a.storage_key FROM cad_artifacts a WHERE a.build_id = ANY($1::uuid[])",
            build_ids,
        )
    removed = 0
    root = os.path.realpath(artifact_root())
    for r in rows:
        real = os.path.realpath(os.path.join(root, r["storage_key"]))
        if not (real.startswith(root + os.sep)):
            continue
        try:
            os.unlink(real)
            removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("could not remove a retired cad artifact", exc_info=True)
    return removed


async def enforce_retention(pool, revision_id: str) -> int:
    """Keep the N most recent SUCCEEDED builds of a revision; drop the rest.

    Only succeeded builds are counted and only succeeded builds are dropped. A failed
    build holds no bytes and its error is the record of what went wrong — retaining
    by total count would quietly delete the diagnosis of a repeated failure.
    """
    keep = retained_builds_per_revision()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM cad_builds WHERE revision_id=$1 AND status='succeeded' "
            "AND experiment_id IS NULL ORDER BY created_at DESC OFFSET $2",
            uuid.UUID(str(revision_id)), keep,
        )
    stale = [r["id"] for r in rows]
    if not stale:
        return 0
    await _unlink_build_files(pool, stale)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM cad_builds WHERE id = ANY($1::uuid[])", stale)
    return len(stale)


async def reap_orphans(pool, dry_run: bool = False) -> dict:
    """Remove files under the CAD root that no ``cad_artifacts`` row claims.

    The cases this exists for: a crash between the write and the insert in
    :func:`finish_build`, and a CASCADE delete of a project or user, which takes the
    rows and cannot take the files. Both leave bytes that nothing will ever serve and
    that no quota counts.

    Row-authoritative in one direction only. A row whose file is missing is NOT
    deleted here — that is data loss caused by something already wrong, and it is
    reported instead.
    """
    root = os.path.realpath(artifact_root())
    if not os.path.isdir(root):
        return {"scanned": 0, "orphans": 0, "removed": 0, "missing_files": 0}

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT storage_key FROM cad_artifacts")
    known = {os.path.realpath(os.path.join(root, r["storage_key"])) for r in rows}

    scanned = orphans = removed = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            real = os.path.realpath(os.path.join(dirpath, name))
            scanned += 1
            if real in known:
                continue
            orphans += 1
            if dry_run:
                continue
            try:
                os.unlink(real)
                removed += 1
            except OSError:
                logger.warning("could not reap an orphaned cad artifact", exc_info=True)

    missing = sum(1 for k in known if not os.path.isfile(k))
    if missing:
        logger.warning("%d cad_artifacts rows have no file on disk", missing)
    return {"scanned": scanned, "orphans": orphans, "removed": removed,
            "missing_files": missing}


# ---------------------------------------------------------------------------
# Authoring jobs (UX-0)
# ---------------------------------------------------------------------------

# The columns a running job is allowed to move. Everything else about a job is
# settled when it is created, and an update that could rewrite `user_id` or
# `description` would let a bug in the runner change whose turn this was.
_JOB_MUTABLE = (
    "status", "phase", "title", "project_id", "revision_id", "build_id",
    "conformance", "error_code", "error_detail", "activity",
)

_JOB_UUID_COLS = ("project_id", "revision_id", "build_id")


def _row_job(row) -> dict:
    activity = row["activity"]
    if isinstance(activity, str):  # asyncpg hands JSONB back as text without a codec
        try:
            activity = json.loads(activity)
        except ValueError:
            activity = []
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "phase": row["phase"],
        # UX-G: the queue is per conversation, so a cancel has to know which one this
        # turn belongs to before it can take the turn out of it.
        "conversation_id": row["conversation_id"],
        "description": row["description"],
        "provider": row["provider"],
        "model": row["model"],
        "title": row["title"],
        "project_id": str(row["project_id"]) if row["project_id"] else None,
        "revision_id": str(row["revision_id"]) if row["revision_id"] else None,
        "build_id": str(row["build_id"]) if row["build_id"] else None,
        "conformance": row["conformance"],
        "error_code": row["error_code"],
        "error_detail": row["error_detail"],
        "activity": activity if isinstance(activity, list) else [],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
    }


async def create_job(pool, user_id: int, description: str, *,
                     conversation_id: str | None = None,
                     provider: str | None = None,
                     model: str | None = None,
                     queued: bool = False) -> dict:
    """Mint the id the chat card will name, before the model has been asked anything.

    ``queued`` (UX-G) mints the same row in the waiting state instead of the running
    one, so a turn that has not started yet is still a real, nameable, cancellable
    thing rather than a message the browser is holding on to.
    """
    status, phase = ("queued", "queued") if queued else ("running", "starting")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO cad_jobs (id, user_id, conversation_id, description, "
            "provider, model, status, phase) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *",
            uuid.uuid4(), int(user_id), conversation_id,
            (description or "")[:4000], provider, model, status, phase,
        )
    return _row_job(row)


async def find_active_job(pool, user_id: int,
                          conversation_id: str | None) -> dict | None:
    """The turn this conversation already has in flight, running or waiting.

    UX-G asks a question the lane could not previously answer: is anything already
    authoring here? Without it a second message starts a second turn against the same
    project, and two models propose revisions over each other with no way to tell
    afterwards which one the user meant. Scoped to the conversation because that is
    what the user perceives as "this design session" — a different chat is a different
    piece of work and has every right to run at the same time.
    """
    if not conversation_id:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cad_jobs WHERE user_id=$1 AND conversation_id=$2 "
            "AND status IN ('running', 'queued') ORDER BY created_at ASC LIMIT 1",
            int(user_id), str(conversation_id),
        )
    return _row_job(row) if row else None


async def has_running_job(pool, user_id: int,
                          conversation_id: str | None) -> bool:
    """Is a turn actually running here, as opposed to merely waiting?

    Distinct from :func:`find_active_job` because the two answer different questions.
    Checking for "anything active" decides whether a new turn should wait; checking for
    "anything *running*" closes the race that follows — the turn in front can finish
    between the first check and the moment the new one joins the queue, and the drain
    it triggered would then have looked at an empty queue. Without this the follow-up
    would wait for a turn that had already ended.
    """
    if not conversation_id:
        return False
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT 1 FROM cad_jobs WHERE user_id=$1 AND conversation_id=$2 "
            "AND status='running' LIMIT 1", int(user_id), str(conversation_id)))


async def count_waiting_jobs(pool, user_id: int,
                             conversation_id: str | None) -> int:
    """How many turns are waiting their turn — what the card's "2nd in line" says."""
    if not conversation_id:
        return 0
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            "SELECT COUNT(*) FROM cad_jobs WHERE user_id=$1 AND conversation_id=$2 "
            "AND status='queued'", int(user_id), str(conversation_id)) or 0)


async def get_job(pool, job_id: str, user_id: int) -> dict | None:
    """404-shaped: another user's job reads as a job that does not exist."""
    try:
        jid = uuid.UUID(str(job_id))
    except (TypeError, ValueError):
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cad_jobs WHERE id=$1 AND user_id=$2", jid, int(user_id),
        )
    return _row_job(row) if row else None


async def update_job(pool, job_id: str, **fields) -> None:
    """Move a running job forward. Unknown keys are dropped, not raised on — the
    runner is a background task and a typo there must not kill the turn silently."""
    sets: list[str] = []
    args: list = []
    for key, value in fields.items():
        if key not in _JOB_MUTABLE:
            continue
        args.append(
            json.dumps(value) if key == "activity"
            else uuid.UUID(str(value)) if key in _JOB_UUID_COLS and value
            else None if key in _JOB_UUID_COLS
            else value
        )
        cast = "::jsonb" if key == "activity" else ""
        sets.append(f"{key}=${len(args)}{cast}")
    if not sets:
        return
    if fields.get("status") in ("succeeded", "failed", "cancelled"):
        sets.append("finished_at=NOW()")
    args.append(uuid.UUID(str(job_id)))
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE cad_jobs SET {', '.join(sets)} WHERE id=${len(args)}", *args,
        )


async def claim_queued_job(pool, job_id: str) -> bool:
    """Move a waiting turn to running — once, and only while it is still waiting.

    The guard is the same shape as ``cancel_job_if_running``'s and for the same
    reason: between reaching the front of the queue and being started, a turn can have
    been cancelled or reaped, and the check and the write have to be one statement or
    the gap they close reopens. Returns whether this caller is the one that claimed it.
    """
    try:
        jid = uuid.UUID(str(job_id))
    except (TypeError, ValueError):
        return False
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE cad_jobs SET status='running', phase='starting' "
            "WHERE id=$1 AND status='queued'", jid,
        )
    return str(result).rsplit(" ", 1)[-1] != "0"


async def cancel_job_if_running(pool, job_id: str) -> bool:
    """Mark a turn cancelled, but only while it still claims to be running.

    ``update_job`` would happily write ``cancelled`` over ``succeeded``, and there is
    a real window where that is wrong: the runner drops its task handle before it
    writes the outcome, so a cancel arriving in that gap finds nothing to interrupt
    and would relabel a turn that had in fact just finished. The guard lives in the
    WHERE clause because the check and the write have to be one statement — two
    statements reopen the gap they were meant to close.

    Returns whether the row actually moved.
    """
    try:
        jid = uuid.UUID(str(job_id))
    except (TypeError, ValueError):
        return False
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE cad_jobs SET status='cancelled', phase='cancelled', "
            "finished_at=NOW() WHERE id=$1 AND status IN ('queued','running')", jid,
        )
    return str(result).rsplit(" ", 1)[-1] != "0"


# ---------------------------------------------------------------------------
# Design activity (UX-2)
#
# The panel asks a question none of the tables above answers on its own: *what has
# happened to this project, in order?* There is no `cad_events` table and this gate
# does not add one. Every row a timeline could show already has a durable home —
# `cad_jobs.activity` records what the model did, `cad_revisions` records what was
# asked for, `cad_builds` records what the engine made of it — so an event table would
# be a fourth copy of facts that are already written, with its own retention policy,
# its own orphan reaper, and its own opportunity to disagree with the rows it mirrors.
#
# Merging the three at read time costs one index (added above) and keeps exactly one
# writer per fact.
#
# The recipe lane is the reason revisions and builds are read rather than jobs alone:
# a slider change creates no job row at all, so a jobs-only timeline would show the
# authoring turn and then go silent for every edit the user made by hand.
# ---------------------------------------------------------------------------

# Every timeline row is public by construction. Job events were sanitized when they
# were written (see `cad_jobs._Activity`); revision and build rows are projected field
# by field here, and the fields not named are not emitted. `storage_key`, prompts,
# credentials and paths have no route to this list.
MAX_PROJECT_ACTIVITY = 400

# The ceiling on what one cursor read will merge. Larger than the panel's window because
# a client resuming from an old cursor is asking about the *whole* history, not the tail
# of it — but still bounded, because this is a merge in Python and an unbounded one is a
# way for a long-lived project to make every reconnect slower than the last.
MAX_STREAM_EVENTS = 5000


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _sort_at(ev: dict) -> datetime:
    """A timeline row's instant, as a comparable value. An unparseable stamp sorts to
    the beginning rather than raising — one malformed row must not cost the panel its
    whole history."""
    try:
        dt = datetime.fromisoformat(str(ev["at"]))
    except (TypeError, ValueError, KeyError):
        return _EPOCH
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _measurements(validation) -> dict | None:
    """The handful of numbers worth showing on a timeline row.

    Not the whole validation blob: the build route already serves that, and a row that
    dumped it would bury the two facts a person scanning history actually reads.
    """
    v = _jsonb(validation)
    if not isinstance(v, dict):
        return None
    out = {}
    for key in ("volume_mm3", "surface_area_mm2", "solid_count"):
        if v.get(key) is not None:
            out[key] = v[key]
    bbox = v.get("bbox_mm")
    if isinstance(bbox, dict):
        out["bbox_mm"] = bbox
    return out or None


async def project_activity(pool, project_id: str, user_id: int,
                           limit: int = MAX_PROJECT_ACTIVITY) -> list[dict]:
    """The project's design activity, oldest first.

    Ownership is in every WHERE clause rather than checked once by the caller, for the
    same reason `get_project` puts it there: a read that filters is one early return
    safer than a read that compares.
    """
    try:
        pid = uuid.UUID(str(project_id))
    except (TypeError, ValueError):
        return []
    uid = int(user_id)

    async with pool.acquire() as conn:
        jobs = await conn.fetch(
            "SELECT id, activity, provider, model FROM cad_jobs "
            "WHERE project_id=$1 AND user_id=$2 ORDER BY created_at",
            pid, uid,
        )
        revs = await conn.fetch(
            "SELECT r.id, r.seq, r.source_kind, r.recipe_name, r.created_by, "
            "r.model_provider, r.model_name, r.created_at, r.accepted_at, r.provenance "
            "FROM cad_revisions r JOIN cad_projects p ON p.id = r.project_id "
            "WHERE r.project_id=$1 AND p.user_id=$2 ORDER BY r.seq",
            pid, uid,
        )
        builds = await conn.fetch(
            "SELECT b.id, b.revision_id, b.status, b.duration_ms, b.validation, "
            "b.conformance_status, b.error_code, b.error_detail, b.created_at, "
            "b.finished_at, r.seq "
            "FROM cad_builds b JOIN cad_revisions r ON r.id = b.revision_id "
            "JOIN cad_projects p ON p.id = r.project_id "
            "WHERE r.project_id=$1 AND p.user_id=$2 AND b.experiment_id IS NULL "
            "ORDER BY b.created_at",
            pid, uid,
        )
        # DE-10. The pictures belong in the timeline, at the moment the shutter fired.
        # Derived here rather than written by the upload route, for the same reason the
        # build rows are: a render's row should exist exactly as long as the render
        # does, and a second record of the same fact is a second thing that can go
        # stale. `variant` is the camera preset and only a render carries one.
        shots = await conn.fetch(
            "SELECT a.id, a.build_id, a.variant, a.created_at, a.size_bytes, a.meta, "
            "b.revision_id, r.seq "
            "FROM cad_artifacts a JOIN cad_builds b ON b.id = a.build_id "
            "JOIN cad_revisions r ON r.id = b.revision_id "
            "JOIN cad_projects p ON p.id = r.project_id "
            "WHERE r.project_id=$1 AND p.user_id=$2 AND b.experiment_id IS NULL "
            "AND a.format='png' AND a.variant <> '' "
            "ORDER BY a.created_at",
            pid, uid,
        )

    events: list[dict] = []

    for job in jobs:
        acts = job["activity"]
        if isinstance(acts, str):
            try:
                acts = json.loads(acts)
            except ValueError:
                acts = []
        if not isinstance(acts, list):
            continue
        jid = str(job["id"])
        for ev in acts:
            if not isinstance(ev, dict) or not ev.get("at"):
                continue
            # The id is what lets a live stream event and its persisted twin collapse
            # into one row in the panel instead of appearing twice.
            events.append({**ev, "id": f"job:{jid}:{ev.get('seq')}", "job_id": jid})

    for r in revs:
        seq = r["seq"]
        source = r["source_kind"] or "recipe"
        who = r["created_by"] or "user"
        prov = _jsonb(r["provenance"]) if r["provenance"] else None
        if source == "import":
            label = f"Revision {seq} imported"
        elif who == "ai":
            label = f"Revision {seq} proposed"
        else:
            label = f"Revision {seq} created"
        ev = {
            "id": f"rev:{r['id']}",
            "at": r["created_at"].isoformat() if r["created_at"] else None,
            "kind": "revision",
            "label": label,
            "revision_id": str(r["id"]),
            "seq": seq,
            "source_kind": source,
            "created_by": who,
        }
        if r["recipe_name"]:
            ev["recipe"] = r["recipe_name"]
        if r["model_name"]:
            ev["model"] = r["model_name"]
            ev["provider"] = r["model_provider"]
        # The imported file's own name and digest — the one honest answer an imported
        # part has to "where did this come from". Never the path it arrived on.
        if isinstance(prov, dict):
            ev["provenance"] = {
                k: prov[k] for k in ("filename", "sha256", "size_bytes", "reader")
                if prov.get(k) is not None
            } or None
        events.append(ev)

        # Acceptance is its own moment, and only when it is a moment: the backfill that
        # added `accepted_at` stamped it equal to `created_at` for every pre-existing
        # revision, and emitting those would invent an approval nobody gave.
        acc = r["accepted_at"]
        if acc and r["created_at"] and acc > r["created_at"]:
            events.append({
                "id": f"acc:{r['id']}",
                "at": acc.isoformat(),
                "kind": "accepted",
                "label": f"Revision {seq} accepted",
                "revision_id": str(r["id"]),
                "seq": seq,
            })

    for b in builds:
        status = b["status"]
        seq = b["seq"]
        if status == "succeeded":
            label = f"Built revision {seq}"
        elif status == "failed":
            label = f"Revision {seq} failed to build"
        elif status == "cancelled":
            label = f"Build of revision {seq} cancelled"
        else:
            label = f"Building revision {seq}"
        ev = {
            # A build's row is dated by when it FINISHED, because that is when what it
            # says became true. A build dated by its start would sort ahead of the
            # revision edits a user made while waiting for it.
            "at": (b["finished_at"] or b["created_at"]).isoformat()
            if (b["finished_at"] or b["created_at"]) else None,
            "id": f"build:{b['id']}",
            "kind": "build",
            "label": label,
            "build_id": str(b["id"]),
            "revision_id": str(b["revision_id"]),
            "seq": seq,
            "status": status,
            "ok": status == "succeeded",
        }
        if b["duration_ms"] is not None:
            ev["duration_ms"] = b["duration_ms"]
        # Two verdicts, kept apart here exactly as they are kept apart in the row.
        if b["conformance_status"]:
            ev["conformance"] = b["conformance_status"]
        if b["error_code"]:
            ev["error_code"] = b["error_code"]
        if b["error_detail"]:
            ev["error_detail"] = str(b["error_detail"])[:400]
        m = _measurements(b["validation"])
        if m:
            ev["measurements"] = m
        events.append(ev)

    for a in shots:
        preset = str(a["variant"] or "")
        meta = _jsonb(a["meta"]) if a["meta"] else {}
        events.append({
            "id": f"render:{a['id']}",
            "at": a["created_at"].isoformat() if a["created_at"] else None,
            "kind": "render",
            # What the picture is OF, not a verdict about it. The disclaimer the render
            # routes carry — an inspection view, never dimensional proof — belongs on
            # the panel that shows the image, not welded into every row label.
            "label": f"{_RENDER_LABELS.get(preset, preset)} captured",
            "render_id": str(a["id"]),
            "build_id": str(a["build_id"]),
            "revision_id": str(a["revision_id"]),
            "preset": preset,
            "seq": a["seq"],
            "size_bytes": a["size_bytes"],
            "filename": f"view-{preset}.png",
            # The digest of the geometry that was on screen when the shutter fired.
            # It is what lets a reader tell a picture of THIS revision from one taken
            # of a part that has since been rebuilt.
            "source_sha256": (meta or {}).get("source_sha256"),
        })

    events = [e for e in events if e.get("at")]
    # Parsed, not string-compared. Job events stamp UTC and Postgres hands back the
    # session timezone, so two rows a second apart can carry different offsets and sort
    # into the wrong order as text.
    events.sort(key=_sort_at)

    # UX-B. The stream ordinal, assigned here and **before the window below**, which is
    # what makes it usable as a cursor: dropping the oldest rows would otherwise shift
    # every remaining number down and a client holding `stream_seq = 12` would silently
    # skip whatever slid past it.
    #
    # Not called `seq`: on a revision or build row `seq` already means *which revision*,
    # and one field that means "revision 3" on one row and "the 3rd thing that happened"
    # on the next is a bug waiting for a client to write it.
    #
    # It is a position, not an identity, and it moves. A build's row is dated by when it
    # finished, so a build that completes lands later in the order than it did while it
    # was running — and that is the behaviour the workspace wants: the row is re-sent
    # with a new ordinal and the client, which already collapses rows by `id`, updates
    # the one it has instead of appending a second. Ordinals shifting is why `id` is the
    # identity and this is only the cursor.
    for i, ev in enumerate(events, 1):
        ev["stream_seq"] = i
    if len(events) > limit:
        # Drop the OLDEST, not the newest: a timeline that truncated the recent end
        # would show a project frozen at its beginning.
        events = events[-limit:]
    return events


async def project_events(pool, project_id: str, user_id: int,
                         after_seq: int = 0, limit: int = 200) -> tuple[list[dict], int]:
    """Everything that has happened to this project after ``after_seq``, and the cursor.

    The second half of the return is **the cursor to hold next**, not the highest ordinal
    that exists — the difference matters exactly when the window truncates. Handing back
    the highest would tell a client to resume past rows it was never sent, and the gap
    would be unaskable-for. So: the last row actually returned, or the highest that
    exists when there was nothing to return, which is what lets a caller advance through
    a quiet stretch without re-reading it.

    Replay is the whole contract. The same call with the same cursor returns the same
    rows, because none of it is generated at connect time — it is the three tables that
    were already written, read again.
    """
    all_events = await project_activity(pool, project_id, user_id,
                                        limit=MAX_STREAM_EVENTS)
    highest = all_events[-1]["stream_seq"] if all_events else 0
    try:
        after = max(0, int(after_seq))
    except (TypeError, ValueError):
        after = 0
    fresh = [e for e in all_events if e["stream_seq"] > after]
    if len(fresh) > limit:
        # The OLDEST of the fresh rows, not the newest: a client resuming from a cursor
        # is walking forward, and handing it the tail would strand a gap behind it.
        fresh = fresh[:limit]
    return fresh, (fresh[-1]["stream_seq"] if fresh else highest)


# ---------------------------------------------------------------------------
# The workspace snapshot (UX-B)
#
# One read that answers "what am I looking at?" — because the three panels of the focus
# workspace are three views of *one* state, and assembling that state from four separate
# routes is how they end up disagreeing. The tree, the viewport and the inspector must
# never be describing different revisions, and the cheapest way to guarantee that is for
# one query to decide it once.
#
# The decision this makes, and makes server-side on purpose, is **which geometry is on
# screen**. §3's rule — the accepted model stays visible while a new one builds, and good
# geometry is never replaced by a loading screen or a failure — is a policy, and a policy
# each client re-derives is a policy each client gets subtly wrong.
# ---------------------------------------------------------------------------

_ACTIVE_BUILD_STATES = ("queued", "running")


async def active_job(pool, project_id: str, user_id: int) -> dict | None:
    """The authoring turn still running against this project, if there is one.

    Read separately from the builds because a job outlives any single build: the model
    can be reasoning, repairing, or between tool calls with no build in flight at all,
    and a workspace that inferred "busy" from builds alone would show an idle project
    while a turn was mid-thought.
    """
    try:
        pid = uuid.UUID(str(project_id))
    except (TypeError, ValueError):
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cad_jobs WHERE project_id=$1 AND user_id=$2 "
            "AND status='running' ORDER BY created_at DESC LIMIT 1",
            pid, int(user_id),
        )
    return _row_job(row) if row else None


def _displayed(revisions: list[dict]) -> dict | None:
    """Which revision's geometry belongs on screen, given the history newest-first.

    The newest revision that actually built. Not the newest revision — that one may be
    mid-build or failed, and swapping a good part for a spinner or an error is precisely
    what §3 forbids. Not the accepted one either: a proposal the user is being asked to
    judge has to be visible for them to judge it.

    ``None`` means nothing in this project has ever built, which is a real state (a
    project created from a template and not yet built) and reads as an empty viewport
    rather than as a failure.
    """
    for rev in revisions:
        build = rev.get("latest_build") or {}
        if build.get("status") != "succeeded":
            continue
        glb = next((a for a in (build.get("artifacts") or [])
                    if a.get("format") == "glb"), None)
        return {
            "revision_id": rev["id"],
            "seq": rev["seq"],
            "state": rev["state"],
            "build_id": build["id"],
            # The id to fetch, never a path. The artifact route is the only thing that
            # turns one into bytes, and it re-checks ownership when it does.
            "glb_artifact_id": (glb or {}).get("id"),
            # UX-A's tree. Null on a build made before the engine emitted one — the
            # hierarchy panel then says it has none rather than inventing a body.
            "scene_manifest": build.get("scene_manifest"),
            "validation": build.get("validation"),
            "conformance": build.get("conformance"),
            "conformance_status": build.get("conformance_status"),
        }
    return None


async def workspace_snapshot(pool, project_id: str, user_id: int, *,
                             history_limit: int = 50,
                             activity_limit: int = MAX_PROJECT_ACTIVITY) -> dict | None:
    """Everything the focus workspace needs to draw itself, from one consistent read.

    ``None`` for a project the caller does not own — the same answer as one that does not
    exist, matching every other read in this module.
    """
    project = await get_project(pool, project_id, user_id)
    if not project:
        return None

    revisions = await list_revisions(pool, project_id, user_id, limit=history_limit)
    builds = await latest_builds_by_revision(pool, project_id, user_id)
    for rev in revisions:
        rev["latest_build"] = builds.get(rev["id"])

    by_id = {rev["id"]: rev for rev in revisions}
    accepted = by_id.get(project.get("head_revision") or "")
    latest = revisions[0] if revisions else None

    # A build still in flight, whatever revision it belongs to. Newest first, so a user
    # who queued two edits sees the one that is actually running.
    running = sorted(
        (b for b in builds.values() if b.get("status") in _ACTIVE_BUILD_STATES),
        key=lambda b: b.get("created_at") or "", reverse=True)

    activity, cursor = await project_events(pool, project_id, user_id,
                                            after_seq=0, limit=activity_limit)
    displayed = _displayed(revisions)

    return {
        "project": project,
        # The binding the spec asks for, promoted out of the project row so the client
        # does not have to know where it lives. Null is legitimate: a project can be
        # created outside a conversation and adopted by one later.
        "conversation_id": project.get("conversation_id"),
        "accepted": accepted,
        "latest": latest,
        "displayed": displayed,
        "active_build": running[0] if running else None,
        "active_job": await active_job(pool, project_id, user_id),
        "history": revisions,
        "activity": activity,
        # Where the event stream stands as of this snapshot. A client opens the stream
        # with exactly this number and receives everything after it — which is what makes
        # a refresh continue the timeline instead of replaying it twice.
        "event_cursor": cursor,
        "capabilities": _workspace_capabilities(displayed),
    }


async def resolve_selection(pool, user_id: int, project_id: str,
                            revision_id: str, node_id: str) -> dict | None:
    """Turn three ids a client sent into the authoritative facts about that node.

    UX-D §5. The client is allowed to *name* a selection and nothing else: it sends
    opaque ids, and every human-readable word that later reaches a model comes from
    here. A chip that carried its own label would let a page assert "the user selected
    the mounting boss" about a node called something else entirely, and the model would
    have no way to tell.

    Four things are checked, and any of them failing returns ``None`` — the same answer
    as a node that does not exist, on purpose:

    * the project belongs to this user (ownership is in the WHERE clause);
    * the revision belongs to *that* project, not merely to the same user;
    * the revision's latest build produced a scene manifest;
    * the node is in that manifest.

    The last one is what makes a stale selection safe. A node id from an earlier build
    is not in the current one, so it resolves to nothing rather than to a body that
    happens to share a slot.
    """
    try:
        pid = uuid.UUID(str(project_id))
        rid = uuid.UUID(str(revision_id))
    except (ValueError, AttributeError, TypeError):
        return None
    if not isinstance(node_id, str) or not node_id:
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT p.title AS project_title, r.seq AS revision_seq, "
            "       b.id AS build_id, b.status AS build_status, b.scene_manifest "
            "  FROM cad_revisions r "
            "  JOIN cad_projects p ON p.id = r.project_id "
            "  LEFT JOIN LATERAL ("
            "        SELECT id, status, scene_manifest FROM cad_builds "
            "         WHERE revision_id = r.id AND experiment_id IS NULL "
            "         ORDER BY created_at DESC LIMIT 1"
            "  ) b ON TRUE "
            " WHERE r.id = $1 AND r.project_id = $2 AND p.user_id = $3",
            rid, pid, int(user_id),
        )
    if not row:
        return None

    manifest = _jsonb(row["scene_manifest"]) if row["scene_manifest"] else None
    node = next((n for n in (manifest or {}).get("nodes", [])
                 if n.get("node_id") == node_id), None)
    if not node:
        return None

    return {
        "project_id": str(project_id),
        "project_title": row["project_title"],
        "revision_id": str(revision_id),
        "revision_seq": row["revision_seq"],
        "build_id": str(row["build_id"]) if row["build_id"] else None,
        "node_id": node_id,
        "label": node.get("label") or "",
        "kind": node.get("kind") or "",
        "status": node.get("status") or "",
        # Present only on a feature row. It is the one field that lets a model act on a
        # selection precisely — it names the CadIR operation to edit.
        "cadir_operation_id": node.get("cadir_operation_id"),
        "selectable": bool(node.get("selectable")),
    }


def _workspace_capabilities(displayed: dict | None) -> dict:
    """What this workspace can actually do *right now*, derived rather than declared.

    Every flag is read off the state above it. A capability list written as constants
    would keep claiming selection works on a build whose engine never emitted a tree,
    and the panel would offer a click that can only do nothing.
    """
    manifest = (displayed or {}).get("scene_manifest") or {}
    nodes = manifest.get("nodes") or []
    selection = manifest.get("selection") or {}
    return {
        "units": "mm",
        "hierarchy": bool(nodes),
        # A body is selectable only if the exporter actually put its pick key in the GLB;
        # `tag_glb` nulls the ones that did not land, so this counts real clickable rows.
        "select_bodies": any(n.get("kind") == "body" and n.get("glb_pick_key")
                             for n in nodes),
        "select_faces": bool(selection.get("faces")),
        "select_edges": bool(selection.get("edges")),
        # The engine's own sentence for why, carried through rather than restated in the
        # UI — one claim, one place it is kept true.
        "selection_reason": selection.get("reason"),
    }


# ---------------------------------------------------------------------------
# CAD sessions (CS-1)
#
# A session is the room a part is made in: one project, one dedicated conversation,
# one restorable view. Everything here is ownership-scoped and 404-shaped — a session
# belonging to someone else reads exactly like a session that does not exist, which is
# the same shape every other read in this module takes.
# ---------------------------------------------------------------------------

MAX_VIEW_STATE_BYTES = 16_384


def _row_session(row) -> dict:
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]) if row["project_id"] else None,
        "job_id": str(row["job_id"]) if row["job_id"] else None,
        "source_conversation_id": row["source_conversation_id"],
        "cad_conversation_id": row["cad_conversation_id"],
        "title": row["title"] or "",
        "view_state": _jsonb(row["view_state"]) or {},
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def create_session(pool, user_id: int, *, cad_conversation_id: str,
                         source_conversation_id: str | None = None,
                         project_id: str | None = None,
                         job_id: str | None = None,
                         title: str = "") -> dict:
    """Open a room for a part.

    A session can be minted before its project exists — see the table comment — so
    ``project_id`` is optional and ``job_id`` is how the binding arrives later.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO cad_sessions (id, user_id, project_id, job_id, "
            "source_conversation_id, cad_conversation_id, title) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
            uuid.uuid4(), int(user_id), _uuid_or_none(project_id),
            _uuid_or_none(job_id), source_conversation_id,
            str(cad_conversation_id), (title or "")[:200],
        )
    return _row_session(row)


def _uuid_or_none(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


async def _bind_project(conn, row):
    """Fill in the project the model created after this session opened.

    The job is the only thing that knows: it is minted before the project and records
    the id the moment ``cad_create_project`` returns. Doing it on read rather than
    asking the job runner to write sessions keeps the runner unaware of them — it has
    one job, and a turn started from an API call with no session at all must keep
    working exactly as it does now.
    """
    if row["project_id"] or not row["job_id"]:
        return row
    project_id = await conn.fetchval(
        "SELECT project_id FROM cad_jobs WHERE id=$1 AND user_id=$2",
        row["job_id"], row["user_id"])
    if not project_id:
        return row
    # A project can be deleted while its session survives; the guard keeps that from
    # turning a read into a foreign-key error.
    bound = await conn.fetchrow(
        "UPDATE cad_sessions SET project_id=$1, updated_at=NOW() "
        "WHERE id=$2 AND project_id IS NULL "
        "AND EXISTS (SELECT 1 FROM cad_projects WHERE id=$1 AND user_id=$3) "
        "RETURNING *", project_id, row["id"], row["user_id"])
    return bound or row


async def get_session(pool, session_id: str, user_id: int) -> dict | None:
    sid = _uuid_or_none(session_id)
    if sid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cad_sessions WHERE id=$1 AND user_id=$2", sid, int(user_id))
        if not row:
            return None
        row = await _bind_project(conn, row)
    return _row_session(row)


async def session_for_conversation(pool, user_id: int,
                                   conversation_id: str | None) -> dict | None:
    """The session a message belongs to, if it was sent inside one.

    This is what makes a session project-*bound* rather than merely project-shaped.
    Without it the second message in a session would be read as a fresh request and
    the model would reach for ``cad_create_project`` again, leaving the room with a
    part it is not showing.
    """
    if not conversation_id:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cad_sessions WHERE user_id=$1 AND cad_conversation_id=$2",
            int(user_id), str(conversation_id))
        if not row:
            return None
        row = await _bind_project(conn, row)
    return _row_session(row)


async def session_for_project(pool, user_id: int, project_id: str) -> dict | None:
    """The room a project is being made in, so a card can link to it."""
    pid = _uuid_or_none(project_id)
    if pid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cad_sessions WHERE user_id=$1 AND project_id=$2",
            int(user_id), pid)
    return _row_session(row) if row else None


async def list_sessions(pool, user_id: int, *, limit: int = 50) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM cad_sessions WHERE user_id=$1 "
            "ORDER BY updated_at DESC LIMIT $2", int(user_id), int(limit))
    return [_row_session(r) for r in rows]


async def save_session_view(pool, session_id: str, user_id: int,
                            view_state: dict) -> dict | None:
    """Remember where the user was: camera, selection, revision, open file, tab.

    Capped and merged rather than replaced, so a panel can save its own corner without
    holding — and possibly stomping — the rest of the view. The cap exists because this
    column is written from the browser on every camera settle; unbounded client JSON in
    a row that updates that often is a way to fill a database by accident.
    """
    sid = _uuid_or_none(session_id)
    if sid is None or not isinstance(view_state, dict):
        return None
    blob = json.dumps(view_state)
    if len(blob) > MAX_VIEW_STATE_BYTES:
        raise CadStoreError("view_state_too_large",
                            "That view is too large to remember.")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE cad_sessions SET view_state = view_state || $1::jsonb, "
            "updated_at=NOW() WHERE id=$2 AND user_id=$3 RETURNING *",
            blob, sid, int(user_id))
    return _row_session(row) if row else None


async def rename_session(pool, session_id: str, user_id: int,
                         title: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE cad_sessions SET title=$1, updated_at=NOW() "
            "WHERE id=$2 AND user_id=$3 RETURNING *",
            (title or "")[:200], _uuid_or_none(session_id), int(user_id))
    return _row_session(row) if row else None
