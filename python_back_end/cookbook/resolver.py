"""
GGUF resolver — find a HuggingFace GGUF repo for an Ollama-runnable model that
llmfit recommended but didn't record a `gguf_sources` URL for.

Ollama pulls GGUF via `ollama pull hf.co/<repo>:<quant>`. When llmfit returns a
base model (e.g. "Qwen/Qwen2.5-Coder-7B-Instruct") with no GGUF source, the GGUF
almost always exists on HF in a sibling repo — the official "<Model>-GGUF", or a
known quanter (bartowski / lmstudio-community / unsloth / …). This module searches
HF for that repo, verifies the requested quant has a matching .gguf file, and
returns the pullable `hf.co/<repo>:<quant>` tag.

General-purpose by design (this is open source — for whoever deploys Harvis): no
hardcoded per-model mappings, optional HF_TOKEN for higher rate limits, in-memory
cache, and it fails closed (returns None) so the caller surfaces a clean
"no GGUF found" instead of kicking off a broken pull.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

HF_API = "https://huggingface.co/api"
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
RESOLVE_TIMEOUT = float(os.getenv("COOKBOOK_RESOLVE_TIMEOUT", "12"))

# Known-good GGUF quanters, preferred after an exact-name / same-org match.
_PREFERRED = (
    "bartowski", "lmstudio-community", "unsloth", "thebloke",
    "second-state", "mradermacher", "qwen", "google", "meta-llama",
)

# Inference-format suffixes stripped to recover the base model name.
_FORMAT_SUFFIX = re.compile(
    r"[-_.]?(awq|gptq([-_]?int\d+)?|int\d+|fp\d+|w\d+a\d+|marlin|exl2|mlx|bnb|nf4)$",
    re.IGNORECASE,
)

# Common GGUF quants to fall back to when the exact requested quant is absent.
_FALLBACK_QUANTS = ("Q4_K_M", "Q4_0", "Q5_K_M", "Q6_K", "Q8_0", "Q3_K_M", "Q2_K")

# (name, quant) -> resolved ollama tag or None
_cache: Dict[Tuple[str, str], Optional[str]] = {}


def _headers() -> dict:
    return {"authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}


def _base_name(model_name: str) -> str:
    """Last path segment, with any -GGUF / inference-format suffix removed."""
    seg = model_name.rstrip("/").split("/")[-1]
    seg = re.sub(r"[-_.]?gguf$", "", seg, flags=re.IGNORECASE)
    prev = None
    while prev != seg:
        prev = seg
        seg = _FORMAT_SUFFIX.sub("", seg)
    return seg


def _quant_norm(q: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (q or "").lower())


def _score_repo(repo_id: str, base: str, org: str) -> int:
    rid = repo_id.lower()
    name_part = rid.split("/")[-1]
    repo_org = rid.split("/")[0]
    base_l = base.lower()
    score = 0
    if name_part.endswith("-gguf"):
        score += 20
    if name_part == f"{base_l}-gguf":
        score += 100
    if base_l and base_l in name_part:
        score += 40
    if org and repo_org == org.lower():
        score += 50  # same org as the base model → official build
    for i, p in enumerate(_PREFERRED):
        if repo_org == p:
            score += 30 - i
            break
    for bad in ("abliterated", "uncensored", "-i1", "imatrix"):
        if bad in name_part and bad not in base_l:
            score -= 8
    return score


async def resolve_gguf(model_name: str, quant: str) -> Optional[str]:
    """Return an Ollama-pullable `hf.co/<repo>:<quant>` tag, or None if no GGUF
    build can be found. Cached per (model_name, quant)."""
    key = (model_name or "", quant or "")
    if key in _cache:
        return _cache[key]
    result = await _resolve(model_name, quant)
    _cache[key] = result
    return result


async def _resolve(model_name: str, quant: str) -> Optional[str]:
    name = (model_name or "").strip().removeprefix("hf.co/").rstrip("/")
    if not name:
        return None
    qn = _quant_norm(quant)

    # Already a GGUF repo → trust it directly.
    if name.lower().endswith("gguf"):
        return f"hf.co/{name}:{quant}" if quant else f"hf.co/{name}"

    base = _base_name(name)
    org = name.split("/")[0] if "/" in name else ""
    try:
        async with httpx.AsyncClient(
            timeout=RESOLVE_TIMEOUT, follow_redirects=True, headers=_headers()
        ) as c:
            r = await c.get(
                f"{HF_API}/models",
                params={
                    "search": f"{base} GGUF",
                    "filter": "gguf",
                    "sort": "downloads",
                    "direction": -1,
                    "limit": 20,
                },
            )
            if r.status_code != 200:
                logger.warning("cookbook resolver: HF search '%s' -> %s", base, r.status_code)
                return None
            cands: List[str] = [
                (m.get("id") or m.get("modelId")) for m in r.json() if (m.get("id") or m.get("modelId"))
            ]
            ranked = sorted(
                ((rid, _score_repo(rid, base, org)) for rid in cands),
                key=lambda t: t[1],
                reverse=True,
            )
            # Verify the quant exists in the best candidates (then fall back).
            for rid, _ in ranked[:4]:
                try:
                    mr = await c.get(f"{HF_API}/models/{rid}")
                    if mr.status_code != 200:
                        continue
                    ggufs = [
                        str(s.get("rfilename", ""))
                        for s in mr.json().get("siblings", [])
                        if str(s.get("rfilename", "")).lower().endswith(".gguf")
                    ]
                    if not ggufs:
                        continue
                    if qn and any(qn in _quant_norm(f) for f in ggufs):
                        logger.info("cookbook resolver: %s (%s) -> hf.co/%s", model_name, quant, rid)
                        return f"hf.co/{rid}:{quant}"
                    for fb in _FALLBACK_QUANTS:
                        if any(_quant_norm(fb) in _quant_norm(f) for f in ggufs):
                            logger.info("cookbook resolver: %s -> hf.co/%s:%s (fallback)", model_name, rid, fb)
                            return f"hf.co/{rid}:{fb}"
                except Exception:
                    continue
            return None
    except Exception as e:  # noqa: BLE001
        logger.warning("cookbook resolver: %s failed: %s", model_name, str(e)[:140])
        return None
