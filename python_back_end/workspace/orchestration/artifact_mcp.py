"""A brokered file-delivery tool for sidecar engines: ``POST /api/workspace/artifact-mcp``.

An auto-launched Claude/Kimi sidecar runs read-only (see the ``--disallowedTools``
list in :mod:`engine_adapter`), so it cannot call ``Write``. That is the correct
posture for a run the user never explicitly asked for — but it also meant a model
asked to "make a 3D model in an HTML page" composed the whole page and then had no
way to hand it over. The run finished with zero artifacts and the UI had no Preview
button to offer, because there was nothing to preview.

This module is the narrow door that fixes that without reopening ``Write``. The
model does not get a filesystem; it gets one tool that accepts a *name*, *content*
and a *media type*, and Harvis decides what that turns into. The backend has no
mount of the sidecar's scratch volume at all, so the delivered bytes go straight
into ``workspace_artifacts`` — which is where the Artifacts tab, the Preview button
and the download endpoints already read from.

That has a pleasant consequence for the threat model: **there is no path on any
filesystem to traverse.** ``relative_path`` is a label on a database row, not a
destination. The rules below (no absolute paths, no ``..``, no hidden segments, a
bounded depth, an extension allowlist) are still enforced, because the label is
shown to a human and used to pick a renderer — but a bug in them cannot escape a
directory, because no directory is ever opened.

What the rules do carry weight for:

* **No overwrite.** A ``path`` already delivered by this run is refused rather than
  replaced, so a second call cannot quietly rewrite the artifact a user already
  opened.
* **Quotas.** A bounded file count and total size per run, so a loop that keeps
  calling this tool fills a quota instead of a disk.
* **Text only.** ``content`` is a string. Nothing here accepts base64 or bytes, so
  this tool cannot be used to smuggle an executable into the artifact store.
* **Identity is injected, never claimed.** The run this writes to comes from a
  server-signed header written at launch, exactly like the CAD context header. The
  model cannot name a workspace, and the bearer token is scoped to one user.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

SERVER_NAME = "harvis-artifacts"
SERVER_INFO = {"name": SERVER_NAME, "version": "0.1"}
PROTOCOL_VERSION = "2024-11-05"

# JSON-RPC 2.0 codes, matching cad_mcp so both doors answer a client the same way.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

TOOL_NAME = "write_new_artifact"

# How a sidecar reaches this endpoint — a sibling container on the backend's own
# Docker network, so the internal service name is the only one that resolves.
SIDECAR_ARTIFACT_MCP_URL = os.getenv(
    "HARVIS_ARTIFACT_MCP_URL", "http://backend:8000/api/workspace/artifact-mcp")

# Same lifetime as the CAD sidecar token: long enough for a slow run, short enough
# that a token left in a process listing is dead before anyone goes looking.
SIDECAR_TOKEN_MINUTES = 90

CONTEXT_HEADER = "x-harvis-artifact-context"

# One file, capped at the same 512 KiB the post-run capture sweep already applies to
# files it finds on disk — so a file delivered through this tool and one written by a
# user-initiated run are subject to the same limit.
MAX_FILE_BYTES = 512 * 1024
MAX_FILES_PER_RUN = 12
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_PATH_LEN = 160
MAX_DEPTH = 3

# Text formats a browser or the artifact viewer can render. Deliberately no archive,
# no binary, no executable script format beyond the .js that an HTML page inlines —
# and .js here is a *stored* file, never something Harvis runs.
ALLOWED_TYPES: dict[str, str] = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".svg": "image/svg+xml",
}

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ArtifactWriteRefused(Exception):
    """A refusal the model should read and correct, not a transport failure."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def normalize_path(raw: Any) -> str:
    """Validate a model-supplied artifact name and return the stored label.

    Rejects anything that would read as a filesystem destination rather than a
    name. See the module docstring for why this is defence in depth rather than
    the only thing standing between the model and the disk.
    """
    if not isinstance(raw, str):
        raise ArtifactWriteRefused("invalid_path", "relative_path must be a string")
    path = raw.strip()
    if not path:
        raise ArtifactWriteRefused("invalid_path", "relative_path is required")
    if len(path) > MAX_PATH_LEN:
        raise ArtifactWriteRefused(
            "invalid_path", f"relative_path is longer than {MAX_PATH_LEN} characters")
    if "\x00" in path or "\\" in path:
        raise ArtifactWriteRefused(
            "invalid_path", "relative_path may not contain backslashes or null bytes")
    if path.startswith("/") or path.startswith("~") or ":" in path:
        raise ArtifactWriteRefused(
            "invalid_path", "relative_path must be relative — no absolute or drive paths")

    segments = path.split("/")
    if len(segments) > MAX_DEPTH:
        raise ArtifactWriteRefused(
            "invalid_path", f"relative_path may be at most {MAX_DEPTH} levels deep")
    for seg in segments:
        if seg in ("", ".", ".."):
            raise ArtifactWriteRefused(
                "invalid_path", "relative_path may not contain empty, '.' or '..' segments")
        if not _SEGMENT_RE.match(seg):
            raise ArtifactWriteRefused(
                "invalid_path",
                "each part of relative_path must start with a letter or digit and use "
                "only letters, digits, dot, dash or underscore")

    ext = "." + segments[-1].rsplit(".", 1)[-1].lower() if "." in segments[-1] else ""
    if ext not in ALLOWED_TYPES:
        allowed = ", ".join(sorted(ALLOWED_TYPES))
        raise ArtifactWriteRefused(
            "unsupported_type", f"{ext or 'a file with no extension'} is not deliverable; "
                                f"allowed: {allowed}")
    return "/".join(segments)


def resolve_media_type(path: str, declared: Any) -> str:
    """The media type for a stored artifact, derived from its extension.

    The extension is authoritative because it is what every downstream renderer
    keys on. A declared type that disagrees is refused rather than ignored — a
    silent correction would let a caller believe it had labelled something one way
    while Harvis stored it another.
    """
    ext = "." + path.rsplit(".", 1)[-1].lower()
    derived = ALLOWED_TYPES[ext]
    if declared in (None, ""):
        return derived
    if not isinstance(declared, str):
        raise ArtifactWriteRefused("invalid_media_type", "media_type must be a string")
    if declared.split(";")[0].strip().lower() != derived:
        raise ArtifactWriteRefused(
            "invalid_media_type",
            f"media_type {declared!r} does not match {ext} (expected {derived})")
    return derived


def tool_spec() -> dict:
    """The MCP tool definition the sidecar sees in ``tools/list``."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Deliver a finished text file to the user as a run artifact — this is the "
            "ONLY way to produce a file they can open, preview or download. Use it "
            "whenever you have written something the user asked to see: an HTML page, "
            "an SVG, a Markdown report, a CSV. An HTML file is rendered in a sandboxed "
            "preview, so make it SELF-CONTAINED — inline the CSS and JavaScript rather "
            "than linking sibling files, because the preview cannot fetch them. "
            "Each path may be delivered once per run and cannot be overwritten."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": (
                        "The file name shown to the user, e.g. 'index.html' or "
                        "'report/summary.md'. Relative, at most "
                        f"{MAX_DEPTH} levels deep. Allowed extensions: "
                        + ", ".join(sorted(ALLOWED_TYPES))
                    ),
                },
                "content": {
                    "type": "string",
                    "description": f"The complete file contents, at most {MAX_FILE_BYTES} bytes of UTF-8.",
                },
                "media_type": {
                    "type": "string",
                    "description": "Optional. Must agree with the extension if given.",
                },
            },
            "required": ["relative_path", "content"],
        },
    }


async def _run_totals(pool, workspace_id: str) -> tuple[int, int, set[str]]:
    """Files already delivered for this run: count, total bytes, and their paths."""
    if pool is None:
        return 0, 0, set()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT path, COALESCE(octet_length(content), 0) AS n
            FROM workspace_artifacts
            WHERE workspace_id = $1 AND artifact_type = 'file'
            """,
            workspace_id,
        )
    paths = {r["path"] for r in rows if r["path"]}
    return len(rows), sum(int(r["n"] or 0) for r in rows), paths


async def call_write_new_artifact(
    args: dict, *, pool, workspace_id: str,
    save_artifact: Callable[..., Any],
) -> tuple[dict, bool]:
    """Run the tool. Returns ``(payload, ok)`` — a refusal is a result, not an error.

    ``save_artifact`` is injected rather than imported so this module does not pull
    in the whole workspace router (which imports this one's caller).
    """
    try:
        path = normalize_path(args.get("relative_path"))
        content = args.get("content")
        if not isinstance(content, str):
            raise ArtifactWriteRefused("invalid_content", "content must be a string")
        if not content.strip():
            raise ArtifactWriteRefused("invalid_content", "content is empty")
        size = len(content.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise ArtifactWriteRefused(
                "too_large", f"content is {size} bytes; the limit is {MAX_FILE_BYTES}")
        media_type = resolve_media_type(path, args.get("media_type"))

        count, total, existing = await _run_totals(pool, workspace_id)
        if path in existing:
            raise ArtifactWriteRefused(
                "already_exists",
                f"{path} was already delivered by this run; choose a different name")
        if count >= MAX_FILES_PER_RUN:
            raise ArtifactWriteRefused(
                "quota_files", f"this run has already delivered {count} files "
                               f"(limit {MAX_FILES_PER_RUN})")
        if total + size > MAX_TOTAL_BYTES:
            raise ArtifactWriteRefused(
                "quota_bytes", f"this run's artifacts would exceed {MAX_TOTAL_BYTES} bytes")
    except ArtifactWriteRefused as refused:
        return {"ok": False, "error": refused.reason, "message": refused.message}, False

    artifact_id = await save_artifact(
        pool, workspace_id, "file", path=path, content=content)
    if not artifact_id:
        return {"ok": False, "error": "save_failed",
                "message": "the artifact could not be stored"}, False

    previewable = media_type in ("text/html", "image/svg+xml")
    return {
        "ok": True,
        "artifact_id": artifact_id,
        "path": path,
        "media_type": media_type,
        "bytes": size,
        "message": (
            f"Delivered {path} ({size} bytes)."
            + (" The user can open it with the Preview button." if previewable
               else " It is available in the run's Artifacts tab.")
        ),
    }, True


def sidecar_artifact_mcp_server(user_id: int | None, workspace_id: str | None) -> dict | None:
    """The ``mcpServers`` entry that lets a sidecar deliver files, or ``None``.

    ``None`` when there is no run to attach artifacts to or no user to scope the
    token — registering a server whose every call fails costs the model a round
    trip and reads to it as its own mistake.

    The workspace id travels in a server-written header beside the bearer token,
    never in the tool arguments, for the same reason the CAD context header does:
    a process that could forge one could equally have stolen the other, and the
    model is never asked for it.
    """
    if not user_id or not workspace_id:
        return None
    # Late import: `main` imports the workspace package, so a module-level import
    # would cycle. One signer for every Harvis token.
    try:
        from main import create_access_token
        from datetime import timedelta
    except Exception:
        logger.debug("artifact mcp: token signer unavailable", exc_info=True)
        return None

    token = create_access_token({"sub": str(int(user_id))},
                                timedelta(minutes=SIDECAR_TOKEN_MINUTES))
    ctx = base64.b64encode(
        json.dumps({"workspace_id": str(workspace_id)}).encode("utf-8")).decode("ascii")
    return {SERVER_NAME: {
        "type": "http",
        "url": SIDECAR_ARTIFACT_MCP_URL,
        "headers": {"Authorization": f"Bearer {token}", CONTEXT_HEADER: ctx},
    }}


def injected_workspace_id(header_value: str | None) -> str | None:
    """Read the server-injected run id. Never raises — an unreadable header means
    the launch site set none, and the endpoint then has nothing to write to."""
    if not header_value:
        return None
    try:
        data = json.loads(base64.b64decode(header_value))
    except Exception:
        logger.debug("artifact mcp: unreadable context header", exc_info=True)
        return None
    wid = data.get("workspace_id") if isinstance(data, dict) else None
    return str(wid) if wid else None


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def error_response(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_result(payload: dict, ok: bool) -> dict:
    text = payload.get("message") or json.dumps(payload, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": not ok,
    }


async def handle_jsonrpc(message: dict, *, pool, workspace_id: str | None,
                         save_artifact: Callable[..., Any]) -> dict | None:
    """One JSON-RPC message in, one response out — or ``None`` for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return error_response(None, INVALID_REQUEST, "expected a JSON-RPC 2.0 request")

    req_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return error_response(req_id, INVALID_PARAMS, "params must be an object")
    is_notification = "id" not in message

    if method == "initialize":
        return None if is_notification else _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if method and method.startswith("notifications/"):
        return None
    if method == "ping":
        return None if is_notification else _result(req_id, {})
    if method == "tools/list":
        return None if is_notification else _result(req_id, {"tools": [tool_spec()]})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return error_response(req_id, INVALID_PARAMS, "arguments must be an object")
        if name != TOOL_NAME:
            return error_response(req_id, METHOD_NOT_FOUND, f"unknown tool: {name}")
        if not workspace_id:
            payload, ok = {"ok": False, "error": "no_run",
                           "message": "this session has no run to attach artifacts to"}, False
        else:
            payload, ok = await call_write_new_artifact(
                args, pool=pool, workspace_id=workspace_id, save_artifact=save_artifact)
        return None if is_notification else _result(req_id, _tool_result(payload, ok))

    if is_notification:
        return None
    return error_response(req_id, METHOD_NOT_FOUND, f"unknown method: {method}")
