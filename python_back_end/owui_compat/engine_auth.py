"""Per-user credentials for external cloud code engines (Phase E2).

Codex (GPT) and Claude Code run on hosted vendor models through the USER's OWN API
key — the operator pays nothing. Keys are stored encrypted (reusing main.encrypt_api_key,
the same Fernet pattern as OpenClaw BYO + GitHub) and are **write-only** at the
frontend: the GET endpoint returns only `{api_key_saved, verified_at, last_error}`,
never the key. The decrypted key is read ONLY at run time (`get_verified_engine_key`)
and injected into the sidecar per-exec — never logged, never returned.

Endpoints (registered in owui_compat/router.py):
  GET    /api/owui/engine-auth/{engine}           — status (no key)
  POST   /api/owui/engine-auth/{engine}           — save key (encrypt, write-only)
  POST   /api/owui/engine-auth/{engine}/verify    — verify key against the vendor, set verified_at
  POST   /api/owui/engine-auth/{engine}/disconnect — delete the row

`{engine}` ∈ {codex, claude-code}. `codex` covers the Codex GPT engine; `claude-code`
covers Claude Code. (OpenCode is local + needs no key, so it has no auth row.)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

# Auth-bearing engines (NOT opencode — it's local, no key). Maps the auth-row engine id
# to the vendor verify contract.
AUTH_ENGINES = {"codex", "claude-code"}

# Per-user auth modes. Phase E4B: Claude Code supports BOTH an Anthropic API key
# (ANTHROPIC_API_KEY) AND a Claude subscription OAuth token (CLAUDE_CODE_OAUTH_TOKEN, from
# `claude setup-token` — Pro/Max/Team/Enterprise). The user picks ONE; we store the mode so
# the runtime injects the right env var (never both — ANTHROPIC_API_KEY officially wins).
AUTH_MODES = {"api_key", "oauth_token"}
# Only Claude Code has a subscription/OAuth mode; Codex is API-key-only.
OAUTH_ENGINES = {"claude-code"}
_CLAUDE_CODE_CONTAINER = os.getenv("HARVIS_CLAUDE_CODE_CONTAINER", "harvis-claude-code")


async def _engine_auth_row(pool, user_id: int, engine: str):
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT api_key_encrypted, auth_mode, verified_at, last_error FROM user_engine_auth "
                "WHERE user_id=$1 AND engine=$2",
                user_id, engine,
            )
    except Exception:
        return None


async def user_has_verified_engine(pool, user_id: int, engine: str) -> bool:
    """True iff the user has a verified key for this engine (used by the readiness probe)."""
    row = await _engine_auth_row(pool, user_id, engine)
    return bool(row and row["verified_at"] is not None and row["api_key_encrypted"])


async def get_verified_engine_key(pool, user_id: int, engine: str) -> Optional[str]:
    """Decrypt the user's verified credential AT RUN TIME (for per-exec injection). None if
    absent or unverified. NEVER log the return value."""
    auth = await get_verified_engine_auth(pool, user_id, engine)
    return auth[0] if auth else None


async def get_verified_engine_auth(pool, user_id: int, engine: str) -> Optional[tuple[str, str]]:
    """Decrypt the verified credential AND return its auth_mode → ``(secret, auth_mode)``.
    Phase E4B: the caller injects ANTHROPIC_API_KEY for ``api_key`` mode or
    CLAUDE_CODE_OAUTH_TOKEN for ``oauth_token`` mode — never both. None if absent/unverified.
    NEVER log the secret."""
    row = await _engine_auth_row(pool, user_id, engine)
    if not row or row["verified_at"] is None or not row["api_key_encrypted"]:
        return None
    try:
        from main import decrypt_api_key
        secret = decrypt_api_key(row["api_key_encrypted"])
        if not secret:
            return None
        mode = (row["auth_mode"] or "api_key") if "auth_mode" in row else "api_key"
        return secret, mode
    except Exception:
        return None


async def get_verified_auth_mode(pool, user_id: int, engine: str) -> Optional[str]:
    """Return the auth_mode ('api_key' | 'oauth_token') of a user's VERIFIED credential for an
    engine, or None if absent/unverified — WITHOUT decrypting the secret. Used by the cloud-chat
    model list to decide which catalog to surface without touching the encrypted key."""
    row = await _engine_auth_row(pool, user_id, engine)
    if not row or row["verified_at"] is None or not row["api_key_encrypted"]:
        return None
    return (row["auth_mode"] or "api_key") if "auth_mode" in row else "api_key"


async def _verify_oauth_token_via_cli(token: str) -> tuple[bool, str]:
    """Verify a Claude SUBSCRIPTION OAuth token by running the real Claude Code CLI in the
    sidecar with CLAUDE_CODE_OAUTH_TOKEN injected — the EXACT runtime path. A clean exit
    proves the token authenticates. We do NOT hit the Anthropic Messages API: a subscription
    token is for Claude Code, not normal API requests. NEVER use ``--bare`` (it ignores
    CLAUDE_CODE_OAUTH_TOKEN). The token is passed to ``docker exec -e`` only and never logged."""
    argv = [
        "docker", "exec",
        "-e", f"CLAUDE_CODE_OAUTH_TOKEN={token}",
        # The sidecar bakes CLAUDE_CODE_SIMPLE=1 (simple/bare mode) which IGNORES the OAuth
        # token and reads only ANTHROPIC_API_KEY — disable it so the token is actually used.
        "-e", "CLAUDE_CODE_SIMPLE=",
        "-u", "1001", "-w", "/tmp",
        _CLAUDE_CODE_CONTAINER,
        "claude", "-p", "Reply OK", "--output-format", "text", "--dangerously-skip-permissions",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=75)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return False, "Subscription token verification timed out."
        if proc.returncode == 0:
            return True, ""
        # Surface a short, token-free reason. The CLI prints auth errors ("Not logged in",
        # "401 Invalid bearer token") to STDOUT, so include both streams.
        combined = ((out or b"") + b"\n" + (err or b"")).decode("utf-8", "replace").strip()
        detail = combined[:200] or f"exit {proc.returncode}"
        return False, f"Claude Code rejected the subscription token: {detail}"
    except FileNotFoundError:
        return False, "Verification unavailable (docker CLI missing in backend)."
    except Exception as exc:
        return False, f"Verification request failed: {type(exc).__name__}"


async def _verify_credential(engine: str, secret: str, auth_mode: str) -> tuple[bool, str]:
    """Cheap real auth check against the vendor. Returns (ok, error_message). Branches on
    auth_mode: API key → vendor HTTP check; Claude subscription OAuth token → CLI smoke."""
    if engine == "claude-code" and auth_mode == "oauth_token":
        return await _verify_oauth_token_via_cli(secret)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if engine == "codex":
                # No token spend — just list models.
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {secret}"},
                )
                if r.status_code == 200:
                    return True, ""
                return False, f"OpenAI rejected the key (HTTP {r.status_code})."
            elif engine == "claude-code":
                # API-key mode: minimal Messages call, max_tokens:1.
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": secret,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-3-5-haiku-20241022",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                if r.status_code == 200:
                    return True, ""
                return False, f"Anthropic rejected the key (HTTP {r.status_code})."
    except Exception as exc:
        return False, f"Verification request failed: {type(exc).__name__}"
    return False, "Unknown engine."


def register_engine_auth_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _check_engine(engine: str):
        if engine not in AUTH_ENGINES:
            raise HTTPException(status_code=400, detail="unknown auth engine")

    @router.get("/api/owui/engine-auth/{engine}")
    async def engine_auth_status(engine: str, request: Request, user=Depends(get_current_user)):
        _check_engine(engine)
        pool = getattr(request.app.state, "pg_pool", None)
        row = await _engine_auth_row(pool, int(user.id), engine)
        return {
            "engine": engine,
            "api_key_saved": bool(row and row["api_key_encrypted"]),
            "auth_mode": (row["auth_mode"] if row and row["auth_mode"] else "api_key"),
            "supports_oauth": engine in OAUTH_ENGINES,  # Claude Code → subscription token mode
            "verified_at": row["verified_at"].isoformat() if row and row["verified_at"] else None,
            "last_error": (row["last_error"] if row else None),
        }

    @router.post("/api/owui/engine-auth/{engine}")
    async def engine_auth_save(engine: str, request: Request, user=Depends(get_current_user)):
        _check_engine(engine)
        try:
            body = await request.json()
        except Exception:
            body = {}
        # Accept the secret under `credential` (E4B) or `api_key` (back-compat) — for the
        # oauth_token mode it's a Claude subscription token, not an API key.
        key = (body or {}).get("credential") or (body or {}).get("api_key")
        if not isinstance(key, str) or not key.strip():
            raise HTTPException(status_code=400, detail="credential is required")
        key = key.strip()
        auth_mode = ((body or {}).get("auth_mode") or "api_key").strip()
        if auth_mode not in AUTH_MODES:
            raise HTTPException(status_code=400, detail="invalid auth_mode")
        if auth_mode == "oauth_token" and engine not in OAUTH_ENGINES:
            raise HTTPException(status_code=400, detail=f"{engine} does not support subscription-token auth")
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        from main import encrypt_api_key
        enc = encrypt_api_key(key)
        # Save resets verified_at (must re-verify after a credential/mode change).
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_engine_auth (user_id, engine, api_key_encrypted, auth_mode, verified_at, last_error, updated_at) "
                "VALUES ($1, $2, $3, $4, NULL, NULL, NOW()) "
                "ON CONFLICT (user_id, engine) DO UPDATE SET api_key_encrypted=EXCLUDED.api_key_encrypted, "
                "auth_mode=EXCLUDED.auth_mode, verified_at=NULL, last_error=NULL, updated_at=NOW()",
                int(user.id), engine, enc, auth_mode,
            )
        return {"engine": engine, "api_key_saved": True, "auth_mode": auth_mode, "verified_at": None}

    @router.post("/api/owui/engine-auth/{engine}/verify")
    async def engine_auth_verify(engine: str, request: Request, user=Depends(get_current_user)):
        _check_engine(engine)
        try:
            body = await request.json()
        except Exception:
            body = {}
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        uid = int(user.id)
        row = await _engine_auth_row(pool, uid, engine)
        # Auth mode: request wins, else the stored row, else api_key.
        auth_mode = ((body or {}).get("auth_mode")
                     or (row["auth_mode"] if row and row["auth_mode"] else "api_key")).strip()
        if auth_mode not in AUTH_MODES:
            raise HTTPException(status_code=400, detail="invalid auth_mode")
        if auth_mode == "oauth_token" and engine not in OAUTH_ENGINES:
            raise HTTPException(status_code=400, detail=f"{engine} does not support subscription-token auth")
        # Secret from the request (`credential`/`api_key`), else the stored one.
        secret = (body or {}).get("credential") or (body or {}).get("api_key")
        if isinstance(secret, str) and secret.strip():
            secret = secret.strip()
        else:
            secret = None
            if row and row["api_key_encrypted"]:
                try:
                    from main import decrypt_api_key
                    secret = decrypt_api_key(row["api_key_encrypted"]) or None
                except Exception:
                    secret = None
        if not secret:
            raise HTTPException(status_code=400, detail="No credential to verify — save one first")

        ok, err = await _verify_credential(engine, secret, auth_mode)
        from main import encrypt_api_key
        enc = encrypt_api_key(secret)
        async with pool.acquire() as conn:
            if ok:
                await conn.execute(
                    "INSERT INTO user_engine_auth (user_id, engine, api_key_encrypted, auth_mode, verified_at, last_error, updated_at) "
                    "VALUES ($1, $2, $3, $4, NOW(), NULL, NOW()) "
                    "ON CONFLICT (user_id, engine) DO UPDATE SET api_key_encrypted=EXCLUDED.api_key_encrypted, "
                    "auth_mode=EXCLUDED.auth_mode, verified_at=NOW(), last_error=NULL, updated_at=NOW()",
                    uid, engine, enc, auth_mode,
                )
            else:
                await conn.execute(
                    "INSERT INTO user_engine_auth (user_id, engine, api_key_encrypted, auth_mode, verified_at, last_error, updated_at) "
                    "VALUES ($1, $2, $3, $4, NULL, $5, NOW()) "
                    "ON CONFLICT (user_id, engine) DO UPDATE SET api_key_encrypted=EXCLUDED.api_key_encrypted, "
                    "auth_mode=EXCLUDED.auth_mode, verified_at=NULL, last_error=$5, updated_at=NOW()",
                    uid, engine, enc, auth_mode, err[:300],
                )
        return {"engine": engine, "ok": ok, "auth_mode": auth_mode, "error": (None if ok else err), "verified_at": (int(time.time()) if ok else None)}

    @router.post("/api/owui/engine-auth/{engine}/disconnect")
    async def engine_auth_disconnect(engine: str, request: Request, user=Depends(get_current_user)):
        _check_engine(engine)
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM user_engine_auth WHERE user_id=$1 AND engine=$2", int(user.id), engine
            )
        return {"engine": engine, "ok": True}
