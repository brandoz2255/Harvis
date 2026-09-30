"""In-cluster node listing for the hosting capability.

Talks to the API server the way every pod can: service-account token and CA
from the projected secret, KUBERNETES_SERVICE_HOST/PORT from the environment.
Results — success or failure — are cached for 30 s so the settings page polling
does not turn into a stream of API calls, and a broken RBAC binding does not
get retried on every click.

Error text is composed here, never lifted from the response: the only place the
token exists is the Authorization header, and it must not leak into a message a
caller could see or a log line could keep.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional

import httpx

TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

CACHE_TTL_S = 30.0
_TIMEOUT_S = 3.0

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "nodes": None, "error": None}


class NodeListError(RuntimeError):
    """A plain-English reason the node listing failed; safe to show to a user."""


def _read_secret(path: str, what: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = fh.read().strip()
    except OSError as exc:
        raise NodeListError(
            f"no service-account {what} at {path} ({exc.__class__.__name__})"
        ) from None
    if not value:
        raise NodeListError(f"service-account {what} at {path} is empty")
    return value


def list_nodes_uncached(
    environ: Optional[dict[str, str]] = None,
    *,
    token_path: str = TOKEN_PATH,
    ca_path: str = CA_PATH,
    transport: Optional[httpx.BaseTransport] = None,
) -> list[dict[str, Any]]:
    """GET /api/v1/nodes as the pod's service account. Raises NodeListError only."""
    env = os.environ if environ is None else environ
    host = (env.get("KUBERNETES_SERVICE_HOST") or "").strip()
    port = (env.get("KUBERNETES_SERVICE_PORT") or "443").strip()
    if not host:
        raise NodeListError("KUBERNETES_SERVICE_HOST is not set — not running inside a cluster")

    token = _read_secret(token_path, "token")
    verify: Any = ca_path if os.path.exists(ca_path) else True
    url = f"https://{host}:{port}/api/v1/nodes"
    api = f"{host}:{port}"

    try:
        with httpx.Client(timeout=_TIMEOUT_S, verify=verify, transport=transport) as hc:
            r = hc.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException:
        raise NodeListError(f"the Kubernetes API at {api} did not answer within {_TIMEOUT_S:g}s") from None
    except httpx.HTTPError as exc:
        raise NodeListError(
            f"could not reach the Kubernetes API at {api} ({exc.__class__.__name__})"
        ) from None
    finally:
        del token

    if r.status_code in (401, 403):
        raise NodeListError(
            f"the Kubernetes API answered HTTP {r.status_code}: the backend's service "
            "account is not allowed to list nodes (re-run ./install.sh --k8s to "
            "restore its RBAC binding)"
        )
    if r.status_code != 200:
        raise NodeListError(f"the Kubernetes API answered HTTP {r.status_code} for /api/v1/nodes")

    try:
        items = (r.json() or {}).get("items")
    except ValueError:
        raise NodeListError("the Kubernetes API returned a non-JSON node list") from None
    if not isinstance(items, list):
        raise NodeListError("the Kubernetes API returned a node list without 'items'")
    return items


def fetch_cluster_nodes() -> list[dict[str, Any]]:
    """Cached front for ``list_nodes_uncached`` — the default fetcher for describe_hosting."""
    now = time.monotonic()
    with _lock:
        if now - _cache["at"] < CACHE_TTL_S:
            if _cache["error"] is not None:
                raise NodeListError(_cache["error"])
            return list(_cache["nodes"] or [])

    try:
        nodes = list_nodes_uncached()
    except NodeListError as exc:
        with _lock:
            _cache.update(at=time.monotonic(), nodes=None, error=str(exc))
        raise
    except Exception as exc:  # noqa: BLE001 — e.g. ssl errors from a bad ca.crt
        # Same cache and the same scrubbing as the expected failures: a raw
        # exception text is not something a caller should see, and an error
        # that skips the cache is retried on every poll.
        message = f"listing nodes failed ({exc.__class__.__name__})"
        with _lock:
            _cache.update(at=time.monotonic(), nodes=None, error=message)
        raise NodeListError(message) from None
    with _lock:
        _cache.update(at=time.monotonic(), nodes=nodes, error=None)
    return nodes


def reset_cache() -> None:
    with _lock:
        _cache.update(at=0.0, nodes=None, error=None)
