"""A watchable screen for a headed browser session.

Each headed session gets its own X display (Xvfb), its own VNC server on that
display (x11vnc), and a slot in a shared websockify token file so the browser
can reach it through one WebSocket port. The user watches through noVNC and can
take the wheel, which is the whole point of a governed computer: the run is
visible while it happens, not summarised afterwards.

Design notes worth keeping:

* **One websockify, many displays.** A process per session would need a port per
  session published somewhere. A single websockify on 6080 with a token file
  keeps the container's surface to one port, which is what lets nginx proxy it
  on the app's existing port on every platform.
* **The token is the capability.** It is a 32-hex string minted per session and
  never derived from the agent id, so a leaked URL grants exactly one session's
  screen and dies with it.
* **Non-root.** Xvfb and x11vnc both run fine as an unprivileged user as long as
  /tmp/.X11-unix exists and is writable; the Dockerfile creates it.

Everything here degrades: if Xvfb is not installed, ``start`` returns None and
the caller falls back to a headless session with no screen. That keeps a build
that skipped the extra packages working.
"""

from __future__ import annotations

import atexit
import logging
import os
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

TOKEN_DIR = os.getenv("HARVIS_VNC_TOKEN_DIR", "/tmp/harvis-vnc-tokens")
NOVNC_ROOT = os.getenv("HARVIS_NOVNC_ROOT", "/opt/novnc")
WEBSOCKIFY_PORT = int(os.getenv("HARVIS_VNC_WS_PORT", "6080"))

_DISPLAY_BASE = int(os.getenv("HARVIS_VNC_DISPLAY_BASE", "100"))
_VNC_PORT_BASE = int(os.getenv("HARVIS_VNC_PORT_BASE", "5900"))
_MAX_DISPLAYS = max(1, int(os.getenv("HARVIS_VNC_MAX_DISPLAYS", "8")))

_lock = threading.Lock()
_screens: Dict[str, "Screen"] = {}
_websockify: Optional[subprocess.Popen] = None


class Screen:
    """One session's display: Xvfb + x11vnc + a websockify token."""

    def __init__(self, session_id: str, display: int, vnc_port: int, width: int, height: int):
        self.session_id = session_id
        self.display = display
        self.vnc_port = vnc_port
        self.width = width
        self.height = height
        self.token = secrets.token_hex(16)
        self.xvfb: Optional[subprocess.Popen] = None
        self.x11vnc: Optional[subprocess.Popen] = None
        # True while the user is driving. Every agent action is refused with a
        # 423 until they hand it back, so the agent cannot fight them for the
        # mouse or act on a page they navigated to.
        self.taken_over = False

    @property
    def display_name(self) -> str:
        return f":{self.display}"

    def env(self) -> Dict[str, str]:
        return {"DISPLAY": self.display_name}

    def to_dict(self) -> dict:
        return {
            "display": self.display_name,
            "vncPort": self.vnc_port,
            "token": self.token,
            "width": self.width,
            "height": self.height,
            "takenOver": self.taken_over,
        }


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


def available() -> bool:
    """True when this image can actually show a screen."""
    return _have("Xvfb") and _have("x11vnc")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _next_slot_locked() -> Optional[int]:
    used = {sc.display for sc in _screens.values()}
    for i in range(_MAX_DISPLAYS):
        n = _DISPLAY_BASE + i
        if n in used:
            continue
        if not _port_free(_VNC_PORT_BASE + i):
            continue
        return i
    return None


def _write_tokens_locked() -> None:
    """Rewrite the websockify token file from the live screens.

    One file, rewritten whole, because websockify's TokenFile plugin re-reads
    the source on each connection — so a removed session's token stops working
    the moment its screen is gone.
    """
    os.makedirs(TOKEN_DIR, exist_ok=True)
    path = os.path.join(TOKEN_DIR, "tokens")
    tmp = path + ".tmp"
    lines = [f"{sc.token}: 127.0.0.1:{sc.vnc_port}\n" for sc in _screens.values()]
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    os.replace(tmp, path)


def _ensure_websockify_locked() -> None:
    global _websockify
    if _websockify is not None and _websockify.poll() is None:
        return
    if not (_have("websockify") or _have("python3")):
        return
    os.makedirs(TOKEN_DIR, exist_ok=True)
    cmd = [
        "websockify",
        "--token-plugin=TokenFile",
        f"--token-source={TOKEN_DIR}",
    ]
    if os.path.isdir(NOVNC_ROOT):
        cmd += ["--web", NOVNC_ROOT]
    cmd.append(str(WEBSOCKIFY_PORT))
    try:
        _websockify = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        logger.info("browser-runner: websockify listening on %s", WEBSOCKIFY_PORT)
    except FileNotFoundError:
        logger.warning("browser-runner: websockify not installed; no watchable screen")
        _websockify = None


# Where a teammate's Firefox profile lives, so its logins survive between runs.
# A named Docker volume in compose — never a host path, because this image runs
# the same way on Windows, macOS and Linux Docker Desktop.
PROFILE_ROOT = os.getenv("HARVIS_BROWSER_PROFILE_ROOT", "/profiles")

# A profile key names a directory Firefox will read and write, and it arrives
# over HTTP. Checking it character by character is stricter than a path join
# plus a prefix test, and it cannot be fooled by encoding tricks, "..", an
# absolute path, or a symlink-shaped name.
PROFILE_KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")
PROFILE_KEY_MAX = 64


class BadProfileKey(ValueError):
    """The caller asked for a profile key that is not allowed to be a path."""


def profile_key_ok(key: str) -> bool:
    """True when ``key`` may become a directory name under the profiles root."""
    key = (key or "").strip().lower()
    if not key or len(key) > PROFILE_KEY_MAX:
        return False
    return all(c in PROFILE_KEY_CHARS for c in key)


def profile_dir(key: str, *, create: bool = True) -> str:
    """Resolve a profile key to its directory, raising on anything suspicious."""
    normalised = (key or "").strip().lower()
    if not profile_key_ok(normalised):
        raise BadProfileKey("profile must be 1-64 chars of [a-z0-9-_]")
    path = os.path.join(PROFILE_ROOT, normalised)
    if create:
        os.makedirs(path, exist_ok=True)
        clean_profile_locks(path)
    return path


def clean_profile_locks(profile_dir: str) -> None:
    """Remove Firefox's lock files so a crashed session's profile still opens.

    Firefox refuses to start on a profile that still holds ``.parentlock`` from
    a process that died without cleaning up — which is exactly what a killed
    container leaves behind. The lock protects against two live Firefoxes on one
    profile; we serialise that ourselves (one session per profile key), so
    clearing it on open is safe and stops a teammate from being permanently
    locked out of its own logins by one bad shutdown.
    """
    for name in (".parentlock", "lock", ".lock"):
        try:
            os.unlink(os.path.join(profile_dir, name))
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("could not clear %s in %s: %s", name, profile_dir, exc)


def start(session_id: str, *, width: int = 1280, height: int = 800) -> Optional[Screen]:
    """Bring up a screen for ``session_id``. None when this image cannot."""
    if not available():
        logger.info("browser-runner: Xvfb/x11vnc missing — headed session denied")
        return None
    with _lock:
        if session_id in _screens:
            return _screens[session_id]
        slot = _next_slot_locked()
        if slot is None:
            logger.warning("browser-runner: no free display slot (max %s)", _MAX_DISPLAYS)
            return None
        screen = Screen(
            session_id, _DISPLAY_BASE + slot, _VNC_PORT_BASE + slot, int(width), int(height)
        )
        try:
            screen.xvfb = subprocess.Popen(
                [
                    "Xvfb", screen.display_name,
                    "-screen", "0", f"{screen.width}x{screen.height}x24",
                    "-nolisten", "tcp",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return None

        # Wait for the X socket rather than sleeping a fixed amount: a slow
        # first start would otherwise hand Firefox a display that is not there.
        sock = f"/tmp/.X11-unix/X{screen.display}"
        deadline = time.time() + 10
        while time.time() < deadline and not os.path.exists(sock):
            if screen.xvfb.poll() is not None:
                logger.warning("browser-runner: Xvfb exited immediately on %s", screen.display_name)
                return None
            time.sleep(0.05)
        if not os.path.exists(sock):
            logger.warning("browser-runner: Xvfb never came up on %s", screen.display_name)
            _terminate(screen.xvfb)
            return None

        try:
            screen.x11vnc = subprocess.Popen(
                [
                    "x11vnc", "-display", screen.display_name,
                    "-rfbport", str(screen.vnc_port),
                    "-localhost",      # only websockify, in this container, can reach it
                    "-nopw",           # the websockify token is the credential
                    "-forever", "-shared", "-quiet", "-noxdamage",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            _terminate(screen.xvfb)
            return None

        _screens[session_id] = screen
        _write_tokens_locked()
        _ensure_websockify_locked()
        logger.info(
            "browser-runner: screen %s up for session %s (vnc %s)",
            screen.display_name, session_id, screen.vnc_port,
        )
        return screen


def get(session_id: str) -> Optional[Screen]:
    with _lock:
        return _screens.get(session_id)


def set_takeover(session_id: str, taken: bool) -> Optional[Screen]:
    with _lock:
        screen = _screens.get(session_id)
        if screen is not None:
            screen.taken_over = bool(taken)
        return screen


def _terminate(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def stop(session_id: str) -> None:
    with _lock:
        screen = _screens.pop(session_id, None)
        if screen is None:
            return
        _write_tokens_locked()
    _terminate(screen.x11vnc)
    _terminate(screen.xvfb)
    logger.info("browser-runner: screen %s down", screen.display_name)


def stop_all() -> None:
    for sid in list(_screens):
        stop(sid)
    global _websockify
    _terminate(_websockify)
    _websockify = None


atexit.register(stop_all)
