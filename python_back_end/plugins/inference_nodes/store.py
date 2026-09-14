"""Database half of the node registry.

Nodes an administrator registers through ``POST /api/inference-nodes`` live here;
``HARVIS_INFERENCE_NODES`` nodes never do. The schema is created on first use as
well as by migration 016, the same self-healing pattern as the cron store, so a
database restored from before this plugin does not break the picker.

A bearer token is Fernet-encrypted through ``main.encrypt_api_key`` — the same path
SSH credentials and engine keys take — and decrypted only to build a request header.
It is never returned by any endpoint.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS inference_nodes (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    base_url        TEXT NOT NULL,
    dialect         TEXT NOT NULL DEFAULT 'openai',
    label           TEXT NOT NULL DEFAULT '',
    hardware        TEXT NOT NULL DEFAULT '',
    token_encrypted TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    priority        INTEGER NOT NULL DEFAULT 100,
    created_by      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_schema_ready = False


def _encrypt(token: str) -> str | None:
    if not token:
        return None
    from main import encrypt_api_key  # lazy: main imports this package's router

    return encrypt_api_key(token)


def _decrypt(blob: str | None) -> str:
    if not blob:
        return ""
    try:
        from main import decrypt_api_key

        return decrypt_api_key(blob) or ""
    except Exception as e:
        # A token that cannot be decrypted (key rotated) is a node without a token,
        # which the probe will report as HTTP 401 — visible, and not a crash.
        logger.warning("inference_nodes: token decrypt failed (%s)", type(e).__name__)
        return ""


async def ensure_schema(pool) -> None:
    global _schema_ready
    if _schema_ready:
        return
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    _schema_ready = True


async def list_nodes(pool) -> list[dict]:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, base_url, dialect, label, hardware, token_encrypted, enabled, priority "
            "FROM inference_nodes ORDER BY priority, name"
        )
    return [
        {
            "name": r["name"], "base_url": r["base_url"], "dialect": r["dialect"],
            "label": r["label"], "hardware": r["hardware"], "enabled": r["enabled"],
            "priority": r["priority"], "token": _decrypt(r["token_encrypted"]),
        }
        for r in rows
    ]


async def upsert_node(pool, spec, *, keep_token: bool, user_id=None) -> None:
    """Insert or update by name. ``keep_token`` leaves the stored token untouched
    (an edit that did not mention it); otherwise the spec's token replaces it, and an
    empty token clears it."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO inference_nodes
                (name, base_url, dialect, label, hardware, token_encrypted, enabled, priority, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (name) DO UPDATE SET
                base_url = EXCLUDED.base_url,
                dialect = EXCLUDED.dialect,
                label = EXCLUDED.label,
                hardware = EXCLUDED.hardware,
                token_encrypted = CASE WHEN $10 THEN inference_nodes.token_encrypted
                                       ELSE EXCLUDED.token_encrypted END,
                enabled = EXCLUDED.enabled,
                priority = EXCLUDED.priority,
                updated_at = NOW()
            """,
            spec.name, spec.base_url, spec.dialect, spec.label, spec.hardware,
            None if keep_token else _encrypt(spec.token),
            spec.enabled, spec.priority, user_id, bool(keep_token),
        )


async def delete_node(pool, name: str) -> bool:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        status = await conn.execute("DELETE FROM inference_nodes WHERE name = $1", name)
    return status.endswith(" 1")
