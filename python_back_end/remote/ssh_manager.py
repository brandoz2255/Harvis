"""SSH connection-profile CRUD (Phase 7 — SCAFFOLD ONLY, flagged OFF by default).

This module stores per-user SSH host profiles so a FUTURE, user-approved runtime
can offer remote device + folder access. As shipped it can perform **no SSH I/O
whatsoever**:

  * No SSH library is imported — no paramiko, no asyncssh, nothing that can
    open a socket to port 22.
  * Every endpoint sits behind the ``HARVIS_SSH_ENABLED`` env flag. When the
    flag is absent/0 (the DEFAULT) every endpoint returns
    403 ``{"detail": "SSH access is disabled pending security review"}``.
  * The connect/test endpoint is ADDITIONALLY stubbed: even with the flag ON it
    returns 501 ``{"detail": "SSH connect not yet implemented — pending user approval"}``.

Credential handling follows owui_compat/engine_auth.py exactly: the secret
(private key text or password) is Fernet-encrypted via ``main.encrypt_api_key``
and is **write-only** at the API — GET/list return only ``has_credential``
(bool), never the secret. ``main.decrypt_api_key`` is intentionally never
called here; only the future approved runtime may decrypt.

Endpoints (all JWT-auth'd via auth_optimized.get_current_user_optimized):
  GET    /api/remote/ssh/hosts             — list this user's host profiles (no secrets)
  POST   /api/remote/ssh/hosts             — create a profile (credential optional, write-only)
  GET    /api/remote/ssh/hosts/{host_id}   — one profile (no secrets)
  PUT    /api/remote/ssh/hosts/{host_id}   — update fields / replace or clear credential
  DELETE /api/remote/ssh/hosts/{host_id}   — delete the profile (and its encrypted credential)
  POST   /api/remote/ssh/hosts/{host_id}/test — STUB: always 501 (see above)

Registration (main.py, next to the other router includes):
    from remote.ssh_manager import ssh_router
    app.include_router(ssh_router)

Schema: ``user_ssh_hosts`` is created lazily (CREATE TABLE IF NOT EXISTS) on the
first flag-enabled request — additive only, no destructive SQL, and no lifespan
edit needed in main.py.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized
from remote.validation import (
    validate_host_string,
    validate_port,
    validate_profile_name,
    validate_username,
)

logger = logging.getLogger(__name__)

# ─── Feature flag (module-level gate; default OFF) ─────────────────────────────

SSH_FLAG_ENV = "HARVIS_SSH_ENABLED"
SSH_DISABLED_DETAIL = "SSH access is disabled pending security review"
SSH_CONNECT_STUB_DETAIL = "SSH connect not yet implemented — pending user approval"

AUTH_TYPES = {"key", "password"}
_MAX_CREDENTIAL_LEN = 16384  # generous cap for a PEM private key


def ssh_enabled() -> bool:
    """True iff HARVIS_SSH_ENABLED is a truthy value. Read at request time so a
    restart with the env flipped (or a monkeypatched test) takes effect — the
    default, with the var absent, is OFF."""
    return os.getenv(SSH_FLAG_ENV, "0").strip().lower() in {"1", "true", "yes", "on"}


async def _require_ssh_enabled() -> None:
    """Router-level dependency: hard 403 on EVERY endpoint while the flag is off."""
    if not ssh_enabled():
        raise HTTPException(status_code=403, detail=SSH_DISABLED_DETAIL)


# The flag dependency is attached at the ROUTER level so it runs for every
# endpoint (including any added later) before the handler body executes.
ssh_router = APIRouter(
    prefix="/api/remote/ssh",
    tags=["remote-ssh"],
    dependencies=[Depends(_require_ssh_enabled)],
)

# ─── Schema (additive only; follows the engine_auth / orchestration pattern) ───

USER_SSH_HOSTS_SCHEMA_SQL = """
-- Phase 7 scaffold: per-user SSH connection profiles. The credential (private
-- key text or password) is Fernet-encrypted via main.encrypt_api_key and is
-- write-only at the API (GET returns only a has_credential bool). No code in
-- this module ever decrypts it. Additive only — no destructive SQL.
CREATE TABLE IF NOT EXISTS user_ssh_hosts (
    id                    SERIAL PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    name                  TEXT NOT NULL,
    host                  TEXT NOT NULL,
    port                  INTEGER NOT NULL DEFAULT 22,
    username              TEXT NOT NULL,
    auth_type             TEXT NOT NULL DEFAULT 'key',  -- 'key' | 'password'
    credential_encrypted  TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_user_ssh_hosts_user
    ON user_ssh_hosts(user_id, updated_at DESC);
"""

# Phase 4 (Execution Core): governed probe/exec columns, added additively so an
# existing Phase-7-scaffold table upgrades in place with no data loss.
#   jump_host_id          — optional ProxyJump through another owned profile
#   auth_method           — how run_ssh authenticates: agent|key_file|stored_secret|manual
#   host_key_fingerprint  — pinned SHA256 fp (NULL ⇒ never trusted ⇒ exec 409s)
#   known_hosts_line      — the raw known_hosts text appended on /trust
#   key_path              — relative path under HARVIS_SSH_KEYS_DIR for key_file auth
#   allowed_cwds/commands — reserved allowlists (enforcement lands later)
#   risk_lane             — permission lane (default 5 = external services)
USER_SSH_HOSTS_PHASE4_SQL = """
ALTER TABLE user_ssh_hosts ADD COLUMN IF NOT EXISTS jump_host_id INTEGER;
ALTER TABLE user_ssh_hosts ADD COLUMN IF NOT EXISTS auth_method TEXT DEFAULT 'agent';
ALTER TABLE user_ssh_hosts ADD COLUMN IF NOT EXISTS host_key_fingerprint TEXT;
ALTER TABLE user_ssh_hosts ADD COLUMN IF NOT EXISTS known_hosts_line TEXT;
ALTER TABLE user_ssh_hosts ADD COLUMN IF NOT EXISTS key_path TEXT;
ALTER TABLE user_ssh_hosts ADD COLUMN IF NOT EXISTS allowed_cwds JSONB;
ALTER TABLE user_ssh_hosts ADD COLUMN IF NOT EXISTS allowed_commands JSONB;
ALTER TABLE user_ssh_hosts ADD COLUMN IF NOT EXISTS risk_lane INTEGER DEFAULT 5;
"""

# run_ssh authentication methods (distinct from auth_type key|password, which is
# the credential SHAPE). auth_method selects HOW ssh authenticates.
AUTH_METHODS = {"agent", "key_file", "stored_secret", "manual"}

# All columns needed by the exec / trust paths — kept as one list so the SELECT
# and the public wire shape stay in sync.
_FULL_COLUMNS = (
    "id, name, host, port, username, auth_type, credential_encrypted, "
    "jump_host_id, auth_method, host_key_fingerprint, known_hosts_line, "
    "key_path, risk_lane, created_at, updated_at"
)

_schema_ready = False


async def ensure_ssh_schema(pool) -> None:
    """Idempotently create + upgrade user_ssh_hosts. Called lazily from the
    endpoints (memoized per process) so main.py's lifespan needs no edit."""
    global _schema_ready
    if _schema_ready or pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(USER_SSH_HOSTS_SCHEMA_SQL)
        await conn.execute(USER_SSH_HOSTS_PHASE4_SQL)
    _schema_ready = True
    logger.info("user_ssh_hosts schema ensured (Phase 4 columns present)")


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _uid(user) -> int:
    """User id from either the dict (auth_optimized) or object (main) user shape."""
    return int(user["id"] if isinstance(user, dict) else user.id)


def _pool_or_503(request: Request):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    return pool


def _row_public(row) -> dict:
    """Safe wire shape: NEVER includes the credential (only has_credential).

    ``auth_method``/``trusted`` are surfaced additively — ``trusted`` is True iff
    a host-key fingerprint has been pinned (via /test → /trust), which the exec
    path requires. Rows read before the Phase-4 columns exist tolerate absence.
    """
    def _get(key, default=None):
        try:
            return row[key]
        except (KeyError, IndexError):
            return default

    return {
        "id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "auth_type": row["auth_type"],
        "auth_method": _get("auth_method") or "agent",
        "risk_lane": _get("risk_lane") or 5,
        "has_credential": bool(row["credential_encrypted"]),
        "trusted": bool(_get("host_key_fingerprint")),
        "host_key_fingerprint": _get("host_key_fingerprint"),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _validate_profile_fields(
    *, name: object, host: object, port: object, username: object, auth_type: object
) -> None:
    """Run all pure validators; raise 400 with the first failure reason."""
    for ok, reason in (
        validate_profile_name(name),
        validate_host_string(host),
        validate_port(port),
        validate_username(username),
    ):
        if not ok:
            raise HTTPException(status_code=400, detail=reason)
    if auth_type not in AUTH_TYPES:
        raise HTTPException(status_code=400, detail="auth_type must be 'key' or 'password'")


def _encrypt_credential(credential: str) -> str:
    """Fernet-encrypt via the SAME path as engine_auth (main.encrypt_api_key).
    Imported lazily (engine_auth pattern) to avoid a circular import at load."""
    from main import encrypt_api_key

    return encrypt_api_key(credential)


def _clean_credential(body: dict) -> Optional[str]:
    """Extract + sanity-check an optional write-only credential from the body."""
    credential = body.get("credential")
    if credential is None:
        return None
    if not isinstance(credential, str) or not credential.strip():
        raise HTTPException(status_code=400, detail="credential must be a non-empty string")
    if len(credential) > _MAX_CREDENTIAL_LEN:
        raise HTTPException(status_code=400, detail="credential is too large")
    return credential


def _clean_auth_method(body: dict, *, default: str) -> str:
    """Validate an optional auth_method; fall back to the given default."""
    am = body.get("auth_method")
    if am is None:
        return default
    if not isinstance(am, str) or am not in AUTH_METHODS:
        raise HTTPException(status_code=400, detail=f"auth_method must be one of {sorted(AUTH_METHODS)}")
    return am


def _clean_key_path(body: dict) -> Optional[str]:
    """Validate an optional key_path (for key_file auth). Relative, no traversal;
    the absolute confinement to the keys dir is re-checked at exec time."""
    kp = body.get("key_path")
    if kp is None:
        return None
    if not isinstance(kp, str) or not kp.strip():
        raise HTTPException(status_code=400, detail="key_path must be a non-empty string")
    kp = kp.strip()
    if kp.startswith("/") or ".." in kp.split("/") or "\x00" in kp:
        raise HTTPException(status_code=400, detail="key_path must be a relative path with no traversal")
    return kp


async def _fetch_owned(conn, user_id: int, host_id: int):
    row = await conn.fetchrow(
        f"SELECT {_FULL_COLUMNS} FROM user_ssh_hosts WHERE id=$1 AND user_id=$2",
        host_id, user_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="SSH host profile not found")
    return row


# ─── Endpoints ─────────────────────────────────────────────────────────────────


@ssh_router.get("/hosts")
async def list_ssh_hosts(request: Request, user=Depends(get_current_user_optimized)):
    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_FULL_COLUMNS} FROM user_ssh_hosts WHERE user_id=$1 "
            "ORDER BY updated_at DESC",
            _uid(user),
        )
    return {"hosts": [_row_public(r) for r in rows]}


@ssh_router.post("/hosts", status_code=201)
async def create_ssh_host(request: Request, user=Depends(get_current_user_optimized)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")

    name = body.get("name")
    host = body.get("host")
    port = body.get("port", 22)
    username = body.get("username")
    auth_type = body.get("auth_type", "key")
    _validate_profile_fields(name=name, host=host, port=port, username=username, auth_type=auth_type)
    auth_method = _clean_auth_method(body, default="agent")
    key_path = _clean_key_path(body)

    credential = _clean_credential(body)
    enc = _encrypt_credential(credential) if credential else None

    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO user_ssh_hosts "
                "(user_id, name, host, port, username, auth_type, credential_encrypted, auth_method, key_path) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
                f"RETURNING {_FULL_COLUMNS}",
                _uid(user), name.strip(), host, int(port), username, auth_type, enc, auth_method, key_path,
            )
    except Exception as exc:
        if exc.__class__.__name__ == "UniqueViolationError":
            raise HTTPException(status_code=409, detail="a profile with this name already exists")
        raise
    return _row_public(row)


@ssh_router.get("/hosts/{host_id}")
async def get_ssh_host(host_id: int, request: Request, user=Depends(get_current_user_optimized)):
    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    async with pool.acquire() as conn:
        row = await _fetch_owned(conn, _uid(user), host_id)
    return _row_public(row)


@ssh_router.put("/hosts/{host_id}")
async def update_ssh_host(host_id: int, request: Request, user=Depends(get_current_user_optimized)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")

    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    uid = _uid(user)
    async with pool.acquire() as conn:
        row = await _fetch_owned(conn, uid, host_id)

        # Merge: absent field → keep current value; present → validate + replace.
        name = body.get("name", row["name"])
        host = body.get("host", row["host"])
        port = body.get("port", row["port"])
        username = body.get("username", row["username"])
        auth_type = body.get("auth_type", row["auth_type"])
        _validate_profile_fields(name=name, host=host, port=port, username=username, auth_type=auth_type)
        auth_method = _clean_auth_method(body, default=row["auth_method"] or "agent")
        key_path = _clean_key_path(body) if "key_path" in body else row["key_path"]

        # Credential is write-only: present+non-empty → re-encrypt & replace;
        # clear_credential=true → null it out; absent → unchanged.
        enc = row["credential_encrypted"]
        credential = _clean_credential(body)
        if credential is not None:
            enc = _encrypt_credential(credential)
        elif body.get("clear_credential") is True:
            enc = None

        # Any change to how we CONNECT (host/port/user/auth) invalidates a prior
        # host-key trust — force a fresh /test + /trust before exec can run again.
        connection_changed = (
            host != row["host"] or int(port) != int(row["port"]) or username != row["username"]
        )
        fp_reset_sql = ", host_key_fingerprint=NULL, known_hosts_line=NULL" if connection_changed else ""

        try:
            updated = await conn.fetchrow(
                "UPDATE user_ssh_hosts SET name=$3, host=$4, port=$5, username=$6, "
                "auth_type=$7, credential_encrypted=$8, auth_method=$9, key_path=$10, "
                f"updated_at=NOW(){fp_reset_sql} "
                "WHERE id=$1 AND user_id=$2 "
                f"RETURNING {_FULL_COLUMNS}",
                host_id, uid, name.strip(), host, int(port), username, auth_type, enc, auth_method, key_path,
            )
        except Exception as exc:
            if exc.__class__.__name__ == "UniqueViolationError":
                raise HTTPException(status_code=409, detail="a profile with this name already exists")
            raise
    return _row_public(updated)


@ssh_router.delete("/hosts/{host_id}")
async def delete_ssh_host(host_id: int, request: Request, user=Depends(get_current_user_optimized)):
    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_ssh_hosts WHERE id=$1 AND user_id=$2", host_id, _uid(user)
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="SSH host profile not found")
    return {"ok": True, "deleted": host_id}


# ─── Trace-run scoping + emit + audit (Phase 4 governance) ─────────────────────
# SSH probe/exec trace events need a workspace_runs home so the FK-backed
# workspace_events inserts succeed and the frontend can stream them via
# /api/harvis/runs/{id}/stream. We upsert ONE deterministic per-user-per-host
# run whose id embeds the caller's uid (no cross-user collision, mirrors
# harvis_exec._resolve_scoped_workspace).


def _ssh_run_id(user_id: int, host_id: int) -> str:
    return f"ssh-u{int(user_id)}-h{int(host_id)}"


async def _ensure_ssh_run(pool, user_id: int, host_id: int, host: str) -> str:
    run_id = _ssh_run_id(user_id, host_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workspace_runs (id, user_id, session_id, task_brief, status)
            VALUES ($1, $2, $1, $3, 'ssh')
            ON CONFLICT (id) DO NOTHING
            """,
            run_id, int(user_id), f"SSH target {host}",
        )
    return run_id


async def _emit(pool, run_id: str, event_type: str, payload: dict) -> None:
    from workspace.terminal_container import emit_terminal_event

    await emit_terminal_event(pool, run_id, event_type=event_type, payload=payload)


async def _audit_ssh(
    pool, *, session_key: str, tool: str, input_obj: dict,
    status_code: int, output_meta: Optional[dict] = None, error: Optional[str] = None,
) -> None:
    """Mirror tools.openclaw_proxy._audit — write one openclaw_tool_audit row.
    Never breaks the call on logging failure."""
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO openclaw_tool_audit(session_key, tool, input, output_meta, status_code, error) "
                "VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)",
                session_key, tool, json.dumps(input_obj), json.dumps(output_meta or {}),
                status_code, error,
            )
    except Exception:
        return


# ─── Governed probe / trust / exec ─────────────────────────────────────────────


@ssh_router.post("/hosts/{host_id}/test")
async def test_ssh_host(host_id: int, request: Request, user=Depends(get_current_user_optimized)):
    """PROBE (TOFU step 1): ssh-keyscan the host, compute SHA256 fingerprints,
    and present them as UNTRUSTED. Registers a pending approval + emits an
    approval_request trace event. Nothing is persisted/trusted here — the user
    must eyeball the fingerprint and confirm via POST /hosts/{id}/trust."""
    from remote import ssh_exec
    from workspace.orchestration.risk import register_pending

    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    uid = _uid(user)
    async with pool.acquire() as conn:
        row = await _fetch_owned(conn, uid, host_id)

    try:
        known_hosts_line, fingerprints = await ssh_exec.keyscan(row["host"], int(row["port"]))
    except PermissionError as exc:
        # SSRF guard: loopback / link-local (incl. cloud metadata) targets are refused.
        raise HTTPException(status_code=400, detail=str(exc))
    except TimeoutError:
        raise HTTPException(status_code=504, detail="ssh-keyscan timed out — host unreachable?")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ssh-keyscan not installed in this image")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ssh-keyscan failed: {exc}")

    if not fingerprints:
        raise HTTPException(
            status_code=502,
            detail="no host key returned (host unreachable, or not running ssh on this port)",
        )

    run_id = await _ensure_ssh_run(pool, uid, host_id, row["host"])
    # action_id MUST be prefixed with "<run_id>-" so risk.get_pending_for_run(run_id)
    # (which matches aid.startswith(f"{run_id}-")) can find it on the /trust call.
    action_id = f"{run_id}-probe-{uuid.uuid4().hex}"
    register_pending(action_id, {
        "tool": "ssh.probe",
        "host_id": host_id,
        "host": row["host"],
        "port": int(row["port"]),
        "fingerprints": fingerprints,
        "known_hosts_line": known_hosts_line,
    })
    await _emit(pool, run_id, "approval_request", {
        "action_id": action_id,
        "tool": "ssh.probe",
        "host": row["host"],
        "port": int(row["port"]),
        "fingerprints": fingerprints,
        "reason": "First connection — verify the host key fingerprint before trusting.",
        "run_id": run_id,
    })
    await _audit_ssh(
        pool, session_key=run_id, tool="ssh.probe",
        input_obj={"host": row["host"], "port": int(row["port"])},
        status_code=200, output_meta={"fingerprints": fingerprints, "action_id": action_id},
    )
    return {
        "status": "pending_fingerprint",
        "action_id": action_id,
        "run_id": run_id,
        "fingerprints": fingerprints,
    }


@ssh_router.post("/hosts/{host_id}/trust")
async def trust_ssh_host(host_id: int, request: Request, user=Depends(get_current_user_optimized)):
    """TOFU step 2: resolve the pending probe. On approve, pin the scanned
    known_hosts line into the per-user known_hosts file AND store the
    fingerprint + line on the row (now exec-eligible). On deny, store nothing."""
    from workspace.orchestration.risk import get_pending_for_run, resolve_action
    from remote import ssh_exec

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    action_id = body.get("action_id")
    approved = body.get("approved")
    if not isinstance(action_id, str) or not action_id:
        raise HTTPException(status_code=400, detail="action_id is required")
    if not isinstance(approved, bool):
        raise HTTPException(status_code=400, detail="approved must be a boolean")

    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    uid = _uid(user)
    async with pool.acquire() as conn:
        row = await _fetch_owned(conn, uid, host_id)  # ownership gate + 404

    run_id = _ssh_run_id(uid, host_id)
    # Defense in depth: the action_id is namespaced by the per-user-per-host run
    # id, so it can only be resolved by its owner against its own host.
    if not action_id.startswith(f"{run_id}-"):
        raise HTTPException(status_code=400, detail="action_id does not belong to this host")
    pending = get_pending_for_run(run_id)
    if not pending or pending.get("action_id") != action_id:
        raise HTTPException(status_code=404, detail="no matching pending fingerprint approval")

    known_hosts_line = pending.get("known_hosts_line") or ""
    fingerprints = pending.get("fingerprints") or []
    primary_fp = fingerprints[0] if fingerprints else None

    # Validate an approval has a scanned key BEFORE consuming the pending action, so a
    # malformed pending can be retried rather than silently discarded on resolve.
    if approved and (not known_hosts_line or not primary_fp):
        raise HTTPException(status_code=409, detail="pending approval has no scanned key to trust")

    resolve_action(action_id, approved)

    if not approved:
        await _emit(pool, run_id, "decision", {
            "tool": "ssh.probe", "lane": 5, "policy": "deny",
            "reason": "host key fingerprint rejected by user", "source": "fingerprint_trust",
            "run_id": run_id,
        })
        await _audit_ssh(
            pool, session_key=run_id, tool="ssh.trust",
            input_obj={"host": row["host"], "approved": False},
            status_code=200, output_meta={"trusted": False},
        )
        return {"ok": True, "trusted": False}

    # Pin into the per-user known_hosts file + persist on the row (presence validated above).
    ssh_exec.append_known_hosts(uid, known_hosts_line)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_ssh_hosts SET host_key_fingerprint=$3, known_hosts_line=$4, updated_at=NOW() "
            "WHERE id=$1 AND user_id=$2",
            host_id, uid, primary_fp, known_hosts_line,
        )
    await _emit(pool, run_id, "decision", {
        "tool": "ssh.probe", "lane": 5, "policy": "allow",
        "reason": "host key trusted (fingerprint pinned)", "source": "fingerprint_trust",
        "fingerprint": primary_fp, "run_id": run_id,
    })
    await _audit_ssh(
        pool, session_key=run_id, tool="ssh.trust",
        input_obj={"host": row["host"], "approved": True},
        status_code=200, output_meta={"trusted": True, "fingerprint": primary_fp},
    )
    return {"ok": True, "trusted": True, "fingerprint": primary_fp}


@ssh_router.post("/hosts/{host_id}/exec")
async def exec_ssh_host(host_id: int, request: Request, user=Depends(get_current_user_optimized)):
    """Run one command on a TRUSTED host over ssh (lane 5, governed).

    Preconditions: HARVIS_SSH_ENABLED on (router-level 403 otherwise) AND the
    host's fingerprint pinned (409 otherwise). Routes through authorize_action
    (lane 5) and lands the full decision → tool_call → terminal_output →
    tool_result trace + an openclaw_tool_audit row."""
    from workspace.orchestration.authz import authorize_action
    from owui_compat.workspace_method import LANE_EXTERNAL_SERVICES
    from remote import ssh_exec

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    command = body.get("command")
    if not isinstance(command, str) or not command.strip():
        raise HTTPException(status_code=400, detail="command must be a non-empty string")
    timeout = body.get("timeout_s", 60)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = 60
    timeout = max(1, min(600, timeout))

    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    uid = _uid(user)
    async with pool.acquire() as conn:
        row = await _fetch_owned(conn, uid, host_id)

    if not row["host_key_fingerprint"]:
        raise HTTPException(
            status_code=409,
            detail="host not trusted yet, run /test then /trust",
        )

    run_id = await _ensure_ssh_run(pool, uid, host_id, row["host"])

    # Phase 2 choke point (lane 5). With the flag off this denies (the same gate
    # the router-level 403 enforces) — belt-and-suspenders + a traced decision.
    async def _emit_decision(payload: dict) -> None:
        await _emit(pool, run_id, "decision", {**payload, "run_id": run_id})

    res = await authorize_action(
        tool_name="ssh.exec",
        args={"command": command, "host": row["host"]},
        lane=LANE_EXTERNAL_SERVICES,
        permission_mode=None,
        run_id=run_id,
        emit=_emit_decision,
    )
    if not res.allowed:
        await _audit_ssh(
            pool, session_key=run_id, tool="ssh.exec",
            input_obj={"host": row["host"], "command": command},
            status_code=403, error=res.reason or "denied by execution policy",
        )
        raise HTTPException(status_code=403, detail=res.reason or "denied by execution policy")

    # Resolve an optional jump host (must be another profile OWNED by the caller).
    profile = dict(row)
    if row["jump_host_id"]:
        async with pool.acquire() as conn:
            jrow = await conn.fetchrow(
                f"SELECT {_FULL_COLUMNS} FROM user_ssh_hosts WHERE id=$1 AND user_id=$2",
                int(row["jump_host_id"]), uid,
            )
        if jrow is None:
            raise HTTPException(status_code=409, detail="configured jump host not found or not owned")
        profile["jump"] = {
            "username": jrow["username"], "host": jrow["host"], "port": int(jrow["port"]),
        }

    preview = command.strip().splitlines()[0][:120] if command.strip() else ""
    await _emit(pool, run_id, "tool_call", {
        "tool": "ssh.exec",
        "args": {"command": command, "host": row["host"], "preview": preview},
        "target": {"kind": "ssh", "id": host_id},
        "run_id": run_id,
    })

    try:
        result = await ssh_exec.run_ssh(profile, command, user_id=uid, timeout=timeout)
    except Exception as exc:  # unexpected — argv build / spawn failure
        logger.error("[ssh-exec:%s] run_ssh failed: %s", run_id, exc)
        await _audit_ssh(
            pool, session_key=run_id, tool="ssh.exec",
            input_obj={"host": row["host"], "command": command},
            status_code=502, error=str(exc),
        )
        raise HTTPException(status_code=502, detail=f"ssh exec failed: {exc}")

    for stream in ("stdout", "stderr"):
        text = result.get(stream) or ""
        if text:
            await _emit(pool, run_id, "terminal_output", {
                "tool": "ssh.exec",
                "stream": stream,
                "text": text,
                "target": {"kind": "ssh", "id": host_id},
                "run_id": run_id,
            })

    exit_code = int(result.get("exit_code", -1))
    await _emit(pool, run_id, "tool_result", {
        "tool": "ssh.exec",
        "success": exit_code == 0,
        "summary": f"exit={exit_code} out={len(result.get('stdout') or '')}B err={len(result.get('stderr') or '')}B",
        "args": {"command": command, "host": row["host"]},
        "target": {"kind": "ssh", "id": host_id},
        "output": {
            "exit_code": exit_code,
            "truncated": bool(result.get("truncated", False)),
            "stdout_preview": (result.get("stdout") or "")[:400],
            "stderr_preview": (result.get("stderr") or "")[:400],
        },
        "run_id": run_id,
    })
    await _audit_ssh(
        pool, session_key=run_id, tool="ssh.exec",
        input_obj={"host": row["host"], "port": int(row["port"]), "command": command},
        status_code=200,
        output_meta={
            "exit_code": exit_code,
            "truncated": bool(result.get("truncated", False)),
            "stdout_bytes": len(result.get("stdout") or ""),
            "stderr_bytes": len(result.get("stderr") or ""),
        },
    )
    return {
        "exit_code": exit_code,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "truncated": bool(result.get("truncated", False)),
    }
