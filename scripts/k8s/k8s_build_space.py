"""Host access the backend has in compose that Kubernetes mode withholds by default.

- /var/run/docker.sock is Build Space. A process that can ask Docker for a
  container with any bind mount owns the host, so a taken-over backend would
  own this machine. Left out unless the operator passes --build-space, together
  with the supplemental group that existed only to read the socket.
- A read-write bind of the host's /tmp becomes a per-pod emptyDir. The backend
  keeps its scratch files (spoken replies, temp uploads) and serves them itself,
  but no longer shares a directory with every other process on the node.
"""

import copy

DOCKER_SOCK = "/var/run/docker.sock"
ENV = "HARVIS_BUILD_SPACE_DOCKER"


def _bind_of(volume, path):
    return volume.get("type") == "bind" and str(volume.get("source", "")).rstrip("/") == path


def restrict(compose, build_space):
    """A copy of the rendered compose config with the host-level mounts removed or swapped."""
    out = copy.deepcopy(compose)
    for svc in (out.get("services") or {}).values():
        vols = svc.get("volumes")
        if not vols:
            continue
        had_socket = any(_bind_of(v, DOCKER_SOCK) for v in vols)
        kept = []
        for v in vols:
            if _bind_of(v, DOCKER_SOCK) and not build_space:
                continue
            if _bind_of(v, "/tmp") and not v.get("read_only"):
                v = {"type": "emptydir", "target": v["target"]}
            kept.append(v)
        svc["volumes"] = kept
        if had_socket and not build_space:
            svc.pop("group_add", None)
    return out
