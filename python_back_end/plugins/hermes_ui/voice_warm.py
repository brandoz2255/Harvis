"""Keep the voice call's model loaded while the call is open.

Turns reach Ollama over its OpenAI-compatible route, which ignores ``keep_alive``
(checked on Ollama 0.20.2), so Ollama unloads the model after its default five idle
minutes and the next spoken turn waits for a reload (about 8 s on the laptop). The
voice call asks Ollama's native API to load the model and hold it for
``HARVIS_VOICE_KEEP_ALIVE`` (default 30m) when the call opens and after each turn.
Only models on this server's Ollama are warmed: a person's own endpoint and cloud
models are left alone. Every failure is logged and dropped; a warm-up never blocks
or breaks a turn.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Optional

import httpx

from plugins import people

from . import providers
from .models import is_hidden_model
from .turn_models import MOA_PREFIX

log = logging.getLogger("hermes_ui.voice")

# The same model is not re-warmed more often than this; each warm-up already
# holds it for the whole keep-alive window.
REWARM_SECONDS = 60
_last: dict[str, float] = {}
_tasks: set[asyncio.Task] = set()
_EXPIRES_RE = re.compile(r"^(.+?T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$")


def keep_alive() -> str:
    return (os.getenv("HARVIS_VOICE_KEEP_ALIVE") or "30m").strip()


async def voice_model(pool, user_id: int, session_model: str) -> str:
    """The local Ollama model a voice turn for this user will run on, or "" when
    there is nothing to warm (own endpoint, cloud model). Mirrors the turn: the
    session's model, then the person's saved default, then model_proxy's auto pick."""
    if await providers.resolve_active_endpoint(pool, user_id):
        return ""
    model = session_model or ""
    if is_hidden_model(model) or model.startswith(MOA_PREFIX):
        model = ""
    admitted = await people.admit_turn(pool, user_id, model, count=False)
    if not admitted.ok:
        return ""
    model = admitted.model or ""
    if not model:
        from owui_compat.capabilities import _read_integrations
        _prefs, model = await _read_integrations(pool, user_id)
        model = model or ""
    if not model:
        # No pick anywhere: the turn goes out as "auto"; warm what that resolves to.
        from workspace.model_proxy import resolve_auto_model
        model = await resolve_auto_model() or ""
    from owui_compat.cloud_chat import is_cloud_chat_model
    if not model or is_cloud_chat_model(model):
        return ""
    return model


def _window_seconds(value: str) -> float:
    """Seconds in a keep-alive like "30m", "2h", "90s" or "600"; a negative value is forever."""
    units = {"s": 1, "m": 60, "h": 3600}
    try:
        if value and value[-1] in units:
            return float(value[:-1]) * units[value[-1]]
        return float(value)
    except ValueError:
        return 1800.0


def _held_long_enough(ps: dict, model: str, window: float) -> bool:
    """Is ``model`` already loaded and held at least ``window`` more seconds? An Ollama
    set to keep models longer (``OLLAMA_KEEP_ALIVE=-1``) must not be cut back to ours."""
    from datetime import datetime, timezone
    for m in ps.get("models") or []:
        if model not in (m.get("name"), m.get("model")):
            continue
        # Ollama writes nanoseconds and a Z or local offset; fromisoformat takes microseconds.
        hit = _EXPIRES_RE.match(str(m.get("expires_at") or ""))
        if not hit:
            return False
        head, frac, zone = hit.groups()
        zone = "+00:00" if zone in (None, "Z") else zone
        try:
            expires = datetime.fromisoformat(f"{head}.{((frac or '') + '000000')[:6]}{zone}")
        except ValueError:
            return False
        return (expires - datetime.now(timezone.utc)).total_seconds() >= window
    return False


def _bases() -> list[str]:
    bases = [os.getenv("OLLAMA_URL", "http://ollama:11434"), os.getenv("DESKTOP_OLLAMA_URL", "")]
    return [b.rstrip("/") for b in bases if b]


async def warm(model: str) -> bool:
    """Load ``model`` and hold it for the keep-alive window. True when an Ollama took it."""
    window = _window_seconds(keep_alive())
    async with httpx.AsyncClient(timeout=180) as client:
        for base in _bases():
            try:
                if window >= 0:
                    ps = await client.get(f"{base}/api/ps", timeout=5)
                    if ps.status_code == 200 and _held_long_enough(ps.json(), model, window):
                        return True
                r = await client.post(f"{base}/api/generate", json={"model": model, "keep_alive": keep_alive()})
            except httpx.HTTPError as exc:
                log.info("voice warm-up: %s unreachable (%s)", base, type(exc).__name__)
                continue
            if r.status_code == 200:
                return True
            # 404: the model lives on the other Ollama (model_proxy routes the same way).
            log.info("voice warm-up: %s answered %s for %s", base, r.status_code, model)
    return False


def schedule(pool, user_id: int, session_model: str, force: bool = False) -> None:
    """Warm the user's voice model in the background, at most once a minute per
    model unless ``force``."""
    async def run() -> None:
        try:
            model = await voice_model(pool, user_id, session_model)
            if not model:
                return
            now = time.monotonic()
            if not force and now - _last.get(model, -REWARM_SECONDS) < REWARM_SECONDS:
                return
            _last[model] = now
            if not await warm(model):
                _last.pop(model, None)
        except Exception as exc:  # noqa: BLE001 — a warm-up must never surface
            log.warning("voice warm-up failed: %s", exc)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def rewarm_after_turn(pool, user_id: int, session_model: Optional[str]) -> None:
    """A turn ran on the OpenAI route, which reset the model's timer to Ollama's
    default; put the voice window back."""
    schedule(pool, user_id, session_model or "", force=True)
