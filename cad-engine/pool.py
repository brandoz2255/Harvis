"""Warm worker pool — the part of Gate 2 that stops paying for OCP twice.

Measured in this image: ``import recipes`` (which pulls build123d and OCP) costs
1.42 s, while the hanger's geometry costs 0.048 s. Every build today pays that
import, so a small part is ~97% startup. This module keeps a small set of workers
that have already paid it and are waiting for a job.

**Why processes and not a fork zygote.** The obvious design is to import OCP once and
``fork`` per build. Three trial forks were measured and each hung for a full 60 s
having produced nothing. A fork carries only the calling thread, so any mutex another
thread held at fork time stays locked forever in the child — and OCCT reaches a
multi-threaded state on its **first build**, not on import (measured: 1 thread through
every import, 16 after the first build; the pool is sized at first use, which is also
why :func:`worker_main._cap_occt_thread_pool` has to run before one). A zygote would
therefore have to fork before it had ever built, which buys the import back but leaves
every child paying first-build costs — and the workers here are long-lived, so the
import is paid twice in the life of the container rather than once per build. The
saving a zygote exists for is already gone.

**Why reuse is safe.** A worker builds many times, so its results must not drift and
its memory must not climb. Both were measured before this was written: 12 alternating
builds across both recipes returned identical volumes *and* identical mesh signatures
on every repeat, and 20 consecutive builds moved current RSS by +3.4 MiB total with
the per-build increment decaying (1.1 → 0.5 → 0.6 → 0.1 MiB). That is a bounded
internal cache, not a leak — but it is not zero either, which is what
:data:`MAX_BUILDS_PER_WORKER` is for.

**What this does not change.** A warm worker is still started with
``start_new_session=True``, so it is still a process-group leader and the Gate 1B
kill path terminates it exactly as before. The difference is only what happens
afterwards: a killed worker is discarded and replaced instead of simply reaped. The
pool never makes a build less killable, and every warm build still reports its result
through ``result.json`` — the same file the one-shot path uses, for the same reason
the runner docstring gives for preferring files to pipes.
"""
from __future__ import annotations

import errno
import itertools
import os
import queue
import signal
import subprocess
import sys
import threading
import time

ENABLED = (os.environ.get("CAD_WARM_POOL", "1").strip().lower()
           not in ("0", "false", "no", "off"))

# Bounds the measured +0.17 MiB/build drift. At 50 that is ~8 MiB before a worker is
# replaced, against a 2 GiB container — small enough to ignore, finite enough that a
# long-lived engine cannot accumulate its way into the ceiling.
MAX_BUILDS_PER_WORKER = int(os.environ.get("CAD_WORKER_MAX_BUILDS", "50"))

# How long a caller waits for a free worker before giving up and spawning a cold one.
# Short on purpose: admission control has already capped concurrency at the pool size,
# so a wait here means a worker is being replaced, and a cold build is a better answer
# than a stall. The fallback is today's behaviour, so the worst case is no worse.
CHECKOUT_TIMEOUT_S = float(os.environ.get("CAD_POOL_CHECKOUT_S", "0.5"))

_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_main.py")


class WarmWorker:
    """One long-lived geometry process, leased to exactly one build at a time."""

    __slots__ = ("proc", "cpus", "index", "builds_done", "log_path", "dead")

    def __init__(self, proc: subprocess.Popen, cpus: list[int], index: int, log_path: str):
        self.proc = proc
        self.cpus = cpus
        self.index = index
        self.log_path = log_path
        self.builds_done = 0
        self.dead = False

    def alive(self) -> bool:
        return not self.dead and self.proc.poll() is None

    def submit(self, workdir: str) -> None:
        """Hand the worker a job. Writing to a pipe the child is reading cannot
        deadlock the way reading an undrained one can, which is why the request goes
        this way and the answer comes back through the filesystem."""
        assert self.proc.stdin is not None
        self.proc.stdin.write(f"{workdir}\n")
        self.proc.stdin.flush()


_spawn_seq = itertools.count()


class Pool:
    def __init__(self, size: int, cpu_slices: list[list[int]]):
        self.size = size
        self._cpu_slices = cpu_slices
        self._free: queue.Queue[WarmWorker] = queue.Queue()
        self._lock = threading.Lock()
        self._started = False

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        for i in range(self.size):
            worker = self._spawn(i)
            if worker is not None:
                self._free.put(worker)

    def _spawn(self, index: int) -> WarmWorker | None:
        cpus = self._cpu_slices[index % len(self._cpu_slices)]
        env = _worker_env(cpus)
        # A file, not a pipe. The worker's own tracebacks and anything OCCT decides
        # to print go here; a pipe nobody drains would block the worker at 64 KB, and
        # the only thing draining it would have to be another thread doing nothing else.
        #
        # Named by owning process and spawn, not by slot. Slot-named logs are opened
        # "wb", so replacing a worker truncated the log of the one it replaced —
        # destroying the traceback of the very worker whose death caused the
        # replacement.
        #
        # The pid is there because the spawn counter only makes names unique *within*
        # an interpreter. The test suite runs inside this same container by design, and
        # its own pool restarted the counter at zero, reopened the live server's
        # `..._0_0.log` and `..._1_1.log`, and — once retirement started deleting spent
        # logs — unlinked them out from under two running workers, which then had
        # nowhere to write a traceback. Measured: a full suite run left the server's two
        # logs gone.
        log_path = f"/tmp/cad_pool_worker_{os.getpid()}_{index}_{next(_spawn_seq)}.log"
        try:
            log = open(log_path, "wb")
        except OSError:
            return None
        try:
            proc = subprocess.Popen(
                [sys.executable, _WORKER, "--serve"],
                cwd=os.path.dirname(_WORKER) or "/app",
                env=env,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,   # its own group, so Gate 1B can still kill it
                close_fds=True,
                text=True,
            )
        except OSError:
            log.close()
            return None
        finally:
            # Popen dup'd the descriptor; this process does not need its copy.
            with _suppress_os_error():
                log.close()
        return WarmWorker(proc, cpus, index, log_path)

    def shutdown(self) -> None:
        while True:
            try:
                worker = self._free.get_nowait()
            except queue.Empty:
                return
            self.retire(worker)

    # --- leasing -------------------------------------------------------------

    def checkout(self, timeout: float = CHECKOUT_TIMEOUT_S) -> WarmWorker | None:
        """Lease a live worker, or None if the caller should spawn a cold one.

        Exclusive by construction: a worker is on the free queue or leased, never
        both. Two builds sharing one interpreter would share OCCT's global state, and
        nothing downstream would notice until the geometry was wrong.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            try:
                worker = self._free.get(timeout=max(0.0, remaining)) if remaining > 0 \
                    else self._free.get_nowait()
            except queue.Empty:
                return None
            if worker.alive():
                return worker
            # Died while idle. Replace it now so the pool does not silently shrink to
            # nothing over a long uptime, then keep looking for a live one.
            self.retire(worker)
            self._replace(worker.index)

    def release(self, worker: WarmWorker, *, reusable: bool) -> None:
        """Return a worker, or retire and replace it.

        ``reusable`` is False whenever the build did not end normally — a deadline
        kill, a cancel, or a worker that exited. A process that was just SIGKILLed
        mid-``BRepAlgoAPI`` is not something to hand the next caller.
        """
        worker.builds_done += 1
        if (not reusable or not worker.alive()
                or worker.builds_done >= MAX_BUILDS_PER_WORKER):
            self.retire(worker)
            self._replace(worker.index)
            return
        self._free.put(worker)

    def _replace(self, index: int) -> None:
        fresh = self._spawn(index)
        if fresh is not None:
            self._free.put(fresh)

    def retire(self, worker: WarmWorker) -> None:
        retire(worker)

    def stats(self) -> dict:
        return {"size": self.size, "free": self._free.qsize(),
                "max_builds_per_worker": MAX_BUILDS_PER_WORKER}


def retire(worker: WarmWorker) -> None:
    """Stop a worker that is not currently running a build.

    Deliberately simpler than the runner's ``_terminate_group``: that one runs while a
    build is in flight and has to report survivors, because a grandchild outliving the
    kill is a Gate 1B failure. Here the build is already over, so this only has to be
    certain the process is gone.

    Module-level so a caller holding a lease can always dispose of it, including after
    the pool itself has been shut down underneath them.
    """
    worker.dead = True
    proc = worker.proc
    try:
        with _suppress_os_error():
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.close()
        if proc.poll() is not None:
            return
        _killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=2.0)
            return
        except subprocess.TimeoutExpired:
            pass
        _killpg(proc.pid, signal.SIGKILL)
        with _suppress_os_error():
            proc.wait(timeout=2.0)
    finally:
        _discard_empty_log(worker)


# "ready\n" — everything a healthy worker ever writes to its own log.
_READY_MARKER_BYTES = 6


def _discard_empty_log(worker: WarmWorker) -> None:
    """Drop a retired worker's log when it holds nothing worth reading.

    Per-spawn log names exist because slot-named ones truncated the log of the worker
    they replaced, destroying the traceback that explained the replacement. But nothing
    then removed them, and workers are replaced routinely — every
    ``MAX_BUILDS_PER_WORKER`` and after every killed build. One test run left **51**
    files behind. Each is tiny, but /tmp is a 512 MB tmpfs and unbounded is unbounded.

    Size, not content, decides: a healthy worker writes exactly ``ready``, so anything
    longer is a traceback and is kept. Called only after the process is confirmed gone,
    so nothing is still writing to it.
    """
    try:
        if os.path.getsize(worker.log_path) <= _READY_MARKER_BYTES:
            os.unlink(worker.log_path)
    except OSError:
        # Already gone, or a tmpfs that filled. Never worth failing a retirement over.
        pass


class _suppress_os_error:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(
            exc_type, (OSError, subprocess.TimeoutExpired, ValueError))


def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except OSError as e:
        if e.errno not in (errno.ESRCH, errno.EPERM):
            raise


def _worker_env(cpus: list[int]) -> dict[str, str]:
    """The same allowlist the one-shot child gets, with the affinity pinned for the
    worker's whole life rather than per build.

    For life, because OCCT sizes its thread pool at first use and never resizes it.
    Re-pinning a worker between builds would leave a pool built for the old mask —
    which is exactly the oversubscription this pinning exists to prevent.
    """
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["CAD_CPU_AFFINITY"] = ",".join(str(c) for c in cpus)
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "TBB_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[var] = str(len(cpus))
    return env


_pool: Pool | None = None
_pool_lock = threading.Lock()


def get_pool() -> Pool | None:
    """The process-wide pool, or None when warm workers are switched off."""
    return _pool


def init(size: int, cpu_slices: list[list[int]]) -> Pool | None:
    global _pool
    if not ENABLED:
        return None
    with _pool_lock:
        if _pool is None:
            _pool = Pool(size, cpu_slices)
            _pool.start()
        return _pool


def shutdown() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown()
            _pool = None
