"""Harvis Knowledge Bases — a GitHub repo (or other source) ingested into a
searchable vector store and attachable to a chat as RAG context.

This is K3. It deliberately reuses OpenWebUI's *existing* "Attach Knowledge"
composer flow (InputMenu → Knowledge.svelte → a ``{type:"collection"}``
attachment that rides in the chat body's ``files``). So we only implement:

  1. enough of OWUI's ``/api/v1/knowledge/*`` contract for that picker to list +
     attach our KBs (``GET /``, ``/search``, ``/{id}``, ``/{id}/files``, delete);
  2. a Harvis-native ``POST /api/owui/kb/from-repo`` that clones a *public*
     GitHub repo, walks its text/code files, chunks + embeds them, and stores the
     vectors in ``owui_knowledge_chunks``;
  3. ``retrieve_context()`` — the chat-time RAG that ``chat_completion._inject_
     knowledge`` calls when a collection is attached.

Embeddings reuse the notebook embedding pipeline's model list + 4096-dim target
(so a KB shares the same vector geometry as notebooks). The blocking Ollama
``/api/embeddings`` call is offloaded with ``asyncio.to_thread`` so it never
stalls the event loop. NOTE: cloning is public-only (no token) — a rogue private
repo just fails the clone, surfaced as the KB's ``error`` status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from types import SimpleNamespace
from typing import Callable, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

EMBED_DIM = 4096
_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
_EMBED_MODELS = [
    os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
    "qwen3-embedding:4b",
    "mxbai-embed-large",
    "llama3.1:8b",   # installed fallback — supports /api/embeddings (4096-dim)
    "mistral",
]
_WORKING_EMBED_MODEL: Optional[str] = None

# Which files are worth ingesting (text/code) and what to skip / cap.
_INGEST_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".md", ".mdx", ".rst",
    ".txt", ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env.example",
    ".go", ".rs", ".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".rb",
    ".php", ".swift", ".scala", ".sh", ".bash", ".zsh", ".sql", ".html", ".css",
    ".scss", ".svelte", ".vue", ".lua", ".r", ".pl", ".dockerfile",
}
_INGEST_NAMES = {"dockerfile", "makefile", "readme", "license", "contributing"}
_SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", ".svelte-kit", "__pycache__",
    ".venv", "venv", "env", "vendor", ".cache", "target", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".mypy_cache", "out", ".turbo", "bin", "obj",
}
_MAX_FILE_BYTES = 200_000
_MAX_FILES = 600

CREATE_OWUI_KNOWLEDGE_SQL = """
CREATE TABLE IF NOT EXISTS owui_knowledge (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'github_repo',
    source_ref  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_owui_knowledge_user ON owui_knowledge(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS owui_knowledge_chunks (
    id            BIGSERIAL PRIMARY KEY,
    knowledge_id  TEXT NOT NULL REFERENCES owui_knowledge(id) ON DELETE CASCADE,
    path          TEXT NOT NULL,
    content       TEXT NOT NULL,
    embedding     vector(4096),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_owui_kb_chunks_kb ON owui_knowledge_chunks(knowledge_id);
"""


# ─────────────────────────── embedding (sync, to_thread'd) ──────────────────
def _embed_sync(text: str) -> Optional[list]:
    """Blocking Ollama embed → a 4096-dim vector (or None). Always call via
    ``asyncio.to_thread`` so the event loop isn't stalled by ``requests``."""
    global _WORKING_EMBED_MODEL
    import requests

    candidates = ([_WORKING_EMBED_MODEL] if _WORKING_EMBED_MODEL else []) + _EMBED_MODELS
    seen = set()
    for model in candidates:
        if not model or model in seen:
            continue
        seen.add(model)
        try:
            r = requests.post(
                f"{_OLLAMA_URL}/api/embeddings",
                json={"model": model, "prompt": text[:8000]},
                timeout=60,
            )
            if r.status_code == 200:
                emb = r.json().get("embedding")
                if emb:
                    _WORKING_EMBED_MODEL = model
                    if len(emb) < EMBED_DIM:
                        emb = emb + [0.0] * (EMBED_DIM - len(emb))
                    elif len(emb) > EMBED_DIM:
                        emb = emb[:EMBED_DIM]
                    return emb
        except Exception:
            continue
    return None


def _to_pgvector(vec: list) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


def _chunk(text: str, title: str) -> list:
    """Reuse the notebook chunker (paragraph-first, 1000c / 200c overlap)."""
    from notebooks.ingestion import IngestionService

    svc = IngestionService(None)  # only _chunk_text is used — it never touches .manager
    return [c for (c, _meta) in svc._chunk_text(text, SimpleNamespace(title=title))]


# ─────────────────────────────── persistence ────────────────────────────────
def _kb_to_owui(row) -> dict:
    meta = row["meta"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    meta = meta or {}
    created = row["created_at"]
    updated = row["updated_at"]
    return {
        "id": row["id"],
        "user_id": str(row["user_id"]),
        "name": row["name"],
        "description": row["description"] or "",
        "data": {"file_ids": []},
        "meta": {
            **meta,
            "kind": row["kind"],
            "source_ref": row["source_ref"],
            "status": row["status"],
            "error": row["error"],
        },
        "files": [],
        "status": row["status"],
        "type": "collection",
        "created_at": int(created.timestamp()) if created else None,
        "updated_at": int(updated.timestamp()) if updated else None,
    }


async def _set_status(pool, kb_id: str, status: str, *, error: str = None, meta_update: dict = None) -> None:
    async with pool.acquire() as conn:
        if meta_update:
            await conn.execute(
                "UPDATE owui_knowledge SET status=$2, error=$3, meta = meta || $4::jsonb, updated_at=NOW() WHERE id=$1",
                kb_id, status, error, json.dumps(meta_update),
            )
        else:
            await conn.execute(
                "UPDATE owui_knowledge SET status=$2, error=$3, updated_at=NOW() WHERE id=$1",
                kb_id, status, error,
            )


# ─────────────────────────────── ingestion ──────────────────────────────────
def _should_ingest(filename: str) -> bool:
    name = filename.lower()
    base, ext = os.path.splitext(name)
    if ext in _INGEST_EXTS:
        return True
    if name in _INGEST_NAMES or base in _INGEST_NAMES:
        return True
    return False


async def _git_clone(url: str, branch: str, dest: str) -> None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}

    async def _run(args):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _out, err = await proc.communicate()
        return proc.returncode, (err or b"").decode("utf-8", "replace")

    # Try the requested branch first, then fall back to the repo's default branch.
    rc, err = await _run(["git", "clone", "--depth", "1", "--single-branch", "--branch", branch, url, dest])
    if rc != 0:
        shutil.rmtree(dest, ignore_errors=True)
        rc, err = await _run(["git", "clone", "--depth", "1", url, dest])
    if rc != 0:
        raise RuntimeError((err.strip().splitlines() or ["git clone failed"])[-1][:300])


async def ingest_repo_into_kb(pool, kb_id: str, owner: str, repo: str, branch: str) -> None:
    tmp = tempfile.mkdtemp(prefix="harvis-kb-")
    repo_dir = os.path.join(tmp, "repo")
    try:
        await _set_status(pool, kb_id, "processing")
        await _git_clone(f"https://github.com/{owner}/{repo}.git", branch or "main", repo_dir)

        files_done = 0
        chunks_done = 0
        truncated = False
        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
            for fn in sorted(files):
                if files_done >= _MAX_FILES:
                    truncated = True
                    break
                if not _should_ingest(fn):
                    continue
                fpath = os.path.join(root, fn)
                try:
                    if os.path.getsize(fpath) > _MAX_FILE_BYTES:
                        continue
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except Exception:
                    continue
                if not text.strip():
                    continue
                rel = os.path.relpath(fpath, repo_dir)
                rows = []
                for ch in _chunk(text, rel):
                    vec = await asyncio.to_thread(_embed_sync, ch)
                    if vec is None:
                        continue
                    rows.append((kb_id, rel, ch, _to_pgvector(vec)))
                if rows:
                    async with pool.acquire() as conn:
                        await conn.executemany(
                            "INSERT INTO owui_knowledge_chunks (knowledge_id, path, content, embedding) "
                            "VALUES ($1, $2, $3, $4::vector)",
                            rows,
                        )
                    chunks_done += len(rows)
                files_done += 1
            if files_done >= _MAX_FILES:
                truncated = True
                break

        if chunks_done == 0:
            await _set_status(pool, kb_id, "error",
                              error="No ingestible text/code files found in the repo.")
            return
        await _set_status(pool, kb_id, "ready",
                          meta_update={"file_count": files_done, "chunk_count": chunks_done, "truncated": truncated})
        logger.info("KB %s ingested %d files / %d chunks from %s/%s%s",
                    kb_id, files_done, chunks_done, owner, repo, " (truncated)" if truncated else "")
    except Exception as e:  # noqa: BLE001
        logger.error("KB ingest failed for %s (%s/%s): %s", kb_id, owner, repo, e)
        await _set_status(pool, kb_id, "error", error=str(e)[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────── chat-time retrieval ────────────────────────────
async def retrieve_context(pool, kb_ids: list, query_text: str, *, user_id=None,
                           top_k: int = 6, max_chars: int = 8000) -> list:
    """Embed the query, vector-search each attached KB, return formatted context
    blocks (one per KB, file-path cited). Owner-scoped. Never raises."""
    try:
        vec = await asyncio.to_thread(_embed_sync, query_text)
    except Exception:
        return []
    if vec is None:
        return []
    qv = _to_pgvector(vec)
    blocks: list = []
    async with pool.acquire() as conn:
        for kb_id in kb_ids:
            try:
                kb = await conn.fetchrow(
                    "SELECT name FROM owui_knowledge WHERE id=$1 AND ($2::int IS NULL OR user_id=$2)",
                    kb_id, int(user_id) if user_id is not None else None,
                )
                if not kb:
                    continue
                rows = await conn.fetch(
                    "SELECT path, content, 1 - (embedding <=> $1::vector) AS sim "
                    "FROM owui_knowledge_chunks "
                    "WHERE knowledge_id=$2 AND embedding IS NOT NULL "
                    "ORDER BY embedding <=> $1::vector LIMIT $3",
                    qv, kb_id, top_k,
                )
            except Exception:
                logger.warning("KB retrieve failed for %s", kb_id, exc_info=True)
                continue
            if not rows:
                continue
            parts: list = []
            used = 0
            for r in rows:
                snippet = f"[{r['path']}]\n{r['content']}"
                if used + len(snippet) > max_chars and parts:
                    break
                parts.append(snippet)
                used += len(snippet)
            if parts:
                blocks.append(f"### Knowledge base: {kb['name']}\n" + "\n\n".join(parts))
    return blocks


# ─────────────────────────────── routes ─────────────────────────────────────
class FromRepoBody(BaseModel):
    owner: Optional[str] = None
    repo: Optional[str] = None
    branch: str = "main"
    url: Optional[str] = None


def _parse_repo(body: FromRepoBody):
    owner = (body.owner or "").strip()
    repo = (body.repo or "").strip()
    url = (body.url or "").strip()
    # Allow owner/repo packed into either field, or a full GitHub URL.
    if url:
        u = url.split("github.com/", 1)[-1]
        u = u.replace("https://", "").replace("http://", "").strip("/")
        parts = [p for p in u.split("/") if p]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
    if not owner and "/" in repo:
        owner, repo = repo.split("/", 1)
    repo = repo.removesuffix(".git").strip("/")
    owner = owner.strip("/")
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="Provide a public repo as owner/repo or a GitHub URL.")
    return owner, repo


def register_knowledge_routes(router: APIRouter, get_current_user: Callable) -> None:
    """Attach the Knowledge-Base routes to the OWUI facade router."""

    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        return pool

    async def _list(request: Request, user) -> dict:
        pool = _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM owui_knowledge WHERE user_id=$1 ORDER BY updated_at DESC",
                int(user.id),
            )
        items = [_kb_to_owui(r) for r in rows]
        return {"items": items, "total": len(items)}

    # ── OWUI contract: list / search / single / files (literals BEFORE {id}) ──
    @router.get("/api/v1/knowledge/")
    async def kb_list(request: Request, user=Depends(get_current_user), page: int = None):  # noqa: ARG001
        return await _list(request, user)

    @router.get("/api/v1/knowledge/list")
    async def kb_list_alias(request: Request, user=Depends(get_current_user)):
        return (await _list(request, user))["items"]

    @router.get("/api/v1/knowledge/search")
    async def kb_search(request: Request, user=Depends(get_current_user),
                        query: str = None, view_option: str = None, page: int = None):  # noqa: ARG001
        res = await _list(request, user)
        if query:
            q = query.lower()
            res["items"] = [k for k in res["items"]
                            if q in (k["name"] or "").lower() or q in (k["description"] or "").lower()]
            res["total"] = len(res["items"])
        return res

    @router.get("/api/v1/knowledge/{kb_id}")
    async def kb_get(kb_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM owui_knowledge WHERE id=$1 AND user_id=$2", kb_id, int(user.id)
            )
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        return _kb_to_owui(row)

    @router.get("/api/v1/knowledge/{kb_id}/files")
    async def kb_files(kb_id: str, request: Request, user=Depends(get_current_user),
                       page: int = 1, query: str = None, view_option: str = None,
                       order_by: str = None, direction: str = None):  # noqa: ARG001
        # KB content is repo-chunks, not discrete OWUI files; the picker shows
        # "No files" and the KB itself stays selectable as a collection.
        return {"items": [], "total": 0}

    @router.delete("/api/v1/knowledge/{kb_id}/delete")
    async def kb_delete(kb_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM owui_knowledge WHERE id=$1 AND user_id=$2", kb_id, int(user.id)
            )
        return True

    # ── Harvis-native: create a KB from a public GitHub repo ─────────────────
    @router.post("/api/owui/kb/from-repo")
    async def kb_from_repo(body: FromRepoBody, request: Request, background: BackgroundTasks,
                           user=Depends(get_current_user)):
        owner, repo = _parse_repo(body)
        branch = (body.branch or "main").strip() or "main"
        pool = _pool(request)
        kb_id = str(uuid.uuid4())
        name = f"{owner}/{repo}"
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO owui_knowledge (id, user_id, name, description, kind, source_ref, status) "
                "VALUES ($1, $2, $3, $4, 'github_repo', $5, 'pending')",
                kb_id, int(user.id), name, f"GitHub repo {owner}/{repo} ({branch})", f"{owner}/{repo}@{branch}",
            )
        background.add_task(ingest_repo_into_kb, pool, kb_id, owner, repo, branch)
        return {"id": kb_id, "name": name, "status": "pending"}

    @router.get("/api/owui/kb/{kb_id}/status")
    async def kb_status(kb_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, status, error, meta FROM owui_knowledge WHERE id=$1 AND user_id=$2",
                kb_id, int(user.id),
            )
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        meta = row["meta"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return {"id": row["id"], "name": row["name"], "status": row["status"],
                "error": row["error"], "meta": meta or {}}
