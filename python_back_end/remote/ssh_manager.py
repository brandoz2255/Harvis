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

import logging
import os
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

_schema_ready = False


async def ensure_ssh_schema(pool) -> None:
    """Idempotently create user_ssh_hosts. Called lazily from the endpoints
    (memoized per process) so main.py's lifespan needs no edit."""
    global _schema_ready
    if _schema_ready or pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(USER_SSH_HOSTS_SCHEMA_SQL)
    _schema_ready = True
    logger.info("user_ssh_hosts schema ensured")


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
    """Safe wire shape: NEVER includes the credential (only has_credential)."""
    return {
        "id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "auth_type": row["auth_type"],
        "has_credential": bool(row["credential_encrypted"]),
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


async def _fetch_owned(conn, user_id: int, host_id: int):
    row = await conn.fetchrow(
        "SELECT id, name, host, port, username, auth_type, credential_encrypted, "
        "created_at, updated_at FROM user_ssh_hosts WHERE id=$1 AND user_id=$2",
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
            "SELECT id, name, host, port, username, auth_type, credential_encrypted, "
            "created_at, updated_at FROM user_ssh_hosts WHERE user_id=$1 "
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

    credential = _clean_credential(body)
    enc = _encrypt_credential(credential) if credential else None

    pool = _pool_or_503(request)
    await ensure_ssh_schema(pool)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO user_ssh_hosts (user_id, name, host, port, username, auth_type, credential_encrypted) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) "
                "RETURNING id, name, host, port, username, auth_type, credential_encrypted, created_at, updated_at",
                _uid(user), name.strip(), host, int(port), username, auth_type, enc,
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

        # Credential is write-only: present+non-empty → re-encrypt & replace;
        # clear_credential=true → null it out; absent → unchanged.
        enc = row["credential_encrypted"]
        credential = _clean_credential(body)
        if credential is not None:
            enc = _encrypt_credential(credential)
        elif body.get("clear_credential") is True:
            enc = None

        try:
            updated = await conn.fetchrow(
                "UPDATE user_ssh_hosts SET name=$3, host=$4, port=$5, username=$6, "
                "auth_type=$7, credential_encrypted=$8, updated_at=NOW() "
                "WHERE id=$1 AND user_id=$2 "
                "RETURNING id, name, host, port, username, auth_type, credential_encrypted, created_at, updated_at",
                host_id, uid, name.strip(), host, int(port), username, auth_type, enc,
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


@ssh_router.post("/hosts/{host_id}/test")
async def test_ssh_host(host_id: int, request: Request, user=Depends(get_current_user_optimized)):
    """Connect/test STUB — intentionally does NOTHING, even with the flag on.

    The scaffold ships with zero SSH I/O (no paramiko/asyncssh anywhere in the
    codebase). Returning 501 unconditionally — before any DB lookup — also
    avoids becoming an existence oracle for other users' profile ids. A real
    implementation lands only after explicit user approval of the security
    review (dependency choice, host-key verification, egress policy)."""
    raise HTTPException(status_code=501, detail=SSH_CONNECT_STUB_DETAIL)
