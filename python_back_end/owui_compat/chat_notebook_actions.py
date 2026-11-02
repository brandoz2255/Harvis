"""Chat actions that reach the Notebooks page: "make a notebook about Mars with some sources" and
"make me a quiz on Mars" (see chat_actions for how a turn gets here).

Both re-enter code the Notebooks page already uses: ``notebooks.discover._add_urls`` adds URL sources
and queues the normal ingester, and the Studio's ``onb_notebook_generate`` writes the artifact. The
reply carries a link the chat renders as a pill (``#/notebooks?nb=<id>``) that opens the notebook.

Sources come from links in the user's own message, or else from a short web search on the topic. A
link the model wrote is never used: a model can invent one. A study artifact needs read sources, so it
is generated in the background once ingestion settles; the Studio panel picks it up when it lands.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from fastapi.responses import StreamingResponse

from . import chat_abilities
from .chat_action_handlers import Ctx, clip, reply

logger = logging.getLogger(__name__)

DISCOVER_RESULTS = 5
MAX_LINKS = 10
READY_WAIT_S = 180.0
READY_POLL_S = 4.0
SEARCH_BUDGET_S = 20.0

chat_abilities.register(chat_abilities.Ability(
    "notebook", "making notebooks with sources", "make a notebook about Mars with some sources"))
chat_abilities.register(chat_abilities.Ability(
    "study", "quizzes, flashcards, mind maps and study guides", "make me a quiz on Mars"))

KINDS = {
    "quiz": ("quiz", "quiz"), "quizzes": ("quiz", "quiz"),
    "flashcards": ("flashcards", "set of flashcards"), "flash cards": ("flashcards", "set of flashcards"),
    "flashcard": ("flashcards", "set of flashcards"), "flash card": ("flashcards", "set of flashcards"),
    "mindmap": ("mindmap", "mind map"), "mind map": ("mindmap", "mind map"),
    "study guide": ("study_guide", "study guide"), "study_guide": ("study_guide", "study guide"),
    "briefing": ("briefing", "briefing"), "briefing doc": ("briefing", "briefing"),
    "faq": ("faq", "FAQ"), "timeline": ("timeline", "timeline"),
    "data table": ("data_table", "data table"), "data_table": ("data_table", "data table"),
}

_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+")
_TASKS: set = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


class _Background:
    """Stands in for FastAPI's BackgroundTasks so ``_add_urls`` can queue ingestion from a chat turn."""

    def add_task(self, fn, *args, **kwargs) -> None:
        _spawn(fn(*args, **kwargs))


def user_links(text: str) -> list[str]:
    return [u.rstrip(".,;:!?") for u in _URL.findall(text or "")][:MAX_LINKS]


def pill(notebook: Any, extra: str = "") -> str:
    title = clip(getattr(notebook, "title", "") or "Notebook", 80).replace("[", "(").replace("]", ")")
    return f"[📓 {title}](#/notebooks?nb={notebook.id}{extra})"


# ── fast paths (no model) ────────────────────────────────────────────────────
_LEAD = r"^\W*(?:(?:hey|hi|ok|okay|please|pls|harvis)[,\s]+)*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
_SOURCES_TAIL = r"(?:,?\s+(?:with|and\s+add|and\s+find)\s+(?:some\s+|a\s+few\s+)?(?:good\s+)?(?:sources?|links?|pages?)\b.*)?"
_NB_FAST = re.compile(
    _LEAD + r"(?:make|create|build|start|set\s+up)\s+(?:me\s+)?(?:an?\s+)?(?:new\s+)?notebook"
    r"(?:\s+with\s+(?:some\s+|a\s+few\s+)?(?:sources?|links?))?\s+(?:about|on|for|called|named|titled)\s+"
    r"(?P<topic>.+?)" + _SOURCES_TAIL + r"\s*[.!]?$", re.I | re.S)
# Only the kinds whose words mean a study artifact; "timeline" and "briefing" are everyday words and go
# through the model instead.
_STUDY_FAST = re.compile(
    _LEAD + r"(?:make|create|build|generate|give)\s+(?:me\s+)?(?:an?\s+)?(?:quick\s+|short\s+)?"
    r"(?P<kind>quiz|flash\s?cards?|mind\s?map|study\s+guide)\s+(?:about|on|for|from|of|covering)\s+"
    r"(?P<topic>.+?)\s*[.!]?$", re.I | re.S)
# "this", "the code above": the subject is the conversation, which a web search cannot find.
_POINTS_BACK = re.compile(r"^(?:this|that|it|these|those|the\s+above|above|what\s+we|our\s+(?:chat|conversation)|"
                          r"the\s+(?:code|chat|conversation|file|answer|text)\b)", re.I)
_FROM_NB = re.compile(r"^(?:(?P<topic>.+?)\s+(?:from|in|using)\s+)?(?:my|the)\s+"
                      r"(?:(?P<a>.+?)\s+notebook|notebook\s+(?:called\s+|named\s+)?(?P<b>.+?))$", re.I)


def split_notebook(topic: str) -> tuple[str, str]:
    """``(topic, notebook name)`` from "Mars", "my Mars notebook" or "rovers from my Mars notebook"."""
    topic = topic.strip().strip("\"'")
    m = _FROM_NB.match(topic)
    if not m:
        return topic, ""
    return (m.group("topic") or "").strip(), (m.group("a") or m.group("b") or "").strip().strip("\"'")


def notebook_fast_path(text: str) -> Optional[tuple[str, dict]]:
    if not text or len(text) > 400 or "\n" in text.strip():
        return None
    m = _NB_FAST.match(text)
    if m:
        topic = clip(_URL.sub("", m.group("topic")), 120).strip(" ,")
        if topic and not _POINTS_BACK.match(topic):
            return "make_notebook", {"topic": topic}
        return None
    m = _STUDY_FAST.match(text)
    if m:
        topic, name = split_notebook(m.group("topic"))
        if (topic and _POINTS_BACK.match(topic)) or not (topic or name):
            return None
        return "make_study", {"kind": m.group("kind"), "topic": topic, "notebook": name}
    return None


# ── shared steps ─────────────────────────────────────────────────────────────
def _manager(ctx: Ctx):
    from notebooks.router import get_notebook_manager

    return get_notebook_manager(ctx.request)


async def _discover(topic: str) -> list[dict]:
    from agent_reach.tools import web_search
    from notebooks.discover import shape_results

    try:
        raw = await asyncio.wait_for(web_search(topic, DISCOVER_RESULTS), timeout=SEARCH_BUDGET_S)
    except Exception as exc:  # noqa: BLE001
        logger.info("chat notebook: web search for %r failed: %s", topic, exc)
        return []
    return shape_results(raw, DISCOVER_RESULTS)


async def _new_notebook(ctx: Ctx, manager, title: str, topic: str) -> tuple[Any, int]:
    """Create a notebook and add sources; returns the notebook and how many sources were added."""
    from notebooks.discover import _add_urls
    from notebooks.models import CreateNotebookRequest

    notebook = await manager.create_notebook(ctx.user_id, CreateNotebookRequest(title=title))
    links = user_links(ctx.text)
    items = [{"url": u, "title": ""} for u in links] if links else await _discover(topic)
    if not items:
        return notebook, 0
    added = await _add_urls(manager, _Background(), notebook.id, ctx.user_id, items, "chat")
    return notebook, len(added["added"])


async def _find_notebook(manager, user_id: int, name: str):
    wanted = name.lower().strip()
    notebooks, _ = await manager.list_notebooks(user_id, 100, 0)
    exact = [n for n in notebooks if (n.title or "").lower().strip() == wanted]
    return (exact or [n for n in notebooks if wanted in (n.title or "").lower()] or [None])[0]


def _title(topic: str) -> str:
    topic = clip(topic, 80)
    return topic[:1].upper() + topic[1:]


# ── make_notebook ────────────────────────────────────────────────────────────
async def make_notebook(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    topic = clip(_URL.sub("", str(args.get("topic") or args.get("title") or "")), 120).strip(" ,")
    title = _title(args.get("title") or topic)
    if not title:
        return None
    manager = _manager(ctx)
    notebook, count = await _new_notebook(ctx, manager, title, topic or title)
    if count:
        plural = "source" if count == 1 else "sources"
        text = (f"I made the notebook **{notebook.title}** and added {count} {plural}. They are being read now; "
                f"open it to watch them come in.")
    else:
        text = (f"I made the notebook **{notebook.title}**, but I could not find sources for it. "
                "Open it and add some from Sources.")
    return reply(f"{text}\n\n{pill(notebook)}")


# ── make_study ───────────────────────────────────────────────────────────────
async def _sources_settled(manager, notebook_id, user_id: int) -> bool:
    """Wait for ingestion; True when at least one source is ready to generate from."""
    waited = 0.0
    while True:
        sources = await manager.list_sources(notebook_id, user_id)
        states = [getattr(s.status, "value", s.status) for s in sources]
        busy = any(s in ("pending", "processing") for s in states)
        if not busy or waited >= READY_WAIT_S:
            return "ready" in states
        await asyncio.sleep(READY_POLL_S)
        waited += READY_POLL_S


async def generate_when_ready(request, manager, notebook_id, user_id: int, kind: str, prompt: str) -> None:
    try:
        if not await _sources_settled(manager, notebook_id, user_id):
            logger.info("chat notebook: %s has no ready source; %s not made", notebook_id, kind)
            return
        from onb_compat.router import onb_notebook_generate

        body = {"kind": kind, **({"prompt": prompt} if prompt else {})}
        await onb_notebook_generate(str(notebook_id), body, request, {"id": user_id}, manager)
        logger.info("chat notebook: made %s in %s", kind, notebook_id)
    except Exception:
        logger.warning("chat notebook: %s for %s failed", kind, notebook_id, exc_info=True)


async def make_study(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    kind_word = " ".join(str(args.get("kind") or "").lower().replace("-", " ").split())
    if kind_word not in KINDS:
        return None
    kind, label = KINDS[kind_word]
    topic, name = clip(args.get("topic"), 120), clip(args.get("notebook"), 80)
    if topic and not name:
        topic, name = split_notebook(topic)
    manager = _manager(ctx)
    notebook = await _find_notebook(manager, ctx.user_id, name) if name else None
    if notebook is None and name and not topic:
        return reply(f"I could not find a notebook called \"{name}\". Say what the {label} should be about and "
                     "I will make a notebook for it.")
    prompt = f"Focus on {topic}." if notebook is not None and topic else ""
    note = ""
    if notebook is None:
        notebook, count = await _new_notebook(ctx, manager, _title(topic), topic)
        if not count:
            return reply(f"I made the notebook **{notebook.title}**, but I could not find sources for it, so there "
                         f"is nothing to make a {label} from yet. Add sources, then ask again.\n\n{pill(notebook)}")
        note = f"I made the notebook **{notebook.title}** with {count} source{'s' if count != 1 else ''}. "
    _spawn(generate_when_ready(ctx.request, manager, notebook.id, ctx.user_id, kind, prompt))
    return reply(f"{note}I am making a {label} from **{notebook.title}** now. It appears in the notebook's Studio "
                 f"panel in a minute or two.\n\n{pill(notebook, f'&make={kind}')}")


# ── wiring for chat_actions ──────────────────────────────────────────────────
NOTEBOOK_CUE = re.compile(r"\b(?:make|create|build|start|set\s+up|new)\b[^.?!]{0,40}\bnotebooks?\b", re.I)
STUDY_CUE = re.compile(r"\b(?:quiz(?:zes)?|flash\s?cards?|mind\s?maps?|study\s+guides?|briefing\s+doc\w*|faqs?)\b",
                       re.I)

_STR = {"type": "string"}


def tool_specs(tool) -> dict:
    return {
        "make_notebook": tool(
            "make_notebook", "Make a new notebook (a research workspace) and fill it with web sources on a topic.",
            {"topic": _STR, "title": _STR}, ["topic"]),
        "make_study": tool(
            "make_study", "Make a quiz, flashcards, mind map, study guide, briefing, FAQ, timeline or data table "
            "from a notebook. `notebook` is the name of one of the user's notebooks if they named one.",
            {"kind": {"type": "string", "enum": ["quiz", "flashcards", "mindmap", "study_guide", "briefing", "faq",
                                                 "timeline", "data_table"]},
             "topic": _STR, "notebook": _STR}, ["kind"]),
    }


HANDLERS = {"make_notebook": make_notebook, "make_study": make_study}
