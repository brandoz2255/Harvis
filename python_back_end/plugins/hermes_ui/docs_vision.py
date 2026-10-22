"""Ask a local vision model whether rendered pages look broken.

Never loads anything it can avoid: the model is the one named in the request when it
can see images, else the first installed of FALLBACKS, preferring one Ollama already
holds in memory. Pages go one at a time, downscaled, and every failure just skips the
page: the code checks never wait on this.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

log = logging.getLogger("hermes_ui.docs")

FALLBACKS = ("gemma3:4b", "gemma4:e2b", "gemma4:e4b")
MAX_PAGES = 6
MAX_WIDTH = 896
PAGE_TIMEOUT_S = 45
# Each check holds one blocking Ollama call at a time, for up to PAGE_TIMEOUT_S. Their own threads, and a cap on
# how many checks look at once, keep a burst of them from using up the threads the rest of the backend shares.
MAX_CHECKS = 2
_POOL = ThreadPoolExecutor(max_workers=MAX_CHECKS * 2, thread_name_prefix="docs-vision")
_active = 0
MAX_PER_PAGE = 3
# One yes/no question per problem, not "list the problems": asked for a list, a small model names a problem on
# every page (measured: gemma3:4b flagged all of four correct slides), and asked yes/no it mostly answers false.
# A blank page is not asked at all; the pixels say that.
QUESTIONS = {
    "text_runs_off_the_page_edge": "text runs off the edge of the page or out of its box",
    "two_shapes_overlap": "shapes drawn on top of each other",
    "text_too_faint_to_read": "text too faint to read",
}
SCHEMA = {"type": "object", "properties": {k: {"type": "boolean"} for k in QUESTIONS}, "required": list(QUESTIONS)}
PROMPT = ("Look at this rendered slide and answer each question about what is visible. "
          "Answer false unless the problem is obvious; most slides are fine.")
_NO_PROBLEM = re.compile(r"^(none|no (visible )?(issues?|problems?)|n/?a|nothing|looks (fine|good))\b", re.I)


def _base() -> str:
    return (os.environ.get("OLLAMA_URL") or "http://host.docker.internal:11434").rstrip("/")


def _call(path: str, payload: Optional[dict] = None, timeout: float = 10) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(_base() + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:    # noqa: S310 - OLLAMA_URL is operator config
        return json.loads(resp.read())


async def _ask(path: str, payload: Optional[dict] = None, timeout: float = 10) -> dict:
    return await asyncio.get_running_loop().run_in_executor(_POOL, _call, path, payload, timeout)


def _names(listing: dict) -> list[str]:
    return [str(m.get("name") or m.get("model") or "") for m in listing.get("models") or []]


async def pick_model(requested: Optional[str] = None) -> Optional[str]:
    """The vision model to use, or None when this Ollama has none to offer."""
    if isinstance(requested, str) and requested.strip():
        try:
            shown = await _ask("/api/show", {"model": requested.strip()})
            if "vision" in (shown.get("capabilities") or []):
                return requested.strip()
        except Exception:                                             # noqa: BLE001 - unknown model: use a fallback
            log.info("hermes_ui: requested vision model %r not usable, picking another", requested.strip())
    try:
        installed = _names(await _ask("/api/tags"))
        try:
            loaded = _names(await _ask("/api/ps"))
        except Exception:                                             # noqa: BLE001 - only a preference
            loaded = []
    except Exception as exc:                                          # noqa: BLE001 - Ollama down or unreachable
        log.info("hermes_ui: vision check skipped, Ollama not reachable (%s)", type(exc).__name__)
        return None
    have = [m for m in FALLBACKS if m in installed]
    return next((m for m in have if m in loaded), have[0] if have else None)


def downscale(png: bytes, max_width: int = MAX_WIDTH) -> bytes:
    """The page as a PNG no wider than ``max_width`` (a model reads nothing more from extra pixels)."""
    from PIL import Image

    with Image.open(io.BytesIO(png)) as im:
        im = im.convert("RGB")
        if im.width > max_width:
            im = im.resize((max_width, max(round(im.height * max_width / im.width), 1)), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
        return out.getvalue()


def parse_reply(reply: str) -> list[str]:
    """Problems a reply reports: the yes/no object when there is one, else whatever list it gave instead."""
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S)
    start = text.find("{")
    if 0 <= start < (text.find("[") if "[" in text else len(text)):
        try:
            answers, _end = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            answers = None
        if isinstance(answers, dict):
            return [phrase for key, phrase in QUESTIONS.items() if answers.get(key) is True]
    return parse_problems(text)


def parse_problems(reply: str) -> list[str]:
    """Problems named in a model's reply: the first [...] in it, read as JSON, else as quoted strings."""
    text = reply or ""
    start = text.find("[")
    if start < 0:
        return []
    end = text.rfind("]")
    chunk = text[start:end + 1] if end > start else text[start:]
    items: list[Any] = []
    try:
        loaded = json.loads(chunk)
        items = loaded if isinstance(loaded, list) else []
    except ValueError:
        # Cut off or not quite JSON: take the quoted strings that are there.
        items = re.findall(r'"((?:[^"\\]|\\.){4,200})"', chunk)
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item = next((v for v in item.values() if isinstance(v, str)), "")
        if not isinstance(item, str):
            continue
        item = " ".join(item.split()).strip(" .")
        if 3 <= len(item) <= 200 and not _NO_PROBLEM.match(item) and item not in out:
            out.append(item)
    return out[:MAX_PER_PAGE]


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[1:2].islower() else text


def pick_pages(count: int, limit: int = MAX_PAGES) -> list[int]:
    """Up to ``limit`` page indexes spread across ``count`` pages, first and last included."""
    if count <= limit:
        return list(range(count))
    return sorted({round(i * (count - 1) / (limit - 1)) for i in range(limit)})


def is_blank(png: bytes) -> bool:
    from PIL import Image, ImageStat

    with Image.open(io.BytesIO(png)) as im:
        return max(ImageStat.Stat(im.convert("L")).stddev) < 1.0


def _left(deadline: Optional[float]) -> Optional[float]:
    """Seconds until ``deadline`` (a time.monotonic() value), None for no deadline."""
    return None if deadline is None else deadline - time.monotonic()


async def review_page(model: str, png: bytes, deadline: Optional[float] = None) -> list[str]:
    """Problems on one page. Raises asyncio.TimeoutError, without asking the model, if ``deadline`` has passed."""
    if await asyncio.to_thread(is_blank, png):
        return ["the page is blank"]
    image = await asyncio.to_thread(downscale, png)
    payload = {"model": model, "stream": False, "keep_alive": "5m", "format": SCHEMA,
               "options": {"num_ctx": 4096, "temperature": 0},
               "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(image).decode()]}]}
    left = _left(deadline)
    if left is not None and left <= 0:
        raise asyncio.TimeoutError
    reply = await _ask("/api/chat", payload, timeout=PAGE_TIMEOUT_S if left is None else min(PAGE_TIMEOUT_S, left))
    return parse_reply((reply.get("message") or {}).get("content") or "")


async def vision_check(pages: list[bytes], label, requested: Optional[str] = None,
                       deadline: Optional[float] = None) -> dict:
    """{issues, model, done, skipped, busy, timed_out}: ``label(i)`` names page ``i`` ('slide 3').

    model is None if none is available; busy is True, with nothing looked at, when MAX_CHECKS checks are already running.
    ``deadline`` is a time.monotonic() value: no model is asked after it, the pages not reached count as skipped, and
    timed_out is True."""
    global _active
    result = {"issues": [], "model": None, "done": 0, "skipped": 0, "busy": False, "timed_out": False}
    if _active >= MAX_CHECKS:
        result["busy"] = True
        return result
    _active += 1
    try:
        return await _look(pages, label, requested, result, deadline)
    finally:
        _active -= 1


async def _look(pages: list[bytes], label, requested: Optional[str], result: dict,
                deadline: Optional[float] = None) -> dict:
    left = _left(deadline)
    if left is not None and left <= 0:
        result["timed_out"] = True
        return result
    try:
        model = result["model"] = await asyncio.wait_for(pick_model(requested), left)
    except asyncio.TimeoutError:
        result["timed_out"] = True
        return result
    if not model or not pages:
        return result
    todo = pick_pages(len(pages))
    for n, i in enumerate(todo):
        left = _left(deadline)
        if left is not None and left <= 0:
            result["timed_out"] = True
            result["skipped"] += len(todo) - n
            break
        wait = PAGE_TIMEOUT_S + 5 if left is None else min(PAGE_TIMEOUT_S + 5, left)
        try:
            problems = await asyncio.wait_for(review_page(model, pages[i], deadline), wait)
        except Exception as exc:                                      # noqa: BLE001 - one page must not stop the rest
            log.info("hermes_ui: vision check skipped page %d (%s)", i + 1, type(exc).__name__)
            result["skipped"] += 1
            left = _left(deadline)
            result["timed_out"] = result["timed_out"] or (left is not None and left <= 0)
            continue
        result["done"] += 1
        result["issues"] += [{"severity": "warn", "where": label(i), "message": f"Looks like {_lower_first(p)}"}
                             for p in problems]
    return result
