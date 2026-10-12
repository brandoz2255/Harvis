"""The Cloudflare Tunnel in Kubernetes (HARVIS_EXPOSURE=lan+tunnel).

compose_to_k8s.py renders cloudflared from compose's `tunnel` profile like any
other service; this module tightens what Docker's tunnel-edge network gave it:

- cloudflared may open exactly two things: nginx's tunnel entrance (8081) and
  the internet on Cloudflare's ports (7844, and 443). Not the LAN, not the node, not the model
  server or the database, so a public hostname routed anywhere else finds
  nothing, here as in Docker.
- Nothing may open cloudflared.
- nginx's 8081 takes connections from cloudflared only; 80 and 443 stay open
  to the LoadBalancer as before. 8081 is never a LoadBalancer port.

Under the network lock (HARVIS_TUNNEL_NETWORKS) it is rendered with 0 replicas
and scripts/tunnel-guard.sh scales it up only on an allowed network.
"""

NAME = "cloudflared"
APP = "app.kubernetes.io/name"
METRICS_PORT = 2000
EDGE_PORT = 7844
TUNNEL_PORT = 8081
# Everything that is not the internet: RFC 1918, carrier-grade NAT (Tailscale),
# link-local and loopback. The cluster's own 10.42/10.43 ranges are inside 10/8.
PRIVATE = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
           "169.254.0.0/16", "127.0.0.0/8")

_FROM_CLOUDFLARED = {"podSelector": {"matchLabels": {APP: NAME}}}


def nginx_ingress():
    """nginx's ingress rules: the site for everyone, the tunnel entrance for cloudflared."""
    return [{"ports": [{"protocol": "TCP", "port": 80}, {"protocol": "TCP", "port": 443}]},
            {"from": [_FROM_CLOUDFLARED], "ports": [{"protocol": "TCP", "port": TUNNEL_PORT}]}]


def _deployment(gen):
    for o in gen.objects:
        if o.get("kind") == "Deployment" and o["metadata"]["name"] == NAME:
            return o
    return None


def _policy(gen, name, spec):
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": gen.meta(name, {APP: NAME}), "spec": spec}


def _harden(dep, replicas):
    dep["spec"]["replicas"] = replicas
    # It holds no data, so a new pod may start before the old one goes.
    dep["spec"]["strategy"] = {"type": "RollingUpdate",
                               "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}}
    pod = dep["spec"]["template"]["spec"]
    # The network lock stops it by scaling to 0; it must not keep serving for
    # the default 30 s while it drains.
    pod["terminationGracePeriodSeconds"] = 2
    c = pod["containers"][0]
    args = list(c.get("args") or [])
    if args[:1] == ["tunnel"] and "--metrics" not in args:
        args[1:1] = ["--metrics", f"0.0.0.0:{METRICS_PORT}"]
    c["args"] = args
    # /ready answers 200 only while a connection to Cloudflare is up.
    ready = {"httpGet": {"port": METRICS_PORT, "path": "/ready"}, "timeoutSeconds": 3}
    c["readinessProbe"] = {**ready, "periodSeconds": 10, "failureThreshold": 3}
    c["livenessProbe"] = {**ready, "initialDelaySeconds": 30, "periodSeconds": 30, "failureThreshold": 6}
    c.pop("startupProbe", None)
    # The image's user is the name "nonroot", which runAsNonRoot cannot check.
    c["securityContext"] = {"runAsUser": 65532, "runAsGroup": 65532, "runAsNonRoot": True,
                            "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]}}


def add(gen):
    dep = _deployment(gen)
    if dep is None:
        return
    _harden(dep, gen.o.tunnel_replicas)
    sel = {"matchLabels": {APP: NAME}}
    dns = {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
           "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}
    gen.objects += [
        _policy(gen, f"{NAME}-no-ingress", {"podSelector": sel, "policyTypes": ["Ingress"], "ingress": []}),
        _policy(gen, f"{NAME}-egress", {"podSelector": sel, "policyTypes": ["Egress"], "egress": [
            {"to": [{"podSelector": {"matchLabels": {APP: "nginx"}}}],
             "ports": [{"protocol": "TCP", "port": TUNNEL_PORT}]},
            dns,
            {"to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": list(PRIVATE)}}],
             # 443 is Cloudflare's fallback for its API; nothing else is reachable.
             "ports": [{"protocol": "TCP", "port": EDGE_PORT}, {"protocol": "UDP", "port": EDGE_PORT},
                       {"protocol": "TCP", "port": 443}]},
        ]}),
    ]
