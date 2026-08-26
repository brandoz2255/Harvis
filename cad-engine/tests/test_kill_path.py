"""Gate 1B — proof that a started build can be stopped.

Every assertion here exists because Gate 1A could not make it. The Gate 0 baseline
measured a single malformed request holding the GIL for 45.91 s while ``/health``
blocked for 43.269 s; the fix is a separate process, and a separate process is only
worth anything if it actually dies. So these tests do not check that a timeout was
*reported* — they check that nothing is left running afterwards.

Two deliberate choices:

* The child entrypoint is a parameter (``runner.run_build(entrypoint=...)``) and the
  tests point it at their own scripts. The alternative was adding a runaway recipe to
  the production allowlist, which would ship a denial-of-service primitive in order
  to prove we can survive one.
* Survivor checks read ``/proc`` rather than shelling out. ``ps`` is not installed in
  this image — verified at Gate 1A — and ``runner.group_members`` needs the parser in
  production anyway, to decide whether SIGTERM was enough.

Run: ``docker exec harvis-cad python -m pytest tests/test_kill_path.py -q -p no:cacheprovider``
(the ``-p`` is not optional: the rootfs is read-only and pytest's cache would try to
write beside the source).
"""
from __future__ import annotations

import glob
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

import admission
import runner
import server

# Short enough to keep the suite quick, long enough to clear process spawn (~40 ms).
FAST_DEADLINE = 0.6
FAST_GRACE = 0.4


# --- fixtures ---------------------------------------------------------------

STUBBORN = """
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if os.fork() == 0:                       # grandchild, equally stubborn
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(0.05)
while True:
    time.sleep(0.05)
"""

SLEEPER = """
import sys, time
while True:
    time.sleep(0.05)
"""


@pytest.fixture(scope="module")
def scripts(tmp_path_factory):
    d = tmp_path_factory.mktemp("kill_fixtures")
    out = {}
    for name, body in (("stubborn.py", STUBBORN), ("sleeper.py", SLEEPER)):
        p = d / name
        p.write_text(body)
        out[name.split(".")[0]] = str(p)
    return out


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


# --- helpers ----------------------------------------------------------------

def _scratch_dirs() -> set[str]:
    return set(glob.glob("/tmp/cad_*"))


def _own_children() -> list[int]:
    """Direct children of this process, from /proc. Used to prove nothing is left
    behind — a leaked build shows up here as a zombie or a live process."""
    me = os.getpid()
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8", errors="replace") as fh:
                line = fh.read()
        except OSError:
            continue
        close = line.rfind(")")
        if close < 0:
            continue
        fields = line[close + 2:].split()
        if len(fields) >= 2 and int(fields[1]) == me:
            out.append(int(entry))
    return out


def _rss_bytes() -> int:
    with open("/proc/self/statm", encoding="utf-8") as fh:
        return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def _run_in_thread(**kwargs) -> tuple[threading.Thread, dict]:
    """Start a build on a background thread, returning the thread and a box that
    receives the exception it raised (or ``None``)."""
    box: dict = {}

    def go():
        try:
            with runner.run_build(**kwargs):
                box["exc"] = None
        except BaseException as e:  # noqa: BLE001 — the test inspects the type
            box["exc"] = e

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t, box


def _wait_for_pid(build_id: str, timeout: float = 5.0) -> int:
    """The child's pid, which is also its pgid (start_new_session=True)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        handle = runner.get_handle(build_id)
        if handle is not None and handle.proc is not None:
            return handle.proc.pid
        time.sleep(0.01)
    raise AssertionError("the build never registered a process")


# --- 1. the deadline kills the whole group ----------------------------------

def test_deadline_kills_the_process_group(scripts):
    """The headline assertion. A child that ignores SIGTERM and forks a grandchild
    must be gone — both of them — once the deadline has passed."""
    before = _scratch_dirs()
    t, box = _run_in_thread(
        recipe="helmet_hanger_v1", params={}, deadline_s=FAST_DEADLINE,
        grace_s=FAST_GRACE, build_id="t-deadline", entrypoint=scripts["stubborn"],
    )
    pgid = _wait_for_pid("t-deadline")
    # The grandchild needs a moment to exist, or the test proves nothing.
    end = time.monotonic() + 3.0
    while time.monotonic() < end and len(runner.group_members(pgid)) < 2:
        time.sleep(0.02)
    assert len(runner.group_members(pgid)) >= 2, "fixture never forked a grandchild"

    t.join(timeout=15)
    assert not t.is_alive()
    assert isinstance(box["exc"], runner.BuildTimeout)
    assert runner.group_members(pgid) == [], "a process survived the kill"
    assert _scratch_dirs() == before, "the workdir outlived the build"


# --- 2. cancel is not a failure ---------------------------------------------

def test_cancel_returns_cancelled_and_kills(scripts):
    before = _scratch_dirs()
    t, box = _run_in_thread(
        recipe="helmet_hanger_v1", params={}, deadline_s=30.0,
        grace_s=FAST_GRACE, build_id="t-cancel", entrypoint=scripts["sleeper"],
    )
    pgid = _wait_for_pid("t-cancel")
    started = time.monotonic()
    assert runner.get_handle("t-cancel").cancel() is True

    t.join(timeout=10)
    elapsed = time.monotonic() - started
    assert not t.is_alive()
    # BuildCancelled, not BuildTimeout and not BuildFailed: the caller asked for it,
    # and the 30 s deadline proves the deadline is not what stopped it.
    assert isinstance(box["exc"], runner.BuildCancelled)
    assert elapsed < FAST_GRACE + 2.0, f"cancel took {elapsed:.2f}s"
    assert runner.group_members(pgid) == []
    assert _scratch_dirs() == before


def test_cancel_of_an_unknown_build_is_404(client):
    r = client.post("/cad/cancel/not-a-real-build")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "unknown_build"


# --- 3. the workdir is the parent's responsibility ---------------------------

def test_workdir_removed_after_a_successful_build(client):
    before = _scratch_dirs()
    r = client.post("/cad/execute", json={"recipe": "helmet_hanger_v1", "params": {}})
    assert r.status_code == 200, r.text
    assert _scratch_dirs() == before


def test_successful_build_reports_child_measurements(client):
    """The child is the only process that can see its own peak RSS, and it is the
    number `cad_builds.peak_rss_bytes` will store in Gate 3."""
    r = client.post("/cad/execute", json={"recipe": "helmet_hanger_v1", "params": {}})
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    assert v["peak_rss_bytes"] > 50 * 1024 * 1024   # OCP alone is bigger than this
    assert v["duration_ms"] >= 0
    assert v["brep_valid"] is True


# --- 4. admission control answers honestly -----------------------------------

def test_slots_are_bounded():
    held = []
    try:
        for _ in range(admission.MAX_CONCURRENT):
            cm = admission.slot()
            cm.__enter__()
            held.append(cm)
        assert admission.active() == admission.MAX_CONCURRENT
        with pytest.raises(admission.QueueFull):
            with admission.slot():
                pass
    finally:
        for cm in held:
            cm.__exit__(None, None, None)
    assert admission.active() == 0


def test_saturated_engine_returns_429_and_stays_healthy(client):
    """N+1 gets a fast, honest 429 — never a silent wait — and /health keeps
    answering, which is the property Gate 0 measured at 43.269 s."""
    held = []
    try:
        for _ in range(admission.MAX_CONCURRENT):
            cm = admission.slot()
            cm.__enter__()
            held.append(cm)

        started = time.monotonic()
        r = client.post("/cad/execute", json={"recipe": "helmet_hanger_v1", "params": {}})
        elapsed = time.monotonic() - started
        assert r.status_code == 429
        assert r.json()["detail"]["error_code"] == "queue_full"
        assert elapsed < 1.0, f"the 429 took {elapsed:.2f}s — that is a queue, not a refusal"

        h = client.get("/health")
        assert h.status_code == 200
        assert h.json()["active_builds"] == admission.MAX_CONCURRENT
    finally:
        for cm in held:
            cm.__exit__(None, None, None)


def test_health_stays_responsive_while_a_build_runs(scripts):
    """The point of the subprocess: geometry no longer holds this process's GIL."""
    with TestClient(server.app) as client:
        t, _box = _run_in_thread(
            recipe="helmet_hanger_v1", params={}, deadline_s=1.5,
            grace_s=FAST_GRACE, build_id="t-health", entrypoint=scripts["sleeper"],
        )
        _wait_for_pid("t-health")
        worst = 0.0
        for _ in range(20):
            t0 = time.monotonic()
            assert client.get("/health").status_code == 200
            worst = max(worst, time.monotonic() - t0)
            time.sleep(0.02)
        t.join(timeout=15)
    assert worst < 1.0, f"/health worst case {worst:.3f}s while a build ran"


# --- 5. the Gate 0 payload, one gate later -----------------------------------

def test_nan_is_rejected_and_leaves_nothing_running(client):
    """The exact request that froze the worker for 45.91 s. It is rejected by the
    schema now, so the interesting assertion is the second one: no process was ever
    spawned, so there is nothing left to kill."""
    before_children = set(_own_children())
    before_dirs = _scratch_dirs()
    # Hand-built body: a strict JSON client cannot emit NaN — httpx raises locally.
    r = client.post(
        "/cad/execute",
        content=b'{"recipe":"helmet_hanger_v1","params":{"arm_len_mm":NaN}}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "invalid_request"
    assert set(_own_children()) == before_children
    assert _scratch_dirs() == before_dirs


# --- 6. repetition leaks nothing ---------------------------------------------

def test_a_hundred_kills_leak_nothing(scripts):
    """Processes, file descriptors and memory, over 100 killed builds.

    The RSS bound is deliberately loose: the allocator does not return every page,
    and a tight assertion here would fail for reasons that have nothing to do with a
    leak. What it catches is the shape of a leak — linear growth per build.
    """
    before_dirs = _scratch_dirs()
    before_fds = len(os.listdir("/proc/self/fd"))
    # One warm-up so the first iteration's lazy imports are not counted as growth.
    for _ in range(3):
        with pytest.raises(runner.BuildTimeout):
            with runner.run_build(recipe="helmet_hanger_v1", params={},
                                  deadline_s=0.15, grace_s=0.3,
                                  entrypoint=scripts["sleeper"]):
                pass
    before_rss = _rss_bytes()

    for _ in range(100):
        with pytest.raises(runner.BuildTimeout):
            with runner.run_build(recipe="helmet_hanger_v1", params={},
                                  deadline_s=0.15, grace_s=0.3,
                                  entrypoint=scripts["sleeper"]):
                pass

    leftovers = _own_children()
    assert leftovers == [], f"{len(leftovers)} processes survived 100 builds"
    assert len(os.listdir("/proc/self/fd")) <= before_fds + 2
    assert _scratch_dirs() == before_dirs
    growth = _rss_bytes() - before_rss
    assert growth < 32 * 1024 * 1024, f"RSS grew {growth / 1e6:.1f} MB over 100 builds"


# --- the /proc parser itself --------------------------------------------------

def test_group_members_sees_this_process():
    assert os.getpid() in runner.group_members(os.getpgid(0))


def test_group_members_of_a_dead_group_is_empty():
    # A pgid that cannot exist: PIDs are bounded by /proc/sys/kernel/pid_max.
    with open("/proc/sys/kernel/pid_max", encoding="utf-8") as fh:
        pid_max = int(fh.read().strip())
    assert runner.group_members(pid_max + 1000) == []
