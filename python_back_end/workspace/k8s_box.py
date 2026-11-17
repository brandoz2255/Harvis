"""A chat's box as a Kubernetes pod, for installs where the backend has no Docker.

In Docker mode a box is a sibling container the backend starts through
/var/run/docker.sock (terminal_container._spawn_isolated). On Kubernetes the
backend gets no socket unless Build Space is on, and the installer refuses Build
Space on an internet-facing install, because a backend that can ask Docker for a
container owns the host. So here a box is a pod in its own namespace, created
through the API server with the backend's service account:

* The namespace enforces Pod Security "restricted": no privileged pods, no host
  paths, no host network, non-root, every capability dropped. A taken-over
  backend can start a box, never a pod that reaches the host.
* A deny-all NetworkPolicy covers every pod there: no ingress, no egress.
* The chat folders reach the pod through one PersistentVolumeClaim made by the
  installer (the backend may not create volumes); each box mounts only its own
  chat's folder via subPath.
* Commands run over the API server's pods/exec, so the box needs no open port.

The installer (scripts/k8s/k8s_boxes.py) creates the namespace, volume, RBAC and
policy, and sets the HARVIS_K8S_BOX_* variables read here.

Not covered yet, still Docker-only: the Terminal tab's interactive shell, app
previews (box_tunnel) and box web access through box-egress.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import json
import logging
import os
import re
import shlex
import ssl
import time
from typing import Callable, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

_CONTAINER = "box"
_PROFILE = "k8s-restricted-v1"
_READY_TIMEOUT_S = float(os.getenv("HARVIS_K8S_BOX_READY_TIMEOUT_S", "90"))
_IDLE_S = float(os.getenv("HARVIS_K8S_BOX_IDLE_S", "1800"))
_OUTPUT_CAP = int(os.getenv("HARVIS_TERMINAL_OUTPUT_CAP", "65536"))
# Waiting reasons that will not fix themselves; reported instead of waited out.
_FAIL_COOLDOWN_S = 60.0
_STUCK = {"ErrImageNeverPull", "ErrImagePull", "ImagePullBackOff", "InvalidImageName",
          "CreateContainerConfigError", "CreateContainerError", "CrashLoopBackOff"}


class BoxError(RuntimeError):
    """A reason the box could not be made or reached; safe to show."""


def enabled() -> bool:
    return (os.getenv("HARVIS_K8S_BOXES") or "").strip().lower() in ("1", "true", "yes", "on")


def _cfg() -> dict:
    return {
        "ns": os.getenv("HARVIS_K8S_BOX_NAMESPACE", "harvis-boxes"),
        "pvc": os.getenv("HARVIS_K8S_BOX_PVC", "harvis-box-sandboxes"),
        "root": os.path.realpath(os.getenv("HARVIS_K8S_BOX_ROOT")
                                 or os.getenv("HARVIS_SANDBOX_ROOT", "/data/artifacts/sandboxes")),
        "node": os.getenv("HARVIS_K8S_BOX_NODE", ""),
        "image": os.getenv("HARVIS_BUILD_RUNNER_IMAGE",
                           os.getenv("HARVIS_ADAPTIVE_REPO_SANDBOX_IMAGE", "harvis-repo-sandbox:local")),
        "mem": os.getenv("HARVIS_BUILD_RUNNER_MEM", "1024m"),
        "cpu": os.getenv("HARVIS_BUILD_RUNNER_CPUS", "1.0"),
        "disk": os.getenv("HARVIS_BUILD_RUNNER_DISK", "10G").strip(),
    }


def pod_name(key: str) -> str:
    """A DNS-1123 pod name for a runner key; a digest keeps two long keys apart."""
    safe = re.sub(r"[^a-z0-9-]+", "-", key.lower()).strip("-")[:40].strip("-")
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"harvis-box-{safe}-{digest}" if safe else f"harvis-box-{digest}"


def subpath_of(workspace_path: str, root: Optional[str] = None) -> str:
    """The chat folder relative to the volume root. Refuses anything outside it, so a
    box can never be pointed at another part of the volume."""
    root = root or _cfg()["root"]
    target = os.path.realpath(workspace_path)
    if not (target + "/").startswith(root.rstrip("/") + "/") or target == root:
        raise BoxError(f"{workspace_path!r} is not a chat folder under {root!r}; "
                       "on Kubernetes only chat boxes can run commands")
    return os.path.relpath(target, root)


def _k8s_quantity(value: str) -> str:
    """Docker-style sizes (1024m, 10G) as Kubernetes quantities (1024Mi, 10Gi)."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgtKMGT]?)[bB]?\s*", value or "")
    if not m:
        return value
    num, unit = m.groups()
    return num + ({"k": "Ki", "m": "Mi", "g": "Gi", "t": "Ti"}.get(unit.lower(), "") if unit else "")


def pod_manifest(key: str, sub: str, cfg: Optional[dict] = None) -> dict:
    """The box pod. Every field Pod Security "restricted" checks is set explicitly,
    so the pod is admitted on its own merits, not only because the namespace lets it."""
    cfg = cfg or _cfg()
    limits = {"memory": _k8s_quantity(cfg["mem"]), "cpu": str(cfg["cpu"])}
    if cfg["disk"]:
        limits["ephemeral-storage"] = _k8s_quantity(cfg["disk"])
    spec = {
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "restartPolicy": "Always",
        "terminationGracePeriodSeconds": 2,
        "securityContext": {"runAsNonRoot": True, "runAsUser": 1001, "runAsGroup": 1001,
                            "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{
            "name": _CONTAINER,
            "image": cfg["image"],
            # The image is imported into k3s by the installer and exists nowhere else:
            # never try a registry (it would ask Docker Hub for harvis-repo-sandbox).
            "imagePullPolicy": "Never",
            "command": ["sh", "-c", "exec tail -f /dev/null"],
            "workingDir": "/workspace",
            "env": [{"name": "HOME", "value": "/tmp"}],
            "securityContext": {"allowPrivilegeEscalation": False, "privileged": False,
                                "capabilities": {"drop": ["ALL"]}},
            "resources": {"limits": limits,
                          "requests": {"memory": "64Mi", "cpu": "50m"}},
            "volumeMounts": [{"name": "chat", "mountPath": "/workspace", "subPath": sub}],
        }],
        "volumes": [{"name": "chat", "persistentVolumeClaim": {"claimName": cfg["pvc"]}}],
    }
    if cfg["node"]:
        spec["nodeSelector"] = {"kubernetes.io/hostname": cfg["node"]}
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": pod_name(key), "namespace": cfg["ns"],
                     "labels": {"app.kubernetes.io/managed-by": "harvis-backend", "harvis.role": "box"},
                     "annotations": {"harvis.box/key": key, "harvis.box/subpath": sub,
                                     "harvis.box/profile": _PROFILE, "harvis.box/image": cfg["image"]}},
        "spec": spec,
    }


# ── API server access ───────────────────────────────────────────────────────
def _api_base() -> str:
    host = os.getenv("KUBERNETES_SERVICE_HOST")
    port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
    if not host:
        raise BoxError("not running in a Kubernetes pod (no KUBERNETES_SERVICE_HOST)")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"https://{host}:{port}"


def _token() -> str:
    # Re-read every call: projected service-account tokens rotate.
    try:
        with open(TOKEN_PATH, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as exc:
        raise BoxError(f"no service-account token ({exc.__class__.__name__})") from None


def _ssl() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=CA_PATH)


async def _api(method: str, path: str, body: Optional[dict] = None) -> tuple[int, dict]:
    """(status, json) for one REST call. Error text is composed here: the token only
    ever sits in the header, never in a message."""
    try:
        async with httpx.AsyncClient(verify=_ssl(), timeout=15.0) as client:
            r = await client.request(method, _api_base() + path, json=body,
                                     headers={"Authorization": f"Bearer {_token()}"})
    except httpx.HTTPError as exc:
        raise BoxError(f"Kubernetes API unreachable ({exc.__class__.__name__})") from None
    try:
        data = r.json()
    except ValueError:
        data = {}
    return r.status_code, data if isinstance(data, dict) else {}


def _pod_path(ns: str, name: str = "") -> str:
    return f"/api/v1/namespaces/{ns}/pods" + (f"/{name}" if name else "")


def _refusal(status: int, data: dict, doing: str) -> BoxError:
    reason = str(data.get("message") or data.get("reason") or "")[:300]
    if status == 403:
        return BoxError(f"{doing}: forbidden ({reason}) — re-run ./install.sh --k8s to grant the box RBAC")
    return BoxError(f"{doing}: HTTP {status} {reason}".strip())


def _ready(pod: dict) -> bool:
    st = pod.get("status") or {}
    return st.get("phase") == "Running" and any(
        c.get("name") == _CONTAINER and c.get("ready") for c in st.get("containerStatuses") or [])


def _explain(reason: str) -> str:
    if "ErrImageNeverPull" in reason or "ErrImagePull" in reason or "ImagePullBackOff" in reason:
        return ("the box image is not loaded into Kubernetes on this machine — re-run "
                "./install.sh --k8s (it imports harvis-repo-sandbox:local)")
    return reason


def _stuck_reason(pod: dict) -> Optional[str]:
    st = pod.get("status") or {}
    if st.get("phase") in ("Failed", "Succeeded"):
        return f"box pod ended ({st.get('phase')}: {st.get('reason') or st.get('message') or 'no reason'})"
    for c in st.get("containerStatuses") or []:
        waiting = (c.get("state") or {}).get("waiting") or {}
        if waiting.get("reason") in _STUCK:
            return f"box pod cannot start: {waiting['reason']} {waiting.get('message', '')[:200]}".strip()
    for cond in st.get("conditions") or []:
        if cond.get("type") == "PodScheduled" and cond.get("status") == "False" and cond.get("reason") == "Unschedulable":
            return f"box pod cannot be scheduled: {cond.get('message', '')[:200]}"
    return None


# ── Lifecycle ───────────────────────────────────────────────────────────────
_lock = asyncio.Lock()
_last_used: dict[str, float] = {}
# A box that just failed to start is not retried for a minute: the UI warms the box on
# every poll, and a missing image turned into hundreds of pod create/delete rounds an hour.
_failed: dict[str, tuple[float, str]] = {}


async def _delete(ns: str, name: str) -> bool:
    status, data = await _api("DELETE", _pod_path(ns, name), {"gracePeriodSeconds": 0})
    if status == 404:
        return False
    if status >= 300:
        raise _refusal(status, data, "deleting the box")
    for _ in range(60):  # a new pod of the same name waits for the old one to go
        status, _d = await _api("GET", _pod_path(ns, name))
        if status == 404:
            return True
        await asyncio.sleep(0.5)
    raise BoxError("the old box pod did not go away in 30s")


async def ensure(key: str, workspace_path: str) -> str:
    """The running box pod for ``key`` (created or replaced as needed); its name."""
    cfg = _cfg()
    if not os.path.isdir(workspace_path):
        raise BoxError(f"chat folder {workspace_path!r} does not exist")
    sub = subpath_of(workspace_path, cfg["root"])
    name = pod_name(key)
    last = _failed.get(name)
    if last and time.time() - last[0] < _FAIL_COOLDOWN_S:
        raise BoxError(last[1])
    try:
        made = await _ensure(cfg, key, name, sub)
        _failed.pop(name, None)
        return made
    except BoxError as exc:
        _failed[name] = (time.time(), str(exc))
        raise


async def _ensure(cfg: dict, key: str, name: str, sub: str) -> str:
    async with _lock:
        status, pod = await _api("GET", _pod_path(cfg["ns"], name))
        if status == 200:
            ann = (pod.get("metadata") or {}).get("annotations") or {}
            same = (ann.get("harvis.box/subpath") == sub and ann.get("harvis.box/profile") == _PROFILE
                    and ann.get("harvis.box/image") == cfg["image"])
            if same and _stuck_reason(pod) is None and pod.get("metadata", {}).get("deletionTimestamp") is None:
                if not _ready(pod):
                    await _wait_ready(cfg["ns"], name)
                _last_used[name] = time.time()
                return name
            await _delete(cfg["ns"], name)
        elif status != 404:
            raise _refusal(status, pod, "looking up the box")
        status, data = await _api("POST", _pod_path(cfg["ns"]), pod_manifest(key, sub, cfg))
        if status >= 300 and status != 409:
            raise _refusal(status, data, "creating the box")
        logger.info("[k8s-box:%s] created pod %s/%s (image=%s sub=%s)", key, cfg["ns"], name, cfg["image"], sub)
        await _wait_ready(cfg["ns"], name)
        _last_used[name] = time.time()
        return name


async def _wait_ready(ns: str, name: str) -> None:
    deadline = time.time() + _READY_TIMEOUT_S
    while True:
        status, pod = await _api("GET", _pod_path(ns, name))
        if status == 200:
            if _ready(pod):
                return
            stuck = _stuck_reason(pod)
            if stuck:
                raise BoxError(_explain(stuck))
        if time.time() > deadline:
            raise BoxError(f"the box pod was not ready after {int(_READY_TIMEOUT_S)}s")
        await asyncio.sleep(1.0)


async def drop(key: str) -> bool:
    """Delete the box pod (the chat folder stays). True when one was removed."""
    name = pod_name(key)
    _last_used.pop(name, None)
    _failed.pop(name, None)  # a deleted box gets a fresh try
    async with _lock:
        return await _delete(_cfg()["ns"], name)


async def sweep_idle(idle_s: float = _IDLE_S) -> int:
    """Delete boxes unused for ``idle_s``. A box this process never used (made before a
    restart) is judged by its age. The next command recreates it, folder intact."""
    ns = _cfg()["ns"]
    status, data = await _api("GET", _pod_path(ns) + "?labelSelector=harvis.role%3Dbox")
    if status != 200:
        return 0
    now, removed = time.time(), 0
    for pod in data.get("items") or []:
        meta = pod.get("metadata") or {}
        name = meta.get("name", "")
        last = _last_used.get(name)
        if last is None:
            created = meta.get("creationTimestamp") or ""
            try:
                last = calendar.timegm(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ"))
            except ValueError:
                continue
        if now - last > idle_s:
            try:
                async with _lock:
                    removed += bool(await _delete(ns, name))
                _last_used.pop(name, None)
            except BoxError as exc:
                logger.warning("[k8s-box] idle sweep could not delete %s: %s", name, exc)
    return removed


async def probe() -> tuple[bool, str]:
    """(ok, detail) — can the backend list pods in the box namespace?"""
    ns = _cfg()["ns"]
    try:
        status, data = await _api("GET", _pod_path(ns) + "?limit=1")
    except BoxError as exc:
        return False, str(exc)
    if status == 200:
        return True, f"Kubernetes boxes in namespace {ns}"
    return False, str(_refusal(status, data, "listing boxes"))


# ── Exec over the API server (pods/exec, v4.channel.k8s.io) ──────────────────
def _exec_path(ns: str, name: str, argv: list[str]) -> str:
    q = "&".join(["container=" + _CONTAINER, "stdout=true", "stderr=true", "stdin=false", "tty=false"]
                 + ["command=" + quote(a, safe="") for a in argv])
    return f"/api/v1/namespaces/{ns}/pods/{name}/exec?{q}"


def exit_code_of(status_json: str) -> int:
    """The exit code in a v4 error-channel Status (0 for Success)."""
    try:
        st = json.loads(status_json or "{}")
    except ValueError:
        return -1
    if st.get("status") == "Success":
        return 0
    for cause in ((st.get("details") or {}).get("causes") or []):
        if cause.get("reason") == "ExitCode":
            try:
                return int(cause.get("message"))
            except (TypeError, ValueError):
                break
    return -1


async def _run(ns: str, name: str, argv: list[str], timeout: float,
               sink: Optional[Callable[[str], None]] = None) -> tuple[int, bytes, bytes, str]:
    from websockets.asyncio.client import connect

    url = _api_base().replace("https://", "wss://", 1) + _exec_path(ns, name, argv)
    out, err, status = bytearray(), bytearray(), ""
    async with connect(url, ssl=_ssl(), subprotocols=["v4.channel.k8s.io"],
                       additional_headers={"Authorization": f"Bearer {_token()}"},
                       max_size=None, open_timeout=15) as ws:
        async def pump() -> None:
            nonlocal status
            async for msg in ws:
                if isinstance(msg, str):
                    msg = msg.encode()
                if not msg:
                    continue
                chan, data = msg[0], msg[1:]
                if chan == 1:
                    out.extend(data)
                elif chan == 2:
                    err.extend(data)
                elif chan == 3:
                    status += data.decode("utf-8", "replace")
                    continue
                else:
                    continue
                if sink is not None and data:
                    sink(data.decode("utf-8", "replace"))
        await asyncio.wait_for(pump(), timeout)
    return exit_code_of(status), bytes(out), bytes(err), status


def _cap(text: str, which: str) -> tuple[str, bool]:
    if len(text) > _OUTPUT_CAP:
        return text[:_OUTPUT_CAP] + f"\n…[{which} truncated at {_OUTPUT_CAP} bytes]", True
    return text, False


async def exec_isolated(key: str, workspace_path: str, cmd: str, timeout: float,
                        workdir: str = "/workspace",
                        sink: Optional[Callable[[str], None]] = None) -> dict:
    """terminal_container.exec_isolated's contract on a box pod: same result shape,
    and it raises on any failure to reach the box (callers refuse, never fall back)."""
    name = await ensure(key, workspace_path)
    ns = _cfg()["ns"]
    wrapped = (f"cd {shlex.quote(workdir)} 2>/dev/null || cd /workspace; "
               f"exec timeout --kill-after=2 {int(timeout)}s sh -c {shlex.quote(cmd)}")
    t0 = time.time()
    try:
        code, out_b, err_b, status = await _run(ns, name, ["sh", "-c", wrapped], timeout + 15, sink)
    except asyncio.TimeoutError:
        code, out_b, err_b, status = 124, b"", b"[the box did not answer in time]", ""
    except OSError as exc:
        raise BoxError(f"cannot reach the box over the API server ({exc.__class__.__name__})") from None
    except Exception as exc:  # websockets handshake refusals carry the HTTP status
        resp = getattr(exc, "response", None)
        code_http = getattr(resp, "status_code", None)
        if code_http == 403:
            raise BoxError("running a command in the box is forbidden — re-run ./install.sh --k8s "
                           "to grant the box RBAC") from None
        raise BoxError(f"cannot exec in the box ({exc.__class__.__name__}"
                       + (f", HTTP {code_http}" if code_http else "") + ")") from None
    _last_used[name] = time.time()
    stdout, t1 = _cap(out_b.decode("utf-8", "replace"), "stdout")
    stderr, t2 = _cap(err_b.decode("utf-8", "replace"), "stderr")
    if code == -1 and status and '"Failure"' in status and not stderr:
        stderr = status[:500]
    return {"stdout": stdout, "stderr": stderr, "exit_code": code,
            "duration_ms": int((time.time() - t0) * 1000), "truncated": t1 or t2, "container": name}
