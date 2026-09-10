"""Instance-wide admin settings — the ones Harvis actually honors.

Why this module exists
----------------------
The forked OWUI admin panel reads ``GET /api/v1/auths/admin/config`` and writes
it back on save. Harvis never implemented that route, so the call 404'd, the
frontend helper threw inside the panel's ``onMount`` ``Promise.all``, and the
whole Settings → General tab rendered blank — including a signup switch that,
even had it rendered, wrote to nothing while enforcement went on reading
``HARVIS_OWUI_ENABLE_SIGNUP``.

The rule this follows is the one ``setup_flow.setup_preferences`` already
states: a control that cannot change the thing it names is worse than no
control. So this serves exactly the keys the backend enforces — today
``ENABLE_SIGNUP`` and ``DEV_MODE`` — and the rewritten panel renders exactly
those keys. Adding a key here means wiring its enforcement in the same commit.

``DEV_MODE`` earns its place by that rule: it is not a label, it is the gate on
which experimental surfaces exist at all. Turning it off removes the Inference
Nodes panel from the settings list, from search, and from its own deep link —
so a Harvis handed to someone else shows only the parts that are finished.

Durability
----------
Values live in ``instance_settings``, the key/value table that already holds
``setup_complete`` and ``admin_user_id``. No new table: a second one for the
same job would just be a place for the two to disagree. Values are TEXT there,
so booleans are stored as ``"true"``/``"false"``.

The env var stays the DEFAULT: a fresh install with no stored row behaves
exactly as it did before, and an operator who prefers .env can keep using it as
long as they never touch the switch. A stored value wins once set, because that
is the one an admin last chose on purpose.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request

from .authz import make_require_admin

logger = logging.getLogger(__name__)

_SIGNUP_KEY = "enable_signup"
_DEV_MODE_KEY = "dev_mode"
_TRUTHY = {"1", "true", "yes", "on"}


def _env_signup_default() -> bool:
    """The .env default, byte-identical to main._signup_enabled's old reading."""
    raw = os.getenv("HARVIS_OWUI_ENABLE_SIGNUP", "").strip().lower()
    if not raw:
        return True
    return raw in _TRUTHY


def _env_dev_mode_default() -> bool:
    """The .env default for developer mode.

    True in code, deliberately. Harvis is pre-1.0 and everything this gates
    shipped in the last few weeks; defaulting to False would make an existing
    install silently lose the Inference Nodes panel on upgrade, which is a
    regression nobody asked for. Flipping this literal to False is the 1.0
    gate — at that point experimental surfaces become opt-IN and a fresh deploy
    shows only what is finished. Until then, set HARVIS_DEV_MODE=false on a
    machine that should look shipped.
    """
    raw = os.getenv("HARVIS_DEV_MODE", "").strip().lower()
    if not raw:
        return True
    return raw in _TRUTHY


def _resolve(stored: str | None, env_default: Callable[[], bool]) -> bool:
    """A stored row wins; absent or blank falls back to the .env default."""
    if isinstance(stored, str) and stored.strip():
        return stored.strip().lower() in _TRUTHY
    return env_default()


async def load_admin_config(conn) -> dict:
    """Stored admin config over the env defaults.

    Takes a connection rather than a pool because the signup path already holds
    one inside its transaction; acquiring a second there would contend with its
    own advisory lock.
    """
    stored: dict[str, str] = {}
    try:
        rows = await conn.fetch(
            "SELECT key, value FROM instance_settings WHERE key = ANY($1::text[])",
            [_SIGNUP_KEY, _DEV_MODE_KEY],
        )
        stored = {r["key"]: r["value"] for r in rows}
    except Exception:  # noqa: BLE001 - cold DB, table not created yet
        logger.debug("admin_config: instance_settings unreadable", exc_info=True)

    return {
        "ENABLE_SIGNUP": _resolve(stored.get(_SIGNUP_KEY), _env_signup_default),
        "DEV_MODE": _resolve(stored.get(_DEV_MODE_KEY), _env_dev_mode_default),
    }


async def signup_enabled(conn) -> bool:
    """The single source of truth for "may a stranger create an account".

    Both the enforcement gate (``main._signup_with_connection``) and the flag
    that draws the "Sign up" link (``config.build_config``) resolve through
    here, so the form and the server can never disagree about whether signup
    is open — a mismatch shows a link that 403s, or hides a working one.
    """
    cfg = await load_admin_config(conn)
    return bool(cfg["ENABLE_SIGNUP"])


async def signup_enabled_via_pool(pool) -> bool:
    """Pool-shaped wrapper for callers outside a transaction (``/api/config``).

    Falls back to the env default: /api/config is boot-critical, and a DB blip
    must not silently hide the signup link on an instance that has it on.
    """
    if pool is None:
        return _env_signup_default()
    try:
        async with pool.acquire() as conn:
            return await signup_enabled(conn)
    except Exception:  # noqa: BLE001 - see docstring
        return _env_signup_default()


async def dev_mode_enabled(conn) -> bool:
    """The single source of truth for "are experimental surfaces visible".

    Read by ``config.build_config`` so the boot payload the frontend gates on
    and the value the admin panel writes can never disagree.
    """
    cfg = await load_admin_config(conn)
    return bool(cfg["DEV_MODE"])


async def dev_mode_enabled_via_pool(pool) -> bool:
    """Pool-shaped wrapper for /api/config, which is boot-critical.

    Falls back to the env default rather than to False: a DB blip must not make
    a developer's panels vanish mid-session.
    """
    if pool is None:
        return _env_dev_mode_default()
    try:
        async with pool.acquire() as conn:
            return await dev_mode_enabled(conn)
    except Exception:  # noqa: BLE001 - see docstring
        return _env_dev_mode_default()


def register_admin_config_routes(router: APIRouter, get_current_user: Callable) -> None:
    require_admin = make_require_admin(get_current_user)

    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return pool

    @router.get("/api/v1/auths/admin/config")
    async def owui_get_admin_config(request: Request, _user=Depends(require_admin)):
        async with _pool(request).acquire() as conn:
            return await load_admin_config(conn)

    @router.post("/api/v1/auths/admin/config")
    async def owui_update_admin_config(request: Request, _user=Depends(require_admin)):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be an object")

        async with _pool(request).acquire() as conn:
            current = await load_admin_config(conn)
            # Only known-honored keys are stored. An unknown key is dropped
            # rather than persisted, so the table can never accumulate settings
            # nothing reads — which is the failure this module exists to end.
            for field, key in (
                ("ENABLE_SIGNUP", _SIGNUP_KEY),
                ("DEV_MODE", _DEV_MODE_KEY),
            ):
                incoming = body.get(field)
                if not isinstance(incoming, bool):
                    continue
                current[field] = incoming
                await conn.execute(
                    """
                    INSERT INTO instance_settings (key, value, updated_at)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    key,
                    "true" if incoming else "false",
                )
            return current
