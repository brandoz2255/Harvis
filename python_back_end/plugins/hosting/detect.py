"""Hosting-mode detection and the /api/capabilities/hosting payload.

Harvis runs either under docker compose (the default) or inside a k3s cluster
that ``./install.sh --k8s`` stands up. The backend cannot see which one launched
it except through the environment, so everything here is a pure function of an
``environ`` mapping plus an injectable node lister — unit-testable with no
cluster and no socket.

Mode precedence: HARVIS_HOSTING_MODE (operator override) wins over the
KUBERNETES_SERVICE_HOST that every in-cluster pod is given, which wins over the
docker default.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Optional

MODE_DOCKER = "docker"
MODE_KUBERNETES = "kubernetes"

DEFAULT_NAMESPACE = "harvis"
DOCKER_SOCKET = "/var/run/docker.sock"

# What the operator runs from the repo root, on the host. Mirrors the notebooks
# capability: the backend cannot run the installer itself, so it hands over the
# exact command instead of a button that pretends.
COMMANDS = {
    "enable": "./install.sh --k8s",
    "disable": "./install.sh --k8s-off",
    "status": "./install.sh --k8s-status",
    "join": "./install.sh --k8s-join-command",
}

_OVERRIDE_ALIASES = {
    "kubernetes": MODE_KUBERNETES,
    "k8s": MODE_KUBERNETES,
    "k3s": MODE_KUBERNETES,
    "docker": MODE_DOCKER,
    "compose": MODE_DOCKER,
}

NodeFetcher = Callable[[], list[dict[str, Any]]]


def hosting_mode(environ: Optional[Mapping[str, str]] = None) -> tuple[str, str]:
    """Return ``(mode, detected_by)`` — the one place that decides docker vs k8s.

    An unrecognised HARVIS_HOSTING_MODE value is ignored rather than trusted, so a
    typo falls through to cluster detection instead of hiding the cluster.
    """
    env = os.environ if environ is None else environ
    override = _OVERRIDE_ALIASES.get((env.get("HARVIS_HOSTING_MODE") or "").strip().lower())
    if override is not None:
        return override, "override"
    if (env.get("KUBERNETES_SERVICE_HOST") or "").strip():
        return MODE_KUBERNETES, "cluster"
    return MODE_DOCKER, "default"


def profile_not_enabled_reason(profile: str, environ: Optional[Mapping[str, str]] = None) -> str:
    """Why a profile-gated service is absent, worded for where Harvis is running.

    Under compose the fix is turning the profile on; under k8s the profile still
    selects what gets deployed, but the installer must be re-run for it to land.
    The docker wording is load-bearing — the installer parses health output —
    so it is kept byte-for-byte.
    """
    mode, _ = hosting_mode(environ)
    if mode == MODE_KUBERNETES:
        return (
            f"not deployed in this cluster — add '{profile}' to COMPOSE_PROFILES "
            "in .env and re-run ./install.sh --k8s"
        )
    return f"compose profile '{profile}' is not enabled"


# ─── Node parsing ---------------------------------------------------------------

_ROLE_PREFIX = "node-role.kubernetes.io/"

_BINARY_UNITS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
}


def _quantity_to_bytes(raw: Any) -> float:
    """Parse a Kubernetes memory quantity ("16384532Ki", "8Gi", "1000000")."""
    text = str(raw or "").strip()
    for suffix, factor in _BINARY_UNITS.items():
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * factor
    return float(text or 0)


def _to_int(raw: Any) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


def parse_node(node: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce one ``/api/v1/nodes`` item to the fields the UI shows.

    Every lookup is defensive: a node object from an older or stripped-down
    kubelet must never make the whole listing fail.
    """
    metadata = node.get("metadata") or {}
    status = node.get("status") or {}
    labels = metadata.get("labels") or {}
    allocatable = status.get("allocatable") or {}
    capacity = status.get("capacity") or {}
    info = status.get("nodeInfo") or {}

    ready = any(
        c.get("type") == "Ready" and c.get("status") == "True"
        for c in (status.get("conditions") or [])
    )
    roles = sorted(
        key[len(_ROLE_PREFIX):]
        for key in labels
        if key.startswith(_ROLE_PREFIX) and key[len(_ROLE_PREFIX):]
    )
    try:
        memory_gib = round(_quantity_to_bytes(capacity.get("memory")) / 1024**3, 1)
    except ValueError:
        memory_gib = 0.0

    return {
        "name": str(metadata.get("name") or ""),
        "ready": ready,
        "roles": roles,
        "gpus": _to_int(allocatable.get("nvidia.com/gpu", 0)),
        "cpu": str(capacity.get("cpu") or ""),
        "memory_gib": memory_gib,
        "version": str(info.get("kubeletVersion") or ""),
    }


# ─── Payload --------------------------------------------------------------------


def describe_hosting(
    environ: Optional[Mapping[str, str]] = None,
    fetch_nodes: Optional[NodeFetcher] = None,
    *,
    docker_socket_path: str = DOCKER_SOCKET,
) -> dict[str, Any]:
    """Build the /api/capabilities/hosting payload. Never raises.

    ``fetch_nodes`` returns raw ``/api/v1/nodes`` items or raises; the default
    is the cached in-cluster lister from ``cluster.py``. Its exception text is
    surfaced as ``nodes_error`` only after the fetcher has scrubbed it — the
    service-account token must never reach a caller.
    """
    env = os.environ if environ is None else environ
    mode, detected_by = hosting_mode(env)

    nodes: list[dict[str, Any]] = []
    nodes_error: Optional[str] = None
    namespace: Optional[str] = None

    if mode == MODE_KUBERNETES:
        namespace = (env.get("HARVIS_K8S_NAMESPACE") or "").strip() or DEFAULT_NAMESPACE
        if fetch_nodes is None:
            from .cluster import fetch_cluster_nodes

            fetch_nodes = fetch_cluster_nodes
        try:
            nodes = [parse_node(n) for n in (fetch_nodes() or [])]
        except Exception as exc:  # noqa: BLE001 — the contract is "never raise"
            nodes = []
            nodes_error = str(exc)[:300] or "listing nodes failed"

    if mode == MODE_KUBERNETES:
        gpu_count = sum(n["gpus"] for n in nodes)
        gpu = {"available": gpu_count > 0, "count": gpu_count}
    else:
        # Compose cannot count devices; "nvidia" only says the runtime is wired,
        # so count 0 here means unknown rather than none.
        nvidia = (env.get("HARVIS_GPU_RUNTIME") or "").strip().lower() == "nvidia"
        gpu = {"available": nvidia, "count": 0}

    lan_url = (env.get("HARVIS_LAN_MODELS_URL") or "").strip()

    return {
        "mode": mode,
        "detected_by": detected_by,
        "namespace": namespace,
        "nodes": nodes,
        "nodes_error": nodes_error,
        "gpu": gpu,
        "lan_models": {"enabled": bool(lan_url), "url": lan_url or None},
        "docker_socket": os.path.exists(docker_socket_path),
        "commands": dict(COMMANDS),
    }
