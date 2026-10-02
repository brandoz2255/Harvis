"""The backend's mount table, as handed over in Kubernetes mode.

Sandboxes are sibling Docker containers bound to a session folder by its HOST
path. In Docker mode the backend reads that from its own container's mounts; a
pod has no container to inspect, so the manifest generator passes the same
table in HARVIS_HOST_MOUNTS (scripts/k8s/k8s_extras.extra_env).
"""

import json
import os
from typing import Optional


def host_mounts_from_env() -> Optional[list[dict]]:
    """``[{"Destination": ..., "Source": ...}, ...]``, or None when unset.

    Raises RuntimeError with a readable reason when the value is malformed, so a
    caller refuses to run instead of guessing a host path."""
    raw = (os.getenv("HARVIS_HOST_MOUNTS") or "").strip()
    if not raw:
        return None
    try:
        table = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(f"HARVIS_HOST_MOUNTS is not valid JSON: {exc}") from None
    if not isinstance(table, list) or not all(isinstance(m, dict) for m in table):
        raise RuntimeError("HARVIS_HOST_MOUNTS must be a list of {Destination, Source} objects")
    return table
