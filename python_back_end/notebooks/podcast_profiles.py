"""Per-user podcast speaker profiles and episode profiles.

A speaker profile is a named cast (1 to 4 speakers, each with a Kokoro voice picked
from ``podcast_audio.KOKORO_VOICES``). An episode profile is a named recipe (style,
which speaker profile to use, a standing briefing). Both live as JSON in one small
table, scoped by ``user_id``: every query below filters on it, so another user's
profile reads as "not found", never as "forbidden".

The table is created on first use (``CREATE TABLE IF NOT EXISTS``, nothing dropped or
altered). The older ``podcast_speaker_profiles`` table holds one speaker per row and
has different columns on different installs, so it is left alone.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from . import podcast_audio
from .podcast_script import MAX_SPEAKERS, STYLE_NOTES

DEFAULT_SPEAKER_PROFILE_ID = "default-duo"
AUTO_VOICE = "__default__"
MAX_PER_KIND = 50
KINDS = ("speaker", "episode")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS podcast_profiles (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('speaker', 'episode')),
    name       TEXT NOT NULL,
    config     JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_podcast_profiles_user_kind ON podcast_profiles(user_id, kind);
"""
_COLS = "id, name, config, created_at, updated_at"
SQL_COUNT = "SELECT COUNT(*) FROM podcast_profiles WHERE user_id = $1 AND kind = $2"
SQL_LIST = f"SELECT {_COLS} FROM podcast_profiles WHERE user_id = $1 AND kind = $2 ORDER BY created_at, id"
SQL_GET = f"SELECT {_COLS} FROM podcast_profiles WHERE id = $1 AND user_id = $2 AND kind = $3"
SQL_INSERT = (
    "INSERT INTO podcast_profiles (user_id, kind, name, config) VALUES ($1, $2, $3, $4::jsonb) "
    f"RETURNING {_COLS}"
)
SQL_UPDATE = (
    "UPDATE podcast_profiles SET name = $1, config = $2::jsonb, updated_at = CURRENT_TIMESTAMP "
    f"WHERE id = $3 AND user_id = $4 AND kind = $5 RETURNING {_COLS}"
)
SQL_DELETE = "DELETE FROM podcast_profiles WHERE id = $1 AND user_id = $2 AND kind = $3 RETURNING id"

_ready = False


class ProfileError(Exception):
    """A request the user can fix. ``status`` is the HTTP code, ``str(exc)`` the message."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def as_uuid(value: Any) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


async def ensure_table(pool) -> None:
    global _ready
    if _ready:
        return
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
    _ready = True


# ─── Validation ────────────────────────────────────────────────────────────────

def _text(body: Dict[str, Any], key: str, limit: int, *, required: bool = False, default: str = "") -> str:
    raw = body.get(key)
    value = " ".join(str(raw).split()) if raw is not None else default
    if required and not value:
        raise ProfileError(400, f"{key} is required.")
    if len(value) > limit:
        raise ProfileError(400, f"{key} must be at most {limit} characters.")
    return value


def clean_speaker(body: Any) -> Dict[str, Any]:
    """A speaker profile body, checked. Unknown voice ids are refused, not dropped."""
    if not isinstance(body, dict):
        raise ProfileError(400, "Expected a JSON object.")
    speakers = body.get("speakers")
    if not isinstance(speakers, list) or not 1 <= len(speakers) <= MAX_SPEAKERS:
        raise ProfileError(400, f"A speaker profile needs 1 to {MAX_SPEAKERS} speakers.")
    cast: List[Dict[str, Any]] = []
    seen: set = set()
    for item in speakers:
        if not isinstance(item, dict):
            raise ProfileError(400, "Each speaker must be an object.")
        name = _text(item, "name", 40, required=True)
        if name.casefold() in seen:
            raise ProfileError(400, f"Two speakers are both called {name!r}.")
        seen.add(name.casefold())
        voice = str(item.get("voice_id") or "").strip() or AUTO_VOICE
        if voice != AUTO_VOICE and not podcast_audio.is_voice(voice):
            raise ProfileError(400, f"Unknown voice {voice!r}. Pick one of the voices the speech service offers.")
        cast.append({
            "name": name,
            "voice_id": voice,
            "backstory": _text(item, "backstory", 500),
            "personality": _text(item, "personality", 500),
            "voice_model": "kokoro",
        })
    return {
        "name": _text(body, "name", 80, required=True),
        "description": _text(body, "description", 500),
        "voice_model": "kokoro",
        "speakers": cast,
    }


def clean_episode(body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise ProfileError(400, "Expected a JSON object.")
    style = _text(body, "style", 40, default="conversational")
    if style not in STYLE_NOTES:
        raise ProfileError(400, f"Unknown style {style!r}. Use one of: {', '.join(STYLE_NOTES)}.")
    try:
        segments = int(body.get("num_segments") or 5)
    except (TypeError, ValueError):
        raise ProfileError(400, "num_segments must be a whole number.")
    if not 1 <= segments <= 20:
        raise ProfileError(400, "num_segments must be between 1 and 20.")
    return {
        "name": _text(body, "name", 80, required=True),
        "description": _text(body, "description", 500),
        "style": style,
        "speaker_config": _text(body, "speaker_config", 64, default=DEFAULT_SPEAKER_PROFILE_ID),
        "language": _text(body, "language", 16, default="en"),
        "default_briefing": _text(body, "default_briefing", 2000),
        "num_segments": segments,
    }


# ─── Storage ───────────────────────────────────────────────────────────────────

def _config(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _iso(dt: Any) -> Optional[str]:
    return dt.isoformat() if hasattr(dt, "isoformat") else None


def _view(row) -> Dict[str, Any]:
    return {
        **_config(row["config"]),
        "id": str(row["id"]),
        "name": row["name"],
        "builtin": False,
        "created": _iso(row["created_at"]),
        "updated": _iso(row["updated_at"]),
    }


def _split(clean: Dict[str, Any]):
    config = {k: v for k, v in clean.items() if k != "name"}
    return clean["name"], json.dumps(config)


async def list_profiles(pool, user_id: int, kind: str) -> List[Dict[str, Any]]:
    await ensure_table(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(SQL_LIST, user_id, kind)
    return [_view(r) for r in rows]


async def get_profile(pool, user_id: int, kind: str, profile_id: Any) -> Optional[Dict[str, Any]]:
    """The user's own profile, or None: another user's id is indistinguishable from a missing one."""
    pid = as_uuid(profile_id)
    if pid is None:
        return None
    await ensure_table(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(SQL_GET, pid, user_id, kind)
    return _view(row) if row else None


async def create_profile(pool, user_id: int, kind: str, clean: Dict[str, Any]) -> Dict[str, Any]:
    await ensure_table(pool)
    name, config = _split(clean)
    async with pool.acquire() as conn:
        if await conn.fetchval(SQL_COUNT, user_id, kind) >= MAX_PER_KIND:
            raise ProfileError(400, f"You can keep at most {MAX_PER_KIND} {kind} profiles. Delete one first.")
        row = await conn.fetchrow(SQL_INSERT, user_id, kind, name, config)
    return _view(row)


async def update_profile(pool, user_id: int, kind: str, profile_id: Any, clean: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pid = as_uuid(profile_id)
    if pid is None:
        return None
    await ensure_table(pool)
    name, config = _split(clean)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(SQL_UPDATE, name, config, pid, user_id, kind)
    return _view(row) if row else None


async def delete_profile(pool, user_id: int, kind: str, profile_id: Any) -> bool:
    pid = as_uuid(profile_id)
    if pid is None:
        return False
    await ensure_table(pool)
    async with pool.acquire() as conn:
        return bool(await conn.fetchrow(SQL_DELETE, pid, user_id, kind))


# ─── Use at generation time ────────────────────────────────────────────────────

async def resolve_cast(pool, user_id: int, ref: Any, *, strict: bool = True) -> Optional[List[Dict[str, Any]]]:
    """The speakers a speaker-profile reference stands for.

    None means "use the defaults" (no reference, or the built-in profile). A reference to
    someone else's profile raises ProfileError(404) when ``strict`` (the caller asked for it
    by id), and quietly means defaults otherwise (an episode profile whose cast was deleted).
    """
    if not ref or ref == DEFAULT_SPEAKER_PROFILE_ID:
        return None
    profile = await get_profile(pool, user_id, "speaker", ref)
    if profile is None:
        if strict:
            raise ProfileError(404, "Speaker profile not found.")
        return None
    return [{"name": s["name"], "voice_id": s.get("voice_id", AUTO_VOICE)} for s in profile["speakers"]]
