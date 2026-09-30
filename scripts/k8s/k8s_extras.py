"""Kubernetes-only pieces that have no line in docker-compose.yaml.

compose_to_k8s.py maps what compose says; this module adds what Kubernetes
needs on top: nginx's resolver, the public LoadBalancer ports, NetworkPolicies
standing in for compose networks, the backend's read-only view of the nodes,
the in-cluster Ollama, and the LAN models endpoint.
"""

import hashlib
import os
import re
import stat

NET_PREFIX = "harvis.net/"
NGINX_CONF_TARGETS = {"/etc/nginx/nginx.conf": "nginx.conf", "/etc/nginx/harvis.conf": "harvis.conf"}
BACKEND_SA = "harvis-backend"
LAN_PROXY = "lan-models"

# The only model-server routes the LAN endpoint forwards. Everything else —
# pulling, deleting, copying, pushing or creating models — is refused, so a
# neighbour can use this machine's models but cannot change them.
LAN_ALLOWED = (
    "/v1/chat/completions", "/v1/completions", "/v1/models", "/v1/embeddings",
    "/api/chat", "/api/generate", "/api/tags", "/api/show", "/api/embed",
    "/api/embeddings", "/api/version",
)


def net_label(net):
    return NET_PREFIX + re.sub(r"[^A-Za-z0-9_.-]", "-", net)[:63].strip("-.")


def bind_host_path_type(path, target):
    """Choose the hostPath type from what is actually on this host right now."""
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return "DirectoryOrCreate"
    if stat.S_ISSOCK(mode):
        return "Socket"
    if stat.S_ISREG(mode):
        return "File"
    return "Directory"


# ── nginx ───────────────────────────────────────────────────────────────────
def nginx_conf_data(gen):
    """nginx.conf + harvis.conf, patched for cluster DNS.

    nginx's resolver ignores the pod's search domains, so short names like
    `backend` that Docker DNS answered must become full cluster names here.
    """
    if getattr(gen, "_nginx_conf", None) is not None:
        return gen._nginx_conf
    with open(os.path.join(gen.o.repo, "nginx.conf")) as fh:
        main = fh.read()
    with open(os.path.join(gen.o.repo, "nginx-harvis.conf")) as fh:
        harvis = fh.read()
    main, n = re.subn(r"resolver\s+127\.0\.0\.11\b[^;]*;",
                      f"resolver {gen.o.dns_ip} valid=10s ipv6=off;", main)
    if n != 1:
        raise SystemExit("nginx.conf: expected exactly one `resolver 127.0.0.11` line to patch")

    def to_fqdn(m):
        return f"{m.group(1)}http://{gen.fqdn(m.group(2))}:{m.group(3)};"

    harvis, n = re.subn(r"(set\s+\$\w+\s+)http://([a-z0-9-]+):(\d+);", to_fqdn, harvis)
    if n == 0:
        raise SystemExit("nginx-harvis.conf: no `set $x_upstream http://name:port;` lines found")
    gen._nginx_conf = {"nginx.conf": main, "harvis.conf": harvis}
    return gen._nginx_conf


def config_override(gen, name, target):
    """Swap nginx's two config bind mounts for a patched ConfigMap."""
    if name != "nginx" or target not in NGINX_CONF_TARGETS:
        return None
    vol = {"name": "nginx-conf", "configMap": {"name": "nginx-conf"}}
    return [vol], {"name": "nginx-conf", "mountPath": target,
                   "subPath": NGINX_CONF_TARGETS[target], "readOnly": True}


# ── per-service tweaks ──────────────────────────────────────────────────────
def extra_env(gen, name):
    if name != "backend":
        return {}
    env = {"HARVIS_HOSTING_MODE": "kubernetes", "HARVIS_K8S_NAMESPACE": gen.ns}
    if gen.o.lan_models_port and gen.o.ollama_image:
        env["HARVIS_LAN_MODELS_URL"] = gen.o.lan_models_url
        env["HARVIS_LAN_MODELS_PORT"] = str(gen.o.lan_models_port)
    return env


def host_aliases(gen, svc):
    names = []
    for entry in svc.get("extra_hosts") or []:
        host, _, ip = str(entry).replace("=", ":", 1).partition(":")
        if ip == "host-gateway":
            names.append(host)
    return [{"ip": gen.o.node_ip, "hostnames": names}] if names else []


def config_hash(gen, name, svc):
    """Changes to a Secret or ConfigMap do not restart pods; this annotation does."""
    h = hashlib.sha256()
    for k, v in sorted((svc.get("environment") or {}).items()):
        h.update(f"{k}={v}\n".encode())
    for k, v in sorted(extra_env(gen, name).items()):
        h.update(f"{k}={v}\n".encode())
    if name == "nginx":
        for k, v in sorted(nginx_conf_data(gen).items()):
            h.update(k.encode() + v.encode())
    return h.hexdigest()[:16]


def pod_tweaks(gen, name, spec):
    if name == "backend":
        spec["serviceAccountName"] = BACKEND_SA
        spec["automountServiceAccountToken"] = True
    else:
        spec["automountServiceAccountToken"] = False


# ── objects added on top of compose ─────────────────────────────────────────
def public_services(gen):
    """Ports compose publishes on every interface become ServiceLB ports."""
    for name, svc in gen.services.items():
        ports = [p for p in svc.get("ports") or []
                 if isinstance(p, dict) and p.get("host_ip", "") in ("", "0.0.0.0", "::")]
        if not ports:
            continue
        gen.objects.append({
            "apiVersion": "v1", "kind": "Service",
            "metadata": gen.meta(f"{name}-public"),
            "spec": {"type": "LoadBalancer",
                     "selector": {"app.kubernetes.io/name": name},
                     "ports": [{"name": f"p{p['published']}", "port": int(p["published"]),
                                "targetPort": int(p["target"])} for p in ports]},
        })


def network_policies(gen):
    """Compose networks as NetworkPolicies (k3s enforces them with kube-router).

    Pods only accept traffic from pods that share a compose network with them,
    as in Docker. Pods whose networks are all `internal: true` get no way out
    except to those same pods and DNS, which is what internal meant in Docker.
    """
    pol = []
    for net in gen.networks:
        lab = net_label(net)
        pol.append(policy(gen, f"net-{net}", {"matchLabels": {lab: "1"}},
                          ingress=[{"from": [{"podSelector": {"matchLabels": {lab: "1"}}}]}]))
    pol.append(policy(gen, "public-nginx", {"matchLabels": {"app.kubernetes.io/name": "nginx"}},
                      ingress=[{}]))
    internal = {n for n, spec in gen.networks.items() if (spec or {}).get("internal")}
    for name, svc in gen.services.items():
        nets = set((svc.get("networks") or {}).keys())
        if not nets or not nets <= internal:
            continue
        to = [{"podSelector": {"matchLabels": {net_label(n): "1"}}} for n in sorted(nets)]
        dns = {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
               "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}
        pol.append(policy(gen, f"internal-only-{name}", {"matchLabels": {"app.kubernetes.io/name": name}},
                          egress=[{"to": to}, dns]))
    gen.objects.extend(pol)


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


def backend_rbac(gen):
    """Read-only node listing for Settings → Hosting. Nothing else."""
    role = f"harvis-{gen.ns}-node-reader"
    gen.objects += [
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": gen.meta(BACKEND_SA)},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
         "metadata": {"name": role, "labels": {"app.kubernetes.io/part-of": "harvis"}},
         "rules": [{"apiGroups": [""], "resources": ["nodes"], "verbs": ["get", "list"]}]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
         "metadata": {"name": role, "labels": {"app.kubernetes.io/part-of": "harvis"}},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": role},
         "subjects": [{"kind": "ServiceAccount", "name": BACKEND_SA, "namespace": gen.ns}]},
    ]


def ollama(gen):
    if not gen.o.ollama_image:
        return
    c = {"name": "ollama", "image": gen.o.ollama_image, "imagePullPolicy": "IfNotPresent",
         "env": [{"name": "OLLAMA_HOST", "value": "0.0.0.0"}],
         "ports": [{"containerPort": 11434}],
         "volumeMounts": [{"name": "models", "mountPath": "/root/.ollama"}],
         "readinessProbe": {"exec": {"command": ["ollama", "list"]}, "periodSeconds": 10, "timeoutSeconds": 5}}
    spec = {"containers": [c], "automountServiceAccountToken": False,
            "nodeSelector": {"kubernetes.io/hostname": gen.o.node_name},
            "volumes": [{"name": "models", "hostPath": {"path": gen.o.ollama_dir, "type": "DirectoryOrCreate"}}]}
    if gen.o.gpu:
        spec["runtimeClassName"] = "nvidia"
        c["resources"] = {"limits": {"nvidia.com/gpu": "1"}}
    labels = {"app.kubernetes.io/name": "ollama", "app.kubernetes.io/part-of": "harvis",
              net_label("ollama-n8n-network"): "1"}
    gen.objects += [
        {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": gen.meta("ollama", {"app.kubernetes.io/name": "ollama"}),
         "spec": {"replicas": 1, "strategy": {"type": "Recreate"},
                  "selector": {"matchLabels": {"app.kubernetes.io/name": "ollama"}},
                  "template": {"metadata": {"labels": labels}, "spec": spec}}},
        {"apiVersion": "v1", "kind": "Service", "metadata": gen.meta("ollama", {"app.kubernetes.io/name": "ollama"}),
         "spec": {"clusterIP": "None", "selector": {"app.kubernetes.io/name": "ollama"},
                  "ports": [{"name": "http", "port": 11434, "targetPort": 11434}]}},
    ]


def lan_models(gen):
    if not (gen.o.lan_models_port and gen.o.ollama_image):
        return
    nginx_img = (gen.services.get("nginx") or {}).get("image") or "nginx:alpine"
    allowed = "|".join(re.escape(p) for p in LAN_ALLOWED)
    conf = f"""# Harvis LAN models endpoint: chat and model listing only.
server {{
    listen 8080;
    resolver {gen.o.dns_ip} valid=10s ipv6=off;
    set $ollama http://{gen.fqdn('ollama')}:11434;
    client_max_body_size 64m;
    proxy_read_timeout 3600s;
    proxy_buffering off;
    location = / {{ default_type text/plain; return 200 "Harvis models endpoint: /v1/chat/completions, /v1/models, /api/chat, /api/tags\\n"; }}
    location ~ ^({allowed})$ {{
        proxy_http_version 1.1;
        proxy_set_header Host localhost;
        proxy_set_header Connection "";
        proxy_pass $ollama;
    }}
    location / {{ default_type text/plain; return 403 "Not shared on the network: only chat and model listing are.\\n"; }}
}}
"""
    labels = {"app.kubernetes.io/name": LAN_PROXY, "app.kubernetes.io/part-of": "harvis"}
    spec = {"automountServiceAccountToken": False,
            "nodeSelector": {"kubernetes.io/hostname": gen.o.node_name},
            "containers": [{"name": "nginx", "image": nginx_img, "imagePullPolicy": "IfNotPresent",
                            "ports": [{"containerPort": 8080}],
                            "resources": {"limits": {"memory": "64Mi"}},
                            "volumeMounts": [{"name": "conf", "mountPath": "/etc/nginx/conf.d"}]}],
            "volumes": [{"name": "conf", "configMap": {"name": LAN_PROXY}}]}
    gen.objects += [
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": gen.meta(LAN_PROXY), "data": {"default.conf": conf}},
        {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": gen.meta(LAN_PROXY, {"app.kubernetes.io/name": LAN_PROXY}),
         "spec": {"replicas": 1, "selector": {"matchLabels": {"app.kubernetes.io/name": LAN_PROXY}},
                  "template": {"metadata": {"labels": labels,
                                            "annotations": {"harvis.dev/config-hash": hashlib.sha256(conf.encode()).hexdigest()[:16]}},
                               "spec": spec}}},
        {"apiVersion": "v1", "kind": "Service", "metadata": gen.meta(LAN_PROXY),
         "spec": {"type": "LoadBalancer", "selector": {"app.kubernetes.io/name": LAN_PROXY},
                  "ports": [{"name": "http", "port": gen.o.lan_models_port, "targetPort": 8080}]}},
        policy(gen, "public-lan-models", {"matchLabels": {"app.kubernetes.io/name": LAN_PROXY}}, ingress=[{}]),
        policy(gen, "ollama-from-lan-models", {"matchLabels": {"app.kubernetes.io/name": "ollama"}},
               ingress=[{"from": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": LAN_PROXY}}}]}]),
    ]


def add_all(gen):
    if "nginx" in gen.services:
        gen.objects.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": gen.meta("nginx-conf"),
                            "data": nginx_conf_data(gen)})
    public_services(gen)
    network_policies(gen)
    backend_rbac(gen)
    ollama(gen)
    lan_models(gen)
