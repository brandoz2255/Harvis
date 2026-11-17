"""Let a text-only model answer about images: a vision model describes them first.

A chat can hold an image while the picked model cannot see (Nemotron on the PAIR
router answers ``500 image input is not supported``). The image also stays in the
chat's history, so every later turn failed the same way. Before a native turn goes
out, this replaces each image part with a text description written by a local
vision model, and tells the answering model that is what it is reading.

Only acts when some Ollama host reports the picked model's capabilities and
"vision" is not among them. Unknown capabilities (a router that reports none) leave
the images alone, so a model that can see is never handed a description instead.

The vision model: HARVIS_VISION_MODEL when it is a vision model on some host, else
one already loaded in memory, else the smallest installed. Descriptions are cached
by image hash, so an image in history is described once, not every turn. Remote
image URLs are not fetched (that would be an outbound request on the user's behalf);
they get a note instead. Never raises: on any failure the image is swapped for a
note, which still beats a turn that cannot answer at all.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

MAX_IMAGES = 6
_DESCRIBE_TIMEOUT_S = float(os.getenv("HARVIS_VISION_BRIDGE_TIMEOUT_S", "120"))
_INFO_TTL_S = 60.0
_CACHE_MAX = 256
_DATA_URL = re.compile(r"^data:(image/[\w.+-]+);base64,(.+)$", re.S)
PROMPT = ("Describe this image for someone who cannot see it, so they can answer questions about it. "
          "Transcribe every piece of visible text exactly (code, error messages, labels, numbers). "
          "Describe layout, charts with their values, diagrams, UI elements and anything notable. "
          "Be factual; do not guess at what is not visible.")

_cache: "OrderedDict[str, str]" = OrderedDict()
_info: dict = {"at": 0.0, "hosts": []}


def enabled() -> bool:
    return os.getenv("HARVIS_VISION_BRIDGE", "1").strip().lower() not in ("0", "false", "no", "off")


def _bases() -> list[str]:
    out: list[str] = []
    try:
        from .ollama_hosts import configured_hosts

        out = [h.base_url.rstrip("/") for h in configured_hosts()]
    except Exception:  # noqa: BLE001
        pass
    primary = (os.getenv("OLLAMA_URL") or "http://ollama:11434").rstrip("/")
    return out + ([primary] if primary not in out else [])


async def _host(client: httpx.AsyncClient, base: str) -> dict:
    """{base, tags: {name: size}, loaded: set, caps: {name: [..] | None}} for one host."""
    info = {"base": base, "tags": {}, "loaded": set(), "caps": {}}
    try:
        r = await client.get(f"{base}/api/tags")
        r.raise_for_status()
        info["tags"] = {m.get("name"): int(m.get("size") or 0) for m in r.json().get("models") or [] if m.get("name")}
    except Exception:  # noqa: BLE001 — host down: it simply offers nothing
        return info
    try:
        r = await client.get(f"{base}/api/ps")
        info["loaded"] = {m.get("name") for m in r.json().get("models") or []}
    except Exception:  # noqa: BLE001
        pass
    for name in info["tags"]:
        try:
            r = await client.post(f"{base}/api/show", json={"model": name})
            caps = r.json().get("capabilities") if r.status_code == 200 else None
            info["caps"][name] = list(caps) if caps else None  # [] from a router = unknown
        except Exception:  # noqa: BLE001
            info["caps"][name] = None
    return info


async def _hosts() -> list[dict]:
    if time.time() - _info["at"] < _INFO_TTL_S and _info["hosts"]:
        return _info["hosts"]
    async with httpx.AsyncClient(timeout=6.0) as client:
        hosts = [await _host(client, b) for b in _bases()]
    _info.update(at=time.time(), hosts=hosts)
    return hosts


def can_see(model: str, hosts: list[dict]) -> Optional[bool]:
    """True/False when any host reports the model's capabilities, None when none does."""
    for h in hosts:
        caps = h["caps"].get(model)
        if caps:
            return "vision" in caps
    return None


def pick_vision(hosts: list[dict], wanted: str = "") -> Optional[tuple[str, str]]:
    """(base_url, model) of the vision model to describe with, or None."""
    seeing = [(h, m) for h in hosts for m, caps in h["caps"].items() if caps and "vision" in caps]
    if wanted:
        for h, m in seeing:
            if m == wanted:
                return h["base"], m
        logger.warning("vision_bridge: HARVIS_VISION_MODEL=%r is not a vision model on any host", wanted)
    if not seeing:
        return None
    # Already in memory first (no load wait), then the smallest (fastest) on disk.
    h, m = min(seeing, key=lambda hm: (hm[1] not in hm[0]["loaded"], hm[0]["tags"].get(hm[1]) or 1 << 62))
    return h["base"], m


async def _describe(base: str, model: str, b64: str, question: str) -> str:
    prompt = PROMPT + (f"\n\nThe user's question about it, for focus: {question[:500]}" if question else "")
    body = {"model": model, "stream": False, "think": False, "options": {"temperature": 0.2},
            "messages": [{"role": "user", "content": prompt, "images": [b64]}]}
    async with httpx.AsyncClient(timeout=_DESCRIBE_TIMEOUT_S) as client:
        r = await client.post(f"{base}/api/chat", json=body)
        if r.status_code == 400 and "think" in r.text.lower():  # a model that rejects the think flag
            body.pop("think")
            r = await client.post(f"{base}/api/chat", json=body)
        r.raise_for_status()
        text = (r.json().get("message") or {}).get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _question(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return ""


def has_images(messages: list) -> bool:
    return any(isinstance(p, dict) and p.get("type") == "image_url"
               for m in messages if isinstance(m, dict) and isinstance(m.get("content"), list)
               for p in m["content"])


async def replace_images(messages: list, model: str, describe: Callable[[str, str], Awaitable[str]],
                         vision_name: Optional[str]) -> int:
    """Swap every image part for text, in place; returns how many images were described.
    ``describe(b64, mime)`` raises on failure; ``vision_name`` None means there is none."""
    n, described = 0, 0
    for m in messages:
        if not (isinstance(m, dict) and isinstance(m.get("content"), list)):
            continue
        parts = []
        for p in m["content"]:
            if not (isinstance(p, dict) and p.get("type") == "image_url"):
                parts.append(p)
                continue
            n += 1
            url = str(((p.get("image_url") or {}).get("url")) if isinstance(p.get("image_url"), dict)
                      else p.get("image_url") or "")
            match = _DATA_URL.match(url)
            if vision_name is None:
                note = (f"[Image {n}: {model} can't see images and no image-reading model is installed, "
                        "so its content is unknown. Tell the user that.]")
            elif not match:
                note = f"[Image {n}: a linked image ({url[:80]}) that was not fetched, so its content is unknown.]"
            elif n > MAX_IMAGES:
                note = f"[Image {n}: not described (only the first {MAX_IMAGES} images are).]"
            else:
                key = hashlib.sha256(match.group(2).encode()).hexdigest()
                desc = _cache.get(key)
                if desc is None:
                    try:
                        desc = await describe(match.group(2), match.group(1))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("vision_bridge: %s could not describe image %d: %s",
                                       vision_name, n, exc.__class__.__name__)
                        desc = ""
                    if desc:
                        _cache[key] = desc
                        while len(_cache) > _CACHE_MAX:
                            _cache.popitem(last=False)
                else:
                    _cache.move_to_end(key)
                if desc:
                    described += 1
                    note = (f"[Image {n}, described by {vision_name} because {model} can't see images. "
                            f"Answer from this description and say it is one if it matters:]\n{desc}")
                else:
                    note = f"[Image {n}: {vision_name} could not describe it, so its content is unknown.]"
            parts.append({"type": "text", "text": note})
        m["content"] = parts
    return described


async def bridge(owui_body: dict) -> None:
    """Describe the turn's images when the picked local model cannot see. Never raises."""
    try:
        messages = owui_body.get("messages")
        model = str(owui_body.get("model") or "")
        if not enabled() or not model or not isinstance(messages, list) or not has_images(messages):
            return
        hosts = await _hosts()
        if can_see(model, hosts) is not False:
            return
        pick = pick_vision(hosts, (os.getenv("HARVIS_VISION_MODEL") or "").strip())
        question = _question(messages)

        async def describe(b64: str, _mime: str) -> str:
            return await _describe(pick[0], pick[1], b64, question)

        t0 = time.time()
        done = await replace_images(messages, model, describe, pick[1] if pick else None)
        logger.info("vision_bridge: %s can't see images; %d described by %s in %.1fs",
                    model, done, pick[1] if pick else "nothing", time.time() - t0)
    except Exception:  # noqa: BLE001 — a failed bridge leaves the turn as it was
        logger.warning("vision_bridge: skipped", exc_info=True)
