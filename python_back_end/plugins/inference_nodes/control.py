"""Turning a local node on and off from inside the container.

The backend runs in Docker and the node runs as a ``systemd --user`` service on the
host, so the container cannot start it: there is no bus, no PID namespace, no way in.
Every other option (an SSH loop back to the host, a privileged socket, docker.sock
gymnastics) hands the container more authority than "please start the GPU service"
deserves.

So the channel is a **file**. The container writes what it wants into ``desired.json``;
a tiny host-side agent (``scripts/freetoken/control-agent.sh``, triggered by a systemd
``.path`` unit) reads it, runs ``systemctl --user start|stop freetoken``, and writes
back what actually happened in ``status.json``. The container never learns anything it
could not already do, and the host decides what a request means.

Both files live in a directory that is bind-mounted into the container — ``/tmp`` on
this box, already mounted, so no compose change was needed. The two sides run as
different uids (1001 in the container, 1000 on the host), which is why each writes its
own file and only ever reads the other's; neither can clobber the other's half.

If the agent is not installed the writes go nowhere, and ``power_state`` says
``controllable: false`` rather than pretending a toggle exists.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

CONTROL_DIR = os.getenv("HARVIS_FREETOKEN_CONTROL_DIR", "/tmp/harvis-freetoken")
DESIRED = "desired.json"
STATUS = "status.json"

# How long the agent may take to notice a request and report back before the backend
# calls the channel dead. The path unit fires within a second; a model load is the slow
# part and is reported through `status.json`, not by silence.
AGENT_STALE_S = float(os.getenv("HARVIS_FREETOKEN_AGENT_STALE_S", "20"))

# How long to wait for a node to come up after asking for it. FreeToken loads the
# checkpoint in 30–90 s from cold, longer if the box is swapping.
WAKE_TIMEOUT_S = float(os.getenv("HARVIS_FREETOKEN_WAKE_TIMEOUT_S", "120"))

# Wake a sleeping node when a chat asks for a model it serves, instead of answering 503.
AUTO_WAKE = (os.getenv("HARVIS_FREETOKEN_AUTO_WAKE", "1").strip().lower()
             not in ("0", "false", "no", "off"))

# The one node this channel controls. There is a single ``freetoken.service`` behind it,
# so a second machine's node is not switchable from here — it needs its own agent and
# its own shared directory, which is a compose change on that box, not a code change.
LOCAL_NODE = os.getenv("HARVIS_FREETOKEN_NODE", "freetoken").strip()


def _path(name: str) -> str:
    return os.path.join(CONTROL_DIR, name)


def _read(name: str) -> dict[str, Any] | None:
    try:
        with open(_path(name), "r", encoding="utf-8") as fh:
            out = json.load(fh)
        return out if isinstance(out, dict) else None
    except (OSError, ValueError):
        return None


def agent_status() -> dict[str, Any] | None:
    """What the host agent last reported, or ``None`` if it has never reported."""
    return _read(STATUS)


def desired() -> dict[str, Any] | None:
    """What was last asked for, or ``None`` if nothing has been."""
    return _read(DESIRED)


def installed() -> bool:
    """Whether a host agent has ever answered on this channel.

    A missing ``status.json`` means the agent is not installed (or the control dir is
    not shared with the container). Both are the operator's problem to fix, and both
    should read as "no toggle here", never as "the node is off".
    """
    return agent_status() is not None


def serving(health: dict | None) -> bool:
    """Whether a node is ready to take a chat, not merely answering its socket.

    FreeToken opens its HTTP port and answers ``/v1/models`` **while the checkpoint is
    still loading** — 30–90 s during which the probe calls it reachable and a routed
    chat would sit there. Its ``/health`` is the honest signal: ``{"status":"loading"}``
    with no ``maintenance`` key on the way up, ``{"status":"ok","maintenance":"serving"}``
    once it can answer. A node with no ``/health`` at all (vLLM, llama-server) is taken
    at its word, because for those the open port really is the whole story.
    """
    if not isinstance(health, dict) or not health:
        return True
    maintenance = str(health.get("maintenance") or "").strip().lower()
    if maintenance:
        return maintenance == "serving"
    status = str(health.get("status") or "").strip().lower()
    if status:
        return status in ("ok", "ready", "healthy", "serving")
    return True


def _stale(status: dict[str, Any] | None, want_at: float) -> bool:
    """True when a request is newer than anything the agent has acknowledged."""
    if not status or not want_at:
        return False
    seen = float(status.get("last_desired_at") or 0.0)
    return seen < want_at - 0.5 and (time.time() - want_at) > AGENT_STALE_S


def request(state: str, *, by: str = "", reason: str = "") -> dict[str, Any]:
    """Ask the host to start or stop the node. Returns the record that was written.

    Writing is all this does — it is a request, not a result. Poll ``power_state`` (or
    call ``wake``) to find out what the host made of it.
    """
    state = (state or "").strip().lower()
    if state not in ("on", "off"):
        raise ValueError(f"power state must be 'on' or 'off', got {state!r}")
    rec = {"state": state, "requested_at": time.time(), "by": by or "", "reason": reason or ""}
    os.makedirs(CONTROL_DIR, exist_ok=True)
    try:
        # 1777 like /tmp itself: the container (uid 1001 here) and the host user (1000)
        # both write into this directory, and the sticky bit still stops either from
        # deleting the other's file. Whichever side creates it first sets the mode; the
        # chmod fails harmlessly for the side that did not.
        os.chmod(CONTROL_DIR, 0o1777)
    except OSError:
        pass
    tmp = _path(DESIRED + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    # Rename so the agent never reads a half-written file. Same directory, so it is
    # atomic; the agent's .path unit fires on the result either way.
    os.replace(tmp, _path(DESIRED))
    logger.info("inference-nodes: asked host to turn FreeToken %s (by=%s)", state, by or "?")
    return rec


def power_state(node_state: Any = None) -> dict[str, Any]:
    """Everything a settings pane needs to draw the switch honestly.

    ``node_state`` is an optional ``NodeState`` — when given, ``running`` is what the
    probe actually saw rather than what the host agent believes, because a node whose
    scheduler died is "active" to systemd and dead to a chat.
    """
    st = agent_status()
    want = desired() or {}
    want_at = float(want.get("requested_at") or 0.0)
    out: dict[str, Any] = {
        "controllable": st is not None,
        "control_dir": CONTROL_DIR,
        "auto_wake": AUTO_WAKE,
        "desired": want.get("state"),
        "desired_at": want_at or None,
        "desired_by": want.get("by") or None,
        "unit_state": (st or {}).get("state"),
        "applied_at": (st or {}).get("applied_at"),
        "agent_error": (st or {}).get("error"),
        "agent_stale": _stale(st, want_at),
    }
    if node_state is not None:
        up = bool(getattr(node_state, "reachable", False))
        ready = up and serving(getattr(node_state, "health", None))
        out["running"] = ready
        # Distinguished on purpose: a switch that reads ON while the checkpoint is still
        # loading sends someone to a chat that will just sit there for a minute.
        out["loading"] = up and not ready
        out["error"] = getattr(node_state, "error", None)
    else:
        out["running"] = (st or {}).get("state") == "active"
        out["loading"] = False
    if st is None:
        out["hint"] = (
            "No host control agent. Run scripts/freetoken/install-user-units.sh on the "
            "machine that runs FreeToken; the backend cannot start a host service by itself."
        )
    return out


async def wake(node_name: str, *, timeout: float | None = None, by: str = "auto") -> bool:
    """Ask for the node and wait until a probe can see it. True if it came up.

    Used both by the settings pane (so the switch does not lie about being on) and by
    ``model_proxy`` when a chat picks a model that lives on a node that is asleep.
    """
    if not installed():
        return False
    from . import probe  # local: probe imports policy, which does not import this module

    request("on", by=by, reason=f"wake {node_name}")
    deadline = time.monotonic() + (timeout if timeout is not None else WAKE_TIMEOUT_S)
    delay = 2.0
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        delay = min(delay * 1.4, 8.0)
        probe.invalidate()
        try:
            states = await probe.snapshot(force=True)
        except Exception:  # a probe failure is not a reason to stop waiting
            continue
        st = states.get(node_name)
        if st is not None and st.reachable and serving(st.health):
            logger.info("inference-nodes: %s is serving after a wake request", node_name)
            return True
        status = agent_status() or {}
        if status.get("error") and float(status.get("applied_at") or 0) > time.time() - 120:
            logger.warning("inference-nodes: host agent could not start %s: %s",
                           node_name, status["error"])
            return False
    logger.warning("inference-nodes: %s did not come up within the wake timeout", node_name)
    return False
