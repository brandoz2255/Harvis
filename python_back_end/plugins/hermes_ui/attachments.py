"""Chat attachments for the browser Hermes UI.

The browser uploads bytes to ``POST /api/v1/files/`` (an ``owui_files`` row per
file) and sends the ids with ``prompt.submit``. This module checks that every id
is the signed-in user's, shapes the references that are stored on the user
message, and turns a transcript's references into the ``files`` list that
``owui_compat.chat_completion._inject_files`` reads from the completion body.
"""
from __future__ import annotations

from typing import Any, Optional

MAX_FILES_PER_MESSAGE = 20
# A long chat keeps only its newest uploads in front of the model; each one is
# re-read every turn, so an unbounded list grows the prompt and the work per turn.
MAX_FILES_PER_TURN = 10
CUSTOM_ENDPOINT_NOTE = ("(Attached files are not sent to custom endpoints, so this model cannot see them. "
                        "Pick a Harvis model to ask about the files.)\n\n")


class AttachmentError(ValueError):
    pass


def requested_ids(raw: Any) -> list[str]:
    """The file ids a prompt.submit names, in order, without repeats.

    Accepts ``[{"id": ...}, ...]`` (what the composer sends) and bare id strings.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AttachmentError("files must be a list")
    ids: list[str] = []
    seen: set[str] = set()
    for item in raw:
        fid = item.get("id") if isinstance(item, dict) else item
        if not isinstance(fid, str) or not fid.strip():
            raise AttachmentError("every attachment needs a file id")
        fid = fid.strip()
        if fid in seen:
            continue
        seen.add(fid)
        ids.append(fid)
        if len(ids) > MAX_FILES_PER_MESSAGE:
            raise AttachmentError(f"at most {MAX_FILES_PER_MESSAGE} attachments per message")
    return ids


async def owned(pool, user_id: int, ids: list[str]) -> list[dict]:
    """The references for ``ids``, in request order; an id that is not this
    user's upload (or does not exist) raises, so a guessed id never reaches the
    model."""
    if not ids:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, filename, content_type, size FROM owui_files "
            "WHERE user_id = $1 AND id = ANY($2::text[])", user_id, ids)
    by_id = {r["id"]: r for r in rows}
    missing = [fid for fid in ids if fid not in by_id]
    if missing:
        raise AttachmentError("attachment not found or not yours")
    return [reference(by_id[fid]) for fid in ids]


def reference(row) -> dict:
    """What a user message stores (and the UI gets back) for one upload."""
    return {
        "type": "file",
        "id": str(row["id"]),
        "name": str(row["filename"] or ""),
        "content_type": str(row["content_type"] or "application/octet-stream"),
        "size": int(row["size"] or 0),
    }


def turn_files(msgs: list[dict]) -> list[dict]:
    """``body["files"]`` for a turn: the uploads the transcript's user messages
    carry, each once, oldest first, keeping the newest ``MAX_FILES_PER_TURN``.
    OWUI keeps a chat's files on every turn the same way, so a follow-up
    question about a file still sees it."""
    first: dict[str, dict] = {}
    last_seen: dict[str, int] = {}
    n = 0
    for m in msgs:
        if m.get("role") != "user":
            continue
        for ref in m.get("attachments") or []:
            fid = ref.get("id") if isinstance(ref, dict) else None
            if isinstance(fid, str) and fid:
                first.setdefault(fid, {"type": "file", "id": fid, "name": ref.get("name") or ""})
                last_seen[fid] = n
                n += 1
    newest = set(sorted(last_seen, key=last_seen.__getitem__)[-MAX_FILES_PER_TURN:])
    return [ref for fid, ref in first.items() if fid in newest]


def latest_turn_has_files(msgs: list[dict]) -> bool:
    last_user: Optional[dict] = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
    return bool(last_user and last_user.get("attachments"))
