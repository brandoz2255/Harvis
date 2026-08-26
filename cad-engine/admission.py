"""Bounded admission control for concurrent builds (Gate 1B).

The plan calls this module ``queue.py``. It is not named that, deliberately:
``/app`` is first on ``sys.path`` inside the container, so a top-level ``queue.py``
would shadow the standard library's ``queue`` for every importer in the process —
``multiprocessing``, ``concurrent.futures``, ``urllib3``. The failure would arrive
as an unrelated ImportError deep in a dependency, at import time, in production.

The semantics the plan asked for are unchanged: a hard cap, and requests over it get
"a fast, honest 429, never a silent wait". So the acquire is **non-blocking**. A
queue that made callers wait would push the latency somewhere the caller cannot see
and cannot cancel, which is the same dishonesty Gate 1B exists to remove — one layer
up.

``threading`` rather than ``asyncio`` because ``server.execute`` is a synchronous
``def``; FastAPI runs it on its threadpool, so these are real OS threads.
"""
from __future__ import annotations

import contextlib
import os
import threading

# Two, not more: Gate 1A measured a build's peak RSS at ~460 MiB, so two concurrent
# builds sit near 920 MiB under the container's 2 GiB ceiling with room for the
# parent — and the container is capped at 2.0 CPUs, so a third would only make all
# three slower. Gate 2's brick benchmark is what should revisit this number.
MAX_CONCURRENT = max(1, int(os.environ.get("CAD_MAX_CONCURRENT_BUILDS", "2")))

_sem = threading.BoundedSemaphore(MAX_CONCURRENT)
_active = 0
_active_lock = threading.Lock()


class QueueFull(RuntimeError):
    """Every build slot is occupied."""


def active() -> int:
    with _active_lock:
        return _active


@contextlib.contextmanager
def slot():
    """Hold a build slot, or raise :class:`QueueFull` immediately."""
    if not _sem.acquire(blocking=False):
        raise QueueFull(f"all {MAX_CONCURRENT} build slots are busy")
    global _active
    with _active_lock:
        _active += 1
    try:
        yield
    finally:
        with _active_lock:
            _active -= 1
        _sem.release()
