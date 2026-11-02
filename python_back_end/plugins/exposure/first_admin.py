"""The first account on a shared server needs a 6-digit code from the host.

On a laptop (``HARVIS_EXPOSURE`` local) the first sign-up becomes admin with no
code: nobody else can reach it. On a shared server anyone on the network could
get there first, so the server makes a 6-digit code, keeps only its hash, and
shows the code where only the host can read it: the backend log and the
installer's last screen. The sign-up form asks for it.

Five wrong codes retire it; the host prints a new one with
``python -m plugins.exposure.first_admin`` inside the backend (the installer
wraps that). Once the admin exists the code is deleted.

An operator's own ``HARVIS_SETUP_CODE`` still wins over all of this, with the same
limit: five wrong guesses lock it until the backend restarts, and on a shared server
a code shorter than 16 characters is refused outright (it could be guessed in minutes).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets

from .mode import shared

logger = logging.getLogger(__name__)

KEY = "first_admin_code"
MAX_TRIES = 5
MIN_MANUAL_LENGTH = 16
MANUAL_KEY = "first_admin_manual_tries"
LOCK = 0x48415256  # the same advisory lock the first sign-up takes
SHOW_AGAIN = "python -m plugins.exposure.first_admin"


def manual_code() -> str:
    return os.getenv("HARVIS_SETUP_CODE", "").strip()


def manual_code_refused() -> bool:
    """A hand-set code too short to guard a server other machines can reach."""
    code = manual_code()
    return bool(code) and shared() and len(code) < MIN_MANUAL_LENGTH


def required() -> bool:
    """Whether an unclaimed server asks for a code at all."""
    return bool(manual_code()) or shared()


def _digest(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


async def _users(conn) -> int:
    return await conn.fetchval("SELECT COUNT(*) FROM users")


async def _load(conn) -> dict | None:
    raw = await conn.fetchval("SELECT value FROM instance_settings WHERE key = $1", KEY)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


async def _store(conn, state: dict) -> None:
    await conn.execute(
        "INSERT INTO instance_settings (key, value, updated_at) VALUES ($1, $2, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        KEY, json.dumps(state))


async def issue(conn) -> str:
    """A fresh code; the old one stops working. Caller holds the lock."""
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(16)
    await _store(conn, {"salt": salt, "hash": _digest(salt, code), "tries": 0})
    return code


def _announce(code: str) -> None:
    logger.warning("🔐 First-admin code for this server: %s  (the first sign-up must enter it; "
                   "show a new one with `%s` in the backend)", code, SHOW_AGAIN)


async def on_startup(conn) -> None:
    """Make a code if the server is shared and unclaimed and none is usable."""
    if manual_code():
        # A restart is the operator's way out of a locked manual code.
        await conn.execute("DELETE FROM instance_settings WHERE key = $1", MANUAL_KEY)
        if manual_code_refused():
            logger.warning("🔐 HARVIS_SETUP_CODE is shorter than %d characters, so this shared server "
                           "will not accept it. Set a longer one in .env and restart.", MIN_MANUAL_LENGTH)
        return
    if not shared():
        return
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", LOCK)
        if await _users(conn):
            await conn.execute("DELETE FROM instance_settings WHERE key = $1", KEY)
            return
        state = await _load(conn)
        if state and state.get("tries", 0) < MAX_TRIES:
            logger.warning("🔐 This server has no admin yet and a first-admin code is waiting. "
                           "Show a new one with `%s` in the backend.", SHOW_AGAIN)
            return
        _announce(await issue(conn))


async def check(conn, code: str | None) -> bool:
    """One attempt at the code. Caller holds the lock in a transaction that commits
    even when this says no, so a wrong guess is counted."""
    manual = manual_code()
    if manual:
        return await _check_manual(conn, manual, code)
    state = await _load(conn)
    if not state or state.get("tries", 0) >= MAX_TRIES:
        return False
    if code and hmac.compare_digest(state["hash"], _digest(state["salt"], code.strip())):
        return True
    state["tries"] = state.get("tries", 0) + 1
    await _store(conn, state)
    if state["tries"] >= MAX_TRIES:
        logger.warning("🔐 Five wrong first-admin codes: that code no longer works. "
                       "Show a new one with `%s` in the backend.", SHOW_AGAIN)
    return False


async def _manual_tries(conn) -> int:
    raw = await conn.fetchval("SELECT value FROM instance_settings WHERE key = $1", MANUAL_KEY)
    try:
        return int(json.loads(raw)["tries"]) if raw else 0
    except (ValueError, KeyError, TypeError):
        return 0


async def _check_manual(conn, manual: str, code: str | None) -> bool:
    if manual_code_refused():
        return False
    tries = await _manual_tries(conn)
    if tries >= MAX_TRIES:
        return False
    if code and hmac.compare_digest(manual.encode(), code.strip().encode()):
        return True
    await conn.execute(
        "INSERT INTO instance_settings (key, value, updated_at) VALUES ($1, $2, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        MANUAL_KEY, json.dumps({"tries": tries + 1}))
    if tries + 1 >= MAX_TRIES:
        logger.warning("🔐 Five wrong HARVIS_SETUP_CODE guesses: it is locked until the backend restarts.")
    return False


async def retired(conn) -> bool:
    if manual_code():
        return await _manual_tries(conn) >= MAX_TRIES
    state = await _load(conn)
    return bool(state) and state.get("tries", 0) >= MAX_TRIES


async def claimed(conn) -> None:
    await conn.execute("DELETE FROM instance_settings WHERE key = $1", KEY)
    await conn.execute("DELETE FROM instance_settings WHERE key = $1", MANUAL_KEY)


async def _main() -> int:
    import asyncpg

    conn = await asyncpg.connect(os.environ["DATABASE_URL"], timeout=10)
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", LOCK)
            if await _users(conn):
                print("This server already has an admin; no code is needed.")
                return 1
            if manual_code():
                print("HARVIS_SETUP_CODE is set, so that is the code to use.")
                return 1
            code = await issue(conn)
    finally:
        await conn.close()
    print(f"First-admin code: {code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
