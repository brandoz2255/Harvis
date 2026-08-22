"""Which Ollama host actually has a model, right now — and which host is down.

Harvis runs inference on more than one box. The laptop's own Ollama (``OLLAMA_URL``)
is always there; the RTX 5080 rig (``DESKTOP_OLLAMA_URL``) is there when its network
is up, and it holds the models the laptop's 8 GB card cannot run — gemma4:12b lives
only on the rig. Every lane that asks "is this model installed?" against a single URL
gets a wrong answer half the time, and the wrong answer is the dangerous one: it says
*missing* when the truth is *on the other box*.

Two things this module refuses to conflate, because collapsing them is what made the
old behaviour dishonest:

* **absent** — the host answered and the tag is not there.
* **unknown** — the host did not answer, so nothing can be concluded. A caller that
  treats unknown as absent silently overrides the user's model choice every time a
  box is asleep.

It also keeps the last tag list each host successfully returned. That is the only way
to say "gemma4:12b exists but the rig is unreachable" instead of having the model
quietly vanish from the picker, which reads to a user as "Harvis lost my model".

Lives under ``owui_compat`` because that directory is bind-mounted into the backend
(see docker-compose) and this needs to be editable without an image rebuild; it is not
an OWUI concept. ``main.py`` and the CAD lane both import it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Short, because the point of this module is a current answer. It exists only to keep a
# burst of callers in one request from firing the same probe several times over.
PROBE_TTL_S = float(os.getenv("HARVIS_OLLAMA_PROBE_TTL_S", "10"))
PROBE_TIMEOUT_S = float(os.getenv("HARVIS_OLLAMA_PROBE_TIMEOUT_S", "4"))

# Same env and same default as workspace/model_proxy.py, so a model does not route to
# the rig for chat and to the laptop for CAD. gemma4 is on the list because its 9 GiB
# image spills off the laptop's 8 GB card into CPU and becomes unusably slow.
DESKTOP_PREFERRED_PREFIXES = tuple(
    p.strip().lower()
    for p in os.getenv("HARVIS_DESKTOP_PREFERRED_MODELS", "gemma4").split(",")
    if p.strip()
)

# What a model was TRAINED for and what it is SERVED with are different numbers, and
# only the second one is true of a running request. Every chat model installed here
# trains at 131072 or more, but the daemon runs with OLLAMA_CONTEXT_LENGTH=24576 and
# model_proxy sends num_ctx=HARVIS_OLLAMA_NUM_CTX on every Ollama call — so 24576 is
# what a conversation actually gets, and anything above it is silently dropped off the
# front of the prompt. Same env and same default as workspace/model_proxy.py:1166 on
# purpose: if that cap moves, this number has to move with it or the UI starts
# promising room the model will not have.
try:
    SERVED_CONTEXT_CAP = int(os.getenv("HARVIS_OLLAMA_NUM_CTX", "24576"))
except ValueError:
    SERVED_CONTEXT_CAP = 24576

# A tag's trained context is a property of the file on disk, so it is asked once per
# host and kept for the life of the process. The probe TTL is 10s and re-pulling a tag
# under the same name is rare enough that a restart is an acceptable way to notice it.
_ctx_cache: dict[str, int] = {}
SHOW_TIMEOUT_S = float(os.getenv("HARVIS_OLLAMA_SHOW_TIMEOUT_S", "8"))


@dataclass
class HostState:
    """What is known about one Ollama host as of the last probe."""

    name: str                      # "laptop" | "desktop"
    base_url: str
    label: str                     # what a user should see: "Ollama", "Desktop 5080"
    reachable: bool = False
    tags: set[str] = field(default_factory=set)       # empty when unreachable
    sizes: dict[str, int] = field(default_factory=dict)   # tag → bytes on disk, when reported
    ctx: dict[str, int] = field(default_factory=dict)     # tag → usable context window, tokens
    last_good_tags: set[str] = field(default_factory=set)   # survives an outage
    last_good_at: float = 0.0
    error: str | None = None       # short, safe: an exception class name or an HTTP code

    def has(self, model: str) -> bool:
        return bool(model) and model in self.tags


def _clean(url: str) -> str:
    """Ollama's native API lives at the root; a configured OpenAI-compatible
    ``…/v1`` base points at the same daemon and must not be probed as-is."""
    return (url or "").strip().rstrip("/").removesuffix("/v1")


def configured_hosts() -> list[tuple[str, str, str]]:
    """(name, base_url, label) for every host that is configured, laptop first.

    A desktop URL equal to the laptop's is one host, not two — that is the normal
    single-box deployment, and listing it twice would double every probe.
    """
    laptop = _clean(os.getenv("OLLAMA_URL", "http://ollama:11434"))
    desktop = _clean(os.getenv("DESKTOP_OLLAMA_URL", ""))
    hosts = [("laptop", laptop, "Ollama")] if laptop else []
    if desktop and desktop != laptop:
        hosts.append(("desktop", desktop, "Desktop 5080"))
    return hosts


_cache: dict[str, HostState] = {}
_cache_at: float = 0.0
_lock = asyncio.Lock()


async def _show_context(hc: httpx.AsyncClient, base_url: str, tag: str) -> None:
    """Ask one model how much context it was built for, and remember the answer.

    Best-effort by design: a tag whose ``/api/show`` fails simply has no entry, and
    every caller already has to handle a model that does not report a window. Failing
    the whole host probe because one manifest could not be read would take the model
    picker down over a number that is only advisory.
    """
    key = f"{base_url}|{tag}"
    if key in _ctx_cache:
        return
    try:
        r = await hc.post(f"{base_url}/api/show", json={"model": tag})
        if r.status_code != 200:
            return
        info = r.json().get("model_info") or {}
    except Exception:
        return
    # Ollama keys this by architecture — "llama.context_length", "gemma3.context_length",
    # and so on — so there is no fixed key to read, only a fixed suffix.
    for k, v in info.items():
        if k.endswith(".context_length") and isinstance(v, int) and v > 0:
            _ctx_cache[key] = min(v, SERVED_CONTEXT_CAP)
            return


async def _probe(name: str, base_url: str, label: str, timeout: float) -> HostState:
    prev = _cache.get(name)
    st = HostState(name=name, base_url=base_url, label=label)
    if prev is not None:
        st.last_good_tags = prev.last_good_tags
        st.last_good_at = prev.last_good_at
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as hc:
            r = await hc.get(f"{base_url}/api/tags")
    except Exception as e:
        # The class name only. A connection error can carry the host, the port and the
        # resolver's opinion of the network, and this string reaches the UI.
        st.error = type(e).__name__
        return st
    if r.status_code != 200:
        st.error = f"HTTP {r.status_code}"
        return st
    try:
        models = r.json().get("models") or []
    except Exception:
        st.error = "bad response"
        return st
    st.reachable = True
    for m in models:
        tag = str(m.get("model") or m.get("name") or "").strip()
        if not tag:
            continue
        st.tags.add(tag)
        size = m.get("size")
        if isinstance(size, int) and size > 0:
            st.sizes[tag] = size
    st.last_good_tags = set(st.tags)
    st.last_good_at = time.time()

    # Context windows for anything this host has not been asked about yet. Cached tags
    # cost nothing, so this is one burst on the first probe after a restart and silence
    # afterwards. Bounded by the same timeout as the rest of the probe.
    unknown = [tg for tg in st.tags if f"{base_url}|{tg}" not in _ctx_cache]
    if unknown:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(SHOW_TIMEOUT_S)) as sc:
                await asyncio.gather(
                    *(_show_context(sc, base_url, tg) for tg in unknown),
                    return_exceptions=True,
                )
        except Exception:
            logger.debug("ollama_hosts: context probe failed for %s", name, exc_info=True)
    for tg in st.tags:
        win = _ctx_cache.get(f"{base_url}|{tg}")
        if win:
            st.ctx[tg] = win
    return st


async def snapshot(*, force: bool = False, timeout: float = PROBE_TIMEOUT_S) -> dict[str, HostState]:
    """Probe every configured host in parallel and return the result by host name.

    ``force`` skips the TTL — that is what a picker's explicit refresh should pass, so
    a rig that just came back online shows up on the click rather than ten seconds later.
    """
    global _cache_at
    async with _lock:
        if not force and _cache and (time.time() - _cache_at) < PROBE_TTL_S:
            return dict(_cache)
        hosts = configured_hosts()
        states = await asyncio.gather(
            *(_probe(n, u, lb, timeout) for n, u, lb in hosts), return_exceptions=True
        )
        fresh: dict[str, HostState] = {}
        for (n, u, lb), st in zip(hosts, states):
            if isinstance(st, HostState):
                fresh[n] = st
            else:
                # gather() with return_exceptions can only land here on a bug in _probe,
                # which already catches its own network errors. Record it rather than
                # dropping the host, so a host never disappears without a reason.
                prev = _cache.get(n)
                fresh[n] = HostState(
                    name=n, base_url=u, label=lb, error=type(st).__name__,
                    last_good_tags=prev.last_good_tags if prev else set(),
                    last_good_at=prev.last_good_at if prev else 0.0,
                )
                logger.warning("ollama_hosts: probe of %s raised %r", n, st)
        _cache.clear()
        _cache.update(fresh)
        _cache_at = time.time()
        return dict(fresh)


def invalidate() -> None:
    """Force the next ``snapshot()`` to re-probe.

    For the picker's explicit refresh, where the caller cannot thread ``force`` down
    through an unrelated function. Clearing the timestamp and not the states keeps
    ``last_good_tags`` — the whole point of which is to outlive a failed probe.
    """
    global _cache_at
    _cache_at = 0.0


def prefers_desktop(model: str) -> bool:
    name = (model or "").lower()
    return bool(name) and any(name.startswith(p) for p in DESKTOP_PREFERRED_PREFIXES)


async def resolve(model: str, *, force: bool = False) -> tuple[str | None, str]:
    """Where to run ``model``: ``(base_url, reason)``.

    ``base_url`` is ``None`` when no reachable host has it. The reason is for the log and
    for an error message, and it distinguishes the two failures that matter:

    * ``"absent"``   — every configured host answered, and none of them has it.
    * ``"unknown"``  — a host that could have it did not answer. Not the same as absent,
      and a caller must not substitute a different model on the strength of it.

    Desktop-preferred models go to the rig when the rig has them even if the laptop does
    too, because the laptop running a 9 GiB model on CPU is a worse outcome than a hop.
    """
    if not (model or "").strip():
        return None, "absent"
    hosts = await snapshot(force=force)
    laptop, desktop = hosts.get("laptop"), hosts.get("desktop")

    if prefers_desktop(model) and desktop is not None and desktop.has(model):
        return desktop.base_url, "desktop-preferred"
    for st in (laptop, desktop):
        if st is not None and st.has(model):
            return st.base_url, st.name
    if any(st is not None and not st.reachable for st in (laptop, desktop)):
        return None, "unknown"
    return None, "absent"


async def available(*, force: bool = False) -> set[str] | None:
    """Every tag reachable anywhere, or ``None`` when no host could be asked.

    ``None`` is the honest answer when nothing answered — the caller then knows it has
    no information, rather than being handed an empty set that looks like "you have no
    models installed".
    """
    hosts = await snapshot(force=force)
    if not hosts:
        return None
    if not any(st.reachable for st in hosts.values()):
        return None
    out: set[str] = set()
    for st in hosts.values():
        out |= st.tags
    return out


async def unreachable_models(*, force: bool = False) -> list[tuple[str, HostState]]:
    """(model, host) for tags a host used to serve and cannot right now.

    This is what lets a picker grey out gemma4:12b with "Desktop 5080 unreachable"
    instead of dropping it, which a user reads as Harvis losing their model.
    """
    hosts = await snapshot(force=force)
    live: set[str] = set()
    for st in hosts.values():
        live |= st.tags
    out: list[tuple[str, HostState]] = []
    for st in hosts.values():
        if st.reachable:
            continue
        for tag in sorted(st.last_good_tags - live):
            out.append((tag, st))
    return out
