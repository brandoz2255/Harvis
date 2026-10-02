"""The session table, and the rule for when a session is over.

Lifetime used to be measured from creation: a session died 300 s after it was
opened whether or not anyone was using it, which is exactly when a person is
halfway through signing in on the Take-over screen. The rule is now two
clocks:

* **idle** (``HARVIS_BROWSER_SESSION_TTL_S``): time since the last action.
  Every call that reaches the driver refreshes it, and a session whose user
  has the wheel never idles out — they are driving in noVNC, not through us.
* **max** (``HARVIS_BROWSER_SESSION_MAX_S``): time since creation. The hard
  cap that stops a forgotten screen from living until the container restarts.

Kept free of selenium so the clocks can be tested in any container that has
Python; app.py owns the drivers, this owns when they are let go.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional


def env_seconds(name: str, default: int, floor: int) -> int:
    """An env var as whole seconds, never below ``floor`` and never garbage."""
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(floor, value)


IDLE_S = env_seconds("HARVIS_BROWSER_SESSION_TTL_S", 900, 30)
MAX_S = env_seconds("HARVIS_BROWSER_SESSION_MAX_S", 4 * 3600, IDLE_S)


class Entry:
    __slots__ = ("session_id", "driver", "created_at", "last_used", "safe_mode", "profile", "headed")

    def __init__(self, session_id: str, driver: Any, now: float, *,
                 safe_mode: bool, profile: Optional[str], headed: bool):
        self.session_id = session_id
        self.driver = driver
        self.created_at = now
        self.last_used = now
        self.safe_mode = safe_mode
        self.profile = profile
        self.headed = headed

    def to_dict(self, now: float) -> Dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "profile": self.profile,
            "headed": self.headed,
            "safeMode": self.safe_mode,
            "createdAt": int(self.created_at),
            "lastUsedAt": int(self.last_used),
            "idleS": int(max(0.0, now - self.last_used)),
        }


class Registry:
    def __init__(self, *, idle_s: int = IDLE_S, max_s: int = MAX_S,
                 clock: Callable[[], float] = time.time):
        self.idle_s = int(idle_s)
        self.max_s = max(int(max_s), self.idle_s)
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: Dict[str, Entry] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def now(self) -> float:
        return self._clock()

    def add(self, session_id: str, driver: Any, *, safe_mode: bool = False,
            profile: Optional[str] = None, headed: bool = False) -> Entry:
        entry = Entry(session_id, driver, self._clock(), safe_mode=safe_mode,
                      profile=profile, headed=headed)
        with self._lock:
            self._entries[session_id] = entry
        return entry

    def touch(self, session_id: str) -> Optional[Entry]:
        """The entry, with its idle clock reset. None when there is no such session."""
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is not None:
                entry.last_used = self._clock()
            return entry

    def peek(self, session_id: str) -> Optional[Entry]:
        with self._lock:
            return self._entries.get(session_id)

    def pop(self, session_id: str) -> Optional[Entry]:
        with self._lock:
            return self._entries.pop(session_id, None)

    def by_profile(self, profile: Optional[str]) -> Optional[Entry]:
        """The live session on a Firefox profile. Two Firefoxes on one profile
        corrupt it, so a second request for a held profile must be refused."""
        if not profile:
            return None
        with self._lock:
            for entry in self._entries.values():
                if entry.profile == profile:
                    return entry
        return None

    def entries(self) -> List[Entry]:
        with self._lock:
            return list(self._entries.values())

    def expire(self, *, keep_alive: Callable[[str], bool] = lambda _sid: False) -> List[Entry]:
        """Remove and return every session past its idle or max lifetime.

        ``keep_alive(session_id)`` True exempts a session from the idle clock
        (the user has the wheel); nothing is exempt from the max clock.
        """
        now = self._clock()
        gone: List[Entry] = []
        with self._lock:
            for sid, entry in list(self._entries.items()):
                over_max = now - entry.created_at > self.max_s
                idle = now - entry.last_used > self.idle_s and not keep_alive(sid)
                if over_max or idle:
                    gone.append(self._entries.pop(sid))
        return gone
