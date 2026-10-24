"""Which Ollama host actually has a model, right now — and which host is down.

Harvis can run inference on more than one machine. This install's own Ollama
(``OLLAMA_URL``) is always first. Any number of other machines can be added — a
desktop, a Mac Studio, a lab GPU box, anything that runs Ollama — and they hold the
models this machine cannot. Every lane that asks "is this model installed?" against a
single URL gets a wrong answer half the time, and the wrong answer is the dangerous
one: it says *missing* when the truth is *on the other box*.

Where the other machines come from:

* ``HARVIS_OLLAMA_HOSTS`` — ``name=url|label=…|prefer=…`` entries separated by commas,
  or a JSON array of objects with the same keys. ``label`` is what users see in the
  model picker ("Mac Studio"); ``prefer`` lists model-name prefixes, joined with ``+``,
  that should run on that machine even when this one has them too (a model too big for
  this machine's card). Without ``prefer``, this machine always wins a model it has.
* ``DESKTOP_OLLAMA_URL`` — the older single-extra-host setting, still honoured as a
  host named ``desktop``. ``DESKTOP_OLLAMA_LABEL`` names it, and
  ``HARVIS_DESKTOP_PREFERRED_MODELS`` (default ``gemma4``) is its ``prefer`` list.

Labels never include the URL: they reach every user's model picker, and a LAN address
there is a map of the operator's network.

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
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import NamedTuple

import httpx

logger = logging.getLogger(__name__)

# Short, because the point of this module is a current answer. It exists only to keep a
# burst of callers in one request from firing the same probe several times over.
PROBE_TTL_S = float(os.getenv("HARVIS_OLLAMA_PROBE_TTL_S", "10"))
PROBE_TIMEOUT_S = float(os.getenv("HARVIS_OLLAMA_PROBE_TIMEOUT_S", "4"))
# A reachable host finishes the handshake in milliseconds; one that is unplugged or off
# the network never answers, so it should not hold the whole read budget.
CONNECT_TIMEOUT_S = float(os.getenv("HARVIS_PROBE_CONNECT_TIMEOUT_S", "1.5"))

# The name of this install's own Ollama. Callers compare against it rather than
# assuming what kind of machine Harvis runs on.
LOCAL = "local"
HOSTS_ENV = "HARVIS_OLLAMA_HOSTS"

# The legacy DESKTOP_OLLAMA_URL host's prefer list. gemma4 was the default because its
# 9 GiB image spills off an 8 GB card into CPU and becomes unusably slow.
DESKTOP_PREFERRED_PREFIXES = tuple(
    p.strip().lower()
    for p in os.getenv("HARVIS_DESKTOP_PREFERRED_MODELS", "gemma4").split(",")
    if p.strip()
)

# ── Ollama cloud models ─────────────────────────────────────────────────────
# Ollama lists ``kimi-k2.6:cloud`` / ``gpt-oss:120b-cloud`` next to local models, but a
# chat with one forwards the prompt to ollama.com. Harvis is local-first, so they are
# left out of every model list and refused as chat targets unless the operator opts in.
CLOUD_MODELS_ENV = "HARVIS_ALLOW_CLOUD_MODELS"


def cloud_models_allowed() -> bool:
    """True when the operator set ``HARVIS_ALLOW_CLOUD_MODELS=1`` (also true/yes/on)."""
    return (os.getenv(CLOUD_MODELS_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


def is_cloud_model(name, entry: dict | None = None) -> bool:
    """Whether an Ollama tag runs on ollama.com rather than on the machine.

    Matches a ``:cloud`` tag and any tag ending ``-cloud`` (``qwen3-coder:480b-cloud``);
    ``entry`` is the raw ``/api/tags`` item, whose ``remote_host`` is set for the same models.
    """
    n = (name or "").strip().lower()
    if ":" in n.rsplit("/", 1)[-1]:
        tag = n.rsplit(":", 1)[-1]
        if tag == "cloud" or tag.endswith("-cloud"):
            return True
    return bool(isinstance(entry, dict) and entry.get("remote_host"))


def is_hidden_cloud_model(name, entry: dict | None = None) -> bool:
    """``is_cloud_model`` with the opt-in applied: True means leave it out / refuse it."""
    return is_cloud_model(name, entry) and not cloud_models_allowed()


def cloud_refusal(name) -> str | None:
    """The plain-English reason a chat naming ``name`` must be refused, or None to allow it."""
    if not is_hidden_cloud_model(name):
        return None
    return (
        f"Model '{name}' is an Ollama cloud model: it would send your prompt to ollama.com. "
        f"Harvis only runs models on your own machines. Pick a local model, or set "
        f"{CLOUD_MODELS_ENV}=1 to allow cloud models."
    )


def drop_cloud(items):
    """``items`` without hidden cloud models. Items are tag strings or raw ``/api/tags``
    dicts (``name`` / ``model`` keys); anything else passes through untouched."""
    out = []
    for it in items or []:
        if isinstance(it, str):
            if is_hidden_cloud_model(it):
                continue
        elif isinstance(it, dict):
            if is_hidden_cloud_model(it.get("name") or it.get("model") or "", it):
                continue
        out.append(it)
    return out


_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")

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

    name: str                      # LOCAL, or the name an operator gave the machine
    base_url: str
    label: str                     # what a user should see: "Ollama", "Mac Studio"
    prefer: tuple[str, ...] = ()   # model-name prefixes this host takes even when LOCAL has them
    reachable: bool = False
    tags: set[str] = field(default_factory=set)       # empty when unreachable
    order: list[str] = field(default_factory=list)    # tags in the order Ollama listed them
    sizes: dict[str, int] = field(default_factory=dict)   # tag → bytes on disk, when reported
    ctx: dict[str, int] = field(default_factory=dict)     # tag → usable context window, tokens
    last_good_tags: set[str] = field(default_factory=set)   # survives an outage
    last_good_at: float = 0.0
    error: str | None = None       # short, safe: an exception class name or an HTTP code

    def has(self, model: str) -> bool:
        want = _tag(model)
        return bool(want) and any(_tag(t) == want for t in self.tags)

    def prefers(self, model: str) -> bool:
        name = (model or "").lower()
        return bool(name) and any(name.startswith(p) for p in self.prefer)


class HostSpec(NamedTuple):
    name: str
    base_url: str
    label: str
    prefer: tuple[str, ...] = ()


def _tag(name: str) -> str:
    """Ollama serves ``qwen3`` as ``qwen3:latest`` and ignores case; compare names that way."""
    n = (name or "").strip().lower()
    if n and ":" not in n.rsplit("/", 1)[-1]:
        n += ":latest"
    return n


def _clean(url: str) -> str:
    """Ollama's native API lives at the root; a configured OpenAI-compatible
    ``…/v1`` base points at the same daemon and must not be probed as-is."""
    return (url or "").strip().rstrip("/").removesuffix("/v1")


def _prefixes(raw) -> tuple[str, ...]:
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = re.split(r"[+;]", str(raw or ""))
    return tuple(p.strip().lower() for p in items if str(p).strip())


def _spec(d: dict) -> HostSpec | None:
    """One extra host from a loosely-typed dict, or None (logged) when it is unusable."""
    name = str(d.get("name") or "").strip().lower()
    url = _clean(str(d.get("url") or d.get("base_url") or ""))
    if not _NAME_RE.fullmatch(name) or name == LOCAL:
        logger.warning("ollama_hosts: %s entry has a bad name %r — skipped", HOSTS_ENV, name)
        return None
    if not url.startswith(("http://", "https://")):
        logger.warning("ollama_hosts: %s entry %r needs an http(s) URL — skipped", HOSTS_ENV, name)
        return None
    label = str(d.get("label") or "").strip() or name
    return HostSpec(name, url, label, _prefixes(d.get("prefer")))


def parse_hosts(raw: str | None) -> list[HostSpec]:
    """``HARVIS_OLLAMA_HOSTS`` → host specs. A bad entry is skipped, not fatal: one typo
    must not take the other machines out of the picker."""
    raw = (raw or "").strip()
    if not raw:
        return []
    items: list[dict] = []
    if raw.startswith("["):
        try:
            loaded = json.loads(raw)
        except ValueError as e:
            logger.warning("ollama_hosts: %s is not valid JSON (%s) — ignored", HOSTS_ENV, e)
            return []
        items = [i for i in loaded if isinstance(i, dict)] if isinstance(loaded, list) else []
    else:
        for entry in raw.split(","):
            head, *attrs = [p.strip() for p in entry.split("|")]
            if not head:
                continue
            if "=" not in head:
                logger.warning("ollama_hosts: %s entry %r is not name=url — skipped", HOSTS_ENV, head)
                continue
            name, url = head.split("=", 1)
            d = {"name": name, "url": url}
            for attr in attrs:
                if "=" in attr:
                    k, v = attr.split("=", 1)
                    d[k.strip().lower()] = v.strip()
            items.append(d)
    return [sp for sp in (_spec(d) for d in items) if sp is not None]


def configured_hosts() -> list[HostSpec]:
    """Every configured host, this install's own first, then the others in the order
    they were listed — which is also the order a model is looked for in.

    A host whose URL equals one already listed is the same daemon, not a second one —
    that is the normal single-box deployment, and listing it twice would double every
    probe. The same goes for a repeated name.
    """
    local = _clean(os.getenv("OLLAMA_URL", "http://ollama:11434"))
    hosts = [HostSpec(LOCAL, local, "Ollama")] if local else []
    extra = parse_hosts(os.getenv(HOSTS_ENV))
    desktop = _clean(os.getenv("DESKTOP_OLLAMA_URL", ""))
    legacy = None
    if desktop:
        legacy = HostSpec(
            "desktop", desktop,
            (os.getenv("DESKTOP_OLLAMA_LABEL") or "").strip() or "Second machine",
            DESKTOP_PREFERRED_PREFIXES,
        )
        extra.append(legacy)
    for sp in extra:
        if any(sp.base_url == h.base_url or sp.name == h.name for h in hosts):
            if sp is legacy and not _warned_dupe and any(
                    h.name != LOCAL and (h.base_url == sp.base_url or h.name == sp.name) for h in hosts):
                _warned_dupe.append(True)
                logger.warning(
                    "ollama_hosts: DESKTOP_OLLAMA_URL repeats a %s entry and is ignored, "
                    "along with its prefer list; add prefer= to that entry to keep it", HOSTS_ENV)
            continue
        hosts.append(sp)
    return hosts


_warned_dupe: list[bool] = []   # log the ignored legacy host once, not per call


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


async def _probe(spec: HostSpec, timeout: float) -> HostState:
    name, base_url = spec.name, spec.base_url
    prev = _cache.get(name)
    st = HostState(name=name, base_url=base_url, label=spec.label, prefer=spec.prefer)
    if prev is not None:
        st.last_good_tags = prev.last_good_tags
        st.last_good_at = prev.last_good_at
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT_S))) as hc:
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
        if not tag or tag in st.tags:
            continue
        if is_hidden_cloud_model(tag, m):
            continue
        st.tags.add(tag)
        st.order.append(tag)
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
            *(_probe(sp, timeout) for sp in hosts), return_exceptions=True
        )
        fresh: dict[str, HostState] = {}
        for sp, st in zip(hosts, states):
            n = sp.name
            if isinstance(st, HostState):
                fresh[n] = st
            else:
                # gather() with return_exceptions can only land here on a bug in _probe,
                # which already catches its own network errors. Record it rather than
                # dropping the host, so a host never disappears without a reason.
                prev = _cache.get(n)
                fresh[n] = HostState(
                    name=n, base_url=sp.base_url, label=sp.label, prefer=sp.prefer,
                    error=type(st).__name__,
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


async def resolve(model: str, *, force: bool = False) -> tuple[str | None, str]:
    """Where to run ``model``: ``(base_url, reason)``.

    ``base_url`` is ``None`` when no reachable host has it. The reason is for the log and
    for an error message, and it distinguishes the two failures that matter:

    * ``"absent"``   — every configured host answered, and none of them has it.
    * ``"unknown"``  — a host that could have it did not answer. Not the same as absent,
      and a caller must not substitute a different model on the strength of it.

    A host whose ``prefer`` list matches gets the model even when this machine has it
    too (``"<name>-preferred"``), because running a model too big for the local card on
    CPU is a worse outcome than a network hop. Otherwise the first host in configured
    order that has it — this machine first — and the reason is that host's name.
    """
    if not (model or "").strip():
        return None, "absent"
    hosts = list((await snapshot(force=force)).values())

    for st in hosts:
        if st.name != LOCAL and st.prefers(model) and st.has(model):
            return st.base_url, f"{st.name}-preferred"
    for st in hosts:
        if st.has(model):
            return st.base_url, st.name
    if any(not st.reachable for st in hosts):
        return None, "unknown"
    return None, "absent"


def host_label(name: str) -> str:
    """The user-facing label of a configured host, or the name when it is not configured."""
    st = _cache.get(name)
    if st is not None:
        return st.label
    for sp in configured_hosts():
        if sp.name == name:
            return sp.label
    return name


async def route(model: str, primary: str | None = None) -> tuple[str, str, str]:
    """``(base_url, host_name, reason)`` for a caller that must send ``model`` somewhere.

    ``primary`` is the Ollama the caller would use on its own (a user's saved provider
    URL, or ``OLLAMA_URL``), returned unchanged unless another configured machine is the
    one that should serve the model — so a single-machine install never probes and
    never changes behaviour. When nothing has the model, ``primary`` is returned and
    ``reason`` says whether that is because it is ``"absent"`` everywhere or a machine
    that might hold it is ``"unknown"`` (not answering), so the caller can say so
    instead of passing on a bare 404.
    """
    hosts = configured_hosts()
    base_primary = (primary or (hosts[0].base_url if hosts else "")).rstrip("/")
    if len(hosts) < 2 or not (model or "").strip():
        return base_primary, LOCAL, "single"
    if primary and _clean(primary) not in {h.base_url for h in hosts}:
        # A user's own saved Ollama, not one of the operator's machines: stay on it.
        return base_primary, LOCAL, "custom"
    base, reason = await resolve(model)
    if base is None:
        return base_primary, LOCAL, reason
    name = reason.removesuffix("-preferred")
    if name == LOCAL:
        return base_primary, LOCAL, reason
    return base, name, reason


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

    This is what lets a picker grey out gemma4:12b with "Mac Studio is not answering"
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
