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


def _tick(ready: bool, reason: str, probe: str, skipped: bool = False) -> dict[str, Any]:
    return {
        "ready": bool(ready),
        "reason": reason or "",
        "probe": probe,
        "skipped": bool(skipped),
    }


# Optional capabilities live behind compose profiles, and profiles are opt-in — a
# correct default install starts neither openclaw nor tts-service. The backend
# cannot see `docker compose --profile`, so compose passes the enabled set in via
# HARVIS_ENABLED_PROFILES. Without that we cannot tell "the operator turned this
# off" from "it crashed", and the safe reading is the former: calling a correct
# install degraded teaches people to ignore the health page.
_SERVICE_PROFILE = {
    "openclaw": "engines",
    "tts": "voice",
    "tts-service": "voice",
    # Notebooks ships as an opt-in pack. Without these entries a CORRECT default
    # install reported Notebooks as broken (nginx 502s /onb because the upstream
    # container does not exist) instead of "not installed" — the exact failure the
    # docstring above warns about, one capability later.
    "notebooks": "notebooks",
    "open-notebook-ui": "notebooks",
    "document-worker": "notebooks",
}


def enabled_profiles() -> set[str]:
    raw = os.getenv("HARVIS_ENABLED_PROFILES", "")
    return {p.strip() for p in raw.replace(";", ",").split(",") if p.strip()}


def service_expected(name: str) -> bool:
    """False when `name` sits behind a compose profile that is not turned on."""
    profile = _SERVICE_PROFILE.get(name)
    if profile is None:
        return True
    return profile in enabled_profiles()


def _not_installed_reason(name: str) -> str:
    return f"not installed — compose profile '{_SERVICE_PROFILE[name]}' is not enabled"


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
        if not service_expected("openclaw"):
            return _tick(False, _not_installed_reason("openclaw"), probe, skipped=True)
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
        # Speech is NOT off when this is skipped: Whisper STT and piper/chatterbox
        # TTS run inside the backend process. tts-service is the SpeechT5 sidecar
        # for notebook podcasts, which is what the `voice` profile turns on.
        if not service_expected("tts"):
            return _tick(False, _not_installed_reason("tts"), probe, skipped=True)
        return _tick(False, str(exc)[:200], probe)


# The Harvis notebooks lane: our own Next.js UI (basePath /onb) talking to this
# backend's onb_compat router. Deliberately NOT the lfnovo `open-notebook` +
# `surrealdb` pair further down the compose file — that is a separate product on
# its own database, and conflating the two is how the install cost got quoted as
# ~2.7 GB of images nobody on this lane needs.
_NOTEBOOKS_PROFILE = "notebooks"
_NOTEBOOKS_SERVICES = ("open-notebook-ui", "document-worker")
# Measured with `docker images`, not read off a comment: open-notebook-ui 278 MB
# + document-worker 1.41 GB. (The compose comment above document-worker claims
# "~200MB" — it is wrong by 7x and should be corrected separately.)
_NOTEBOOKS_DOWNLOAD_MB = 1690
_NOTEBOOKS_ENABLE_COMMAND = "docker compose --profile notebooks up -d"


def _notebooks_ui_url() -> str:
    return os.getenv("ONB_UI_URL", "http://open-notebook-ui:8502").rstrip("/")


async def _probe_notebooks() -> dict[str, Any]:
    """Is the notebooks UI container answering?

    Probes ``/onb`` and not ``/`` — the app is served under that basePath, so the
    root legitimately 404s on a perfectly healthy container.
    """
    probe = f"GET {_notebooks_ui_url()}/onb"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as hc:
            r = await hc.get(f"{_notebooks_ui_url()}/onb")
        if r.status_code < 400:
            return _tick(True, f"HTTP {r.status_code}", probe)
        return _tick(False, f"HTTP {r.status_code}", probe)
    except Exception as exc:
        # Observation loses to nothing here, but a failed probe is ambiguous:
        # the container may be absent (profile off) or crashed (profile on).
        # HARVIS_ENABLED_PROFILES is the only signal that separates them, and it
        # is empty on installs that predate it — so an unset env reads as "not
        # installed", matching the openclaw/tts convention above.
        if not service_expected("open-notebook-ui"):
            return _tick(
                False, _not_installed_reason("open-notebook-ui"), probe, skipped=True
            )
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
        notebooks = await _probe_notebooks()
        artifacts = _probe_artifacts()
        ticks = {
            "database": db,
            "ollama": ollama,
            "openclaw": openclaw,
            "tts": tts,
            "notebooks": notebooks,
            "artifacts": artifacts,
        }
        # A skipped tick is neither ready nor a failure — it is a capability the
        # operator did not install. Counting it either way would lie.
        overall = all(t["ready"] for t in ticks.values() if not t.get("skipped"))
        return {"overall": overall, "ticks": ticks}

    @router.post("/api/setup/test-model")
    async def setup_test_model(
        body: TestModelBody,
        _user=Depends(require_admin),
    ):
        """Direct Ollama /api/chat with a small predict — proves the model loads.

        The budget is 512, not the 8 it used to be. Reasoning models spend their
        token budget on a separate ``thinking`` channel before emitting a single
        character of ``content``: measured on qwen3:0.6b, num_predict=8 and 64
        both stop with done_reason="length" and content="" while thinking is
        mid-sentence, and only at 256 does "OK" arrive. Eight tokens therefore
        reported "empty generation" — the wizard's last step calling a perfectly
        working model broken — and qwen3 is exactly what a modest machine gets
        steered toward. 512 leaves headroom for a slower thinker; the surrounding
        120 s timeout, not the token cap, is what bounds this probe.
        """
        probe = "POST {OLLAMA_URL}/api/chat options.num_predict=512"
        # OLLAMA_URL is normalised to HARVIS_LLM_BASE_URL by main.py at import
        # time (see the canonical-base-URL block there), so this reads the
        # resolved provider address; the literal default is a dead fallback.
        url = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        payload = {
            "model": body.model,
            "stream": False,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "options": {"num_predict": 512},
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
                # A bigger reasoner can still burn the whole budget thinking. That
                # is not a broken model — it loaded and generated — so report it
                # as ready and say plainly which channel answered, rather than
                # failing the wizard on a token cap.
                thinking = ""
                if isinstance(msg, dict):
                    thinking = str(msg.get("thinking") or "").strip()
                if thinking:
                    return {
                        "ready": True,
                        "reason": "ok (reasoning output only — the model ran out of "
                        "tokens while thinking, which still proves it loaded)",
                        "probe": probe,
                        "text": thinking[:500],
                    }
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
        """Apply wizard preferences.

        ``cookie_secure`` takes effect for the RUNNING backend process only — it
        is not durable, because the container's HARVIS_COOKIE_SECURE env (set by
        compose) is authoritative and is restored on restart. Set that var in
        .env for a permanent value (install.sh documents this). ``enable_signup``
        is stored for display; live enforcement always reads
        HARVIS_OWUI_ENABLE_SIGNUP, per the wizard copy.
        """
        updated: list[str] = []
        if body.cookie_secure is not None:
            # Process-level only. We deliberately do NOT persist this to the DB:
            # nothing reads it back (the cookie setters read the env var), so a
            # stored row would be a durable-looking value that silently does
            # nothing after a restart.
            os.environ["HARVIS_COOKIE_SECURE"] = "true" if body.cookie_secure else "false"
            updated.append("cookie_secure")
        if body.enable_signup is not None:
            pool = getattr(request.app.state, "pg_pool", None)
            if pool is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO instance_settings (key, value)
                    VALUES ('enable_signup_preference', $1)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    "true" if body.enable_signup else "false",
                )
            updated.append("enable_signup")
        return {
            "ok": True,
            "updated": updated,
            "cookie_secure_durable": False,
            "note": "cookie_secure applies to this process; set HARVIS_COOKIE_SECURE in .env for a durable value",
        }

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

    @router.get("/api/capabilities/notebooks")
    async def capability_notebooks(_user=Depends(get_current_user)):
        """Is the Notebooks pack installed, and if not, how does one install it?

        ``get_current_user`` rather than ``require_admin``: the Notebooks page is
        an ordinary-user surface, and it needs this answer to tell "not installed"
        apart from "broken" before it mounts the iframe. Nothing here is
        privileged — it is a health probe plus a documented compose command.
        """
        tick = await _probe_notebooks()
        if tick["ready"]:
            state = "running"
        elif tick["skipped"]:
            state = "not_installed"
        else:
            state = "unreachable"
        return {
            "id": "notebooks",
            "state": state,
            "reason": tick["reason"],
            "probe": tick["probe"],
            "profile": _NOTEBOOKS_PROFILE,
            "services": list(_NOTEBOOKS_SERVICES),
            "download_mb": _NOTEBOOKS_DOWNLOAD_MB,
            "enable": {
                "command": _NOTEBOOKS_ENABLE_COMMAND,
                # The backend cannot run this itself: harvis-backend has the docker
                # CLI but no compose plugin, and the repo root is not bind-mounted.
                # Handing the operator the exact command is the honest option —
                # better than a button that pretends and fails.
                "run_from": "the Harvis repo root, on the Docker host",
            },
        }

    return router
