"""
ComfyUI adapter — the primary ImageProvider (docs/plans/image-generation-v0.md §3).

Drives the LOCKED workflow graph in workflows/basic_txt2img.json: only the
whitelisted fields (prompts, size, steps, cfg, seed, ckpt_name) are patched
into a deep copy — the graph shape itself is never user-influenced.

Flow: POST /prompt {prompt: graph, client_id} → poll GET /history/{prompt_id}
until the SaveImage node's output appears → GET /view → PNG bytes.
Readiness = /system_stats answers AND /object_info reports ≥1 checkpoint.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import time
import uuid
from pathlib import Path

import httpx

from .provider import GENERATE_TIMEOUT_S, PROBE_TIMEOUT_S, GenSpec

logger = logging.getLogger(__name__)

_WORKFLOW_PATH = Path(__file__).parent / "workflows" / "basic_txt2img.json"

# Locked node ids in basic_txt2img.json — the whitelist of what txt2img may patch.
_NODE_KSAMPLER = "3"
_NODE_CHECKPOINT = "4"
_NODE_LATENT = "5"
_NODE_POSITIVE = "6"
_NODE_NEGATIVE = "7"

_POLL_INTERVAL_S = 1.0


def _load_workflow() -> dict:
    with open(_WORKFLOW_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class ComfyUIProvider:
    id = "comfyui"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def _checkpoints(self, client: httpx.AsyncClient) -> list[str]:
        """Installed checkpoint names via /object_info (CheckpointLoaderSimple's
        ckpt_name enum). Empty list = reachable but nothing to generate with."""
        resp = await client.get(f"{self.base_url}/object_info/CheckpointLoaderSimple")
        resp.raise_for_status()
        info = resp.json() or {}
        try:
            names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        except (KeyError, IndexError, TypeError):
            return []
        return [str(n) for n in names if n] if isinstance(names, list) else []

    async def readiness(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
                resp = await client.get(f"{self.base_url}/system_stats")
                resp.raise_for_status()
                models = await self._checkpoints(client)
        except Exception as exc:  # noqa: BLE001 — readiness never raises
            return {"ready": False, "url": self.base_url, "reason": f"unreachable: {exc}", "models": []}
        if not models:
            return {"ready": False, "url": self.base_url,
                    "reason": "reachable but no checkpoints installed", "models": []}
        return {"ready": True, "url": self.base_url, "reason": "", "models": models}

    def _patch_graph(self, spec: GenSpec, ckpt_name: str) -> dict:
        graph = copy.deepcopy(_load_workflow())
        graph[_NODE_CHECKPOINT]["inputs"]["ckpt_name"] = ckpt_name
        graph[_NODE_POSITIVE]["inputs"]["text"] = spec.prompt
        graph[_NODE_NEGATIVE]["inputs"]["text"] = spec.negative_prompt
        graph[_NODE_LATENT]["inputs"]["width"] = spec.width
        graph[_NODE_LATENT]["inputs"]["height"] = spec.height
        sampler = graph[_NODE_KSAMPLER]["inputs"]
        sampler["steps"] = spec.steps
        sampler["cfg"] = spec.cfg
        sampler["seed"] = spec.seed if spec.seed is not None else random.randint(0, 2**31 - 1)
        return graph

    async def txt2img(self, spec: GenSpec) -> bytes:
        async with httpx.AsyncClient(timeout=GENERATE_TIMEOUT_S) as client:
            # Resolve the checkpoint honestly: the requested model only if it is
            # actually installed, else the first available one (never a blind name
            # that would 400 deep inside the graph executor).
            available = await self._checkpoints(client)
            if not available:
                raise RuntimeError("ComfyUI has no checkpoints installed")
            ckpt_name = spec.model if spec.model in available else available[0]

            resp = await client.post(
                f"{self.base_url}/prompt",
                json={"prompt": self._patch_graph(spec, ckpt_name), "client_id": uuid.uuid4().hex},
            )
            resp.raise_for_status()
            prompt_id = (resp.json() or {}).get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI rejected the workflow: {resp.text[:300]}")

            # Poll history until the SaveImage output lands (bounded by the deadline).
            deadline = time.monotonic() + GENERATE_TIMEOUT_S
            image_ref = None
            while time.monotonic() < deadline:
                await asyncio.sleep(_POLL_INTERVAL_S)
                hist = await client.get(f"{self.base_url}/history/{prompt_id}")
                hist.raise_for_status()
                entry = (hist.json() or {}).get(prompt_id) or {}
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI execution failed for prompt {prompt_id}")
                for output in (entry.get("outputs") or {}).values():
                    images = output.get("images") or []
                    if images:
                        image_ref = images[0]
                        break
                if image_ref:
                    break
            if not image_ref:
                raise RuntimeError(f"ComfyUI generation timed out after {int(GENERATE_TIMEOUT_S)}s")

            view = await client.get(
                f"{self.base_url}/view",
                params={
                    "filename": image_ref.get("filename", ""),
                    "subfolder": image_ref.get("subfolder", ""),
                    "type": image_ref.get("type", "output"),
                },
            )
            view.raise_for_status()
            return view.content
