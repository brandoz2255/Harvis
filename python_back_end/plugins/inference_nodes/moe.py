"""Which installed models are sparse (MoE), and which of them a node should serve.

Why this exists: FreeToken's whole reason to be is that a mixture-of-experts model
activates a fraction of its weights per token, so the expert banks can sit in host RAM
and stream over PCIe and a 35B model runs on an 8 GB card. That trick applies to *MoE
models only* — FreeToken creates the offload backend at ``engine.py:385`` behind
``if config.model_config.is_moe`` and strips every offload knob for a dense model. So
"is this model MoE?" is the question that decides whether a node is worth waking.

Detection is not a guess. Ollama's ``/api/show`` reports ``<family>.expert_count`` and
``<family>.expert_used_count`` in ``model_info`` for any MoE checkpoint, straight from
the GGUF metadata:

    gpt-oss:20b          gptoss.expert_count=32,   expert_used_count=4
    Qwen3.6-35B-A3B      qwen35moe.expert_count=256, expert_used_count=8
    llama3.1:8b          (no expert keys — dense)

A node's own models are known to be MoE by other means (the checkpoint it was pointed
at), so what this module classifies is what is *installed in Ollama* — the models a
user actually pulled — against what the nodes can serve.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = (os.getenv("OLLAMA_URL", "http://ollama:11434") or "").rstrip("/")
SHOW_TIMEOUT_S = float(os.getenv("HARVIS_MOE_SHOW_TIMEOUT_S", "6"))
SHOW_CONCURRENCY = int(os.getenv("HARVIS_MOE_SHOW_CONCURRENCY", "4"))

_EXPERT_COUNT = re.compile(r"\.expert_count$")
_EXPERT_USED = re.compile(r"\.expert_used_count$")
_PARAM_SIZE = re.compile(r"^([\d.]+)\s*([BMK])$", re.I)
_SCALE = {"K": 1e3, "M": 1e6, "B": 1e9}


def expert_info(show: dict) -> dict | None:
    """``{"total": 256, "active": 8, "family": "qwen35moe"}`` for an MoE model, else None.

    Reads the GGUF metadata Ollama surfaces rather than pattern-matching the model name:
    ``mixtral`` is MoE and so is ``gpt-oss``, and neither says so in its name.
    """
    info = (show or {}).get("model_info")
    if not isinstance(info, dict):
        return None
    total = active = None
    family = ""
    for key, value in info.items():
        if _EXPERT_COUNT.search(key):
            total, family = value, key.rsplit(".", 1)[0]
        elif _EXPERT_USED.search(key):
            active = value
    try:
        total = int(total) if total is not None else 0
    except (TypeError, ValueError):
        total = 0
    if total <= 1:
        # 0 or 1 expert is a dense model however the metadata spells it.
        return None
    try:
        active = int(active) if active is not None else 0
    except (TypeError, ValueError):
        active = 0
    return {"total": total, "active": active or None, "family": family}


def param_count(show: dict) -> float | None:
    """Total parameters from ``details.parameter_size`` ("35.1B"), in raw units."""
    raw = ((show or {}).get("details") or {}).get("parameter_size") or ""
    m = _PARAM_SIZE.match(str(raw).strip())
    if not m:
        return None
    return float(m.group(1)) * _SCALE[m.group(2).upper()]


def active_params(show: dict) -> float | None:
    """Parameters actually used per token — the number that decides if it will be fast.

    A rough proportional estimate (total × active/total experts) rather than a real
    architectural count: it ignores attention and shared experts, so it reads low. Good
    enough to separate "3B active" from "35B dense", which is the only call being made.
    """
    ex = expert_info(show)
    total = param_count(show)
    if not ex or not total or not ex.get("active"):
        return None
    return total * (ex["active"] / ex["total"])


async def _show(client: httpx.AsyncClient, name: str) -> dict | None:
    try:
        r = await client.post(f"{OLLAMA_URL}/api/show", json={"model": name},
                              timeout=SHOW_TIMEOUT_S)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


async def installed_models() -> list[str]:
    """Model names Ollama has pulled. Empty list when Ollama is not answering."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags", timeout=SHOW_TIMEOUT_S)
            r.raise_for_status()
            return [m["name"] for m in (r.json().get("models") or []) if m.get("name")]
    except Exception as exc:
        logger.info("moe scan: Ollama not answering (%s)", type(exc).__name__)
        return []


def verdict(name: str, ex: dict | None, total: float | None,
            node_models: set[str], node_reachable: bool) -> tuple[str, str]:
    """``(verdict, why)`` for one installed model.

    Four outcomes, and only one of them is an action:

    * ``served_by_node`` — a node already serves this exact name; chat routes there.
    * ``node_would_help`` — sparse and too big for the card, but no node has it. This is
      the one worth telling someone about, and it is *not* automatic: FreeToken loads
      its own checkpoint, and its GGUF reader currently understands one architecture
      (``gemma4``), so it cannot pick up Ollama's blob for this model.
    * ``fits_anyway`` — sparse but small enough that Ollama is fine.
    * ``dense`` — no routed experts, so the offload path does not apply at all.
    """
    if name in node_models:
        return "served_by_node", (
            "A node serves this model, so chat already routes there."
            if node_reachable else
            "A node serves this model but is not answering right now."
        )
    if not ex:
        return "dense", "No routed experts — the host-RAM offload path does not apply."
    act = f"{ex['active']} of {ex['total']} experts per token" if ex.get("active") else \
          f"{ex['total']} experts"
    if total and total > 12e9:
        return "node_would_help", (
            f"Sparse ({act}) and large, so most of it is idle on any given token — "
            "the shape FreeToken exists for. Needs its own checkpoint; it cannot serve "
            "Ollama's copy."
        )
    return "fits_anyway", f"Sparse ({act}) but small enough that Ollama handles it."


async def candidates(node_models: set[str] | None = None,
                     node_reachable: bool = True) -> list[dict]:
    """Every installed Ollama model, classified. Sorted most-interesting first."""
    names = await installed_models()
    if not names:
        return []
    node_models = node_models or set()
    sem = asyncio.Semaphore(SHOW_CONCURRENCY)

    async def one(client: httpx.AsyncClient, name: str) -> dict:
        async with sem:
            show = await _show(client, name) or {}
        ex = expert_info(show)
        total = param_count(show)
        kind, why = verdict(name, ex, total, node_models, node_reachable)
        return {
            "name": name,
            "moe": ex is not None,
            "experts": ex,
            "params": total,
            "active_params": active_params(show),
            "family": ((show.get("details") or {}).get("family") or ""),
            "verdict": kind,
            "why": why,
        }

    async with httpx.AsyncClient() as client:
        rows = await asyncio.gather(*(one(client, n) for n in names))

    order = {"node_would_help": 0, "served_by_node": 1, "fits_anyway": 2, "dense": 3}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -(r["params"] or 0), r["name"]))
    return list(rows)
