"""Small builders shared by the Kubernetes-only modules (k8s_extras, k8s_models)."""

import re

NET_PREFIX = "harvis.net/"

# Local keeps the visitor's own address (otherwise nginx sees every visitor as
# 10.42.0.1 and a per-visitor rate limit is one bucket for everyone). With no
# NodePorts the port opens only where ServiceLB listens, not 30000-32767 on every
# node. Both checked on k3s 1.36 ServiceLB, 2026-10-09.
LB_LOCAL = {"externalTrafficPolicy": "Local", "allocateLoadBalancerNodePorts": False}


def probes_from_check(check, start=0):
    """readiness / liveness / startup from one probe body (exec, tcpSocket or httpGet)."""
    out = {"readinessProbe": {**check, "periodSeconds": 10, "failureThreshold": 3},
           "livenessProbe": {**check, "periodSeconds": 30, "failureThreshold": 6}}
    if start:
        out["startupProbe"] = {**check, "periodSeconds": 5, "failureThreshold": max(12, (2 * start + 4) // 5)}
    return out


def net_label(net):
    return NET_PREFIX + re.sub(r"[^A-Za-z0-9_.-]", "-", net)[:63].strip("-.")


def policy(gen, name, selector, ingress=None, egress=None):
    spec = {"podSelector": selector, "policyTypes": []}
    if ingress is not None:
        spec["policyTypes"].append("Ingress")
        spec["ingress"] = ingress
    if egress is not None:
        spec["policyTypes"].append("Egress")
        spec["egress"] = egress
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": gen.meta(name[:63]), "spec": spec}


QUANTITY_UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40,
                  "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "m": 1e-3, "": 1}


def quantity(value):
    """'10161480Ki' / '6Gi' / '3500m' / '4' -> bytes or cores; None if unreadable."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([KMGT]i|[kMGTm]?)\s*", str(value or ""))
    return float(m.group(1)) * QUANTITY_UNITS[m.group(2)] if m else None
