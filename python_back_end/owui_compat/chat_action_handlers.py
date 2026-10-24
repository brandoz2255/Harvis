"""What each chat action does once it has been chosen (see chat_actions).

Every handler re-enters code Harvis already has: the document prompt and chat lane,
the research bridge, the workspace bridge, the image bridge, the cron store and the
memory provider. Nothing here runs model code of its own, and every argument a model
supplied is treated as data: it is length-capped, parameterised or regex-escaped, never
executed and never used to pick another user's rows. Memory and scheduled-job handlers
are scoped to the calling user id only.

A handler returns a ``StreamingResponse`` that answers the turn, or ``None`` to let the
turn fall through to the lanes after it (normal chat). Handlers never raise to the router;
``chat_actions`` wraps the dispatch.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from fastapi.responses import StreamingResponse

from .doc_bridge import KINDS, doc_system_prompt

logger = logging.getLogger(__name__)

MAX_JOBS_PER_USER = 100
MAX_FORGET_AT_ONCE = 3
_CRON_PAGE = "the Scheduled jobs page"


@dataclass
class Ctx:
    """One turn: the request, the body, the caller and what they typed."""

    request: Any
    body: dict
    user: Any
    pool: Any
    user_id: int
    text: str


def clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def reply(text: str) -> StreamingResponse:
    from .image_bridge import _notice_sse

    return _notice_sse(text)


def _last_user_index(messages: list) -> int:
    return next((i for i in range(len(messages) - 1, -1, -1)
                 if isinstance(messages[i], dict) and messages[i].get("role") == "user"), -1)


def with_last_user_text(body: dict, text: str) -> dict:
    """A deep copy of ``body`` whose newest user message says ``text``."""
    out = copy.deepcopy(body)
    messages = out.get("messages") or []
    idx = _last_user_index(messages)
    if idx >= 0:
        messages[idx]["content"] = text
    return out


# ── make_document ────────────────────────────────────────────────────────────
_KIND_WORDS = {
    "deck": "deck", "slides": "deck", "slide": "deck", "presentation": "deck", "powerpoint": "deck",
    "pptx": "deck", "doc": "doc", "document": "doc", "docx": "doc", "report": "doc", "word": "doc",
    "sheet": "sheet", "spreadsheet": "sheet", "excel": "sheet", "xlsx": "sheet", "csv": "sheet",
    "pdf": "pdf",
}


async def make_document(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    word = clip(args.get("kind"), 20).lower()
    kind = word if word in KINDS else _KIND_WORDS.get(word)
    if kind is None:
        return None
    messages = ctx.body.get("messages")
    if not isinstance(messages, list):
        return None
    idx = _last_user_index(messages)
    if idx < 0:
        return None
    # Same placement as doc_bridge.maybe_prepare_doc_turn: next to the question, so a persona
    # or project instruction stays intact. The user's own message is left exactly as typed.
    prompt = doc_system_prompt(kind)
    prev = messages[idx - 1] if idx > 0 else None
    if not (isinstance(prev, dict) and prev.get("role") == "system" and prev.get("content") == prompt):
        messages.insert(idx, {"role": "system", "content": prompt})
    from .chat_completion import run_chat_completion

    logger.info("chat_actions: make_document kind=%s", kind)
    return await run_chat_completion(ctx.request, ctx.body, user_id=ctx.user_id)


# ── deep_research ────────────────────────────────────────────────────────────
async def deep_research(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    question = clip(args.get("question"), 500)
    if len(question) < 3:
        return None
    from .research_bridge import maybe_handle_research

    body = with_last_user_text(ctx.body, f"Deep research: {question}")
    return await maybe_handle_research(ctx.request, body, ctx.user)


# ── start_agent_run ──────────────────────────────────────────────────────────
async def start_agent_run(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    mode = clip(args.get("mode"), 20).lower()
    if mode not in ("agent", "orchestrate"):
        mode = "agent"
    from .workspace_bridge import maybe_handle_workspace

    # The run's brief is the user's own message, which workspace_bridge reads from the body;
    # the model's `goal` argument is only logged, so a paraphrase cannot change the task.
    body = copy.deepcopy(ctx.body)
    body["harvis_mode"] = mode
    logger.info("chat_actions: start_agent_run mode=%s", mode)
    return await maybe_handle_workspace(ctx.request, body, ctx.user)


# ── generate_image ───────────────────────────────────────────────────────────
async def generate_image(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    prompt = clip(args.get("prompt"), 500)
    if len(prompt) < 3:
        return None
    from .image_bridge import maybe_handle_image_generation

    # "create image <prompt>" is image_bridge's explicit prefix: it forces the image lane, so a
    # provider that is off or not ready answers with its honest notice instead of the model guessing.
    body = with_last_user_text(ctx.body, f"create image {prompt}")
    return await maybe_handle_image_generation(ctx.request, body, ctx.user)


# ── schedule_task ────────────────────────────────────────────────────────────
_DAYPART_MERIDIEM = {"morning": "am", "afternoon": "pm", "evening": "pm", "night": "pm"}
_WHEN_RE = re.compile(r"^(?:every|each)\s+(?P<spec>.+?)(?:\s+at\s+(?P<time>.+?))?$")
_DURATION_SPEC = re.compile(r"^(?:\d+\s*)?(?:minutes?|mins?|hours?|hrs?)$")
_BARE_TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?$")


def normalize_when(text: str) -> tuple[Optional[str], bool]:
    """``(schedule_text, needs_time)`` for "every morning at 8" style phrases.

    ``schedule_text`` is what ``cron_schedule.parse_schedule`` understands, or None when the
    phrase is not one this can read. ``needs_time`` is True for a day phrase with no clock time
    ("every morning"), which gets a question instead of a guess.
    """
    clean = " ".join((text or "").strip().lower().rstrip(".!").split())
    m = _WHEN_RE.match(clean)
    if not m:
        return None, False
    spec, at = m.group("spec"), m.group("time")
    if _DURATION_SPEC.match(spec):
        return (None, False) if at else (f"every {spec}", False)
    meridiem = _DAYPART_MERIDIEM.get(spec)
    if spec in _DAYPART_MERIDIEM:
        spec = "day"
    if not at:
        return None, True
    bare = _BARE_TIME.match(at.strip())
    if bare and meridiem and int(bare.group(1)) < 12:
        at = at.strip() + meridiem
    return f"every {spec} at {at.strip()}", False


def _cron_store(pool):
    from plugins.cron.store import PgCronJobStore

    return PgCronJobStore(pool)


_ASK_WHEN = ("What time should it run? For example \"every morning at 8\", \"every weekday at 9:30\" "
             "or \"every 2 hours\". I have not scheduled anything yet.")


async def create_job(ctx: Ctx, when: str, what: str) -> StreamingResponse:
    """Create a chat-context scheduled job for ``ctx.user_id`` and say what was created."""
    from plugins.hermes_ui.cron_schedule import ScheduleError, parse_schedule

    what = clip(what, 500)
    if not what:
        return reply("What should the reminder say? I have not scheduled anything yet.")
    parsed = None
    needs_time = False
    try:
        parsed = parse_schedule(clip(when, 120))
    except ScheduleError:
        text, needs_time = normalize_when(when)
        if text:
            try:
                parsed = parse_schedule(text)
            except ScheduleError:
                parsed = None
    if parsed is None:
        return reply(_ASK_WHEN)
    stype, expr, display = parsed
    store = _cron_store(ctx.pool)
    if len(await store.list_for_user(ctx.user_id)) >= MAX_JOBS_PER_USER:
        return reply(f"You already have {MAX_JOBS_PER_USER} scheduled jobs, so I did not add another. "
                     f"Delete some on {_CRON_PAGE} first.")
    meta = {"context": "chat", "source": "chat_actions", "schedule_display": display}
    # The saved prompt is what the model is asked on each run; wrapping the user's words keeps a
    # run a reminder instead of an attempt to do the task.
    job = await store.create(user_id=ctx.user_id, name=what[:60], schedule_type=stype, schedule_expr=expr,
                             prompt=f"Remind me to {what}", delivery=None, metadata=meta)
    if job is None:
        return reply("I could not save that scheduled job, so nothing was created. Please try again.")
    when_txt = f" Next run: {job.next_run_at.strftime('%Y-%m-%d %H:%M')} UTC." if job.next_run_at else ""
    return reply(
        f"Scheduled: \"{what[:120]}\", {display}. Times are in UTC.{when_txt} "
        f"You can pause or delete it on {_CRON_PAGE} (job \"{job.name}\").")


async def schedule_task(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    when = clip(args.get("when"), 120)
    what = clip(args.get("prompt"), 500)
    if not what:
        return reply("What should the reminder say, and when should it run? I have not scheduled anything yet.")
    if not when:
        return reply(_ASK_WHEN)
    return await create_job(ctx, when, what)


# ── memory ───────────────────────────────────────────────────────────────────
_LEAD = re.compile(r"^\s*(?:asked harvis to remember|remember(?: that)?)\s*[:,-]?\s*", re.I)


async def _provider(pool):
    from plugins.memory.preamble import _get_or_activate_provider

    return await _get_or_activate_provider(pool)


async def _memory_rows(pool, user_id: int) -> list[tuple[int, str]]:
    """``(id, content)`` of this user's own memories, newest first. Pending imports are left out."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, content FROM harvis_user_memory WHERE user_id = $1 "
            "AND COALESCE(metadata->>'pending', '') NOT IN ('true', 'True', '1') "
            "ORDER BY created_at DESC LIMIT 300", int(user_id))
    return [(int(r["id"]), str(r["content"])) for r in rows]


def memory_matches(needle: str, content: str) -> bool:
    """True when ``content`` says what ``needle`` says: a whole-word substring, or the same
    fact in different words (the dedupe rule the memory store already uses)."""
    from plugins.memory import dedupe

    needle = _LEAD.sub("", needle or "").strip(" .!")
    if len(needle) < 3:
        return False
    if re.search(r"(?<![a-z0-9])" + re.escape(needle.lower()) + r"(?![a-z0-9])", content.lower()):
        return True
    return dedupe.same_memory(needle, content)


async def _memory_save(ctx: Ctx, text: str) -> StreamingResponse:
    from plugins.hermes_ui import learn

    fact = clip(text, 280)
    if len(fact) < 3:
        return reply("What should I remember?")
    if not (await learn.settings(ctx.pool, ctx.user_id))["memory"]:
        return reply("Memory is switched off for your account, so I did not save that.")
    saved = await learn.save_facts(ctx.pool, ctx.user_id, [fact], source="chat_action")
    if not saved:
        return reply("I already have that (or it looked like a secret, which I never store), so I did not add it.")
    return reply(f"Saved: \"{saved[0]}\". Say \"forget that {fact[:60]}\" any time to remove it.")


async def _memory_forget(ctx: Ctx, text: str) -> StreamingResponse:
    needle = clip(text, 200)
    if len(_LEAD.sub("", needle).strip(" .!")) < 3:
        return reply("Which memory should I forget? Tell me what it says.")
    provider = await _provider(ctx.pool)
    if provider is None or getattr(provider, "name", "") != "builtin":
        return reply("Forgetting one memory by wording needs the built-in memory store, which is not active, "
                     "so I deleted nothing.")
    hits = [(i, c) for i, c in await _memory_rows(ctx.pool, ctx.user_id) if memory_matches(needle, c)]
    if not hits:
        return reply(f"I could not find a saved memory matching \"{needle[:80]}\", so nothing was deleted.")
    if len(hits) > MAX_FORGET_AT_ONCE:
        shown = "\n".join(f"- {c[:100]}" for _i, c in hits[:6])
        return reply(f"That matches {len(hits)} memories, so I deleted none. Tell me which one:\n{shown}")
    gone = []
    for memory_id, content in hits:
        if await provider.forget(ctx.user_id, memory_id=memory_id):
            gone.append(content)
    if not gone:
        return reply("I found it but could not delete it, so nothing changed.")
    return reply("Forgot:\n" + "\n".join(f"- {_LEAD.sub('', c).strip()[:140]}" for c in gone)
                 + "\nIf that was a mistake, tell me again and I will save it back.")


async def _memory_list(ctx: Ctx) -> StreamingResponse:
    provider = await _provider(ctx.pool)
    entries = await provider.recall(ctx.user_id, query=None, limit=60) if provider is not None else []
    shown = [e.content.strip() for e in entries
             if e.content and not (e.metadata or {}).get("pending")][:20]
    if not shown:
        return reply("I do not have anything saved about you yet.")
    return reply("Here is what I remember about you:\n" + "\n".join(f"- {_LEAD.sub('', s)[:160]}" for s in shown)
                 + "\nSay \"forget that ...\" to remove one.")


async def memory(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    action = clip(args.get("action"), 12).lower()
    text = str(args.get("text") or "")
    if action == "save":
        return await _memory_save(ctx, text)
    if action == "forget":
        return await _memory_forget(ctx, text)
    if action == "list":
        return await _memory_list(ctx)
    return None


# ── search_connectors ────────────────────────────────────────────────────────
async def search_connectors(ctx: Ctx, args: dict) -> Optional[StreamingResponse]:
    """Read-only: names catalog entries that match. It never installs or enables anything."""
    query = clip(args.get("query"), 80).lower()
    if len(query) < 2:
        return None
    from plugins.hermes_ui.rest_capabilities import _merged_catalog

    words = [w for w in re.findall(r"[a-z0-9]+", query) if len(w) > 1]
    hits = []
    for key, src in (await _merged_catalog()).items():
        hay = " ".join(str(src.get(f) or "") for f in ("id", "name", "description", "category")).lower()
        if words and all(w in hay for w in words):
            hits.append((str(src.get("name") or key), clip(src.get("description"), 100)))
    if not hits:
        return reply(f"I did not find a connector matching \"{query}\". Browse the full list under "
                     "Capabilities > Connections.")
    lines = "\n".join(f"- {n}: {d}" if d else f"- {n}" for n, d in hits[:6])
    return reply(f"These connectors match \"{query}\":\n{lines}\n"
                 "I have not installed anything. Install from Capabilities > Connections.")


HANDLERS = {
    "make_document": make_document,
    "deep_research": deep_research,
    "start_agent_run": start_agent_run,
    "generate_image": generate_image,
    "schedule_task": schedule_task,
    "memory": memory,
    "search_connectors": search_connectors,
}

