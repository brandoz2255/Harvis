"""Container defaults every Harvis pod gets, applied after all objects exist.

- seccomp RuntimeDefault: Docker applies its default profile to every
  container; Kubernetes applies none unless asked. This is that parity.
- allowPrivilegeEscalation false: no image here needs setuid (Chromium runs
  with --no-sandbox), so a taken-over process cannot climb back to root.
- NET_RAW dropped: no raw sockets, so a pod cannot forge packets or spoof
  ARP on the node's network. Compose's own cap_drop/cap_add still win.

Privileged containers (the AMD-GPU Ollama) are left alone: the API server
rejects allowPrivilegeEscalation false next to privileged true.

The agent browser also gets an egress policy: public addresses only, so a page,
a redirect or a script on it cannot reach the router, the LAN or the pods next
to it. The backend already refuses a private URL typed into a chat; this is the
layer under it. ``--browser-allow-cidr`` opens a private range again.
"""
from __future__ import annotations

import ipaddress
import re

LABEL_APP = "app.kubernetes.io/name"
DROP = ["NET_RAW"]
BROWSER = "browser-runner"
PRIVATE = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
           "169.254.0.0/16", "127.0.0.0/8", "0.0.0.0/8", "224.0.0.0/4", "240.0.0.0/4")


def _pod_specs(objects):
    for o in objects:
        kind = o.get("kind")
        if kind == "Deployment":
            yield o, o["spec"]["template"]["spec"]
        elif kind == "CronJob":
            yield o, o["spec"]["jobTemplate"]["spec"]["template"]["spec"]


def _container(c, svc):
    sc = c.setdefault("securityContext", {})
    if sc.get("privileged"):
        return
    sc.setdefault("allowPrivilegeEscalation", False)
    caps = sc.setdefault("capabilities", {})
    added = {str(x).upper() for x in svc.get("cap_add") or []}
    drop = [str(x).upper() for x in svc.get("cap_drop") or []] or [d for d in DROP if d not in added]
    if added - {"ALL"}:
        caps.setdefault("add", sorted(added - {"ALL"}))
    if drop:
        caps.setdefault("drop", drop)


def apply(gen):
    by_app = {}
    for name, svc in gen.services.items():
        # compose_to_k8s.dns_name; importing it from here would be circular.
        by_app.setdefault(re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:63].rstrip("-"), svc)
    for o, spec in _pod_specs(gen.objects):
        app = ((o.get("metadata") or {}).get("labels") or {}).get(LABEL_APP, "")
        svc = by_app.get(app) or {}
        spec.setdefault("securityContext", {}).setdefault("seccompProfile", {"type": "RuntimeDefault"})
        for c in spec.get("containers", []) + spec.get("initContainers", []):
            _container(c, svc)


def browser_egress(gen):
    if BROWSER not in gen.services:
        return
    dns = {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
           "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}
    egress = [dns, {"to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": list(PRIVATE)}}]}]
    allowed = []
    for c in getattr(gen.o, "browser_allow_cidr", None) or []:
        try:
            allowed.append(str(ipaddress.IPv4Network(c, strict=False)))
        except ValueError:
            raise SystemExit(f"HARVIS_BROWSER_ALLOW_CIDRS: {c!r} is not an IPv4 range like 192.168.1.0/24")
    if allowed:
        egress.append({"to": [{"ipBlock": {"cidr": c}} for c in allowed]})
    gen.objects.append({
        "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
        "metadata": gen.meta(f"{BROWSER}-public-only"),
        "spec": {"podSelector": {"matchLabels": {LABEL_APP: BROWSER}}, "policyTypes": ["Egress"],
                 "egress": egress}})
