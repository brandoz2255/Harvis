"""The trust spine for skills a model writes: it may only PROPOSE, a person approves.

A skill is text the model reads on later turns, so whoever can change that text
can steer every later chat. Three rules keep that in human hands:

* A model proposes. ``propose`` writes ``meta.pending`` and nothing else on an
  existing skill; it never touches ``content``, ``enabled`` or ``meta.audit``.
  A new name gets a disabled, empty placeholder row that carries the proposal.
* A person approves. ``approve`` swaps the pending text in and stamps
  ``audit.content_sha`` with a hash of exactly what was approved: the body AND
  the script files, because swapping a script after approval would be the same
  attack as swapping the body.
* A later change to the text invalidates the approval. ``sha_ok`` is the check
  the skill gate runs; a stored hash that no longer matches makes the skill
  unavailable. Rows with no hash are older approvals and keep working.

Skill script files live in ``meta.files`` as ``{"scripts/name.py": "<text>"}``.
The backend only stores and mirrors them into the sandbox; it never runs them.
"""
from __future__ import annotations

import difflib
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

MAX_CONTENT = 20000
MAX_DESCRIPTION = 1000
MAX_FILES = 5
MAX_FILE_BYTES = 20 * 1024
MAX_DIFF_CHARS = 40000

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}")
_FILE_RE = re.compile(r"scripts/[A-Za-z0-9_.-]+\.(?:py|sh|js)")
_SECRET_RE = re.compile(r"sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}")

# Written at the top of every mirrored script so a later sync knows the file is
# Harvis's to replace or remove, and one the user wrote is left alone.
SCRIPT_MARK = "Harvis mirrors this from Skills; edit it there, changes here are replaced."


class SkillPendingError(ValueError):
    """A refusal whose message is safe to show. ``code`` is one of invalid,
    not_found, no_pending, stale, unchanged."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def meta_dict(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001 — unreadable meta is treated as empty
            return {}
    return raw if isinstance(raw, dict) else {}


def approval_record(user_id: int, via: str, sha: Optional[str] = None) -> dict:
    """The audit record a person approving a skill leaves behind."""
    rec = {"verdict": "supported", "approved_by": user_id, "via": via,
           "approved_at": datetime.now(timezone.utc).isoformat()}
    if sha:
        rec["content_sha"] = sha
    return rec


# ── content hash ─────────────────────────────────────────────────────────────

def clean_files(files: Any) -> dict[str, str]:
    """Validated script files, or SkillPendingError. None and {} mean no files."""
    if files in (None, {}, []):
        return {}
    if not isinstance(files, dict):
        raise SkillPendingError("invalid", "Skill files must be a mapping of path to text.")
    if len(files) > MAX_FILES:
        raise SkillPendingError("invalid", f"A skill can carry at most {MAX_FILES} script files.")
    out: dict[str, str] = {}
    for path, body in files.items():
        if not isinstance(path, str) or not _FILE_RE.fullmatch(path):
            raise SkillPendingError(
                "invalid", "Script files must be named scripts/<name>.py, .sh or .js (letters, digits, . _ -).")
        if not isinstance(body, str) or "\x00" in body:
            raise SkillPendingError("invalid", f"{path} must be plain text.")
        try:
            size = len(body.encode("utf-8"))
        except UnicodeEncodeError:
            raise SkillPendingError("invalid", f"{path} must be plain text.") from None
        if size > MAX_FILE_BYTES:
            raise SkillPendingError("invalid", f"{path} is over {MAX_FILE_BYTES // 1024} KB.")
        out[path] = body
    return out


def content_sha(content: Optional[str], files: Any = None) -> str:
    """Hash of the skill body and its script files. The same text always hashes
    the same; no files, None and {} are one case. Raises SkillPendingError when
    ``files`` is not a mapping, so callers fail closed on a corrupt row."""
    if files in (None, {}, []):
        files = {}
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        raise SkillPendingError("invalid", "Skill files are not readable.")
    payload = json.dumps({"content": content or "", "files": {k: files[k] for k in sorted(files)}},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", "surrogatepass")).hexdigest()


def sha_ok(content: Optional[str], meta: Any) -> bool:
    """False only when a human approval hash exists and the text no longer
    matches it. No stored hash is a legacy approval and stays True."""
    meta = meta_dict(meta)
    audit = meta.get("audit") if isinstance(meta.get("audit"), dict) else {}
    stored = audit.get("content_sha")
    if not stored:
        return True
    try:
        return hmac.compare_digest(str(stored), content_sha(content, meta.get("files")))
    except Exception:  # noqa: BLE001 — fail closed
        return False


# ── script mirroring helpers (used by the sandbox) ───────────────────────────

def script_text(path: str, body: str) -> str:
    """``body`` with the mirror mark as a comment, after a shebang line if there is one."""
    mark = ("// " if path.endswith(".js") else "# ") + SCRIPT_MARK
    if body.startswith("#!"):
        first, _, rest = body.partition("\n")
        return f"{first}\n{mark}\n{rest}"
    return f"{mark}\n{body}"


def is_mirrored_script(text: str) -> bool:
    return any(SCRIPT_MARK in line for line in text.split("\n", 2)[:2])


# ── propose / approve / reject ───────────────────────────────────────────────

_SELECT = ("SELECT id, description, content, meta, enabled FROM owui_skills "
           "WHERE user_id=$1 AND name=$2 FOR UPDATE")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_proposal(description: str, content: str, files: Any) -> tuple[str, str, dict]:
    content = str(content or "")
    if not content.strip():
        raise SkillPendingError("invalid", "A skill can't be empty.")
    if len(content) > MAX_CONTENT:
        raise SkillPendingError("invalid", f"A skill can be at most {MAX_CONTENT} characters.")
    if "\x00" in content:
        raise SkillPendingError("invalid", "A skill must be plain text.")
    if _SECRET_RE.search(content):
        raise SkillPendingError("invalid", "The skill contains something that looks like a credential.")
    description = " ".join(str(description or "").split())[:MAX_DESCRIPTION]
    return description, content, clean_files(files)


async def propose(conn, user_id: int, name: str, description: str, content: str, files: Any,
                  proposed_by: str, session_id: Optional[str]) -> dict:
    """Record a revision for a person to approve. Writes only ``meta.pending`` on
    an existing skill. A new name gets a disabled placeholder row with no body,
    so there is somewhere for the proposal to sit and nothing a chat could inject.
    Replaces any earlier pending revision of the same skill."""
    import uuid

    name = (name or "").strip()
    if not _NAME_RE.fullmatch(name):
        raise SkillPendingError("invalid", "Use letters, numbers, spaces, dots, dashes or underscores (up to 64) for a skill name.")
    description, content, files = _clean_proposal(description, content, files)
    pending = {"description": description, "content": content, "files": files,
               "proposed_by": str(proposed_by or "")[:200], "session_id": str(session_id or "")[:200] or None,
               "at": _now(), "base_sha": ""}
    async with conn.transaction():
        # FOR UPDATE locks nothing when the row does not exist yet, and the table has no
        # unique (user_id, name). Serialise proposers per (user, name) so a second one
        # waits, sees the placeholder, and becomes a revision of it instead of a twin row.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1::text))", f"owui_skills:{int(user_id)}:{name}")
        row = await conn.fetchrow(_SELECT, int(user_id), name)
        if row is None:
            pending["base_sha"] = content_sha("", {})
            meta = {"pending": pending, "audit": {}, "source": "chat_proposed", "category": "drafts"}
            await conn.execute(
                "INSERT INTO owui_skills (id, user_id, name, description, content, meta, enabled) "
                "VALUES ($1, $2, $3, $4, '', $5::jsonb, FALSE)",
                str(uuid.uuid4()), int(user_id), name, description, json.dumps(meta))
            return {"name": name, "created": True, "pending_sha": content_sha(content, files)}
        meta = meta_dict(row["meta"])
        try:
            pending["base_sha"] = content_sha(row["content"], meta.get("files"))
        except SkillPendingError:
            pending["base_sha"] = ""
        if (pending["base_sha"] == content_sha(content, files)
                and description in ("", (row["description"] or "").strip())):
            raise SkillPendingError("unchanged", f"{name} already has exactly this text.")
        meta["pending"] = pending
        await conn.execute("UPDATE owui_skills SET meta=$2::jsonb WHERE id=$1", row["id"], json.dumps(meta))
    return {"name": name, "created": False, "pending_sha": content_sha(content, files)}


def _pending_of(meta: dict) -> dict:
    pending = meta.get("pending")
    if not isinstance(pending, dict):
        raise SkillPendingError("no_pending", "There is nothing waiting for approval on this skill.")
    return pending


def _is_placeholder(row, meta: dict) -> bool:
    """An empty shell ``propose`` made for a brand-new name: never approved, no body."""
    audit = meta.get("audit") if isinstance(meta.get("audit"), dict) else {}
    return (not (row["content"] or "").strip() and audit.get("verdict") != "supported"
            and meta.get("source") == "chat_proposed" and not meta.get("files"))


async def approve(conn, user_id: int, name: str, approver: int, *, expected_sha: Optional[str] = None,
                  via: str = "hermes-pending-approve") -> dict:
    """Swap the pending revision in and stamp the hash of what was approved.
    ``expected_sha`` is the hash the person saw (the listing's ``pending_sha``);
    a different pending revision since then is refused, so an approval can never
    cover text the person did not look at. Approving a brand-new proposal also
    switches the skill on; approving a revision leaves ``enabled`` as it was."""
    name = (name or "").strip()
    async with conn.transaction():
        row = await conn.fetchrow(_SELECT, int(user_id), name)
        if row is None:
            raise SkillPendingError("not_found", f"No skill called {name}.")
        meta = meta_dict(row["meta"])
        pending = _pending_of(meta)
        description, content, files = _clean_proposal(pending.get("description"), pending.get("content"),
                                                      pending.get("files"))
        sha = content_sha(content, files)
        if expected_sha and not hmac.compare_digest(str(expected_sha), sha):
            raise SkillPendingError("stale", "This skill's proposal changed after you opened it. Review it again.")
        prior = meta.get("audit") if isinstance(meta.get("audit"), dict) else {}
        enable = not (row["content"] or "").strip() and prior.get("verdict") != "supported"
        new_meta = {k: v for k, v in meta.items() if k not in ("pending", "files", "audit", "stale_after_edit")}
        new_meta["audit"] = approval_record(int(approver), via, sha)
        if files:
            new_meta["files"] = files
        if new_meta.get("category") == "drafts":
            new_meta["category"] = "learned"
        await conn.execute(
            "UPDATE owui_skills SET description=$2, content=$3, meta=$4::jsonb, "
            "enabled=(enabled OR $5), updated_at=NOW() WHERE id=$1",
            row["id"], description or (row["description"] or ""), content, json.dumps(new_meta), enable)
    return {"name": name, "content_sha": sha, "enabled": bool(row["enabled"] or enable)}


async def reject(conn, user_id: int, name: str) -> dict:
    """Drop the pending revision. An empty placeholder ``propose`` made for a new
    name goes with it; a skill that was ever approved or written by hand stays."""
    name = (name or "").strip()
    async with conn.transaction():
        row = await conn.fetchrow(_SELECT, int(user_id), name)
        if row is None:
            raise SkillPendingError("not_found", f"No skill called {name}.")
        meta = meta_dict(row["meta"])
        _pending_of(meta)
        if _is_placeholder(row, meta):
            await conn.execute("DELETE FROM owui_skills WHERE id=$1", row["id"])
            return {"name": name, "removed_row": True}
        meta.pop("pending", None)
        await conn.execute("UPDATE owui_skills SET meta=$2::jsonb WHERE id=$1", row["id"], json.dumps(meta))
    return {"name": name, "removed_row": False}


# ── review listing ───────────────────────────────────────────────────────────

def _diff(old: str, new: str) -> str:
    lines = difflib.unified_diff((old or "").splitlines(), (new or "").splitlines(),
                                 "current", "proposed", lineterm="")
    return "\n".join(lines)[:MAX_DIFF_CHARS]


async def list_pending(conn, user_id: int) -> list[dict]:
    """Every skill with a revision waiting, with the full proposed text, a diff
    against what is stored now, and the hash an approval must quote back."""
    rows = await conn.fetch(
        "SELECT name, description, content, meta, enabled FROM owui_skills "
        "WHERE user_id=$1 AND meta ? 'pending' ORDER BY updated_at DESC", int(user_id))
    items: list[dict] = []
    for r in rows:
        meta = meta_dict(r["meta"])
        pending = meta.get("pending")
        if not isinstance(pending, dict):
            continue
        try:
            files = clean_files(pending.get("files"))
            pending_sha = content_sha(pending.get("content"), files)
        except SkillPendingError:
            continue  # a malformed revision is not offered for approval
        old_files = meta.get("files") if isinstance(meta.get("files"), dict) else {}
        file_rows = []
        for path in sorted(set(files) | set(old_files)):
            new, old = files.get(path), old_files.get(path)
            file_rows.append({"path": path, "content": new,
                              "status": "removed" if new is None else "added" if old is None
                              else "unchanged" if new == old else "changed",
                              "diff": "" if new == old else _diff(old or "", new or "")})
        try:
            stale = pending.get("base_sha") != content_sha(r["content"], old_files)
        except SkillPendingError:
            stale = True
        items.append({
            "name": r["name"], "enabled": bool(r["enabled"]), "is_new": not (r["content"] or "").strip(),
            "current_description": r["description"] or "", "current_content": r["content"] or "",
            "description": str(pending.get("description") or ""), "content": str(pending.get("content") or ""),
            "files": file_rows, "diff": _diff(r["content"] or "", str(pending.get("content") or "")),
            "proposed_by": pending.get("proposed_by"), "session_id": pending.get("session_id"),
            "at": pending.get("at"), "pending_sha": pending_sha, "stale": stale})
    return items


# ── human approval stamps ────────────────────────────────────────────────────

_ENABLE_SQL = (
    "UPDATE owui_skills SET enabled=$3, updated_at=NOW(), meta = CASE WHEN $3 THEN "
    "  (CASE WHEN COALESCE(meta->'audit'->>'verdict','') = 'supported' THEN meta "
    "        ELSE jsonb_set(meta, '{audit}', $4::jsonb) END)"
    "  || (CASE WHEN meta->>'category' = 'drafts' THEN '{\"category\":\"learned\"}'::jsonb "
    "           ELSE '{}'::jsonb END) "
    "ELSE meta END "
    "WHERE user_id=$1 AND {col}=$2")

_STAMP_SQL = ("UPDATE owui_skills SET meta = jsonb_set(meta, '{{audit,content_sha}}', to_jsonb($3::text), true) "
              "WHERE user_id=$1 AND {col}=$2 AND meta->'audit'->>'verdict' = 'supported'{guard}")


def _target(name: Optional[str], skill_id: Optional[str]) -> tuple[str, str]:
    return ("id", str(skill_id)) if skill_id is not None else ("name", str(name))


async def stamp_current(conn, user_id: int, *, name: Optional[str] = None, skill_id: Optional[str] = None) -> bool:
    """Record the hash of the skill's text as it is now, on an approved skill. The
    write is conditional on that text still being there, so an edit that lands
    between the read and the write is never stamped by mistake."""
    col, val = _target(name, skill_id)
    row = await conn.fetchrow(f"SELECT content, meta FROM owui_skills WHERE user_id=$1 AND {col}=$2", int(user_id), val)
    if not row:
        return False
    meta = meta_dict(row["meta"])
    audit = meta.get("audit") if isinstance(meta.get("audit"), dict) else {}
    if audit.get("verdict") != "supported":
        return False
    files = meta.get("files")
    try:
        sha = content_sha(row["content"], files)
    except SkillPendingError:
        return False
    guard = " AND content=$4 AND meta->'files' IS NOT DISTINCT FROM $5::jsonb"
    tag = await conn.execute(_STAMP_SQL.format(col=col, guard=guard), int(user_id), val, sha,
                             row["content"], None if files is None else json.dumps(files))
    return str(tag).endswith("1")


async def stamp_new_content(conn, user_id: int, name: str, content: str) -> None:
    """Before a person's edit is written: hash the new text, with the skill's
    existing files, onto an approved skill. Until the edit lands the old text no
    longer matches, which fails closed."""
    row = await conn.fetchrow("SELECT meta FROM owui_skills WHERE user_id=$1 AND name=$2", int(user_id), name)
    try:
        meta = meta_dict(row["meta"])
    except (KeyError, TypeError):  # no such skill (the edit will 404), or a row without meta
        meta = {}
    audit = meta.get("audit") if isinstance(meta.get("audit"), dict) else {}
    if audit.get("verdict") != "supported":
        return
    try:
        sha = content_sha(content, meta.get("files"))
    except SkillPendingError:
        return
    await conn.execute(_STAMP_SQL.format(col="name", guard=""), int(user_id), name, sha)


async def set_enabled(conn, user_id: int, *, name: Optional[str] = None, skill_id: Optional[str] = None,
                      enabled: bool, via: str) -> bool:
    """Switch a skill on or off. ON is the person's approval: an unapproved skill
    gets a 'supported' verdict (a draft graduates to 'learned') and every ON
    stamps the hash of the text approved. OFF leaves the audit alone."""
    col, val = _target(name, skill_id)
    tag = await conn.execute(_ENABLE_SQL.replace("{col}", col), int(user_id), val, bool(enabled),
                             json.dumps(approval_record(int(user_id), via)))
    ok = str(tag).endswith("1")
    if ok and enabled:
        await stamp_current(conn, user_id, name=name, skill_id=skill_id)
    return ok
