"""What keeps the harvis-doc pipeline from being used up: bounded build threads and a per-user rate limit.

A build or a render cannot be cancelled once its thread has started, so the threads are the scarce thing.
Every caller (the REST routes, the MCP route, the Claude and Kimi sidecars, the workspace loop) goes through
the same two gates, so a model calling ``docs_export`` in a loop cannot pile up abandoned threads in the
default executor that the rest of the backend shares.

    BUILDS    export_doc and check_source, MAX_BUILDS at once
    RENDERS   the blocking HTTP call to the document sandbox, MAX_RENDERS at once

A gate's slot is held until its thread really ends, even after the caller gave up waiting, and a caller that
finds every slot taken is refused (:class:`Busy`) rather than queued behind them. :func:`hit` is the
per-user sliding-window limit on export, preview and check, shared by all callers.
"""
from __future__ import annotations

import asyncio
import math
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

MAX_BUILDS = 4
MAX_RENDERS = 4
BUSY_MESSAGE = "Too many documents are being built right now. Try again in a moment."

# kind: (calls, per seconds). DOCS_RATE_<KIND>_PER_MIN overrides the count.
RATE_LIMITS = {"export": (20, 60.0), "preview": (30, 60.0), "check": (30, 60.0)}
MAX_TRACKED = 5000                  # (kind, user) windows kept before the idle ones are swept


class Busy(Exception):
    """Every slot of a gate is taken."""


class RateLimited(Exception):
    """The caller used up a kind's allowance; ``message`` is written for the person or model that sent it."""

    def __init__(self, kind: str, retry_after: int):
        self.kind, self.retry_after = kind, retry_after
        self.message = f"Too many {kind} requests. Wait {retry_after} seconds, then try again."
        super().__init__(self.message)


def _quiet(fut: "asyncio.Future[Any]") -> None:
    fut.cancelled() or fut.exception()              # an abandoned job must not log "never retrieved"


class Gate:
    """``limit`` jobs at a time, each on its own thread, counted until the thread ends."""

    def __init__(self, name: str, limit: int):
        self.name, self.limit, self.held = name, limit, 0
        self._pool = ThreadPoolExecutor(max_workers=limit, thread_name_prefix=name)
        self._lock = threading.Lock()

    def _take(self) -> bool:
        with self._lock:
            if self.held >= self.limit:
                return False
            self.held += 1
            return True

    def _give(self) -> None:
        with self._lock:
            self.held -= 1

    def _slot_run(self, fn: Callable, args: tuple):
        try:
            return fn(*args)
        finally:                                    # on the job's thread, so it happens even if the caller is gone
            self._give()

    async def run(self, fn: Callable, *args: Any, timeout: Optional[float] = None):
        """``fn(*args)`` on a gate thread. Raises Busy when the gate is full, asyncio.TimeoutError after
        ``timeout`` (the thread, and its slot, carry on until ``fn`` returns)."""
        if not self._take():
            raise Busy(self.name)
        try:
            fut = asyncio.get_running_loop().run_in_executor(self._pool, self._slot_run, fn, args)
        except BaseException:
            self._give()
            raise
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            fut.add_done_callback(_quiet)
            raise


BUILDS = Gate("docs-build", MAX_BUILDS)
RENDERS = Gate("docs-render", MAX_RENDERS)


# ---- per-user rate limit ----------------------------------------------------------------------

_now: Callable[[], float] = time.monotonic          # tests move the clock
_hits: dict[tuple[str, str], deque] = {}
_hits_lock = threading.Lock()


def _allowance(kind: str) -> tuple[int, float]:
    count, window = RATE_LIMITS[kind]
    raw = os.environ.get(f"DOCS_RATE_{kind.upper()}_PER_MIN", "")
    return (int(raw), 60.0) if raw.strip().isdigit() and int(raw) > 0 else (count, window)


def hit(kind: str, user: Any) -> None:
    """Count one ``kind`` call by ``user``. Raises RateLimited when that is over the allowance in the window.

    A refused call is not counted, so waiting out ``retry_after`` always lets the next one through."""
    count, window = _allowance(kind)
    now = _now()
    with _hits_lock:
        if len(_hits) > MAX_TRACKED:
            for key in [k for k, q in _hits.items() if not q or now - q[-1] >= window]:
                del _hits[key]
        q = _hits.setdefault((kind, str(user)), deque())
        while q and now - q[0] >= window:
            q.popleft()
        if len(q) >= count:
            raise RateLimited(kind, max(1, math.ceil(window - (now - q[0]))))
        q.append(now)


def refund(kind: str, user: Any) -> None:
    """Take back ``user``'s newest ``kind`` hit: the call it counted was refused as Busy and never ran."""
    with _hits_lock:
        q = _hits.get((kind, str(user)))
        if q:
            q.pop()


def reset() -> None:
    """Forget every window. For tests: the table is process-wide, so suites that share a fake user share an allowance."""
    with _hits_lock:
        _hits.clear()
