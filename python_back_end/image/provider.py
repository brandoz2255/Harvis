"""
Harvis Local Image Generation v0 — the provider abstraction
(docs/plans/image-generation-v0.md §3-4).

One ``ImageProvider`` interface; A1111 and ComfyUI are drop-in implementations
behind it. Harvis uses WHICHEVER reports ready — ``resolve_provider()`` probes
A1111 first (dead-simple REST → fastest first working generation), then ComfyUI,
and returns a ``NoneProvider`` that reports honest unavailability when neither
answers. Readiness is HONEST: a probe either sees the provider or it reports
WHY not (unreachable / no models installed) — never a faked ready.

SSRF note: provider base URLs come ONLY from env (with internal-network
defaults) — user input never reaches a URL.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

DEFAULT_A1111_URL = "http://harvis-a1111:7860"
DEFAULT_COMFYUI_URL = "http://harvis-comfyui:8188"

# Short, honest probe — an absent provider answers "unreachable" in ~2s, not 60.
PROBE_TIMEOUT_S = 3.0
# One 512x512 SD1.5 generation on the 5070 is seconds; leave slack for cold VAE load.
GENERATE_TIMEOUT_S = 120.0

_ALLOWED_WORKFLOWS = ("basic_txt2img",)


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


@dataclass
class GenSpec:
    """The ONLY fields Harvis fills into a generation — everything else in the
    provider (sampler, scheduler, graph shape) is locked server-side."""
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg: float = 6.0
    seed: Optional[int] = None
    model: Optional[str] = None
    workflow: str = "basic_txt2img"

    def __post_init__(self):
        self.prompt = (self.prompt or "").strip()
        if not self.prompt:
            raise ValueError("prompt is required")
        self.negative_prompt = (self.negative_prompt or "").strip()
        self.width = _clamp_int(self.width, 256, 1024, 512)
        self.height = _clamp_int(self.height, 256, 1024, 512)
        self.steps = _clamp_int(self.steps, 1, 50, 20)
        try:
            self.cfg = max(1.0, min(30.0, float(self.cfg)))
        except (TypeError, ValueError):
            self.cfg = 6.0
        if self.seed is not None:
            self.seed = _clamp_int(self.seed, 0, 2**31 - 1, 0)
        if self.model is not None:
            self.model = str(self.model).strip()[:256] or None
        if self.workflow not in _ALLOWED_WORKFLOWS:
            raise ValueError(f"unknown workflow {self.workflow!r} (allowed: {', '.join(_ALLOWED_WORKFLOWS)})")


class ImageProvider(Protocol):
    """A local txt2img backend. readiness() NEVER raises — it returns
    {ready, url, reason, models} honestly; txt2img() raises on failure."""
    id: str

    async def readiness(self) -> dict: ...

    async def txt2img(self, spec: GenSpec) -> bytes: ...


class NoneProvider:
    """Honest 'no provider is up' placeholder — readiness carries the per-provider
    reasons gathered at resolve time; txt2img refuses with the same message."""
    id = "none"

    def __init__(self, reason: str):
        self.reason = reason or "no image provider configured"

    async def readiness(self) -> dict:
        return {"ready": False, "url": None, "reason": self.reason, "models": []}

    async def txt2img(self, spec: GenSpec) -> bytes:
        raise RuntimeError(f"no image provider ready: {self.reason}")


def _candidates() -> list:
    """Probe order: A1111 first (simplest REST), then ComfyUI."""
    from .a1111 import A1111Provider
    from .comfyui import ComfyUIProvider
    a1111_url = (os.getenv("HARVIS_IMAGE_A1111_URL") or DEFAULT_A1111_URL).strip() or DEFAULT_A1111_URL
    comfy_url = (os.getenv("HARVIS_IMAGE_COMFYUI_URL") or DEFAULT_COMFYUI_URL).strip() or DEFAULT_COMFYUI_URL
    return [A1111Provider(a1111_url), ComfyUIProvider(comfy_url)]


async def _probe_all() -> list[tuple]:
    """(provider, readiness_report) for every candidate, probed concurrently."""
    providers = _candidates()
    reports = await asyncio.gather(*(p.readiness() for p in providers))
    return list(zip(providers, reports))


async def resolve_provider() -> ImageProvider:
    """The first READY provider, or a NoneProvider whose reason says why each
    candidate isn't (honest degradation, never a silent 503)."""
    reasons: list[str] = []
    for provider, report in await _probe_all():
        if report.get("ready"):
            return provider
        reasons.append(f"{provider.id}: {report.get('reason') or 'not ready'}")
    return NoneProvider("; ".join(reasons))


async def readiness_summary() -> dict:
    """The /api/harvis/providers entry: {kind:'image', id, ready, url, reason, models}."""
    reasons: list[str] = []
    for provider, report in await _probe_all():
        if report.get("ready"):
            return {
                "kind": "image", "id": provider.id, "ready": True,
                "url": report.get("url"), "reason": "",
                "models": report.get("models") or [],
            }
        reasons.append(f"{provider.id}: {report.get('reason') or 'not ready'}")
    return {
        "kind": "image", "id": "none", "ready": False, "url": None,
        "reason": "; ".join(reasons) or "no image provider configured", "models": [],
    }
