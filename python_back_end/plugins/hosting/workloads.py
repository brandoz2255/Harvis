"""What is running in the Harvis namespace, for the admin cluster panel.

Read-only: deployments, their pods, recent warning events, and a pod's log
tail. Everything goes through ``cluster.api_get`` so the service-account token
stays in one Authorization header and every error is composed text. The
parsers are pure and defensive like ``detect.parse_node``: one odd object must
never blank the whole panel.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from .cluster import NodeListError, api_get
from .detect import DEFAULT_NAMESPACE, MODE_KUBERNETES, hosting_mode

CACHE_TTL_S = 10.0
MAX_EVENTS = 25
LOG_TAIL_LINES = 300
LOG_LIMIT_BYTES = 256 * 1024

# Kubernetes object names: lowercase DNS labels. Checked before a name goes into a URL path.
_NAME_RX = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")

# Same redactions as the kubectl proxy: a log line can carry a secret the service printed.
_REDACT = (
    (re.compile(r'(?i)(token|password|passwd|secret|api[_-]?key|auth)\s*[=:]\s*["\']?[^\s,;"\']{8,}["\']?'),
     r"\1: [REDACTED]"),
    (re.compile(r"(?i)-----BEGIN [A-Z ]+-----[^-]+-----END [A-Z ]+-----"), "[REDACTED: PEM]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-.]*"), "[REDACTED: JWT]"),
    (re.compile(r"(?i)(postgres(?:ql)?://[^:/\s]+:)[^@\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"), r"\1[REDACTED]"),
)

Fetcher = Callable[[str, str], Any]

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "key": None, "value": None}


def valid_name(name: str) -> bool:
    return bool(_NAME_RX.match(name or ""))


def redact(text: str) -> str:
    for rx, repl in _REDACT:
        text = rx.sub(repl, text)
    return text


def _ts(raw: Any) -> Optional[float]:
    try:
        return datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _image_tag(image: str) -> str:
    """``ghcr.io/x/harvis-backend@sha256:abcd…`` → ``sha256:abcd1234``; ``x:1.5`` → ``1.5``."""
    image = str(image or "")
    if "@" in image:
        return image.split("@", 1)[1][:19]
    last = image.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else "latest"


def parse_deployment(d: Mapping[str, Any]) -> dict[str, Any]:
    meta = d.get("metadata") or {}
    spec = d.get("spec") or {}
    status = d.get("status") or {}
    containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
    desired = spec.get("replicas")
    desired = 1 if desired is None else int(desired or 0)
    ready = int(status.get("readyReplicas") or 0)
    if desired == 0:
        state = "stopped"
    elif ready >= desired:
        state = "ready"
    elif ready > 0:
        state = "degraded"
    else:
        state = "down"
    return {
        "name": str(meta.get("name") or ""),
        "desired": desired,
        "ready": ready,
        "updated": int(status.get("updatedReplicas") or 0),
        "state": state,
        "images": [{"name": str(c.get("name") or ""), "tag": _image_tag(c.get("image"))} for c in containers],
        "selector": dict(((spec.get("selector") or {}).get("matchLabels")) or {}),
    }


def _waiting_reason(statuses: list) -> Optional[str]:
    for cs in statuses:
        waiting = (cs.get("state") or {}).get("waiting") or {}
        if waiting.get("reason"):
            return str(waiting["reason"])
        term = (cs.get("state") or {}).get("terminated") or {}
        if term.get("reason"):
            return str(term["reason"])
    return None


def parse_pod(p: Mapping[str, Any]) -> dict[str, Any]:
    meta = p.get("metadata") or {}
    spec = p.get("spec") or {}
    status = p.get("status") or {}
    statuses = status.get("containerStatuses") or []
    last_restart = None
    for cs in statuses:
        finished = _ts(((cs.get("lastState") or {}).get("terminated") or {}).get("finishedAt"))
        if finished and (last_restart is None or finished > last_restart):
            last_restart = finished
    return {
        "name": str(meta.get("name") or ""),
        "labels": dict(meta.get("labels") or {}),
        "phase": str(status.get("phase") or "Unknown"),
        "reason": _waiting_reason(statuses) or status.get("reason"),
        "ready": bool(statuses) and all(cs.get("ready") for cs in statuses),
        "restarts": sum(int(cs.get("restartCount") or 0) for cs in statuses),
        "last_restart": last_restart,
        "node": str(spec.get("nodeName") or ""),
        "started": _ts(status.get("startTime")),
        "containers": [str(c.get("name") or "") for c in (spec.get("containers") or [])],
    }


def parse_event(e: Mapping[str, Any]) -> dict[str, Any]:
    obj = e.get("involvedObject") or {}
    meta = e.get("metadata") or {}
    last = _ts(e.get("lastTimestamp")) or _ts(e.get("eventTime")) or _ts(meta.get("creationTimestamp"))
    return {
        "reason": str(e.get("reason") or ""),
        "message": redact(str(e.get("message") or ""))[:500],
        "object": f"{str(obj.get('kind') or '').lower()}/{obj.get('name') or ''}",
        "count": int(e.get("count") or 1),
        "last_seen": last,
    }


def _owned_by(pod: dict[str, Any], selector: dict[str, str]) -> bool:
    return bool(selector) and all(pod["labels"].get(k) == v for k, v in selector.items())


def _default_fetch(path: str, what: str) -> Any:
    return api_get(path, what)


def describe_workloads(
    environ: Optional[Mapping[str, str]] = None,
    fetch: Optional[Fetcher] = None,
) -> dict[str, Any]:
    """The admin cluster panel payload. Never raises; ``error`` says what failed."""
    env = os.environ if environ is None else environ
    mode, _ = hosting_mode(env)
    if mode != MODE_KUBERNETES:
        return {"mode": mode, "namespace": None, "services": [], "unmatched_pods": [], "events": [], "error": None}

    ns = (env.get("HARVIS_K8S_NAMESPACE") or "").strip() or DEFAULT_NAMESPACE
    fetch = fetch or _default_fetch
    out: dict[str, Any] = {"mode": mode, "namespace": ns, "services": [], "unmatched_pods": [], "events": [], "error": None}
    try:
        deployments = [parse_deployment(d) for d in (fetch(f"/apis/apps/v1/namespaces/{ns}/deployments", "list deployments").get("items") or [])]
        pods = [parse_pod(p) for p in (fetch(f"/api/v1/namespaces/{ns}/pods", "list pods").get("items") or [])]
    except NodeListError as exc:
        out["error"] = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001 — "never raises"; no raw text
        out["error"] = f"reading the cluster failed ({exc.__class__.__name__})"
        return out

    claimed: set[str] = set()
    for d in sorted(deployments, key=lambda d: d["name"]):
        selector = d.pop("selector")
        mine = [p for p in pods if _owned_by(p, selector)]
        claimed.update(p["name"] for p in mine)
        d["pods"] = sorted(mine, key=lambda p: p["name"])
        d["restarts"] = sum(p["restarts"] for p in mine)
        if d["state"] == "ready" and any(p["reason"] == "CrashLoopBackOff" for p in mine):
            d["state"] = "degraded"
        out["services"].append(d)
    for p in pods:
        p.pop("labels", None)
        if p["name"] not in claimed:
            out["unmatched_pods"].append(p)

    # Warnings are a nicety: a missing events permission must not blank the services list.
    try:
        raw = fetch(f"/api/v1/namespaces/{ns}/events?fieldSelector=type%3DWarning", "list events").get("items") or []
        events = sorted((parse_event(e) for e in raw), key=lambda e: e["last_seen"] or 0, reverse=True)
        out["events"] = events[:MAX_EVENTS]
    except Exception as exc:  # noqa: BLE001
        out["events_error"] = str(exc) if isinstance(exc, NodeListError) else f"listing events failed ({exc.__class__.__name__})"
    return out


def cached_workloads() -> dict[str, Any]:
    """``describe_workloads`` behind a 10 s cache, so several open admin tabs cost one read."""
    now = time.monotonic()
    with _lock:
        if _cache["value"] is not None and now - _cache["at"] < CACHE_TTL_S:
            return _cache["value"]
    value = describe_workloads()
    with _lock:
        _cache.update(at=time.monotonic(), value=value)
    return value


def reset_cache() -> None:
    with _lock:
        _cache.update(at=0.0, value=None)


def pod_logs(
    pod: str,
    container: Optional[str] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
    previous: bool = False,
    fetch_text: Optional[Callable[[str, str, dict], str]] = None,
) -> dict[str, Any]:
    """The last LOG_TAIL_LINES lines of one pod in the Harvis namespace, redacted.

    The pod must be in our namespace (the path is built here, never taken from
    the caller), and its name and container are validated as DNS labels first.
    """
    env = os.environ if environ is None else environ
    mode, _ = hosting_mode(env)
    if mode != MODE_KUBERNETES:
        raise NodeListError("this Harvis is not running on Kubernetes")
    if not valid_name(pod) or (container and not valid_name(container)):
        raise NodeListError("that is not a valid pod or container name")
    ns = (env.get("HARVIS_K8S_NAMESPACE") or "").strip() or DEFAULT_NAMESPACE
    params: dict[str, Any] = {"tailLines": LOG_TAIL_LINES, "limitBytes": LOG_LIMIT_BYTES, "timestamps": "true"}
    if container:
        params["container"] = container
    if previous:
        params["previous"] = "true"
    path = f"/api/v1/namespaces/{ns}/pods/{pod}/log"
    if fetch_text is None:
        text = api_get(path, "read pod logs", params=params, as_text=True)
    else:
        text = fetch_text(path, "read pod logs", params)
    return {"pod": pod, "container": container, "previous": previous, "lines": redact(str(text or "")).splitlines()}
