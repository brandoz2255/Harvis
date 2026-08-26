"""Subprocess supervisor — the part of Gate 1B that can actually stop a build.

Gate 1A made bad input cheap to reject. It did nothing about work that has already
started: OCP holds the GIL through native OpenCascade calls, `concurrent.futures`
cannot cancel a future that has begun, and an HTTP disconnect propagates nothing.
A `timeout=` parameter bolted onto the old in-process path would have returned a
response while the geometry kept running and kept its slot. That is a lie, and this
module exists so we do not have to tell it.

The mechanism is a process, not a thread. Each build is a child started with
``start_new_session=True``, which makes it a process-group leader whose pgid equals
its pid. Killing the *group* rather than the child is the point: OCCT does not
fork today, but an importer or an exporter that shells out tomorrow would leave an
orphan behind, and that orphan would keep burning the CPU the container is capped at.

Honest limits of this kill path:

* Between the moment the direct child is reaped and the moment we signal the group,
  a PID-reuse window exists in theory. We reap last and signal the group first,
  which keeps the window closed in practice, but it is not a proof.
* A process stopped in an uninterruptible kernel wait (``D`` state) cannot be killed
  by anything, ``SIGKILL`` included. :func:`group_members` reports it, and the caller
  learns about it rather than being told the group is clear.
"""
from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field

# For MAX_CONCURRENT only, so the CPU allotment and the slot count can never disagree.
# admission imports nothing from here, so this is not a cycle.
import admission
import pool as worker_pool

# The deadline is the innermost of three. It must stay strictly below fab_cad's
# httpx timeout (30 s), which stays below nginx's — each layer gives up after the
# layer it depends on, never before. deadline + grace = 23 s worst case.
DEADLINE_S = float(os.environ.get("CAD_BUILD_DEADLINE_S", "20"))
GRACE_S = float(os.environ.get("CAD_BUILD_GRACE_S", "3"))

_POLL_S = 0.05

_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_main.py")

_PID_DIR = re.compile(r"^\d+$")

# Thread-pool env vars, set from the size of a build's CPU allotment. Affinity alone
# already caps what a pool can *use*; these stop it from creating threads it will never
# run, which is 30 of the 47 a single 8x8 brick used to spawn.
_THREAD_VARS = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "TBB_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
)

_slice_lock = threading.Lock()
_slice_turn = 0


def cpu_quota() -> float:
    """CPUs the container may actually use, read from the cgroup rather than guessed.

    ``os.cpu_count()`` and ``sched_getaffinity`` both report the *host's* CPUs — 16 on
    this box — while ``cpus: 2.0`` in Compose is a cgroup bandwidth limit the process
    cannot see. Everything downstream that sizes a thread pool believes the larger
    number, which is the whole reason :func:`cpu_slice` exists.
    """
    for path, parse in (
        ("/sys/fs/cgroup/cpu.max", lambda t: t.split()),                       # v2
        ("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", None),                         # v1
    ):
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read().strip()
        except OSError:
            continue
        try:
            if parse is not None:
                quota, period = parse(text)
                if quota != "max":
                    return max(1.0, float(quota) / float(period))
            else:
                with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", encoding="utf-8") as fh:
                    period = float(fh.read().strip())
                if float(text) > 0 and period > 0:
                    return max(1.0, float(text) / period)
        except (ValueError, OSError):
            continue
    return float(len(os.sched_getaffinity(0)) or 1)


def cpu_slice(concurrency: int) -> list[int]:
    """The CPUs one build gets: the quota divided by the concurrency cap, rotating so
    two simultaneous builds land on *different* CPUs instead of the same one.

    Sized from the cap rather than from how many builds are running right now, because a
    build that started alone must not have to give CPUs back when the next one arrives —
    there is no mechanism to take them, and the pool it built is already sized.
    """
    global _slice_turn
    allowed = sorted(os.sched_getaffinity(0)) or [0]
    per = max(1, min(len(allowed), int(cpu_quota() // max(1, concurrency))))
    with _slice_lock:
        turn = _slice_turn
        _slice_turn += 1
    start = (turn * per) % len(allowed)
    return [allowed[(start + i) % len(allowed)] for i in range(per)]


class BuildTimeout(RuntimeError):
    """The deadline expired and the process group was terminated."""


class BuildCancelled(RuntimeError):
    """A caller cancelled the build; the process group was terminated."""


class BuildFailed(RuntimeError):
    """The child reported a structured failure, or died without reporting one."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def group_members(pgid: int, include_zombies: bool = False) -> list[int]:
    """PIDs currently in process group ``pgid``, read from ``/proc``.

    ``ps`` is not installed in this image (verified at Gate 1A: ``command -v ps``
    → missing), and this is production code rather than a test helper because the
    escalation decision below needs the answer: without it we would either always
    ``SIGKILL`` — defeating the grace period — or trust that ``SIGTERM`` worked.

    ``/proc/<pid>/stat`` must be split on the **last** ``)``. The second field is
    the executable name, unquoted, and may itself contain spaces and parentheses;
    splitting on whitespace mangles those rows silently. After the split, field 0
    is the state, 1 the ppid and 2 the pgrp.

    Zombies are excluded by default, and that distinction is load-bearing rather
    than cosmetic. Killing a child re-parents its grandchildren to PID 1, which in
    this container is uvicorn and does not reap strangers — so a killed grandchild
    lingers in ``/proc`` as state ``Z`` indefinitely. It holds no CPU, no memory and
    no file descriptors; counting it as a survivor would report a successful kill as
    a failed one. What we must never miss is a process still *running*, and that is
    exactly what this returns.
    """
    out: list[int] = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return out
    for name in entries:
        if not _PID_DIR.match(name):
            continue
        try:
            with open(f"/proc/{name}/stat", encoding="utf-8", errors="replace") as fh:
                line = fh.read()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue  # exited between listdir and open — the normal case
        except OSError:
            continue
        close = line.rfind(")")
        if close < 0:
            continue
        fields = line[close + 2:].split()
        if len(fields) < 3:
            continue
        if not include_zombies and fields[0] == "Z":
            continue
        try:
            if int(fields[2]) == pgid:
                out.append(int(name))
        except ValueError:
            continue
    return out


def _child_env(cpus: list[int] | None = None) -> dict[str, str]:
    """An allowlist, not a copy. The child needs almost nothing, and the rootfs is
    read-only: HOME points at the tmpfs that holds the ezdxf font cache, and
    PYTHONDONTWRITEBYTECODE keeps the interpreter from trying to write ``.pyc``
    files next to the source."""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if cpus:
        env["CAD_CPU_AFFINITY"] = ",".join(str(c) for c in cpus)
        for var in _THREAD_VARS:
            env[var] = str(len(cpus))
    return env


@dataclass
class BuildHandle:
    """Registry entry for a running build. Cancellable from another thread."""

    build_id: str
    proc: subprocess.Popen | None = None
    cancelled: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def cancel(self) -> bool:
        """Ask for termination. Returns False if the build already finished.

        Only sets the flag and signals; the thread that owns the wait does the
        escalation, so no two threads ever call ``wait()`` on the same Popen.
        """
        with self._lock:
            self.cancelled = True
            proc = self.proc
        if proc is None or proc.poll() is not None:
            return False
        _signal_group(proc.pid, signal.SIGTERM)
        return True


@dataclass
class BuildOutcome:
    workdir: str
    result: dict
    duration_ms: int
    stl_path: str
    step_path: str | None
    # format -> path, for every file the child actually wrote. `stl_path` and
    # `step_path` stay because the server's frozen response is built from them; this
    # is how a caller reaches the Gate 2 formats without that response changing shape.
    artifacts: dict[str, str] = field(default_factory=dict)


_registry: dict[str, BuildHandle] = {}
_registry_lock = threading.Lock()


def get_handle(build_id: str) -> BuildHandle | None:
    with _registry_lock:
        return _registry.get(build_id)


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except OSError as e:
        if e.errno not in (errno.ESRCH, errno.EPERM):
            raise


def _terminate_group(proc: subprocess.Popen, grace: float) -> list[int]:
    """SIGTERM the group, wait out the grace period, then SIGKILL what is left.

    Returns the PIDs still in the group afterwards — empty is the expected result,
    and a non-empty list means something is unkillable and the caller should say so
    rather than report a clean kill.
    """
    pgid = proc.pid  # start_new_session=True ⇒ the child leads its own group.
    _signal_group(pgid, signal.SIGTERM)

    end = time.monotonic() + grace
    while time.monotonic() < end:
        if proc.poll() is not None and not group_members(pgid):
            break
        time.sleep(_POLL_S)

    # Escalate if the child is still alive OR a grandchild outlived it. Signalling
    # the group before reaping the leader is what keeps the PID-reuse window shut.
    if proc.poll() is None or group_members(pgid):
        _signal_group(pgid, signal.SIGKILL)

    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass  # uninterruptible sleep; reported through the return value

    # SIGKILL is not synchronous: the signal is delivered, then the kernel tears the
    # process down. Give it a moment before declaring anything a survivor, or a
    # perfectly successful kill reads as a failure on a busy box.
    end = time.monotonic() + grace
    while time.monotonic() < end:
        if not [pid for pid in group_members(pgid) if pid != proc.pid]:
            break
        time.sleep(_POLL_S)

    return [pid for pid in group_members(pgid) if pid != proc.pid]


@contextlib.contextmanager
def run_build(
    recipe: str,
    params: dict,
    *,
    step: bool = True,
    formats: list[str] | tuple[str, ...] | None = None,
    deadline_s: float = DEADLINE_S,
    grace_s: float = GRACE_S,
    build_id: str | None = None,
    entrypoint: str = _WORKER,
):
    """Run one build in a killable child. Yields a :class:`BuildOutcome`.

    A context manager because the workdir's lifetime is the point: it is removed on
    the way out whether the build succeeded, failed, timed out or was cancelled.
    The caller reads the artifacts inside the ``with`` block.

    ``entrypoint`` is a seam for the kill-path tests, which point it at a script
    that deliberately forks a grandchild and refuses to die. Adding a runaway
    recipe to the production allowlist to test this would have been the other
    option, and it would have shipped a denial-of-service primitive to prove we
    can survive one.
    """
    workdir = tempfile.mkdtemp(prefix="cad_")
    handle = BuildHandle(build_id=build_id or "")
    if build_id:
        with _registry_lock:
            _registry[build_id] = handle

    leased = None
    lease_reusable = True
    started = time.monotonic()
    try:
        job = {"recipe": recipe, "params": params, "step": bool(step)}
        if formats is not None:
            job["formats"] = list(formats)
        with open(os.path.join(workdir, "job.json"), "w", encoding="utf-8") as fh:
            json.dump(job, fh)

        # A warm worker only for the production entrypoint. The kill-path tests pass
        # their own script, and a pooled process cannot run one — so `entrypoint` is
        # both the test seam and the switch back to a cold spawn.
        pool = worker_pool.get_pool() if entrypoint == _WORKER else None
        if pool is not None:
            leased = pool.checkout()

        result_path = os.path.join(workdir, "result.json")
        if leased is not None:
            proc = leased.proc
            with handle._lock:
                handle.proc = proc
            leased.submit(workdir)
        else:
            cpus = cpu_slice(admission.MAX_CONCURRENT)
            log_path = os.path.join(workdir, "worker.log")
            # Redirected to a file rather than a pipe. A pipe nobody drains blocks the
            # child at 64 KB, and the parent cannot drain it while it is also enforcing
            # the deadline. Unbounded in principle; bounded in practice by the 512 MB
            # /tmp tmpfs, and caught afterwards by the caller's workdir-size check.
            with open(log_path, "wb") as log:
                proc = subprocess.Popen(
                    [sys.executable, entrypoint, workdir],
                    cwd=os.path.dirname(entrypoint) or "/app",
                    env=_child_env(cpus),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,   # its own process group — the whole point
                    close_fds=True,
                )
            with handle._lock:
                handle.proc = proc

        deadline_at = started + deadline_s
        timed_out = False
        cancelled = False
        while True:
            if leased is not None:
                # A warm worker does not exit when the build ends, so "the process
                # finished" is not the signal any more. The result file is, and it is
                # written through os.replace — so it appears whole or not at all.
                if os.path.exists(result_path):
                    break
                if proc.poll() is not None:
                    break       # the worker died mid-build; handled below as usual
                time.sleep(_POLL_S)
            else:
                try:
                    proc.wait(timeout=_POLL_S)
                    break
                except subprocess.TimeoutExpired:
                    pass
            if handle.cancelled:
                cancelled = True
                break
            if time.monotonic() >= deadline_at:
                timed_out = True
                break

        # Re-read the flag after the loop. A cancel that lands while the child is
        # exiting wins the race against `proc.wait()` returning, and without this
        # the build would be reported as a failure — "killed by signal 15" — for
        # doing exactly what the caller asked. Cancelled is not failed.
        if handle.cancelled:
            cancelled = True

        if cancelled or timed_out:
            # A killed worker never goes back on the free list: a process SIGKILLed
            # part-way through a boolean operation is not something to hand the next
            # caller. The pool replaces it, so the cap is restored, not shrunk.
            lease_reusable = False
            survivors = _terminate_group(proc, grace_s)
            if survivors:
                raise BuildFailed(
                    "engine_unkillable",
                    "the geometry process did not respond to termination",
                )
            if cancelled:
                raise BuildCancelled("build cancelled")
            # :g, not :.0f — a sub-second deadline formatted as "0s" reads like a
            # bug in the message rather than the setting it actually describes.
            raise BuildTimeout(f"build exceeded its {deadline_s:g}s deadline")

        duration_ms = int((time.monotonic() - started) * 1000)

        # A child that died on a signal, or died before writing its result, leaves
        # no file. That is reported as an engine failure, never as a success with
        # missing fields.
        result_path = os.path.join(workdir, "result.json")
        if not os.path.exists(result_path):
            if proc.returncode is not None and proc.returncode < 0:
                raise BuildFailed(
                    "geometry_failed",
                    f"the geometry process was killed by signal {-proc.returncode}",
                )
            raise BuildFailed("geometry_failed", "the geometry process produced no result")

        with open(result_path, encoding="utf-8") as fh:
            result = json.load(fh)

        if not result.get("ok"):
            raise BuildFailed(
                str(result.get("error_code") or "geometry_failed"),
                str(result.get("message") or "the geometry engine failed"),
            )

        # Trust the child's own list of what it wrote, then confirm each file is there.
        # A format it reported but did not leave behind is dropped rather than handed
        # to the caller as a path that opens to nothing.
        written = result.get("formats") or (["stl", "step"] if step else ["stl"])
        artifacts = {}
        for fmt in written:
            path = os.path.join(workdir, f"part.{fmt}")
            if os.path.exists(path):
                artifacts[fmt] = path

        stl_path = os.path.join(workdir, "part.stl")
        yield BuildOutcome(
            workdir=workdir,
            result=result,
            duration_ms=duration_ms,
            stl_path=stl_path,
            step_path=artifacts.get("step") if step else None,
            artifacts=artifacts,
        )
    except BaseException:
        # Any exit that is not a clean build — including a failure the child reported
        # structurally — leaves the worker's state unproven. Cheaper to replace it
        # than to reason about what a half-finished boolean left behind.
        lease_reusable = False
        raise
    finally:
        if build_id:
            with _registry_lock:
                _registry.pop(build_id, None)
        if leased is not None:
            # Released before the workdir is removed but after the caller has read
            # the artifacts: the worker is idle from the moment it wrote result.json,
            # and holding the lease through the caller's body is what keeps two
            # builds from ever sharing one interpreter.
            live_pool = worker_pool.get_pool()
            if live_pool is not None:
                live_pool.release(leased, reusable=lease_reusable)
            else:
                worker_pool.retire(leased)   # pool shut down while we held the lease
        else:
            proc = handle.proc
            if proc is not None and proc.poll() is None:
                # Reached only if the caller's own body raised while the child ran.
                _terminate_group(proc, grace_s)
        shutil.rmtree(workdir, ignore_errors=True)
