"""
A1111 / Forge adapter — the fallback ImageProvider: one REST call in, base64
PNG out (docs/plans/image-generation-v0.md §3). Readiness = the sd-models list
answers AND is non-empty (reachable-but-modelless is honestly not ready).
"""

from __future__ import annotations

import base64
import logging

import httpx

from .provider import GENERATE_TIMEOUT_S, PROBE_TIMEOUT_S, GenSpec

logger = logging.getLogger(__name__)


class A1111Provider:
    id = "a1111"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def readiness(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
                resp = await client.get(f"{self.base_url}/sdapi/v1/sd-models")
                resp.raise_for_status()
                models = [
                    m.get("model_name") or m.get("title")
                    for m in resp.json() if isinstance(m, dict)
                ]
        except Exception as exc:  # noqa: BLE001 — readiness never raises
            return {"ready": False, "url": self.base_url, "reason": f"unreachable: {exc}", "models": []}
        models = [m for m in models if m]
        if not models:
            return {"ready": False, "url": self.base_url,
                    "reason": "reachable but no SD checkpoints installed", "models": []}
        return {"ready": True, "url": self.base_url, "reason": "", "models": models}

    async def txt2img(self, spec: GenSpec) -> bytes:
        payload = {
            "prompt": spec.prompt,
            "negative_prompt": spec.negative_prompt,
            "width": spec.width,
            "height": spec.height,
            "steps": spec.steps,
            "cfg_scale": spec.cfg,
            "seed": spec.seed if spec.seed is not None else -1,
        }
        if spec.model:
            payload["override_settings"] = {"sd_model_checkpoint": spec.model}
        async with httpx.AsyncClient(timeout=GENERATE_TIMEOUT_S) as client:
            resp = await client.post(f"{self.base_url}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            images = resp.json().get("images") or []
        if not images:
            raise RuntimeError("A1111 returned no images")
        # May arrive as bare base64 or a data: URI — take the payload either way.
        return base64.b64decode(str(images[0]).split(",", 1)[-1])
