"""UX-0: the authoring turn as a background job with a live stream.

The recipe lane has always answered immediately — it knows the project, revision and
build before it writes a byte, so the chat card can name them and poll. The authoring
lane could not: ``cad_agent.author()`` returns one dict when the whole tool loop is
over, so for the twenty-odd seconds a frontier model spends planning, proposing and
building, the browser had nothing at all. Not a card, not a project to open, not a
line of what was happening.

This module is the missing half. A job row is minted *before* the model is asked
anything, the card names that job id from the first byte, and the loop runs in a task
that reports as it goes: which tool it called, what came back, and the moment a
project id exists — which is the moment "Open CAD Workspace" becomes a real link
rather than a promise.

Two things it deliberately does not do:

* It does not invent an event log. Activity lives on the job row, because whether CAD
  gets a ``cad_events`` table or borrows the workspace one is an open decision, and a
  foundation is a bad place to answer a question nobody asked yet.
* It does not decide anything about the geometry. Every claim the card makes about
  what was built still comes from ``GET /api/cad/builds/{bid}``. This stream says what
  the *model* did; the build says what the *engine* made.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from workspace.secret_redaction import redact_text

from . import cad_agent, cad_designspec, cad_store, fab_cad

logger = logging.getLogger(__name__)

# An authoring turn is minutes of tool calls, not thousands of events. The cap is a
# runaway guard, not a window — a job that hits it has something wrong with it.
MAX_ACTIVITY = 250

# What a folded reasoning row shows before anyone presses it.
THINK_HEADING_LIMIT = 72

# How much reasoning one job may keep, in characters, across all of its rows.
#
# This ceiling is not about the reader's patience — it is about how activity is
# stored. `_Activity.add` rewrites the WHOLE event list on every append, so a row
# holding 2 kB of thought costs that 2 kB again on every row that follows it. Ten
# ordinary thoughts are free; a model that reasons for pages would otherwise turn a
# linear timeline into a quadratic write. Past the budget the headings still land —
# a reader sees that the model kept thinking — and only the expandable bodies stop,
# which is the honest way to run out of room.
THINK_BUDGET = 24_000


class CadJobBroadcaster:
    """Fan-out live job events to every subscriber.

    Copied in shape from ``workspace_router.WorkspaceLiveBroadcaster`` and for the same
    reason: a single queue lets whichever consumer polls first *steal* an event from
    the others, and two browser tabs on one job is an ordinary thing to do.

    The backlog is what closes the replay→subscribe gap. A subscriber that connects
    after the run has begun would otherwise miss everything emitted between the DB
    snapshot it replayed and the moment it attached — and the card would sit on
    "Connecting…" while the model finished behind it.
    """

    __slots__ = ("_subscribers", "_backlog")
    _BACKLOG_MAX = 512

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._backlog: list = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        # Fully synchronous — no await between reading the backlog and joining the
        # subscriber list, so `put()` cannot interleave and drop an event into the gap.
        for item in self._backlog:
            q.put_nowait(item)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def put(self, item) -> None:
        if item is None:
            self._backlog = []  # the run ended; the row is authoritative from here
        else:
            self._backlog.append(item)
            if len(self._backlog) > self._BACKLOG_MAX:
                self._backlog = self._backlog[-self._BACKLOG_MAX:]
        subs = list(self._subscribers)
        if subs:
            await asyncio.gather(*(q.put(item) for q in subs))


_broadcasters: dict[str, CadJobBroadcaster] = {}

# Task references, held for the same reason `cad_router._running` holds build tasks:
# `create_task` returns the only reference, and an authoring turn nobody is awaiting
# can otherwise be collected mid-flight. Keyed by job id, which is what `cancel`
# below looks the running turn up by.
_job_tasks: dict[str, asyncio.Task] = {}

# The build a job is waiting on right now, or nothing between builds. Kept beside the
# row rather than instead of it: the row is what a cancel arriving on another worker
# reads, and this is the fast path for the common case where the cancel lands in the
# same process that started the turn.
_job_builds: dict[str, str] = {}

# UX-G. Turns waiting on the one in front of them, per conversation, oldest first.
#
# The entries carry the *lane* and the tool context, which are live Python objects and
# cannot be written to a row — which is precisely why the queue is memory and the row
# is truth. A queued row is real, nameable and cancellable on its own; this dict only
# decides what runs next. A backend that stops loses the ordering, and the reaper in
# ``cad_store.REAP_STRANDED_CAD_JOBS_SQL`` is what stops an abandoned row from claiming
# forever that it is about to start.
_queued: dict[str, list[dict]] = {}

# Job id → the conversation whose queue holds it, so a cancel can find its entry
# without walking every queue.
_queued_in: dict[str, str] = {}


def broadcaster(job_id: str) -> CadJobBroadcaster:
    b = _broadcasters.get(job_id)
    if b is None:
        b = _broadcasters[job_id] = CadJobBroadcaster()
    return b


async def close(job_id: str) -> None:
    """Send the terminal sentinel and forget the job.

    Dropping the entry is safe precisely because the run is over: a subscriber that
    arrives afterwards gets a fresh empty broadcaster, and the row it replays is now
    the complete story. Keeping them would make this dict grow for the life of the
    process.
    """
    b = _broadcasters.pop(job_id, None)
    if b is not None:
        await b.put(None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Activity vocabulary
#
# One label per tool, written for the person watching rather than the model that
# called it. These are the "design activity" rows — public, sanitized, and never a
# paraphrase of anything private. The tool NAME is public API; its arguments are not
# echoed here at all, which is the cheapest possible way to honour that rule.
# ---------------------------------------------------------------------------

_TOOL_LABELS = {
    "cad_get_capabilities": "Checking what the local engine can build",
    "cad_get_schema": "Reading the parametric schema",
    "cad_create_project": "Creating the project",
    "cad_propose_revision": "Proposing a revision",
    "cad_start_build": "Building the geometry",
    "cad_get_build": "Reading the build result",
    "cad_cancel_build": "Cancelling the build",
    "cad_inspect_revision": "Inspecting the revision",
    "cad_compare_revisions": "Comparing revisions",
    "cad_list_artifacts": "Listing the exports",
    "cad_render_views": "Checking the rendered views",
}


def _tool_label(name: str, ok: bool) -> str:
    # The sidecar lane sees MCP-qualified names ("mcp__harvis-cad__cad_start_build");
    # the HTTP lane sees the bare ones. Same tool, same row.
    bare = name.rsplit("__", 1)[-1] if "__" in name else name
    base = _TOOL_LABELS.get(bare) or f"Calling {bare}"
    return base if ok else f"{base} — refused"


def _think_heading(text: str) -> str:
    """The one line a folded reasoning row shows, taken from the reasoning itself.

    Never written by a second model. A summary of a thought, generated by something
    other than the thing that thought it, is a *claim about* the reasoning, and a
    collapsed row would have no way to tell the reader which of the two it was
    showing — the same rule the `say` row already follows.

    So the heading is the thought's own opening: a summarised thinking block usually
    starts with its own title (often bold, since providers write markdown), and when
    it does not, the first sentence is the closest thing to one the text contains.
    """
    first = ""
    for line in text.splitlines():
        line = line.strip().strip("#").strip()
        if line:
            first = line
            break
    if not first:
        return "Thinking"
    # A bold or emphasised opener is a title the model wrote for itself; keep the
    # words and drop the markup, which would otherwise be printed literally.
    first = re.sub(r"[*_`]+", "", first).strip()
    if len(first) > THINK_HEADING_LIMIT:
        # Cut at the end of a sentence when there is one inside the budget, so the
        # heading reads as a finished thought rather than a truncated paragraph.
        window = first[: THINK_HEADING_LIMIT + 1]
        stop = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
        first = window[:stop] if stop > 24 else window[:THINK_HEADING_LIMIT].rstrip() + "…"
    return first.rstrip(" .")


def _spec_label(stated: dict) -> str:
    """One line naming what the request pinned down, in the reader's own units.

    Composed from `cad_designspec.extract`'s output and nothing else, so a dimension
    appears here only because a regular expression found it in the user's sentence.
    A request nothing could be read from says so — it does not get a hopeful caption.
    """
    parts: list[str] = []
    overall = stated.get("overall_mm")
    edge = stated.get("cube_edge_mm")
    bore = stated.get("bore_diameter_mm")
    if isinstance(overall, list) and len(overall) == 3:
        parts.append(" × ".join(_mm(v) for v in sorted(overall, reverse=True)) + " mm")
    elif isinstance(edge, (int, float)):
        parts.append(f"{_mm(edge)} mm cube")
    else:
        # A sentence that named only some of the envelope — "12 mm tall" on its own —
        # still pinned that one down, and saying so beats saying nothing was read.
        for name in ("length", "width", "height", "depth", "thickness"):
            v = stated.get(f"{name}_mm")
            if isinstance(v, (int, float)):
                parts.append(f"{_mm(v)} mm {name}")
    for key, word in (("across_flats_mm", "across flats"),
                      ("across_corners_mm", "across corners")):
        if isinstance(stated.get(key), (int, float)):
            parts.append(f"{_mm(stated[key])} mm {word}")
    if isinstance(bore, (int, float)):
        through = " through" if stated.get("bore_through") else ""
        parts.append(f"Ø{_mm(bore)} mm{through} bore")
    parts.extend(_v2_stated(stated))
    if not parts:
        return "Read the request — no dimension in it could be read as a requirement"
    return "Read the request — " + ", ".join(parts)


# The part-scoped dimensions regex/v2 reads. Keyed by suffix because the role is the
# prefix — `body_height_mm`, `lid_cavity_depth_mm` — and the role is whatever word the
# user used, not a fixed list this module gets to enumerate.
_V2_SUFFIXES = (
    ("_height_mm", "{n} mm tall {role}"),
    ("_wall_mm", "{n} mm {role} wall"),
    ("_base_mm", "{n} mm {role} base"),
    ("_cavity_depth_mm", "{n} mm deep {role} cavity"),
)


def _v2_stated(stated: dict) -> list[str]:
    """The v2 half of the caption.

    Without this the jar the whole evidence tranche was built around reported "no
    dimension in it could be read as a requirement" on a build that measured nine of
    them: the caption only ever knew the v1 envelope keys, and regex/v2 writes
    part-scoped ones (`body_height_mm`, `lid_cavity_depth_mm`) instead. Still composed
    from `stated` and nothing else — a phrase appears here only because an expression
    found it in the user's own sentence.
    """
    out: list[str] = []
    # Suffix order outside, key order inside: the caption then reads in the order a
    # person describes a part — how tall, then its walls, then its floor, then what
    # is hollowed out of it — rather than alphabetically by role.
    for suffix, template in _V2_SUFFIXES:
        for key in sorted(stated):
            if key.endswith(suffix) and isinstance(stated[key], (int, float)):
                out.append(template.format(n=_mm(stated[key]),
                                           role=key[: -len(suffix)].replace("_", " ")))
    clearance = stated.get("fit_clearance_mm")
    if isinstance(clearance, (int, float)):
        basis = stated.get("fit_clearance_basis")
        # The basis is named because "0.3 mm clearance" means two different gaps
        # depending on it, and the spec recorded which one it assumed.
        out.append(f"{_mm(clearance)} mm {basis} clearance" if isinstance(basis, str)
                   else f"{_mm(clearance)} mm clearance")
    count = stated.get("separate_parts")
    if isinstance(count, int):
        out.append(f"{count} separate parts")
    if stated.get("coaxial"):
        out.append("concentric")
    return out


def _mm(value: Any) -> str:
    """Trim the trailing `.0` a float carries into a sentence about millimetres."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(f)) if f.is_integer() else f"{f:g}"


class _Activity:
    """The job's growing event list, persisted and broadcast as one unit.

    Every append does both: writes the row and publishes to whoever is listening. The
    row is what a reload replays; the broadcast is what a connected card sees now.
    Neither is allowed to fail the run — a design timeline that can kill the part it is
    describing is worse than no timeline.
    """

    def __init__(self, pool, job_id: str) -> None:
        self._pool = pool
        self._job_id = job_id
        self._events: list[dict] = []
        self._seq = 0

    @property
    def events(self) -> list[dict]:
        return self._events

    async def add(self, kind: str, label: str, **extra: Any) -> None:
        self._seq += 1
        event = {"seq": self._seq, "at": _now(), "kind": kind, "label": label}
        event.update({k: v for k, v in extra.items() if v is not None})
        self._events.append(event)
        del self._events[:-MAX_ACTIVITY]
        try:
            await cad_store.update_job(self._pool, self._job_id,
                                       activity=self._events, **_columns(extra))
        except Exception:
            logger.debug("cad_jobs: could not persist activity", exc_info=True)
        try:
            await broadcaster(self._job_id).put(event)
        except Exception:
            logger.debug("cad_jobs: could not broadcast activity", exc_info=True)


# Only these keys, arriving on an activity event, also move the job's own columns.
# Anything else stays inside the event where it was written.
_PROMOTED = ("phase", "title", "project_id", "revision_id", "build_id", "conformance")


def _columns(extra: dict) -> dict:
    return {k: v for k, v in extra.items() if k in _PROMOTED and v is not None}


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

async def run_job(pool, job_id: str, description: str, *, lane, ctx) -> None:
    """Run one authoring turn and record it. Never raises — this is a bare task.

    The honesty rule from ``cad_bridge._native_lane`` carries over unchanged: a lane
    that resolved and then failed is reported as itself. There is no quiet retry on a
    smaller model, because a user told Opus authored their part deserves that to be
    true, and a background job makes a silent substitution *easier* to hide, not more
    acceptable.
    """
    activity = _Activity(pool, job_id)
    started = time.monotonic()
    tool_started = {"at": 0.0}
    # `since` is the clock a "Reasoned for N" line is measured against: the moment the
    # last recorded step finished. Nothing else happens in that gap — a tool call would
    # have written its own row — so it is the model's own time, not the turn's.
    thinking = {"since": started, "spent": 0}

    await activity.add("started", f"Selected {lane.model} via {lane.provider}",
                       phase="authoring", provider=lane.provider, model=lane.model)

    # DE-8e: what the request pinned down, read before the model is asked anything.
    # This is the only thing in the turn that exists *before* geometry does, so it is
    # what the workspace draws its concept sketch from — a scale outline of the stated
    # envelope instead of a spinner over an empty viewport. Extraction is the same
    # regex pass `cad_generate` grades the result against, so the sketch and the
    # conformance verdict are two views of one answer key rather than two opinions.
    try:
        spec = cad_designspec.extract(description)
        stated = spec.get("stated") or {}
        await activity.add("spec", _spec_label(stated),
                           stated=stated or None,
                           unknowns=(spec.get("unknowns") or None),
                           units=spec.get("units"))
    except Exception:  # a sketch is never worth failing a build over
        logger.debug("cad_jobs: could not read a design spec from the request",
                     exc_info=True)

    async def on_event(ev: dict) -> None:
        kind = ev.get("kind")
        if kind == "tool_start":
            tool_started["at"] = time.monotonic()
            return
        if kind == "think":
            # DE-9. The model's reasoning, recorded as a row that is FOLDED — the
            # heading is public, the body is behind a press. That shape is the whole
            # permission: the workspace stops pretending an authoring turn is a list
            # of tool names, and a reader who wants to know why the model chose 5 mm
            # can ask, without the panel shouting private working at everyone who
            # opens it.
            #
            # Redaction happens here rather than at the capture site because this is
            # the persist boundary — the same choke point `workspace_events` uses, and
            # for the same reason it was added there: a run once wrote a live API key
            # into a durable row. Reasoning is the likeliest text in the whole turn to
            # quote a value it read, so it gets the same treatment, no exceptions.
            text = redact_text(str(ev.get("text") or "").strip())
            if not text:
                return
            heading = _think_heading(text)
            ms = int((time.monotonic() - thinking["since"]) * 1000)
            thinking["since"] = time.monotonic()
            if thinking["spent"] + len(text) > THINK_BUDGET:
                # Out of room for bodies, still honest about the step: the row says
                # the model thought and how long for, and simply has nothing to open.
                await activity.add("think", heading, duration_ms=ms, truncated=True)
                return
            thinking["spent"] += len(text)
            # `clipped` is a different fact from `truncated`: truncated means the row
            # kept no body at all, clipped means it kept the opening of one. A body
            # that simply stops mid-word reads as a broken panel, so the reader is
            # told which of the two happened rather than left to guess.
            extra = {"thinking": text, "duration_ms": ms}
            if ev.get("clipped"):
                extra["clipped"] = True
            await activity.add("think", heading, **extra)
            return
        if kind == "say":
            # The model's narration, recorded as its own row so the timeline reads as
            # a turn someone can follow rather than a list of tool names. The label IS
            # the text — there is no summarizing pass here, because a summary of one
            # sentence written by another model would be a second claim about what the
            # first one meant, and the panel would have no way to say which it showed.
            text = str(ev.get("text") or "").strip()
            if text:
                await activity.add("say", text)
            return
        if kind == "tool":
            name = str(ev.get("tool") or "tool")
            ok = bool(ev.get("ok"))
            ms = int((time.monotonic() - tool_started["at"]) * 1000) if tool_started["at"] else None
            await activity.add("tool", _tool_label(name, ok), tool=name, ok=ok,
                               duration_ms=ms, error_code=ev.get("error_code"))
            thinking["since"] = time.monotonic()
        elif kind == "ids":
            # The moment that makes the card's "Open CAD Workspace" a real link.
            await activity.add("project", f"Project ready: {ev.get('title') or 'untitled'}",
                               project_id=ev.get("project_id"),
                               revision_id=ev.get("revision_id"),
                               title=ev.get("title"))
        elif kind == "build_started":
            # Recorded on the row, not only in memory. `cancel` below reads it from
            # the row so it works from any request handler, and so a build that is
            # still running in the engine when this process dies is still nameable
            # afterwards rather than becoming an anonymous unit of work nobody can
            # stop. No activity line: the user learns a build started from the phase.
            _job_builds[job_id] = str(ev.get("build_id") or "")
            await cad_store.update_job(pool, job_id, phase="building",
                                       build_id=ev.get("build_id"))
        elif kind == "build":
            _job_builds.pop(job_id, None)
            await activity.add("build", "Geometry built", phase="building",
                               build_id=ev.get("build_id"),
                               conformance=ev.get("conformance"))

    try:
        result = await cad_agent.author(description, lane=lane, ctx=ctx,
                                        on_event=on_event)
    except asyncio.CancelledError:
        await activity.add("done", "Cancelled")
        await cad_store.update_job(pool, job_id, status="cancelled", phase="cancelled")
        await close(job_id)
        raise
    except Exception as exc:  # a crashed task must still close the card
        logger.warning("cad_jobs: authoring turn failed (%s)", type(exc).__name__,
                       exc_info=True)
        await activity.add("done", "The authoring turn failed")
        await cad_store.update_job(pool, job_id, status="failed", phase="failed",
                                   error_code="job_crashed",
                                   error_detail=type(exc).__name__)
        await close(job_id)
        return
    finally:
        _job_tasks.pop(job_id, None)
        _job_builds.pop(job_id, None)

    ok = bool(result.get("ok") and result.get("build_id"))
    elapsed = int((time.monotonic() - started) * 1000)
    if ok:
        await activity.add("done", "Proposal ready", phase="done",
                           project_id=result.get("project_id"),
                           revision_id=result.get("revision_id"),
                           build_id=result.get("build_id"),
                           title=result.get("title"),
                           conformance=result.get("conformance"),
                           duration_ms=elapsed)
        await cad_store.update_job(pool, job_id, status="succeeded", phase="done")
    else:
        detail = str(result.get("message") or "").strip()
        await activity.add("done", f"{lane.model} couldn't build that", phase="failed",
                           error_code=result.get("error_code"), duration_ms=elapsed)
        await cad_store.update_job(
            pool, job_id, status="failed", phase="failed",
            error_code=str(result.get("error_code") or "no_build"),
            error_detail=detail[:2000],
        )
    await close(job_id)


def start_job(pool, job_id: str, description: str, *, lane, ctx,
              conversation_id: str | None = None) -> asyncio.Task:
    """Spawn the turn and hold its reference. Returns immediately.

    ``conversation_id`` is what lets the finished turn hand off to the next one
    waiting behind it. The hand-off hangs off the task's done callback rather than
    off the end of ``run_job`` because it has to happen however the turn ended —
    succeeded, crashed, or cancelled — and the cancelled path leaves ``run_job``
    through a ``raise``, which no amount of code after it would reach.
    """
    task = asyncio.create_task(
        run_job(pool, job_id, description, lane=lane, ctx=ctx),
        name=f"cad-author-{job_id}",
    )
    _job_tasks[job_id] = task

    def _finished(_task: asyncio.Task) -> None:
        _job_tasks.pop(job_id, None)
        if conversation_id:
            # A task, not an await: this is a synchronous callback, and the drain
            # touches the database.
            asyncio.create_task(drain(pool, conversation_id),
                                name=f"cad-drain-{conversation_id}")

    task.add_done_callback(_finished)
    return task


def enqueue(pool, job_id: str, description: str, *, lane, ctx,
            conversation_id: str) -> int:
    """Put a turn behind the one already running. Returns its place in line.

    Nothing here starts anything. The row already exists in the ``queued`` state, so
    the card the user is looking at names a real turn from the first byte — the same
    property UX-0 gave the running case — and the Stop button on it works before it
    has begun.
    """
    entry = {"job_id": str(job_id), "pool": pool, "description": description,
             "lane": lane, "ctx": ctx}
    waiting = _queued.setdefault(str(conversation_id), [])
    waiting.append(entry)
    _queued_in[str(job_id)] = str(conversation_id)
    return len(waiting)


def dequeue(job_id: str) -> bool:
    """Take a waiting turn out of the line. True if it was actually in one."""
    conv = _queued_in.pop(str(job_id), None)
    if not conv:
        return False
    waiting = _queued.get(conv) or []
    before = len(waiting)
    waiting[:] = [e for e in waiting if e["job_id"] != str(job_id)]
    if not waiting:
        _queued.pop(conv, None)
    return len(waiting) != before


async def drain(pool, conversation_id: str) -> str | None:
    """Start the next waiting turn in this conversation, if there is one.

    The row is re-read and re-checked rather than trusted, because between joining the
    queue and reaching the front a turn can have been cancelled — and starting a model
    on a turn the user has already stopped is the one outcome a queue must not produce.
    A row that is no longer ``queued`` is skipped and the next one considered.
    """
    while True:
        waiting = _queued.get(str(conversation_id))
        if not waiting:
            _queued.pop(str(conversation_id), None)
            return None
        entry = waiting.pop(0)
        job_id = entry["job_id"]
        _queued_in.pop(job_id, None)
        if not waiting:
            _queued.pop(str(conversation_id), None)

        moved = False
        try:
            moved = await cad_store.claim_queued_job(pool, job_id)
        except Exception:
            logger.warning("cad_jobs: could not claim queued job %s", job_id,
                           exc_info=True)
        if not moved:
            continue  # cancelled, reaped, or already claimed — try the next one

        start_job(entry["pool"], job_id, entry["description"], lane=entry["lane"],
                  ctx=entry["ctx"], conversation_id=str(conversation_id))
        return job_id


async def cancel(pool, job: dict) -> dict:
    """Stop an authoring turn, and the geometry it is waiting on.

    Order matters and is the whole substance of this function. The engine is killed
    **first**, because cancelling the coroutine drops the connection it is polling
    over and a build that is already running does not notice a dropped connection —
    kill it afterwards and there is a window where the job reads "cancelled" while
    OpenCascade is still burning a core. Only then is the task cancelled, which
    unwinds ``run_job``'s ``CancelledError`` branch and writes the row.

    Returns what was actually stopped rather than a bare ok, because "cancelled" is a
    claim: a turn whose task this process does not hold — a different worker, or a
    restart since it started — cannot be stopped from here, and saying so is the
    honest answer. The row is still marked, so the turn cannot later be mistaken for
    one that finished on its own.
    """
    job_id = str(job.get("id"))
    if job.get("status") not in ("running", "queued"):
        return {"ok": True, "status": job.get("status"), "cancelled": False,
                "engine_acknowledged": False, "reason": "already_finished"}

    # UX-G: a turn that has not started is stopped by taking it out of the line, and
    # that is a genuine cancellation — there is no engine to reach and no task to
    # interrupt, and nothing of the user's work is lost by it. Handled before the
    # engine kill because a waiting turn has no build to name and would otherwise
    # fall through to the "not running here" branch, which would be a worse answer
    # than the true one.
    if dequeue(job_id):
        await cad_store.cancel_job_if_running(pool, job_id)
        await close(job_id)
        return {"ok": True, "status": "cancelled", "cancelled": True,
                "engine_acknowledged": False, "reason": "was_queued"}

    build_id = _job_builds.get(job_id) or job.get("build_id") or ""
    reached = False
    if build_id:
        try:
            await cad_store.request_cancel(pool, build_id)
            reached = await fab_cad.cancel(build_id)
        except Exception:  # a build that cannot be reached must not block the task
            logger.warning("cad_jobs: could not cancel build %s", build_id,
                           exc_info=True)

    task = _job_tasks.get(job_id)
    if task is None or task.done():
        # Nothing to interrupt here. Mark it so the row stops claiming to be running
        # — but do not report it as cancelled, because whatever is running elsewhere
        # was not touched. A task that is `done()` counts as nothing to interrupt:
        # `cancel()` on a finished task returns False and changes nothing, so calling
        # that a cancellation would be a claim about work that already happened.
        #
        # The write is guarded rather than unconditional, because the runner drops its
        # task handle just before it writes the outcome — a cancel landing in that gap
        # would otherwise stamp "cancelled" over a turn that had succeeded.
        moved = await cad_store.cancel_job_if_running(pool, job_id)
        await close(job_id)
        if not moved:
            return {"ok": True, "status": job.get("status"), "cancelled": False,
                    "engine_acknowledged": reached, "reason": "already_finished"}
        return {"ok": True, "status": "cancelled", "cancelled": False,
                "engine_acknowledged": reached, "reason": "not_running_here"}

    task.cancel()
    return {"ok": True, "status": "cancelling", "cancelled": True,
            "engine_acknowledged": reached, "build_id": build_id or None}


__all__ = ["CadJobBroadcaster", "broadcaster", "cancel", "close", "dequeue",
           "drain", "enqueue", "run_job", "start_job", "MAX_ACTIVITY"]
