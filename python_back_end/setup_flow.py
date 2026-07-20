"""First-run setup probes and completion — honest ticks for the /setup wizard.

Every tick returns ``{ready, reason, probe}`` — never a bare boolean.
Admin JWT required after the instance is claimed (``require_admin``).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(5.0)
_MODEL_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def _tick(ready: bool, reason: str, probe: str) -> dict[str, Any]:
    return {"ready": bool(ready), "reason": reason or "", "probe": probe}


def _artifact_dir() -> Path:
    return Path(os.getenv("ARTIFACT_STORAGE_DIR", "/data/artifacts"))


async def _probe_database(request: Request) -> dict[str, Any]:
    probe = "SELECT 1 via app.state.pg_pool"
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return _tick(False, "no connection pool", probe)
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return _tick(True, "ok", probe)
    except Exception as exc:
        return _tick(False, str(exc)[:200], probe)


async def _probe_ollama() -> dict[str, Any]:
    probe = "GET {OLLAMA_URL}/api/tags"
    url = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as hc:
            r = await hc.get(f"{url}/api/tags")
        if r.status_code != 200:
            return _tick(False, f"HTTP {r.status_code}", probe)
        models = (r.json() or {}).get("models") or []
        n = len(models)
        if n == 0:
            return _tick(False, "reachable but zero models installed", probe)
        return _tick(True, f"{n} model(s)", probe)
    except Exception as exc:
        return _tick(False, str(exc)[:200], probe)


async def _probe_openclaw() -> dict[str, Any]:
    probe = "GET openclaw /health"
    base = os.getenv("OPENCLAW_URL", "ws://openclaw:18789")
    base = base.replace("wss://", "https://").replace("ws://", "http://").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as hc:
            r = await hc.get(f"{base}/health")
        if r.status_code < 400:
            return _tick(True, f"HTTP {r.status_code}", probe)
        return _tick(False, f"HTTP {r.status_code}", probe)
    except Exception as exc:
        return _tick(False, str(exc)[:200], probe)


async def _probe_tts() -> dict[str, Any]:
    probe = "GET {TTS_SERVICE_URL}/health"
    base = os.getenv("TTS_SERVICE_URL", "http://tts-service:8001").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as hc:
            r = await hc.get(f"{base}/health")
        if r.status_code < 400:
            return _tick(True, f"HTTP {r.status_code}", probe)
        return _tick(False, f"HTTP {r.status_code}", probe)
    except Exception as exc:
        return _tick(False, str(exc)[:200], probe)


def _probe_artifacts() -> dict[str, Any]:
    probe = "write+read+unlink sentinel in ARTIFACT_STORAGE_DIR"
    root = _artifact_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix=".harvis-setup-", dir=str(root))
        os.close(fd)
        p = Path(path)
        p.write_text("ok", encoding="utf-8")
        data = p.read_text(encoding="utf-8")
        p.unlink(missing_ok=True)
        if data != "ok":
            return _tick(False, "readback mismatch", probe)
        return _tick(True, f"writable ({root})", probe)
    except Exception as exc:
        return _tick(False, str(exc)[:200], probe)


class TestModelBody(BaseModel):
    model: str = Field(..., min_length=1)


class PreferencesBody(BaseModel):
    cookie_secure: bool | None = None
    enable_signup: bool | None = None


class CompleteBody(BaseModel):
    note: str | None = None


def create_setup_router(
    *,
    get_current_user: Callable,
    require_admin: Callable,
) -> APIRouter:
    router = APIRouter(tags=["setup"])

    @router.get("/api/setup/status")
    async def setup_status(request: Request):
        """Unauthenticated: needs first admin? setup wizard finished?"""
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        try:
            async with pool.acquire() as conn:
                user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
                complete = await conn.fetchval(
                    "SELECT value FROM instance_settings WHERE key = 'setup_complete'"
                )
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail=f"database unavailable: {str(exc)[:200]}"
            )
        return {
            "needs_setup": int(user_count or 0) == 0,
            "setup_complete": (complete or "").strip().lower() in {"1", "true", "yes"},
        }

    @router.get("/api/setup/verify")
    async def setup_verify(
        request: Request,
        _user=Depends(require_admin),
    ):
        """Aggregate honest readiness ticks for the setup wizard."""
        db = await _probe_database(request)
        ollama = await _probe_ollama()
        openclaw = await _probe_openclaw()
        tts = await _probe_tts()
        artifacts = _probe_artifacts()
        ticks = {
            "database": db,
            "ollama": ollama,
            "openclaw": openclaw,
            "tts": tts,
            "artifacts": artifacts,
        }
        overall = all(t["ready"] for t in ticks.values())
        return {"overall": overall, "ticks": ticks}

    @router.post("/api/setup/test-model")
    async def setup_test_model(
        body: TestModelBody,
        _user=Depends(require_admin),
    ):
        """Direct Ollama /api/chat with a tiny predict — proves the model loads."""
        probe = "POST {OLLAMA_URL}/api/chat options.num_predict=8"
        url = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        payload = {
            "model": body.model,
            "stream": False,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "options": {"num_predict": 8},
        }
        try:
            async with httpx.AsyncClient(timeout=_MODEL_TIMEOUT) as hc:
                r = await hc.post(f"{url}/api/chat", json=payload)
            if r.status_code >= 400:
                # Surface Ollama's body — never invent success.
                detail = (r.text or "")[:500]
                return {
                    "ready": False,
                    "reason": detail or f"HTTP {r.status_code}",
                    "probe": probe,
                    "text": "",
                }
            data = r.json() or {}
            text = ""
            msg = data.get("message") or {}
            if isinstance(msg, dict):
                text = str(msg.get("content") or "").strip()
            if not text:
                text = str(data.get("response") or "").strip()
            if not text:
                return {
                    "ready": False,
                    "reason": "empty generation",
                    "probe": probe,
                    "text": "",
                }
            return {"ready": True, "reason": "ok", "probe": probe, "text": text[:500]}
        except Exception as exc:
            return {
                "ready": False,
                "reason": str(exc)[:500],
                "probe": probe,
                "text": "",
            }

    @router.post("/api/setup/preferences")
    async def setup_preferences(
        request: Request,
        body: PreferencesBody,
        _user=Depends(require_admin),
    ):
        """Persist wizard choices that survive without editing .env by hand.

        ``cookie_secure`` is honored by the auth cookie setters when the env var
        is unset. ``enable_signup`` is stored for display; live enforcement still
        uses HARVIS_OWUI_ENABLE_SIGNUP (documented in the wizard copy).
        """
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        updates: dict[str, str] = {}
        if body.cookie_secure is not None:
            updates["cookie_secure"] = "true" if body.cookie_secure else "false"
            # Live for this process so cookie setters see it without restart.
            os.environ["HARVIS_COOKIE_SECURE"] = updates["cookie_secure"]
        if body.enable_signup is not None:
            updates["enable_signup_preference"] = (
                "true" if body.enable_signup else "false"
            )
        if not updates:
            return {"ok": True, "updated": []}
        async with pool.acquire() as conn:
            for key, value in updates.items():
                await conn.execute(
                    """
                    INSERT INTO instance_settings (key, value)
                    VALUES ($1, $2)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    key,
                    value,
                )
        return {"ok": True, "updated": list(updates.keys())}

    @router.post("/api/setup/complete")
    async def setup_complete(
        request: Request,
        body: CompleteBody | None = None,
        _user=Depends(require_admin),
    ):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO instance_settings (key, value)
                VALUES ('setup_complete', 'true')
                ON CONFLICT (key) DO UPDATE SET value = 'true'
                """
            )
        return {"ok": True, "setup_complete": True}

    return router


def cookie_secure_enabled(pool=None) -> bool:
    """Env wins; else instance_settings.cookie_secure; else False."""
    env = os.getenv("HARVIS_COOKIE_SECURE", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    # Unset env — optional DB preference from the setup wizard.
    return False  # sync callers can't await; use cookie_secure_enabled_async


async def cookie_secure_enabled_async(pool) -> bool:
    env = os.getenv("HARVIS_COOKIE_SECURE", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT value FROM instance_settings WHERE key = 'cookie_secure'"
            )
        return (val or "").strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        return False
