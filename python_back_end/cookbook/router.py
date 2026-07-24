"""
Cookbook API — hardware-aware model recommendation + download, aggregated across
per-node `llmfit serve` instances. Thin proxy; llmfit is the engine.

Endpoints (all under /api/cookbook):
  GET  /nodes                 — which configured nodes are alive (drives per-device tabs)
  GET  /system?node=          — that node's detected hardware (CPU/RAM/GPU/VRAM/backend)
  GET  /recommend?node=&...   — top runnable models, pre-ranked by llmfit ("what fits")
  GET  /models?node=&...      — full / searchable fit list
  POST /download              — pull a model into that node's Ollama (SSE progress)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import client, config, resolver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cookbook", tags=["cookbook"])


# ─── Auth (mirror notebooks/router.py — late import avoids circular import on main) ───
async def get_current_user_from_request(request: Request) -> Dict:
    """Resolve the current user via the shared auth_optimized helper."""
    from auth_optimized import get_current_user_optimized
    from fastapi.security import HTTPAuthorizationCredentials

    auth_header = request.headers.get("Authorization")
    credentials = None
    if auth_header and auth_header.startswith("Bearer "):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header[7:])
    pool = getattr(request.app.state, "pg_pool", None)
    return await get_current_user_optimized(credentials=credentials, request=request, pool=pool)


async def require_admin_from_request(request: Request) -> Dict:
    """Admin-only gate for node mutations. Auth first (401), then admin check (403)."""
    from fastapi import HTTPException
    from owui_compat.authz import is_admin

    user = await get_current_user_from_request(request)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Administrator privileges are required to manage cookbook nodes.")
    return user


# ─── Schemas ──────────────────────────────────────────────────────────────────
class AddNodeRequest(BaseModel):
    name: str
    llmfit_url: str
    ollama_url: Optional[str] = ""
    role: Optional[str] = "subhost"


class DownloadRequest(BaseModel):
    node: str
    repo: Optional[str] = None        # llmfit HF repo name, e.g. "org/Model-GGUF"
    quant: Optional[str] = None       # llmfit best_quant, e.g. "Q6_K"
    ollama_tag: Optional[str] = None  # explicit ollama tag (wins over repo/model)
    model: Optional[str] = None       # legacy alias for ollama_tag


def _looks_like_hf_repo(name: str) -> bool:
    """'org/Model-Name' with no ':tag' on the last segment → an HF repo id, not an Ollama tag."""
    return "/" in name and ":" not in name.split("/")[-1]


# Runtimes that mean "GPU server / cloud" (vLLM-class) — NOT a local Ollama pull.
_SERVER_RUNTIMES = {"vllm", "tgi", "sglang", "trt", "tensorrt", "tensorrt-llm"}


def _classify(model: dict) -> dict:
    """Tag a llmfit model with its serving target + Ollama-pullability.

    serving='local'  → llama.cpp / GGUF family → runs on THIS device via Ollama.
    serving='server' → vLLM / TGI (AWQ/GPTQ) → needs a GPU server / cloud, not Ollama.

    Local models are 'downloadable': even when llmfit didn't record a `gguf_sources`
    URL, the download path resolves a GGUF repo from HuggingFace at pull time. Server
    models are not Ollama-pullable (a different runtime), so they're flagged instead.
    """
    rt = str(model.get("runtime", "")).lower()
    server = rt in _SERVER_RUNTIMES
    model["serving"] = "server" if server else "local"
    model["downloadable"] = not server
    if server:
        model["reason"] = "vLLM / GPU-server model (AWQ/GPTQ) — needs a GPU server, not local Ollama"
    return model


# Fit tiers, best → worst — the primary sort key.
_FIT_RANK = {"perfect": 4, "good": 3, "marginal": 2, "tight": 1, "too_tight": 0, "too tight": 0}


def _fit_rank(m) -> int:
    if not isinstance(m, dict):
        return -1
    return _FIT_RANK.get(str(m.get("fit_level", "")).lower(), 0)


def _gpu_first(m) -> int:
    # GPU-only run path beats CPU/offload modes (prioritize GPU usage, offload second).
    return 1 if (isinstance(m, dict) and str(m.get("run_mode", "")).lower() == "gpu") else 0


def _score_of(m) -> float:
    try:
        return float(m.get("score") or 0.0) if isinstance(m, dict) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _rank(models: list) -> list:
    """Classify each model, then re-order. Priority keys, all descending:
        1. fit tier (Perfect > Good > …)     — runs-well-on-this-machine first
        2. GPU run-path (gpu before offload) — prioritize GPU usage, CPU/offload second
        3. downloadable (Ollama-pullable)    — within a single scope this is constant
        4. llmfit score                      — Odysseus's FIT-then-SCORE tiebreak
    Stable sort preserves llmfit's order within full ties.
    """
    classified = [_classify(m) if isinstance(m, dict) else m for m in models]
    classified.sort(
        key=lambda m: (
            _fit_rank(m),
            _gpu_first(m),
            1 if (isinstance(m, dict) and m.get("downloadable")) else 0,
            _score_of(m),
        ),
        reverse=True,
    )
    return classified


def _enrich(resp):
    """Add serving/downloadable/reason to each model, then re-rank (fit, then pullable)."""
    if isinstance(resp, dict) and isinstance(resp.get("models"), list):
        resp["models"] = _rank(resp["models"])
    elif isinstance(resp, list):
        resp = _rank(resp)
    return resp


# ─── Endpoints ────────────────────────────────────────────────────────────────
@router.get("/nodes")
async def list_nodes(current_user: Dict = Depends(get_current_user_from_request)):
    """Ping each configured node's llmfit /health concurrently. Never raises — reports per-node."""
    names = list(config.NODES.keys())
    results = await asyncio.gather(*(client.health(config.NODES[n]["llmfit"]) for n in names))
    return {
        "nodes": [
            {
                "name": n,
                "role": config.NODES[n].get("role", "subhost"),
                "llmfit_url": config.NODES[n]["llmfit"],
                "ollama_url": config.NODES[n]["ollama"],
                **h,
            }
            for n, h in zip(names, results)
        ]
    }


import re

_NODE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,48}$")


def _norm_url(u: str) -> str:
    u = (u or "").strip().rstrip("/")
    if u and not u.startswith(("http://", "https://")):
        u = "http://" + u
    return u


@router.post("/nodes")
async def add_node(req: AddNodeRequest, request: Request, current_user: Dict = Depends(require_admin_from_request)):
    """Register another machine running `llmfit serve` as an inference node.

    Admin-only. The llmfit URL is probed for reachability BEFORE the node is saved,
    so a typo can't leave a permanently-offline entry in the picker. Persisted to
    `cookbook_nodes` (survives restart) and merged into the live registry.
    """
    name = (req.name or "").strip()
    if not _NODE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Node name must be 1–49 chars: letters, digits, space, . _ -")
    if config.is_baseline(name):
        raise HTTPException(status_code=400, detail=f"'{name}' is a built-in node and can't be redefined.")

    llmfit = _norm_url(req.llmfit_url)
    ollama = _norm_url(req.ollama_url or "")
    if not llmfit:
        raise HTTPException(status_code=400, detail="llmfit_url is required (e.g. http://192.168.1.50:8787)")

    # Reachability probe — refuse to save a node whose llmfit doesn't answer.
    probe = await client.health(llmfit)
    if not probe.get("alive"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"llmfit at {llmfit} did not respond. Start `llmfit serve --host 0.0.0.0 --port 8787` "
                f"on that machine and make sure the backend can reach it over the LAN."
                + (f" ({probe['error']})" if probe.get("error") else "")
            ),
        )

    pool = getattr(request.app.state, "pg_pool", None)
    try:
        await config.persist_node(pool, name, "subhost", llmfit, ollama)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Node storage unavailable (no database).")
    config.register_node(name, "subhost", llmfit, ollama)
    logger.info("cookbook: registered node %r (llmfit=%s ollama=%s)", name, llmfit, ollama)
    return {"name": name, "role": "subhost", "llmfit_url": llmfit, "ollama_url": ollama, **probe}


@router.delete("/nodes/{name}")
async def remove_node(name: str, request: Request, current_user: Dict = Depends(require_admin_from_request)):
    """Remove a user-added node. Admin-only. Built-in (env/default) nodes are protected."""
    if config.is_baseline(name):
        raise HTTPException(status_code=400, detail=f"'{name}' is a built-in node and can't be removed.")
    if name not in config.NODES:
        raise HTTPException(status_code=404, detail=f"Unknown node '{name}'.")
    pool = getattr(request.app.state, "pg_pool", None)
    await config.delete_persisted_node(pool, name)
    config.unregister_node(name)
    logger.info("cookbook: removed node %r", name)
    return {"removed": name}


@router.get("/system")
async def get_system(node: str, current_user: Dict = Depends(get_current_user_from_request)):
    """That node's detected hardware (proxy llmfit /api/v1/system)."""
    cfg = config.node_or_400(node)
    return await client.get_json(cfg["llmfit"], "/api/v1/system")


@router.get("/installed")
async def list_installed(node: str, current_user: Dict = Depends(get_current_user_from_request)):
    """Models actually pulled into this node's Ollama — i.e. what you can swap to/use."""
    cfg = config.node_or_400(node)
    ollama = cfg.get("ollama")
    if not ollama:
        return {"models": [], "ollama_url": ""}
    try:
        data = await client.get_json(ollama, "/api/tags")
    except HTTPException as e:  # ollama unreachable → empty, not a hard error
        return {"models": [], "ollama_url": ollama, "error": str(e.detail)[:200]}
    models = data.get("models", []) if isinstance(data, dict) else []
    models.sort(key=lambda m: (m.get("size", 0) if isinstance(m, dict) else 0), reverse=True)
    return {"models": models, "ollama_url": ollama}


@router.get("/recommend")
async def recommend(
    node: str,
    use_case: Optional[str] = None,
    min_fit: Optional[str] = None,
    limit: Optional[int] = None,
    runtime: Optional[str] = None,
    sort: Optional[str] = None,
    max_context: Optional[int] = None,
    force_runtime: Optional[str] = None,
    current_user: Dict = Depends(get_current_user_from_request),
):
    """Top runnable models for this node, pre-ranked by llmfit (proxy /api/v1/models/top)."""
    cfg = config.node_or_400(node)
    return _enrich(await client.get_json(
        cfg["llmfit"],
        "/api/v1/models/top",
        params={
            "use_case": use_case,
            "min_fit": min_fit,
            "limit": limit,
            "runtime": runtime,
            "sort": sort,
            "max_context": max_context,
            "force_runtime": force_runtime,
        },
    ))


@router.get("/models")
async def list_models(
    node: str,
    search: Optional[str] = None,
    use_case: Optional[str] = None,
    min_fit: Optional[str] = None,
    limit: Optional[int] = None,
    runtime: Optional[str] = None,
    sort: Optional[str] = None,
    current_user: Dict = Depends(get_current_user_from_request),
):
    """Browse / search the full fit list (proxy /api/v1/models[/{search}])."""
    cfg = config.node_or_400(node)
    path = f"/api/v1/models/{search}" if search else "/api/v1/models"
    return _enrich(await client.get_json(
        cfg["llmfit"],
        path,
        params={
            "use_case": use_case,
            "min_fit": min_fit,
            "limit": limit,
            "runtime": runtime,
            "sort": sort,
        },
    ))


@router.post("/download")
async def download(req: DownloadRequest, current_user: Dict = Depends(get_current_user_from_request)):
    """
    Pull a model into the chosen node's Ollama, streaming progress as SSE.

    Requires an Ollama tag (e.g. 'qwen2.5-coder:14b'). A raw HuggingFace repo id
    404s on Ollama, so pass `ollama_tag` (the frontend should surface it from the
    recommend list). HF→Ollama auto-mapping is intentionally NOT done here.
    """
    cfg = config.node_or_400(req.node)
    if not cfg.get("ollama"):
        raise HTTPException(status_code=400, detail=f"Node '{req.node}' has no ollama url configured")

    # Resolve what to pull. Explicit ollama_tag/model wins; otherwise resolve the
    # model's real GGUF repo on HuggingFace (llmfit often omits `gguf_sources`, and a
    # bare base repo 404s on Ollama) → hf.co GGUF bridge.
    tag = (req.ollama_tag or req.model or "").strip()
    if not tag and req.repo:
        tag = await resolver.resolve_gguf(req.repo, req.quant or "")
        if not tag:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"No GGUF build found on HuggingFace for '{req.repo}'"
                    + (f" ({req.quant})" if req.quant else "")
                    + ". It may be a vLLM/GPU-server-only model (AWQ/GPTQ)."
                ),
            )
    if not tag:
        raise HTTPException(status_code=400, detail="Provide repo (+quant) or ollama_tag")
    # An explicit tag that's a bare HF repo (no hf.co/ prefix, no :tag) isn't pullable.
    if not tag.startswith("hf.co/") and _looks_like_hf_repo(tag):
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{tag}' looks like a bare HuggingFace repo. Pass repo (+quant) for an "
                f"hf.co GGUF pull, or a real ollama_tag (e.g. 'qwen2.5-coder:14b')."
            ),
        )

    logger.info("cookbook: pulling %r on node %s (%s)", tag, req.node, cfg["ollama"])
    return StreamingResponse(
        client.ollama_pull_stream(cfg["ollama"], tag),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
