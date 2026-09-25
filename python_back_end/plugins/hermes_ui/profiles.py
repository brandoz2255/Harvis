"""Per-user Hermes profiles (the Profiles page and the Bots roster).

A profile is a name, a SOUL.md persona, an optional model, a description and
the desktop's ``ui_meta`` / avatar. ``default`` always exists: its persona
IS Harvis's own soul (plugins/soul, the ``user_soul`` table) and its model is
the picker's saved default, so the main chat and the Hermes UI agree. Every
other profile is a record under ``settings.hermes_ui.profiles``.

REST shapes: front_end/hermes-desktop-ui/src/api/profiles.ts (ProfileInfo,
ProfileSoul). RPC shapes: src/plugins/hermes-bots/{profile-config,data}.ts.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized
from plugins.soul import loader as soul_loader

from . import settings_store, store

router = APIRouter(prefix="/hermes-api/api/profiles", tags=["hermes-ui"])
logger = logging.getLogger(__name__)

DEFAULT = "default"
PROFILES_KEY = "profiles"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_RESERVED = frozenset({"sessions", "active", "import", "all", "hermes"})
MAX_SOUL_CHARS = 200_000
MAX_ASSET_CHARS = 1_500_000  # a 160px PNG avatar is ~30 KB; this only stops abuse
EXPORT_FORMAT = "harvis-profile"
EXPORT_VERSION = 1


class ProfileError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def normalize_name(raw: Any) -> str:
    name = str(raw or "").strip().lower()
    if not name:
        raise ProfileError("Profile name required")
    if not _NAME_RE.match(name) or ".." in name or name in _RESERVED:
        raise ProfileError("Profile names are lowercase letters, digits, '.', '_' or '-' (max 64)")
    return name


async def _records(pool, uid: int) -> dict[str, dict]:
    raw = await settings_store.get_key(pool, uid, PROFILES_KEY, {})
    return {k: v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}


async def _save(pool, uid: int, records: dict[str, dict]) -> None:
    await settings_store.set_key(pool, uid, PROFILES_KEY, records)


async def _require(pool, uid: int, name: str) -> tuple[dict[str, dict], dict]:
    records = await _records(pool, uid)
    if name == DEFAULT:
        return records, records.setdefault(DEFAULT, {})
    if name not in records:
        raise ProfileError(f"profile not found: {name}", 404)
    return records, records[name]


# ── soul / model (default routes to Harvis's own persona + picker) ──────────

async def get_soul(pool, uid: int, name: str) -> dict:
    """ProfileSoul: {content, exists}."""
    if name == DEFAULT:
        saved = await soul_loader.load_soul(pool, uid)
        exists = bool(saved and saved.strip())
        return {"content": saved if exists else soul_loader.DEFAULT_SOUL_MD, "exists": exists}
    _, rec = await _require(pool, uid, name)
    content = str(rec.get("soul") or "")
    return {"content": content, "exists": bool(content.strip())}


async def set_soul(pool, uid: int, name: str, content: Any) -> None:
    text = content if isinstance(content, str) else ""
    if len(text) > MAX_SOUL_CHARS:
        raise ProfileError("SOUL.md is too large")
    if name == DEFAULT:
        if await soul_loader.save_soul(pool, uid, text) is None:
            raise ProfileError("could not save the persona", 500)
        return
    records, rec = await _require(pool, uid, name)
    rec["soul"] = text
    await _save(pool, uid, records)
    await _sync_bot(pool, uid, name, rec)


async def _model_of(pool, uid: int, name: str, rec: dict) -> tuple[str | None, str | None]:
    if name == DEFAULT:
        return (await store.get_default_model(pool, uid)) or "harvis-default", "harvis"
    return rec.get("model") or None, rec.get("provider") or None


# ── profile ↔ Harvis bot bridge ─────────────────────────────────────────────
# Bot Mode's roster is profiles, but a chat's agent identity (system prompt,
# model) and its per-bot history are keyed on a Harvis bot (bots.py,
# ``owui_subagents`` + ``chat.bot_id``). Every non-default profile is therefore
# backed by one bot, linked by ``rec["bot_id"]`` so the profile name and the
# bot handle never have to agree. Bots made on the old /bots page are adopted
# into the roster on the next list, so there is one set of bots, not two.

CANONICAL_TITLE = "Bot Chat"  # hermes-bots canonical-chat.ts CANONICAL_CHAT_TITLE
PREVIEW_CHARS = 160


def _bot_fields(name: str, rec: dict, base: Optional[dict] = None) -> dict:
    """The bot body for create/update. update_bot REPLACES the row, so the bot's
    own extras (avatar, notebooks, starters, tools) are carried through from ``base``."""
    from . import bots
    base = base or {}
    return {
        "title": (rec.get("display_name") or base.get("name") or name)[: bots.MAX_NAME],
        "description": str(rec.get("description") or "")[: bots.MAX_DESCRIPTION],
        # SOUL.md may be far longer than a bot's instructions allow; the profile
        # keeps the full text, the bot gets the prefix it can hold.
        "instructions": str(rec.get("soul") or "")[: bots.MAX_INSTRUCTIONS],
        "model": str(rec.get("model") or "")[: bots.MAX_MODEL],
        "avatar": base.get("avatar") or None,
        "notebook_ids": base.get("notebook_ids") or [],
        "starter_prompts": base.get("starter_prompts") or [],
        "tools": base.get("tools") or None,
    }


async def ensure_bot(pool, uid: int, name: str) -> Optional[dict]:
    """The Harvis bot behind a non-default profile, creating it on first need."""
    from . import bots
    if name == DEFAULT:
        return None
    records, rec = await _require(pool, uid, name)
    bot = await bots.get_bot(pool, uid, str(rec.get("bot_id") or ""))
    if bot:
        return bot
    try:
        bot = await bots.create_bot(pool, uid, _bot_fields(name, rec))
    except bots.BotError as exc:
        raise ProfileError(f"could not create a bot for {name}: {exc}") from exc
    rec["bot_id"] = bot["id"]
    await _save(pool, uid, records)
    return bot


async def resolve_session_bot(pool, uid: int, profile: Any) -> Optional[dict]:
    """The bot a ``session.create`` for ``profile`` should speak as (None = plain Harvis)."""
    raw = str(profile or "").strip()
    if not raw:
        return None
    try:
        name = normalize_name(raw)
        return await ensure_bot(pool, uid, name)
    except Exception as exc:  # noqa: BLE001 — a chat must still open as plain Harvis
        logger.warning("profile %r has no bot identity (%s); using plain Harvis", raw, exc)
        return None


async def _sync_bot(pool, uid: int, name: str, rec: dict) -> None:
    """Mirror the profile's identity onto its bot. Best effort: a bot-side
    validation failure must not undo a profile edit the user just made."""
    from . import bots
    if name == DEFAULT or not rec.get("bot_id"):
        return
    try:
        base = await bots.get_bot(pool, uid, str(rec["bot_id"]))
        if base:
            await bots.update_bot(pool, uid, base["id"], _bot_fields(name, rec, base))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not sync bot for profile %s: %s", name, exc)


def _unique_name(base: str, records: dict[str, dict]) -> str:
    try:
        stem = normalize_name(base)
    except ProfileError:
        stem = "bot"
    name, n = stem, 1
    while name == DEFAULT or name in records:
        n += 1
        name = f"{stem[:58]}-{n}"
    return name


async def _adopt_bots(pool, uid: int, records: dict[str, dict]) -> bool:
    """Give every Harvis bot that no profile links to a profile record. Returns
    True when records changed (the caller saves once)."""
    from . import bots
    try:
        all_bots = await bots.list_bots(pool, uid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not list bots to adopt: %s", exc)
        return False
    linked = {str(r.get("bot_id")) for r in records.values() if r.get("bot_id")}
    changed = False
    for bot in all_bots:
        if bot["id"] in linked:
            continue
        name = _unique_name(bot.get("handle") or bot.get("name") or "bot", records)
        records[name] = {
            "created_at": time.time(),
            "display_name": bot.get("name") or name,
            "description": bot.get("description") or "",
            "soul": bot.get("instructions") or "",
            "model": bot.get("model") or None,
            "bot_id": bot["id"],
        }
        changed = True
    return changed


def _content_text(raw: Any) -> str:
    """A message's content as plain text (asyncpg hands JSONB back as a string;
    content is a string or a list of {type, text} parts)."""
    value = raw
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, list):
        value = " ".join(str(p.get("text") or "") for p in value if isinstance(p, dict))
    return " ".join(str(value or "").split())[:PREVIEW_CHARS]


_PREVIEW_SQL = """
WITH picked AS (
    SELECT DISTINCT ON (chat->>'bot_id', title = $3)
           id, chat->>'bot_id' AS bot_id, title, updated_at
    FROM owui_chats
    WHERE user_id = $1 AND chat->>'bot_id' = ANY($2::text[])
    ORDER BY chat->>'bot_id', title = $3, updated_at DESC
)
SELECT p.bot_id, p.id, p.title, p.updated_at,
       (SELECT m->'content' FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(c.chat->'messages') = 'array'
                 THEN c.chat->'messages' ELSE '[]'::jsonb END) WITH ORDINALITY AS t(m, i)
        ORDER BY i DESC LIMIT 1) AS last_content
FROM picked p JOIN owui_chats c ON c.id = p.id
"""


async def _chat_previews(pool, uid: int, bot_ids: list[str]) -> dict[str, dict]:
    """Per bot: its canonical Bot Chat and its newest other chat, each with the
    LAST message said (any role) as the preview. One query for the whole roster."""
    if not bot_ids:
        return {}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_PREVIEW_SQL, uid, bot_ids, CANONICAL_TITLE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bot previews unavailable: %s", exc)
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        sid = str(r["id"])
        entry = {"last_active": r["updated_at"].timestamp() if r["updated_at"] else None,
                 "preview": _content_text(r["last_content"])}
        slot = out.setdefault(r["bot_id"], {})
        if (r["title"] or "") == CANONICAL_TITLE:
            slot["canonical_session"] = {**entry, "id": sid, "resolved_id": sid,
                                         "title": CANONICAL_TITLE, "root_title": CANONICAL_TITLE}
        else:
            slot["last_session"] = entry
    return out


# ── roster ───────────────────────────────────────────────────────────────────

async def _row(pool, uid: int, name: str, rec: dict, preview: Optional[dict] = None) -> dict:
    """One row that satisfies both ProfileInfo (REST) and RosterRow (Bot Mode)."""
    model, provider = await _model_of(pool, uid, name, rec)
    ui_meta = rec.get("ui_meta") if isinstance(rec.get("ui_meta"), dict) else {}
    preview = preview or {}
    return {
        "name": name,
        "display_name": rec.get("display_name") or ("Harvis" if name == DEFAULT else name),
        "description": rec.get("description") or "",
        "title": rec.get("title"),
        "path": f"/harvis/{name}",
        "is_default": name == DEFAULT,
        "has_env": name == DEFAULT,
        "model": model,
        "provider": provider,
        "skill_count": 0,
        "has_avatar": bool((rec.get("assets") or {}).get("avatar")),
        "ui_meta": ui_meta,
        "ui_meta_revisions": {k: int(rec.get("ui_meta_rev") or 0) for k in ui_meta},
        "last_session": preview.get("last_session"),
        "canonical_session": preview.get("canonical_session"),
        "created_at": rec.get("created_at"),
    }


async def list_profiles(pool, uid: int) -> list[dict]:
    records = await _records(pool, uid)
    if await _adopt_bots(pool, uid, records):
        await _save(pool, uid, records)
    names = sorted(k for k in records if k != DEFAULT)
    previews = await _chat_previews(
        pool, uid, [str(records[n]["bot_id"]) for n in names if records[n].get("bot_id")])
    rows = [await _row(pool, uid, DEFAULT, records.get(DEFAULT) or {})]
    for name in names:
        rec = records[name]
        rows.append(await _row(pool, uid, name, rec, previews.get(str(rec.get("bot_id") or ""))))
    return rows


def profiles_payload(rows: list[dict]) -> dict:
    return {"profiles": rows}


async def describe(pool, uid: int, name: str) -> dict:
    _, rec = await _require(pool, uid, name)
    model, provider = await _model_of(pool, uid, name, rec)
    return {
        **await _row(pool, uid, name, rec),
        "soul": (await get_soul(pool, uid, name))["content"],
        "model": {"default": model or "", "provider": provider or ""},
        "skills": [], "toolsets": [], "mcp_servers": [],
    }


# ── portable document (export / import) ─────────────────────────────────────

async def export_document(pool, uid: int, name: str) -> dict:
    records, rec = await _require(pool, uid, name)
    model, provider = await _model_of(pool, uid, name, rec)
    ui_meta = rec.get("ui_meta") if isinstance(rec.get("ui_meta"), dict) else {}
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "name": name,
        "display_name": rec.get("display_name") or ("Harvis" if name == DEFAULT else name),
        "description": str(rec.get("description") or ""),
        "soul": (await get_soul(pool, uid, name))["content"],
        "model": model,
        "provider": provider,
        "ui_meta": ui_meta,
    }


async def import_document(pool, uid: int, document: Any, name_override: Any = None) -> dict:
    """Create a NEW profile from an exported document; an existing name gets a numeric suffix."""
    if not isinstance(document, dict) or document.get("format") != EXPORT_FORMAT:
        raise ProfileError("not a Harvis profile export (expected format 'harvis-profile')")
    if document.get("version") not in (None, EXPORT_VERSION):
        raise ProfileError("unsupported profile export version")
    base = normalize_name(name_override if isinstance(name_override, str) and name_override.strip()
                          else document.get("name"))
    records = await _records(pool, uid)
    name, n = base, 1
    while name == DEFAULT or name in records:
        n += 1
        name = f"{base[:60]}-{n}"
    payload: dict[str, Any] = {"name": name, "description": document.get("description") or ""}
    if isinstance(document.get("soul"), str):
        payload["soul"] = document["soul"]
    if document.get("model") and document.get("provider"):
        payload["model"], payload["provider"] = document["model"], document["provider"]
    row = await create(pool, uid, payload)
    extras: dict[str, Any] = {}
    if isinstance(document.get("display_name"), str) and document["display_name"].strip():
        extras["display_name"] = document["display_name"].strip()[:80]
    if isinstance(document.get("ui_meta"), dict):
        extras["ui_meta"] = document["ui_meta"]
    if extras:
        records = await _records(pool, uid)
        records[name].update(extras)
        await _save(pool, uid, records)
    return row


# ── mutations ────────────────────────────────────────────────────────────────

async def create(pool, uid: int, payload: dict) -> dict:
    name = normalize_name(payload.get("name"))
    records = await _records(pool, uid)
    if name == DEFAULT or name in records:
        raise ProfileError(f"profile already exists: {name}", 409)
    rec: dict[str, Any] = {"created_at": time.time(),
                           "description": str(payload.get("description") or "")}
    clone_from = payload.get("clone_from")
    if clone_from is None and payload.get("clone_from_default"):
        clone_from = DEFAULT
    if isinstance(clone_from, str) and clone_from.strip():
        src = normalize_name(clone_from)
        _, src_rec = await _require(pool, uid, src)
        rec["soul"] = (await get_soul(pool, uid, src))["content"]
        if src != DEFAULT:
            rec["model"], rec["provider"] = src_rec.get("model"), src_rec.get("provider")
    if isinstance(payload.get("soul"), str):
        rec["soul"] = payload["soul"][:MAX_SOUL_CHARS]
    if payload.get("model") and payload.get("provider"):
        rec["model"], rec["provider"] = str(payload["model"]), str(payload["provider"])
    records[name] = rec
    await _save(pool, uid, records)
    # Back the new profile with a bot now, so its first chat already speaks as it.
    # Best effort: the profile exists either way, and ensure_bot runs again on
    # its first session.create if this attempt failed.
    try:
        await ensure_bot(pool, uid, name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("profile %s created without a bot yet: %s", name, exc)
    return await _row(pool, uid, name, (await _records(pool, uid)).get(name, rec))


async def configure(pool, uid: int, name: str, payload: dict) -> dict:
    """profiles.configure: apply each present section; report what was applied."""
    applied: dict[str, bool] = {}
    if isinstance(payload.get("soul"), str):
        await set_soul(pool, uid, name, payload["soul"])
        applied["soul"] = True
    records, rec = await _require(pool, uid, name)
    if "model" in payload or "provider" in payload:
        model, provider = str(payload.get("model") or ""), str(payload.get("provider") or "")
        if name == DEFAULT:
            await store.set_default_model(pool, uid, "" if model == "harvis-default" else model)
        else:
            rec["model"], rec["provider"] = model or None, provider or None
        applied["model"] = True
    for key in ("description", "display_name", "title"):
        if isinstance(payload.get(key), str):
            rec[key] = payload[key][:500]
            applied[key] = True
    if isinstance(payload.get("ui_meta"), dict):
        merged = dict(rec.get("ui_meta") or {})
        merged.update(payload["ui_meta"])
        rec["ui_meta"] = merged
        rec["ui_meta_rev"] = int(rec.get("ui_meta_rev") or 0) + 1
        applied["ui_meta"] = True
    for key in ("disabled_skills", "enabled_toolsets", "enabled_mcp_servers"):
        if isinstance(payload.get(key), list):
            rec[key] = [str(v) for v in payload[key]]
            applied[key] = True
    await _save(pool, uid, records)
    if applied.keys() & {"model", "description", "display_name"}:
        await _sync_bot(pool, uid, name, rec)
    return {"ok": True, "applied": applied}


async def rename(pool, uid: int, name: str, new_name: Any) -> str:
    target = normalize_name(new_name)
    if name == DEFAULT:
        raise ProfileError("The default profile cannot be renamed")
    records, rec = await _require(pool, uid, name)
    if target == DEFAULT or target in records:
        raise ProfileError(f"profile already exists: {target}", 409)
    del records[name]
    records[target] = rec
    await _save(pool, uid, records)
    return target


async def delete(pool, uid: int, name: str) -> None:
    if name == DEFAULT:
        raise ProfileError("The default profile cannot be deleted")
    from . import bots
    records, rec = await _require(pool, uid, name)
    bot_id = str(rec.get("bot_id") or "")
    del records[name]
    await _save(pool, uid, records)
    # The bot IS this profile's identity; leaving it would re-adopt it next list.
    if bot_id:
        try:
            await bots.delete_bot(pool, uid, bot_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("profile %s deleted but its bot %s was not: %s", name, bot_id, exc)


async def set_asset(pool, uid: int, name: str, asset: Any, data: Any) -> None:
    key = str(asset or "").strip()
    if key != "avatar":
        raise ProfileError("only the 'avatar' asset is supported")
    if not isinstance(data, str) or not data.startswith("data:image/") or len(data) > MAX_ASSET_CHARS:
        raise ProfileError("avatar must be an image data URL under 1.5 MB")
    records, rec = await _require(pool, uid, name)
    rec.setdefault("assets", {})[key] = data
    await _save(pool, uid, records)


async def get_asset(pool, uid: int, name: str, asset: Any) -> dict:
    _, rec = await _require(pool, uid, name)
    data = (rec.get("assets") or {}).get(str(asset or ""))
    return {"found": bool(data), "data": data or None}


# ── REST ─────────────────────────────────────────────────────────────────────

def _uid(user) -> int:
    return int(getattr(user, "id", None) or getattr(user, "user_id", None) or user["id"])


def _http(exc: ProfileError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


def _name(raw: str) -> str:
    try:
        return normalize_name(raw)
    except ProfileError as exc:
        raise _http(exc) from exc


# Two desktop reads with nothing behind them in Harvis yet. They answer with the
# protocol's empty shapes (same as ws.m_projects_tree) instead of the facade's 404.
@router.get("/projects/tree")
async def profiles_projects_tree(user=Depends(get_current_user_optimized)):
    return {"projects": [], "active_id": None, "scoped_session_ids": []}


@router.post("/sessions/pull-requests")
async def profiles_session_pull_requests(request: Request, user=Depends(get_current_user_optimized)):
    """Harvis sessions are not tied to git branches, so no session has a pull request."""
    ids = (await _body(request)).get("ids")
    scanned = [str(i) for i in ids][:500] if isinstance(ids, list) else []
    return {"pull_requests": {}, "scanned": scanned}


@router.get("")
async def profiles_list(request: Request, user=Depends(get_current_user_optimized)):
    return profiles_payload(await list_profiles(request.app.state.pg_pool, _uid(user)))


@router.get("/active")
async def profiles_active(user=Depends(get_current_user_optimized)):
    return {"current": DEFAULT, "profile": DEFAULT}


@router.post("")
async def profiles_create(request: Request, user=Depends(get_current_user_optimized)):
    try:
        row = await create(request.app.state.pg_pool, _uid(user), await _body(request))
    except ProfileError as exc:
        raise _http(exc) from exc
    return {"ok": True, "name": row["name"], "path": row["path"]}


@router.post("/import")
async def profiles_import(request: Request, user=Depends(get_current_user_optimized)):
    """Create a profile from a document produced by ``/{name}/export`` (JSON, not a tarball)."""
    body = await _body(request)
    document = body.get("archive") if isinstance(body.get("archive"), dict) else body
    try:
        row = await import_document(request.app.state.pg_pool, _uid(user), document, body.get("name"))
    except ProfileError as exc:
        raise _http(exc) from exc
    return {"ok": True, "name": row["name"], "path": row["path"], "desktop": None}


@router.post("/{name}/export")
async def profiles_export(name: str, request: Request, user=Depends(get_current_user_optimized)):
    """The profile as one JSON document (soul + model + description); no secrets are included."""
    try:
        document = await export_document(request.app.state.pg_pool, _uid(user), _name(name))
    except ProfileError as exc:
        raise _http(exc) from exc
    return {"ok": True, "archive": document, "name": document["name"]}


@router.get("/{name}/setup-command")
async def profiles_setup_command(name: str, user=Depends(get_current_user_optimized)):
    raise HTTPException(501, "Harvis profiles have no CLI setup command; they are ready to use from this page.")


@router.get("/{name}/soul")
async def profiles_soul(name: str, request: Request, user=Depends(get_current_user_optimized)):
    try:
        return await get_soul(request.app.state.pg_pool, _uid(user), _name(name))
    except ProfileError as exc:
        raise _http(exc) from exc


@router.put("/{name}/soul")
async def profiles_soul_put(name: str, request: Request, user=Depends(get_current_user_optimized)):
    try:
        await set_soul(request.app.state.pg_pool, _uid(user), _name(name), (await _body(request)).get("content"))
    except ProfileError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.patch("/{name}")
async def profiles_patch(name: str, request: Request, user=Depends(get_current_user_optimized)):
    pool, uid, body = request.app.state.pg_pool, _uid(user), await _body(request)
    try:
        current = _name(name)
        if "new_name" in body:
            current = await rename(pool, uid, current, body["new_name"])
        else:
            await configure(pool, uid, current, body)
    except ProfileError as exc:
        raise _http(exc) from exc
    return {"ok": True, "name": current, "path": f"/harvis/{current}"}


@router.delete("/{name}")
async def profiles_delete(name: str, request: Request, user=Depends(get_current_user_optimized)):
    try:
        await delete(request.app.state.pg_pool, _uid(user), _name(name))
    except ProfileError as exc:
        raise _http(exc) from exc
    return {"ok": True, "path": f"/harvis/{name}"}
