"""Which node actually has a model, right now — and which node is down.

The same contract as ``owui_compat.ollama_hosts`` for the same reason: a lane that
asks "is this model somewhere?" must get *absent* and *unknown* as different answers,
and a node that is asleep must keep its last model list so the picker can grey the
model out instead of dropping it.

Dialect-aware. An OpenAI node is asked ``/v1/models`` (FreeToken, vLLM, llama-server
all answer it); ``/health`` and ``/v1/stats`` are read when present because FreeToken
reports throughput and VRAM there and the picker can show them. An Ollama node is
asked ``/api/tags``. Ollama's own OpenAI shim lacks the context length, which is why
it keeps its native probe.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from .registry import configured_nodes, env_nodes
from .types import NodeSpec, NodeState

logger = logging.getLogger(__name__)

PROBE_TTL_S = float(os.getenv("HARVIS_NODE_PROBE_TTL_S", "10"))
PROBE_TIMEOUT_S = float(os.getenv("HARVIS_NODE_PROBE_TIMEOUT_S", "4"))

_cache: dict[str, NodeState] = {}
_cache_at: float = 0.0
_lock = asyncio.Lock()
_app = None


def attach(app) -> None:
    """Remember the FastAPI app so DB-registered nodes can be read from its pool.

    Called once at startup; until then (and when the pool is absent) only the env
    nodes exist, which is the honest degraded mode rather than an error.
    """
    global _app
    _app = app


def _pool():
    return getattr(getattr(_app, "state", None), "pg_pool", None)


def probed_at() -> float:
    return _cache_at


def kv_capacity(stats: dict | None) -> int | None:
    """Tokens the server's KV cache can hold, from FreeToken's ``/v1/stats``; else None."""
    kv = (stats or {}).get("kv")
    if not isinstance(kv, dict):
        return None
    pages = kv.get("total_pages")
    size = kv.get("page_size") or 1
    if isinstance(pages, int) and pages > 0 and isinstance(size, int) and size > 0:
        return pages * size
    return None


def _ctx_of(entry: dict) -> int | None:
    # FreeToken reports context_length; vLLM max_model_len; llama-server neither.
    for key in ("context_length", "max_model_len", "max_context_length"):
        v = entry.get(key)
        if isinstance(v, int) and v > 0:
            return v
    return None


async def _probe_openai(spec: NodeSpec, timeout: float, st: NodeState) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), headers=spec.headers()) as hc:
        try:
            r = await hc.get(f"{spec.base_url}/v1/models")
        except Exception as e:
            # Class name only: a connection error carries the host and port and this
            # string reaches the UI.
            st.error = type(e).__name__
            return
        if r.status_code != 200:
            st.error = f"HTTP {r.status_code}"
            return
        try:
            data = r.json().get("data") or []
        except Exception:
            st.error = "bad response"
            return
        st.reachable = True
        for m in data:
            mid = str(m.get("id") or "").strip()
            if not mid:
                continue
            st.models.add(mid)
            ctx = _ctx_of(m)
            if ctx:
                st.ctx[mid] = ctx
        # Informational side reads. A node without them is still a healthy node.
        for path, slot in (("/health", "health"), ("/v1/stats", "stats")):
            try:
                rr = await hc.get(f"{spec.base_url}{path}")
                if rr.status_code == 200:
                    payload = rr.json()
                    if isinstance(payload, dict):
                        setattr(st, slot, payload)
            except Exception:
                pass
        cap = kv_capacity(st.stats)
        if cap:
            # The model's window is not the window the *server* can hold. FreeToken on
            # the 8 GB laptop reports context_length 262144 but reserves a 4096-token
            # KV cache, and clips max_tokens to what is left of that — so the picker
            # and the usage meter must show the cache, not the paper number.
            for mid in list(st.models):
                st.ctx[mid] = min(st.ctx.get(mid) or cap, cap)


async def _probe_ollama(spec: NodeSpec, timeout: float, st: NodeState) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), headers=spec.headers()) as hc:
        try:
            r = await hc.get(f"{spec.base_url}/api/tags")
        except Exception as e:
            st.error = type(e).__name__
            return
        if r.status_code != 200:
            st.error = f"HTTP {r.status_code}"
            return
        try:
            models = r.json().get("models") or []
        except Exception:
            st.error = "bad response"
            return
        st.reachable = True
        for m in models:
            tag = str(m.get("model") or m.get("name") or "").strip()
            if tag:
                st.models.add(tag)


async def _probe(spec: NodeSpec, timeout: float) -> NodeState:
    st = NodeState(spec=spec)
    prev = _cache.get(spec.name)
    if prev is not None:
        st.last_good_models = prev.last_good_models
        st.last_good_at = prev.last_good_at
    if spec.dialect == "ollama":
        await _probe_ollama(spec, timeout, st)
    else:
        await _probe_openai(spec, timeout, st)
    st.probed_at = time.time()
    if st.reachable:
        st.last_good_models = set(st.models)
        st.last_good_at = st.probed_at
    return st


async def snapshot(*, force: bool = False, timeout: float = PROBE_TIMEOUT_S) -> dict[str, NodeState]:
    """Probe every configured node in parallel; by node name.

    ``force`` skips the TTL for an explicit refresh. With zero nodes configured this
    costs one registry read per TTL and no network at all.
    """
    global _cache_at
    async with _lock:
        if not force and _cache_at and (time.time() - _cache_at) < PROBE_TTL_S:
            return dict(_cache)
        specs = await configured_nodes(_pool())
        states = await asyncio.gather(
            *(_probe(s, timeout) for s in specs), return_exceptions=True
        )
        fresh: dict[str, NodeState] = {}
        for spec, st in zip(specs, states):
            if isinstance(st, NodeState):
                fresh[spec.name] = st
            else:
                prev = _cache.get(spec.name)
                fresh[spec.name] = NodeState(
                    spec=spec,
                    error=type(st).__name__,
                    last_good_models=prev.last_good_models if prev else set(),
                    last_good_at=prev.last_good_at if prev else 0.0,
                    probed_at=time.time(),
                )
                logger.warning("inference_nodes: probe of %s raised %r", spec.name, st)
        _cache.clear()
        _cache.update(fresh)
        _cache_at = time.time()
        return dict(fresh)


def invalidate() -> None:
    """Force the next ``snapshot()`` to re-probe; keeps ``last_good_models``."""
    global _cache_at
    _cache_at = 0.0


def ctx_for(node_name: str, model: str) -> int | None:
    """Context the last probe recorded for ``model`` on ``node_name``; None if unknown."""
    st = _cache.get(node_name)
    if st is None:
        return None
    return st.ctx.get(model)


def known_specs() -> list[NodeSpec]:
    """Specs from the last probe, or the env list before any probe has run."""
    if _cache:
        return [st.spec for st in _cache.values()]
    return env_nodes()


def node_for_url(url: str) -> NodeSpec | None:
    """The node a resolved target URL belongs to, if any.

    ``model_proxy`` keys all of its Ollama-specific body munging on the target URL;
    this is how it learns that a URL is a node and must be left OpenAI-shaped.
    """
    u = (url or "").strip()
    if not u:
        return None
    for spec in known_specs():
        if u == spec.base_url or u.startswith(spec.base_url + "/"):
            return spec
    return None


async def resolve(model: str, *, force: bool = False) -> tuple[NodeState | None, str]:
    """Where to run ``model``: ``(state, reason)``.

    ``state`` is ``None`` when no reachable node has it, and the reason then says which
    failure it was: ``"absent"`` (every node answered, none has it), ``"unknown:<node>"``
    (a node that last had it did not answer), or ``"no-nodes"``.
    """
    if not (model or "").strip():
        return None, "absent"
    states = await snapshot(force=force)
    if not states:
        return None, "no-nodes"
    for st in sorted(states.values(), key=lambda s: (s.spec.priority, s.spec.name)):
        if st.has(model):
            return st, st.spec.name
    for st in states.values():
        if not st.reachable and model in st.last_good_models:
            return None, f"unknown:{st.spec.name}"
    return None, "absent"


async def unreachable_models(*, force: bool = False) -> list[tuple[str, NodeState]]:
    """(model, node) for models a node used to serve and cannot right now."""
    states = await snapshot(force=force)
    live: set[str] = set()
    for st in states.values():
        live |= st.models
    out: list[tuple[str, NodeState]] = []
    for st in states.values():
        if st.reachable:
            continue
        for model in sorted(st.last_good_models - live):
            out.append((model, st))
    return out


async def live_stats(name: str, *, timeout: float = PROBE_TIMEOUT_S) -> dict | None:
    """Fresh ``/health`` + ``/v1/stats`` for one node, bypassing the cache. ``None``
    when no node has that name."""
    spec = next((s for s in await configured_nodes(_pool()) if s.name == name), None)
    if spec is None:
        return None
    out: dict = {"name": spec.name, "label": spec.label, "reachable": False, "error": None,
                 "health": {}, "stats": {}}
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), headers=spec.headers()) as hc:
        for path, slot in (("/health", "health"), ("/v1/stats", "stats")):
            try:
                r = await hc.get(f"{spec.base_url}{path}")
            except Exception as e:
                out["error"] = out["error"] or type(e).__name__
                continue
            if r.status_code == 200:
                out["reachable"] = True
                try:
                    payload = r.json()
                    out[slot] = payload if isinstance(payload, dict) else {}
                except Exception:
                    pass
            else:
                out["error"] = out["error"] or f"HTTP {r.status_code}"
    return out
