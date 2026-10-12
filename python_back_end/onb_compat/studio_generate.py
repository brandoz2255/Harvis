"""Structured Studio artifacts: quiz, flashcards and mind map.

Moved out of router.py so the parsing can be tested without the web stack and so
the three kinds share one hardened path: a schema-constrained request (Ollama
``format``), an 8k context so the source text is not silently cut, a JSON reader
that survives code fences, <think> blocks and output cut off mid-way, one retry,
and a plain-language error when the model still returns nothing usable.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

CONTENT_CHARS = 9000
NUM_CTX = 8192
NUM_PREDICT = 3500
MAX_MAP_NODES = 60
MAX_MAP_DEPTH = 4


class StudioError(Exception):
    """The artifact could not be made. ``str(exc)`` is shown to the user."""


# Ollama structured-output schemas — constrain small models to the EXACT shape the
# interactive renderers need (passed as `format`, not just "json").
_QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["q", "options", "answer"],
            },
        }
    },
    "required": ["questions"],
}
_FLASHCARDS_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
                "required": ["front", "back"],
            },
        }
    },
    "required": ["cards"],
}


def _normalize_quiz(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Coerce model output to [{q, options[str], answer:int, explanation}] — tolerant of
    the ways small models wander (A/B/C/D keys, letter answers, stray fields)."""
    raw = data.get("questions") or data.get("quiz") or data.get("items") if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        q_text = item.get("q") or item.get("question") or item.get("text") or ""
        opts = item.get("options")
        if not isinstance(opts, list):
            lettered = []
            for k in ("A", "B", "C", "D", "E", "F"):
                if k in item:
                    v = item[k]
                    if isinstance(v, list):
                        v = v[0] if v else ""
                    lettered.append(str(v))
            opts = lettered
        opts = [str(o) for o in opts if o not in (None, "")] if isinstance(opts, list) else []
        if not str(q_text).strip() or len(opts) < 2:
            continue
        ans = item.get("answer")
        if isinstance(ans, str):
            mm = re.search(r"\d+", ans)
            if mm:
                ans = int(mm.group())
            elif ans.strip().upper() in ("A", "B", "C", "D", "E", "F"):
                ans = "ABCDEF".index(ans.strip().upper())
            else:
                ans = 0
        if not isinstance(ans, int) or ans < 0 or ans >= len(opts):
            ans = 0
        out.append({
            "q": str(q_text),
            "options": opts,
            "answer": ans,
            "explanation": str(item.get("explanation") or item.get("rationale") or ""),
        })
    return out


def _normalize_flashcards(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Coerce model output to [{front, back}] — tolerant of term/definition aliases."""
    raw = data.get("cards") or data.get("flashcards") or data.get("items") if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        front = item.get("front") or item.get("term") or item.get("question") or item.get("q") or ""
        back = item.get("back") or item.get("definition") or item.get("answer") or item.get("a") or ""
        if not str(front).strip() or not str(back).strip():
            continue
        out.append({"front": str(front), "back": str(back)})
    return out


_MINDMAP_LEAF = {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}
_MINDMAP_MID = {
    "type": "object",
    "properties": {"label": {"type": "string"}, "children": {"type": "array", "items": _MINDMAP_LEAF}},
    "required": ["label"],
}
_MINDMAP_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "children": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "children": {"type": "array", "items": _MINDMAP_MID}},
                "required": ["label"],
            },
        },
    },
    "required": ["title", "children"],
}


def _node(item: Any, depth: int, budget: List[int]) -> Optional[Dict[str, Any]]:
    if isinstance(item, str):
        item = {"label": item}
    if not isinstance(item, dict) or budget[0] <= 0:
        return None
    label = " ".join(str(item.get("label") or item.get("title") or item.get("name") or item.get("text") or "").split())
    if not label:
        return None
    budget[0] -= 1
    kids: List[Dict[str, Any]] = []
    raw_kids = item.get("children") or item.get("branches") or item.get("nodes") or item.get("subtopics") or []
    if depth < MAX_MAP_DEPTH and isinstance(raw_kids, list):
        for kid in raw_kids:
            child = _node(kid, depth + 1, budget)
            if child:
                kids.append(child)
    return {"label": label[:140], "children": kids}


def _normalize_mindmap(data: Any) -> Dict[str, Any]:
    """``{title, children:[{label, children:[...]}]}`` or an empty dict when unusable."""
    if not isinstance(data, dict):
        return {}
    budget = [MAX_MAP_NODES]
    raw = data.get("children") or data.get("branches") or data.get("nodes") or data.get("topics") or []
    children = [n for n in (_node(k, 1, budget) for k in raw if raw) if n] if isinstance(raw, list) else []
    if not children:
        return {}
    title = " ".join(str(data.get("title") or data.get("label") or data.get("root") or "Mind map").split())
    return {"title": title[:140], "children": children}


def parse_json_lenient(raw: str) -> Any:
    """Best-effort JSON from model output: fences, <think>, prose around it, truncation."""
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL | re.IGNORECASE).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return {}
    body = text[min(starts):]
    for closer in ("}", "]"):
        end = body.rfind(closer)
        if end > 0:
            try:
                return json.loads(body[: end + 1])
            except ValueError:
                continue
    return _repair_truncated(body)


def _repair_truncated(body: str) -> Any:
    """Cut at the last complete element and close what is still open (output hit the token cap)."""
    stack: List[str] = []
    in_str = esc = False
    cut = None
    for i, ch in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            if stack:
                cut = (i + 1, "".join(reversed(stack)))
    if not cut:
        return {}
    try:
        return json.loads(body[: cut[0]] + cut[1])
    except ValueError:
        return {}


_KINDS: Dict[str, Dict[str, Any]] = {
    "quiz": {
        "schema": _QUIZ_SCHEMA,
        "prompt": (
            "Create 8-10 multiple-choice questions based ONLY on the following content. Return "
            'ONLY a JSON object exactly like {"questions":[{"q":"question text","options":["A","B",'
            '"C","D"],"answer":0,"explanation":"why"}]} where "answer" is the 0-based index of the '
            "correct option and every question has exactly 4 options. No prose, no Markdown, no code "
            "fences. Do not invent facts beyond the content.\n\n{content}"
        ),
    },
    "flashcards": {
        "schema": _FLASHCARDS_SCHEMA,
        "prompt": (
            "Create 12-18 study flashcards based ONLY on the following content. Return ONLY a JSON "
            'object exactly like {"cards":[{"front":"term or question","back":"answer or '
            'definition"}]}. No prose, no Markdown, no code fences. Do not invent facts beyond the '
            "content.\n\n{content}"
        ),
    },
    "mindmap": {
        "schema": _MINDMAP_SCHEMA,
        "prompt": (
            "Build a mind map of the following content. Return ONLY a JSON object exactly like "
            '{"title":"central topic","children":[{"label":"main branch","children":[{"label":"detail",'
            '"children":[{"label":"sub-detail"}]}]}]}. Use 4-7 main branches, each with 2-5 children. '
            "Labels are short phrases (under 10 words), not sentences. No prose, no Markdown, no code "
            "fences. Use ONLY the content; do not invent facts.\n\n{content}"
        ),
    },
}


def _shape(kind: str, data: Any) -> Tuple[str, Dict[str, Any]]:
    """``(title, content)`` for a parsed model reply; empty content when it is unusable."""
    if kind == "quiz":
        items = _normalize_quiz(data) if isinstance(data, dict) else _normalize_quiz({"questions": data})
        return (f"Quiz · {len(items)} questions", {"questions": items}) if items else ("", {})
    if kind == "flashcards":
        items = _normalize_flashcards(data) if isinstance(data, dict) else _normalize_flashcards({"cards": data})
        return (f"Flashcards · {len(items)} cards", {"cards": items}) if items else ("", {})
    tree = _normalize_mindmap(data)
    return (f"Mind map · {tree['title']}", {"tree": tree}) if tree else ("", {})


async def _ask(prompt: str, schema: Dict[str, Any], model: str, ollama_url: str, temperature: float) -> str:
    body: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": schema,
        "options": {"temperature": temperature, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240.0)) as client:
            resp = await client.post(f"{ollama_url}/api/generate", json=body)
            if resp.status_code == 400:  # a server that rejects `format`; ask for plain JSON
                body.pop("format")
                resp = await client.post(f"{ollama_url}/api/generate", json=body)
            resp.raise_for_status()
            return (resp.json().get("response") or "").strip()
    except httpx.TimeoutException as exc:
        raise StudioError("The model took too long to answer. Try again, or pick a faster model.") from exc
    except httpx.HTTPStatusError as exc:
        raise StudioError(f"The model server answered HTTP {exc.response.status_code} for {model}. Check the model is installed.") from exc
    except httpx.HTTPError as exc:
        raise StudioError(f"The model server could not be reached ({type(exc).__name__}).") from exc


async def generate_structured(kind: str, content: str, model: str, ollama_url: str) -> Tuple[str, Dict[str, Any]]:
    """Make a quiz, flashcard set or mind map. Returns ``(title, content)`` or raises StudioError."""
    spec = _KINDS[kind]
    prompt = spec["prompt"].replace("{content}", (content or "")[:CONTENT_CHARS])
    for attempt, temperature in enumerate((0.4, 0.8)):
        raw = await _ask(prompt, spec["schema"], model, ollama_url, temperature)
        title, shaped = _shape(kind, parse_json_lenient(raw))
        if shaped:
            return title, shaped
    noun = {"quiz": "quiz", "flashcards": "flashcards", "mindmap": "mind map"}[kind]
    raise StudioError(
        f"{model} did not return a usable {noun}. Small models sometimes fail at this; try again, "
        "or choose a larger model from the model picker."
    )
