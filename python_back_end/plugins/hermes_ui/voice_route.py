"""Pick the model for a spoken turn by asking Laya one question.

A voice turn (the composer's hands-free conversation stamps ``surface: "voice"``)
asks the `laya` sidecar how to handle what was said:

* ``answer_fast`` — small talk or a quick fact: the small model, chat only.
* ``escalate``    — needs real reasoning: the big model (or the session's), chat only.
* ``tool``        — asks Harvis to do something: the session's model, auto mode, so
  the workspace detectors can start a run.
* ``clarify``     — too vague or garbled: the small model, told to ask one question back.

Laya is a classifier with calibrated confidence and is near chance zero-shot, so an
answer below ``HARVIS_LAYA_MIN_CONFIDENCE`` is ignored. Any failure (profile off,
timeout, bad reply) means no route: the turn runs exactly as a typed one would. A
failure also pauses the lookups for a minute so a missing sidecar costs one fast
connection error, not one per turn.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("hermes_ui.voice_route")

ROUTES = ("answer_fast", "escalate", "tool", "clarify")
QUESTION = {
    "type": "choice",
    "instructions": "A voice assistant just heard the user say this. How should it handle it?",
    "criteria": {
        # Wording measured against spoken samples on 2026-09-25: naming "hi or hello"
        # and "explain, compare, plan" moved greetings and explanations to the right route.
        "answer_fast": "a greeting like hi or hello, small talk, or a short factual question answered in one sentence",
        "escalate": "asks to explain, compare, plan, or reason through something in depth, or to write code",
        "tool": "asks the assistant to do something: run, open, install, search the web, change files or settings",
        "clarify": "too vague, cut off, or garbled to act on",
    },
}
CLARIFY_NOTE = ("The user's last message was spoken and may be cut off or misheard. "
                "Ask one short question to find out what they meant.")
PAUSE_AFTER_FAILURE = 60.0
TIMEOUT = httpx.Timeout(connect=1.0, read=3.0, write=1.0, pool=1.0)

_paused_until = 0.0


@dataclass(frozen=True)
class Route:
    choice: str
    confidence: float


@dataclass(frozen=True)
class Plan:
    model: str
    mode: str
    note: str
    label: str


def _url() -> str:
    return (os.getenv("HARVIS_LAYA_URL") or "").strip().rstrip("/")


def _min_confidence() -> float:
    try:
        return float(os.getenv("HARVIS_LAYA_MIN_CONFIDENCE", "0.5"))
    except ValueError:
        return 0.5


def parse(reply: dict) -> Route | None:
    """The route in a /v1/systemone reply, or None when it is missing or unsure."""
    answer = ((reply or {}).get("answers") or {}).get("route") or {}
    choice = answer.get("choice")
    try:
        confidence = float(answer.get("answer_confidence", answer.get("confidence", 0.0)))
    except (TypeError, ValueError):
        return None
    if choice not in ROUTES or confidence < _min_confidence():
        return None
    return Route(choice, confidence)


async def _ask(text: str, key: str, question: dict, client: httpx.AsyncClient | None) -> dict | None:
    """One Laya question about ``text``; the raw reply, or None when off, paused or failing."""
    global _paused_until
    url, text = _url(), (text or "").strip()
    if not url or not text or time.monotonic() < _paused_until:
        return None
    body = {"state": text[:4000], "questions": {key: question}, "model": "english"}
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=TIMEOUT) as own:
                resp = await own.post(f"{url}/v1/systemone", json=body)
        else:
            resp = await client.post(f"{url}/v1/systemone", json=body)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — a router that is down must never break the turn
        _paused_until = time.monotonic() + PAUSE_AFTER_FAILURE
        log.info("hermes_ui: laya voice router unavailable (%s); pausing %.0fs", exc, PAUSE_AFTER_FAILURE)
        return None


async def decide(text: str, client: httpx.AsyncClient | None = None) -> Route | None:
    reply = await _ask(text, "route", QUESTION, client)
    return parse(reply) if reply is not None else None


# ── voice navigation ─────────────────────────────────────────────────────────
# The UI matches page names itself and only asks here about looser phrasing it
# could not place. Measured 2026-09-25: Laya picked the named page confidently,
# but also sent "open the star map" to Browser at 0.82, so this bar is stricter.

STAY = "stay"
PAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_PAGES = 40


def _page_min_confidence() -> float:
    try:
        return float(os.getenv("HARVIS_LAYA_PAGE_MIN_CONFIDENCE", "0.8"))
    except ValueError:
        return 0.8


def page_question(pages: dict[str, str]) -> dict:
    criteria = {pid: f"asks to open or go to {label}" for pid, label in pages.items()}
    criteria[STAY] = "not asking to open a page: a question, small talk, or a task to do"
    return {"type": "choice",
            "instructions": "The user spoke to an app. Which page, if any, do they want opened?",
            "criteria": criteria}


def clean_pages(raw) -> dict[str, str]:
    """The UI's page list, validated: known-shape ids, short labels, bounded length."""
    pages: dict[str, str] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        pid, label = str(item.get("id") or ""), " ".join(str(item.get("label") or "").split())[:60]
        if PAGE_ID.match(pid) and pid != STAY and label:
            pages[pid] = label
        if len(pages) >= MAX_PAGES:
            break
    return pages


async def pick_page(text: str, pages: dict[str, str], client: httpx.AsyncClient | None = None) -> Route | None:
    """The page the line asks for, or None (not a page request, unsure, or router off)."""
    if not pages:
        return None
    reply = await _ask(text, "page", page_question(pages), client)
    answer = ((reply or {}).get("answers") or {}).get("page") or {}
    choice = answer.get("choice")
    try:
        confidence = float(answer.get("answer_confidence", answer.get("confidence", 0.0)))
    except (TypeError, ValueError):
        return None
    if choice not in pages or confidence < _page_min_confidence():
        return None
    return Route(choice, confidence)


def plan(route: Route, model: str, mode: str) -> Plan:
    """The model, mode and system note a route asks for. ``model`` / ``mode`` are the
    turn's own; a mode the user asked for outright (``mode != "auto"``) is kept."""
    fast = (os.getenv("HARVIS_VOICE_FAST_MODEL") or "").strip() or model
    big = (os.getenv("HARVIS_VOICE_BIG_MODEL") or "").strip() or model
    chat_mode = mode if mode != "auto" else "chat"
    if route.choice == "answer_fast":
        new_model, new_mode, note = fast, chat_mode, ""
    elif route.choice == "escalate":
        new_model, new_mode, note = big, chat_mode, ""
    elif route.choice == "clarify":
        new_model, new_mode, note = fast, chat_mode, CLARIFY_NOTE
    else:
        new_model, new_mode, note = model, mode, ""
    label = (f"Voice route: {route.choice.replace('_', ' ')} ({route.confidence:.2f}) "
             f"on {new_model or 'the Harvis default'}\n")
    return Plan(new_model, new_mode, note, label)
