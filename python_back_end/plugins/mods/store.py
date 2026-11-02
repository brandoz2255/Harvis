"""user_mods rows (migration 024). Every query is scoped by user_id.

Lifecycle: install → draft; approve(hash) → on (the previous on version goes
off); disable → off; crash → broken; rollback → the newest earlier approved
version goes back on. Only a person's own approve call ever sets ``on``.
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from . import manifest as mf

MAX_VERSIONS_PER_MOD = 20
MAX_MODS_PER_USER = 50

_COLS = ("id, name, version, hash, tiers, manifest, source, status, status_reason, "
         "approved_hash, approved_at, created_at")


class ModError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _row(r) -> dict:
    d = dict(r)
    if isinstance(d.get("manifest"), str):
        d["manifest"] = json.loads(d["manifest"])
    for k in ("approved_at", "created_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    d["tiers"] = list(d.get("tiers") or [])
    return d


async def list_mods(pool, user_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_COLS} FROM user_mods WHERE user_id=$1 ORDER BY name, created_at DESC", user_id)
    return [_row(r) for r in rows]


async def install(pool, user_id: int, manifest: dict, resources: dict[str, str], source: str) -> dict:
    """Validate, hash and stage a version as a draft. Re-installing the same bytes
    returns the existing row untouched (an approved version stays approved)."""
    errors, warnings = mf.validate(manifest, resources)
    if errors:
        raise ModError(422, "; ".join(errors))
    hash_ = mf.content_hash(manifest, resources)
    name = manifest["name"]
    async with pool.acquire() as conn, _busy_on_race():
        async with conn.transaction():
            existing = await conn.fetchrow(
                f"SELECT {_COLS} FROM user_mods WHERE user_id=$1 AND name=$2 AND hash=$3",
                user_id, name, hash_)
            if existing:
                return {"mod": _row(existing), "approval": mf.approval_card(manifest, hash_, warnings)}
            names = await conn.fetchval(
                "SELECT count(DISTINCT name) FROM user_mods WHERE user_id=$1 AND name<>$2", user_id, name)
            if names >= MAX_MODS_PER_USER:
                raise ModError(409, f"you already have {MAX_MODS_PER_USER} mods; remove one first")
            row = await conn.fetchrow(
                "INSERT INTO user_mods (user_id, name, version, hash, tiers, manifest, resources, source) "
                f"VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8) RETURNING {_COLS}",
                user_id, name, manifest["version"], hash_, mf.tiers_of(manifest),
                mf.canonical(manifest), mf.canonical(resources), source)
            # Keep the newest drafts. A version the person approved is never pruned, so
            # agent drafts cannot push their rollback history out.
            await conn.execute(
                "DELETE FROM user_mods WHERE id IN (SELECT id FROM user_mods WHERE user_id=$1 AND name=$2 "
                "AND status<>'on' AND approved_hash IS DISTINCT FROM hash "
                "ORDER BY created_at DESC OFFSET $3)",
                user_id, name, MAX_VERSIONS_PER_MOD)
    return {"mod": _row(row), "approval": mf.approval_card(manifest, hash_, warnings)}


class _busy_on_race:
    """Two requests racing on the same mod hit a unique index: answer 409, not 500."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None and issubclass(exc_type, asyncpg.UniqueViolationError):
            raise ModError(409, "this mod changed at the same moment; try again") from exc
        return False


async def _version(conn, user_id: int, name: str, hash_: str):
    row = await conn.fetchrow(
        f"SELECT {_COLS} FROM user_mods WHERE user_id=$1 AND name=$2 AND hash=$3", user_id, name, hash_)
    if row is None:
        raise ModError(404, "no such mod version")
    return row


async def approve(pool, user_id: int, name: str, hash_: str) -> dict:
    """The person said yes to exactly this hash: it goes on, the old one goes off."""
    async with pool.acquire() as conn, _busy_on_race():
        async with conn.transaction():
            row = await _version(conn, user_id, name, hash_)
            await conn.execute(
                "UPDATE user_mods SET status='off', status_reason='replaced' "
                "WHERE user_id=$1 AND name=$2 AND status='on'", user_id, name)
            row = await conn.fetchrow(
                "UPDATE user_mods SET status='on', status_reason=NULL, approved_hash=hash, approved_at=now() "
                f"WHERE id=$1 RETURNING {_COLS}", row["id"])
    return _row(row)


async def set_off(pool, user_id: int, name: str, reason: str = "", broken: bool = False) -> dict | None:
    status = "broken" if broken else "off"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE user_mods SET status=$3, status_reason=$4 WHERE user_id=$1 AND name=$2 AND status='on' "
            f"RETURNING {_COLS}", user_id, name, status, (reason or "")[:300] or None)
    return _row(row) if row else None


async def rollback(pool, user_id: int, name: str) -> dict:
    """Turn the newest approved version older than the current one back on.

    The current one is the version that is on, or, when the person switched it off
    or it crashed, the one approved most recently. A version that crashed is never
    a rollback target."""
    async with pool.acquire() as conn, _busy_on_race():
        async with conn.transaction():
            cur = await conn.fetchrow(
                "SELECT id, status, created_at FROM user_mods WHERE user_id=$1 AND name=$2 "
                "AND approved_hash=hash ORDER BY (status='on') DESC, approved_at DESC LIMIT 1",
                user_id, name)
            if cur is None:
                raise ModError(404, "no earlier approved version to go back to")
            prev = await conn.fetchrow(
                "SELECT id FROM user_mods WHERE user_id=$1 AND name=$2 AND approved_hash=hash "
                "AND status NOT IN ('on','broken') AND id<>$3 AND created_at < $4 "
                "ORDER BY created_at DESC LIMIT 1",
                user_id, name, cur["id"], cur["created_at"])
            if prev is None:
                raise ModError(404, "no earlier approved version to go back to")
            if cur["status"] == "on":
                await conn.execute(
                    "UPDATE user_mods SET status='off', status_reason='rolled back' WHERE id=$1", cur["id"])
            row = await conn.fetchrow(
                f"UPDATE user_mods SET status='on', status_reason=NULL WHERE id=$1 RETURNING {_COLS}", prev["id"])
    return _row(row)


async def card(pool, user_id: int, name: str, hash_: str) -> dict:
    """The approval card for a stored version, built from the bytes the server holds."""
    async with pool.acquire() as conn:
        row = await _version(conn, user_id, name, hash_)
        res = await conn.fetchval("SELECT resources FROM user_mods WHERE id=$1", row["id"])
    mod = _row(row)
    res = json.loads(res) if isinstance(res, str) else dict(res or {})
    _, warnings = mf.validate(mod["manifest"], res)
    return {"mod": mod, "approval": mf.approval_card(mod["manifest"], row["hash"], warnings)}


async def resources(pool, user_id: int, name: str, hash_: str) -> dict[str, str]:
    async with pool.acquire() as conn:
        res = await conn.fetchval(
            "SELECT resources FROM user_mods WHERE user_id=$1 AND name=$2 AND hash=$3", user_id, name, hash_)
    if res is None:
        raise ModError(404, "no such mod version")
    return json.loads(res) if isinstance(res, str) else dict(res)


async def remove(pool, user_id: int, name: str) -> int:
    async with pool.acquire() as conn:
        out = await conn.execute("DELETE FROM user_mods WHERE user_id=$1 AND name=$2", user_id, name)
    return int(out.split()[-1]) if out else 0


async def active_rules(pool, user_id: int) -> list[tuple[str, dict]]:
    """(mod name, hook) for every hook of every mod that is on for its approved hash."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, manifest FROM user_mods WHERE user_id=$1 AND status='on' "
            "AND approved_hash=hash AND 'rules' = ANY(tiers)", user_id)
    out: list[tuple[str, dict]] = []
    for r in rows:
        m: Any = r["manifest"]
        m = json.loads(m) if isinstance(m, str) else m
        for h in (m.get("rules") or {}).get("hooks", []):
            out.append((r["name"], h))
    return out
