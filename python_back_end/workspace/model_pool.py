"""Share load across model tags that are the same model under different names.

NVIDIA PAIR routes a job by its exact model name, so two machines that hold the
same weights under different tags never share work: the lab 4090 has
``qwen3.8:27b-mtp-q4_K_M`` and the 3090 has ``qwen3.8:27b-q4_K_M``, and every
qwen job landed on the 4090. Here, a request for any tag in a pool goes out
under whichever tag has the fewest requests in flight, and PAIR then places it
on the machine that holds that tag. A tie keeps the requested tag, so a lone
chat stays on the model the user picked (and keeps its warm prompt cache); the
second tag only takes work while the first is busy.

    HARVIS_MODEL_POOLS="qwen3.8:27b-mtp-q4_K_M,qwen3.8:27b-q4_K_M"

Pools are separated by ``;``, tags inside one by ``,``. Unset means no pooling.
"""

from __future__ import annotations

import itertools
import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

# A lease whose finally never ran (a stream dropped mid-flight and never
# closed) stops counting after this long, so one leak cannot pin a tag as busy.
_STALE_AFTER_S = 900.0

_in_flight: dict[str, dict[int, float]] = {}
_ids = itertools.count()


def _pools() -> list[list[str]]:
    raw = os.getenv("HARVIS_MODEL_POOLS") or ""
    pools = []
    for group in raw.split(";"):
        tags = [t.strip() for t in group.split(",") if t.strip()]
        if len(tags) > 1:
            pools.append(tags)
    return pools


def pool_for(model: str | None) -> list[str] | None:
    if not model:
        return None
    for pool in _pools():
        if model in pool:
            return pool
    return None


def _busy(tag: str, now: float) -> int:
    leases = _in_flight.get(tag) or {}
    for k in [k for k, t in leases.items() if now - t > _STALE_AFTER_S]:
        del leases[k]
    return len(leases)


@contextmanager
def lease(model: str | None) -> Iterator[str | None]:
    """Yield the tag to send this request under, counting it in flight until exit.

    No awaits between choosing and counting, so concurrent requests on the one
    event loop each see the others' leases."""
    pool = pool_for(model)
    if not pool:
        yield model
        return
    now = time.monotonic()
    pick = min(pool, key=lambda t: (_busy(t, now), t != model))
    key = next(_ids)
    _in_flight.setdefault(pick, {})[key] = now
    if pick != model:
        logger.info("model_pool: %s busy — sending as %s", model, pick)
    try:
        yield pick
    finally:
        _in_flight.get(pick, {}).pop(key, None)
