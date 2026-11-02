"""Notebook sharing: who besides the owner may open a notebook, and as what.

Functions take the pool and trust the caller (NotebookManager) to have proved ownership
before any write. The raw link token is returned once, at creation; only its SHA-256 is
stored, so a database read cannot be turned back into a working link.
"""

import hashlib
import secrets
from typing import Any, Dict, List, Optional
from uuid import UUID

from asyncpg import Pool
from asyncpg.exceptions import ForeignKeyViolationError

VALID_ROLES = ("viewer", "chat_only", "editor")
ROLE_RANK = {"chat_only": 1, "viewer": 2, "editor": 3}
MAX_TOKEN_LEN = 128

_SHARE_COLUMNS = "id, notebook_id, user_id, role, created_by, created_at, revoked_at"

_RANK_SQL = "CASE {r} WHEN 'editor' THEN 3 WHEN 'viewer' THEN 2 ELSE 1 END"

_UPSERT_USER_SHARE = f"""
    INSERT INTO notebook_shares (notebook_id, user_id, role, created_by)
    VALUES ($1, $2, $3, $4)
    ON CONFLICT (notebook_id, user_id) WHERE user_id IS NOT NULL AND revoked_at IS NULL
    DO UPDATE SET role = {{new_role}}
    RETURNING {_SHARE_COLUMNS}
"""


def check_role(role: Any) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {', '.join(VALID_ROLES)}")
    return role


def hash_link_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _share_dict(row: Any) -> Dict[str, Any]:
    data = dict(row)
    data["kind"] = "user" if data.get("user_id") is not None else "link"
    return data


async def get_access(pool: Pool, notebook_id: UUID, user_id: int) -> Optional[str]:
    """'owner', else the strongest active share role the user holds, else None."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT n.user_id AS owner_id,
                   (SELECT s.role FROM notebook_shares s
                     WHERE s.notebook_id = n.id AND s.user_id = $2 AND s.revoked_at IS NULL
                     ORDER BY {_RANK_SQL.format(r='s.role')} DESC LIMIT 1) AS role
            FROM notebooks n
            WHERE n.id = $1 AND n.is_active = TRUE
            """,
            notebook_id, user_id,
        )
    if not row:
        return None
    if row["owner_id"] == user_id:
        return "owner"
    return row["role"]


async def create_user_share(
    pool: Pool, notebook_id: UUID, created_by: int, target_user_id: int, role: str
) -> Dict[str, Any]:
    """Share with one user; sharing again with the same user replaces their role."""
    check_role(role)
    if target_user_id == created_by:
        raise ValueError("the owner already has access")
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                _UPSERT_USER_SHARE.format(new_role="EXCLUDED.role"),
                notebook_id, target_user_id, role, created_by,
            )
        except ForeignKeyViolationError:
            raise ValueError("user not found") from None
    return _share_dict(row)


async def create_link_share(pool: Pool, notebook_id: UUID, created_by: int, role: str) -> Dict[str, Any]:
    """New link share. The returned dict carries `token`, the only time it exists in the clear."""
    check_role(role)
    raw = secrets.token_urlsafe(24)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO notebook_shares (notebook_id, link_token, role, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING {_SHARE_COLUMNS}
            """,
            notebook_id, hash_link_token(raw), role, created_by,
        )
    share = _share_dict(row)
    share["token"] = raw
    return share


async def list_shares(pool: Pool, notebook_id: UUID, include_revoked: bool = False) -> List[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_SHARE_COLUMNS}
            FROM notebook_shares
            WHERE notebook_id = $1 AND ($2 OR revoked_at IS NULL)
            ORDER BY created_at DESC
            """,
            notebook_id, include_revoked,
        )
    return [_share_dict(r) for r in rows]


async def revoke_share(pool: Pool, notebook_id: UUID, share_id: UUID) -> bool:
    """Revoke one share of this notebook. False when it is not this notebook's or already revoked."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE notebook_shares SET revoked_at = NOW()
            WHERE id = $1 AND notebook_id = $2 AND revoked_at IS NULL
            """,
            share_id, notebook_id,
        )
    return result == "UPDATE 1"


async def resolve_link_token(pool: Pool, raw_token: str) -> Optional[Dict[str, Any]]:
    """{share_id, notebook_id, role} for a live link of an active notebook, else None."""
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > MAX_TOKEN_LEN:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.id AS share_id, s.notebook_id, s.role
            FROM notebook_shares s
            JOIN notebooks n ON n.id = s.notebook_id
            WHERE s.link_token = $1 AND s.revoked_at IS NULL AND n.is_active = TRUE
            """,
            hash_link_token(raw_token),
        )
    return dict(row) if row else None


async def accept_link_share(pool: Pool, raw_token: str, user_id: int) -> Optional[Dict[str, Any]]:
    """Turn a link into a share for this user. Never lowers a role they already hold.

    Returns {notebook_id, role}; role is 'owner' when the user owns the notebook.
    """
    link = await resolve_link_token(pool, raw_token)
    if not link:
        return None
    async with pool.acquire() as conn:
        owner_id = await conn.fetchval("SELECT user_id FROM notebooks WHERE id = $1", link["notebook_id"])
        if owner_id == user_id:
            return {"notebook_id": link["notebook_id"], "role": "owner"}
        row = await conn.fetchrow(
            _UPSERT_USER_SHARE.format(
                new_role=(
                    f"CASE WHEN {_RANK_SQL.format(r='EXCLUDED.role')} > "
                    f"{_RANK_SQL.format(r='notebook_shares.role')} "
                    "THEN EXCLUDED.role ELSE notebook_shares.role END"
                )
            ),
            link["notebook_id"], user_id, link["role"], owner_id,
        )
    return {"notebook_id": row["notebook_id"], "role": row["role"]}
