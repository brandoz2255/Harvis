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

CAD_SCHEMA_SQL = (
    CREATE_CAD_PROJECTS_SQL,
    CREATE_CAD_REVISIONS_SQL,
    CREATE_CAD_BUILDS_SQL,
    CREATE_CAD_ARTIFACTS_SQL,
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
        "parameters": _jsonb(row["parameters"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def _row_build(row) -> dict:
    return {
        "id": str(row["id"]),
        "revision_id": str(row["revision_id"]),
        "status": row["status"],
        "duration_ms": row["duration_ms"],
        "peak_rss_bytes": row["peak_rss_bytes"],
        "validation": _jsonb(row["validation"]),
        "error_code": row["error_code"],
        "error_detail": row["error_detail"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
    }


def _row_artifact(row) -> dict:
    """Never includes ``storage_key``. A client that can name a path can probe for
    one, and there is nothing it could do with the value that the artifact route
    does not already do for it."""
    return {
        "id": str(row["id"]),
        "format": row["format"],
        "media_type": row["media_type"],
        "size_bytes": int(row["size_bytes"]),
        "sha256": row["sha256"],
    }


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
            "SELECT * FROM cad_artifacts WHERE build_id=$1 ORDER BY format",
            row["id"],
        )
    out = _row_build(row)
    out["artifacts"] = [_row_artifact(a) for a in arts]
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
            "WHERE r.project_id=$1 AND p.user_id=$2 "
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
    for a in arts:
        by_build.setdefault(str(a["build_id"]), []).append(_row_artifact(a))
    out: dict = {}
    for r in rows:
        b = _row_build(r)
        b["artifacts"] = by_build.get(b["id"], [])
        out[str(r["revision_id"])] = b
    return out


async def latest_measurements(pool, revision_id: str) -> dict | None:
    """The validation report of a revision's most recent succeeded build, or ``None``.

    ``None`` means "never built successfully" and is deliberately not ``{}`` — compare
    has to be able to say "no measurements yet" rather than showing an empty diff that
    reads as "identical".
    """
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT validation FROM cad_builds WHERE revision_id=$1 "
            "AND status='succeeded' ORDER BY created_at DESC LIMIT 1",
            uuid.UUID(str(revision_id)),
        )
    if row is None:
        return None
    out = _jsonb(row)
    return out if isinstance(out, dict) else None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

async def create_project(pool, user_id: int, title: str,
                         conversation_id: str | None = None,
                         revision: dict | None = None) -> dict:
    """A project and, optionally, its first revision — in one transaction.

    A project with no revisions is a state nothing else in this module expects, so
    the two are created together or not at all.
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
                first = await _insert_revision(conn, project_id, None, 1, revision)
                await conn.execute(
                    "UPDATE cad_projects SET head_revision=$1, next_seq=2, updated_at=NOW() "
                    "WHERE id=$2",
                    uuid.UUID(first["id"]), project_id,
                )
            row = await conn.fetchrow("SELECT * FROM cad_projects WHERE id=$1", project_id)
    out = _row_project(row)
    out["revision"] = first
    return out


async def _insert_revision(conn, project_id, parent_id, seq: int, spec: dict) -> dict:
    rid = uuid.uuid4()
    row = await conn.fetchrow(
        "INSERT INTO cad_revisions "
        "(id, project_id, parent_id, seq, design_spec, source_kind, recipe_name, "
        " cadir, parameters, created_by, model_provider, model_name) "
        "VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8::jsonb,$9::jsonb,$10,$11,$12) "
        "RETURNING *",
        rid, project_id, parent_id, int(seq),
        json.dumps(spec.get("design_spec") or {}),
        (spec.get("source_kind") or "recipe")[:32],
        (spec.get("recipe_name") or None),
        json.dumps(spec["cadir"]) if spec.get("cadir") is not None else None,
        json.dumps(spec.get("parameters") or {}),
        (spec.get("created_by") or "user")[:32],
        spec.get("model_provider"), spec.get("model_name"),
    )
    return _row_revision(row)


async def create_revision(pool, project_id: str, user_id: int, spec: dict,
                          base_revision_id: str | None = None) -> dict:
    """Append a revision, advancing ``seq`` and ``head_revision`` atomically.

    The row lock is what makes ``next_seq`` a sequence rather than a suggestion. Two
    concurrent appends that both read ``next_seq = 4`` would either collide on the
    ``UNIQUE (project_id, seq)`` index or, without it, silently produce two revision
    4s; ``FOR UPDATE`` makes the second one wait and read 5.
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
            # Only checked when the caller states a base. A caller that omits it is
            # explicitly appending to whatever the head is now — which is right for a
            # fresh project and for a server-side retry, and wrong for a UI edit,
            # which is why the route requires it there.
            if base_revision_id is not None and str(base_revision_id) != (head or ""):
                raise StaleRevision(str(base_revision_id), head)

            seq = int(proj["next_seq"])
            rev = await _insert_revision(
                conn, proj["id"],
                uuid.UUID(head) if head else None,
                seq, spec,
            )
            await conn.execute(
                "UPDATE cad_projects SET head_revision=$1, next_seq=$2, updated_at=NOW() "
                "WHERE id=$3",
                uuid.UUID(rev["id"]), seq + 1, proj["id"],
            )
    return rev


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


async def fail_build(pool, build_id: str, code: str, detail: str) -> None:
    """Record why a build did not produce geometry. ``detail`` is the sidecar's safe
    text — names and numbers, never a path, argv or host name."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cad_builds SET status=$1, error_code=$2, error_detail=$3, "
            "finished_at=NOW() WHERE id=$4",
            "cancelled" if code == "build_cancelled" else "failed",
            code, (detail or "")[:2000], uuid.UUID(str(build_id)),
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
                       peak_rss_bytes: int | None = None) -> dict:
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
                    "ON CONFLICT (build_id, format) DO UPDATE SET "
                    "media_type=EXCLUDED.media_type, size_bytes=EXCLUDED.size_bytes, "
                    "sha256=EXCLUDED.sha256, storage_key=EXCLUDED.storage_key",
                    uuid.uuid4(), uuid.UUID(str(build_id)), w["format"], w["media_type"],
                    w["size_bytes"], w["sha256"], w["storage_key"],
                )
            await conn.execute(
                "UPDATE cad_builds SET status='succeeded', validation=$1::jsonb, "
                "duration_ms=$2, peak_rss_bytes=$3, finished_at=NOW() WHERE id=$4",
                json.dumps(validation or {}), duration_ms, peak_rss_bytes,
                uuid.UUID(str(build_id)),
            )
    return await get_build(pool, build_id, user_id)


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
            "ORDER BY created_at DESC OFFSET $2",
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
