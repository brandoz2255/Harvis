"""Kubernetes-only pieces that have no line in docker-compose.yaml.

compose_to_k8s.py maps what compose says; this module adds what Kubernetes
needs on top: nginx's resolver, the public LoadBalancer ports, NetworkPolicies
standing in for compose networks, the backend's read-only view of the nodes,
the in-cluster Ollama, and the LAN models endpoint.
"""

import hashlib
import json
import os
import re
import stat

NET_PREFIX = "harvis.net/"
NGINX_CONF_TARGETS = {"/etc/nginx/nginx.conf": "nginx.conf", "/etc/nginx/harvis.conf": "harvis.conf"}
BACKEND_SA = "harvis-backend"
LAN_PROXY = "lan-models"
DB = "pgsql"
DB_BACKUP = "pgsql-backup"
# Services that never join the shared compose networks in Kubernetes: each gets
# its own ingress allowlist instead (see network_policies).
ISOLATED = {DB}

# Probes for services whose compose file has no healthcheck. Keyed by service;
# a port means tcpSocket, a (port, path) pair means httpGet. Each is read with
# the same cadence a compose healthcheck would get (probes_from_check).
#   harvis-mcp: FastAPI with one POST route and no /health, so a TCP accept is
#               the honest check. llmfit: a single static binary, no shell tools.
DEFAULT_PROBES = {
    # (port, path, startup seconds): the backend runs migrations and loads models
    # before /health answers, so a startup probe holds liveness off until it does.
    "backend": (8000, "/health", 600),
    "nginx": 80,
    "harvis-mcp": 8010,
    "harvis-messaging-gateway": (18800, "/health"),
    "llmfit": 8787,
}

# Requests for services whose compose file sets no deploy.resources, so no Harvis
# pod is BestEffort (the first class evicted under memory pressure). Requests
# only: a wrong limit would OOM-kill a pod, a request only orders eviction.
DEFAULT_REQUESTS = {
    "backend": {"memory": "512Mi", "cpu": "100m"},
    "nginx": {"memory": "32Mi", "cpu": "10m"},
    "harvis-mcp": {"memory": "128Mi", "cpu": "50m"},
    "harvis-messaging-gateway": {"memory": "128Mi", "cpu": "50m"},
    "llmfit": {"memory": "32Mi", "cpu": "10m"},
    "browser-runner": {"memory": "256Mi", "cpu": "100m"},
    "preview-runner": {"memory": "128Mi", "cpu": "50m"},
}

# Same exclusions as database-backup/backup.sh: the LangChain vector tables are
# rebuilt from documents and dwarf everything else.
PG_DUMP_EXCLUDES = ("langchain_pg_embedding", "langchain_pg_collection")
BACKUPS_KEPT = 14


def probes_from_check(check, start=0):
    """readiness / liveness / startup from one probe body (exec, tcpSocket or httpGet)."""
    out = {"readinessProbe": {**check, "periodSeconds": 10, "failureThreshold": 3},
           "livenessProbe": {**check, "periodSeconds": 30, "failureThreshold": 6}}
    if start:
        out["startupProbe"] = {**check, "periodSeconds": 5, "failureThreshold": max(12, (2 * start + 4) // 5)}
    return out


def default_probes(name, svc):
    spec = DEFAULT_PROBES.get(name)
    if spec is None:
        return {}
    start = 0
    if isinstance(spec, tuple):
        check = {"httpGet": {"port": spec[0], "path": spec[1]}}
        start = spec[2] if len(spec) > 2 else 0
    else:
        check = {"tcpSocket": {"port": spec}}
    return probes_from_check({**check, "timeoutSeconds": 5}, start)


def default_resources(name):
    req = DEFAULT_REQUESTS.get(name)
    return {"requests": dict(req)} if req else {}

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
    # Sandboxes are sibling Docker containers, bound to a session folder by its HOST
    # path. In Docker mode the backend reads that from its own container's mounts; a
    # pod has no container to inspect, so it gets the same table from here.
    vols, mounts = gen.mounts(name, gen.c["services"][name])
    host = {v["name"]: v["hostPath"]["path"] for v in vols if "hostPath" in v}
    env["HARVIS_HOST_MOUNTS"] = json.dumps(
        [{"Destination": m["mountPath"], "Source": host[m["name"]]} for m in mounts if m["name"] in host])
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
    clients = db_clients(gen)
    if DB in gen.services:
        # The database sits on the shared network in Docker, so every container
        # could open it. Here only the pods that hold a connection string may.
        pol.append(policy(gen, f"{DB}-ingress", {"matchLabels": {"app.kubernetes.io/name": DB}},
                          ingress=[{"from": [{"podSelector": {"matchExpressions": [
                              {"key": "app.kubernetes.io/name", "operator": "In", "values": clients}]}}],
                                    "ports": [{"protocol": "TCP", "port": 5432}]}]))
    internal = {n for n, spec in gen.networks.items() if (spec or {}).get("internal")}
    for name, svc in gen.services.items():
        nets = set((svc.get("networks") or {}).keys())
        if not nets or not nets <= internal:
            continue
        to = [{"podSelector": {"matchLabels": {net_label(n): "1"}}} for n in sorted(nets)]
        if name in clients:
            to.append({"podSelector": {"matchLabels": {"app.kubernetes.io/name": DB}}})
        dns = {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
               "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}
        pol.append(policy(gen, f"internal-only-{name}", {"matchLabels": {"app.kubernetes.io/name": name}},
                          egress=[{"to": to}, dns]))
    gen.objects.extend(pol)


def db_clients(gen):
    """Services that compose itself shows talking to the database.

    Evidence is a connection string or command naming the pgsql host (in the
    service or in a one-shot it runs as an initContainer), or a depends_on it.
    The backup CronJob is always one.
    """
    hosts = {DB}
    if (gen.services.get(DB) or {}).get("container_name"):
        hosts.add(gen.services[DB]["container_name"])
    rx = re.compile(r"(?<![\w.-])(" + "|".join(re.escape(h) for h in sorted(hosts)) + r")(?![\w-])")

    def mentions(svc):
        text = " ".join(str(v) for v in (svc.get("environment") or {}).values())
        for key in ("command", "entrypoint"):
            val = svc.get(key)
            text += " " + (" ".join(val) if isinstance(val, list) else str(val or ""))
        return bool(rx.search(text)) or DB in (svc.get("depends_on") or {})

    out = {DB_BACKUP}
    for name, svc in gen.services.items():
        if name == DB:
            continue
        deps = [gen.services[d] for d in (svc.get("depends_on") or {}) if d in gen.services]
        if mentions(svc) or any(mentions(d) for d in deps if str(d.get("restart", "")).strip('"') in ("no", "")):
            out.add(name)
    return sorted(out)


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
         # Memory request so the pod is Burstable (evicted after BestEffort ones),
         # a limit so one oversized model fails visibly instead of taking the
         # node down, and no CPU limit: inference should keep every core it gets.
         "resources": {"requests": {"memory": gen.o.ollama_memory_request, "cpu": gen.o.ollama_cpu_request},
                       "limits": {"memory": gen.o.ollama_memory_limit}},
         **probes_from_check({"httpGet": {"port": 11434, "path": "/"}, "timeoutSeconds": 5}, start=30)}
    c["readinessProbe"] = {"exec": {"command": ["ollama", "list"]}, "periodSeconds": 10, "timeoutSeconds": 5}
    spec = {"containers": [c], "automountServiceAccountToken": False,
            "nodeSelector": {"kubernetes.io/hostname": gen.o.node_name},
            "volumes": [{"name": "models", "hostPath": {"path": gen.o.ollama_dir, "type": "DirectoryOrCreate"}}]}
    if gen.o.gpu:
        spec["runtimeClassName"] = "nvidia"
        c["resources"]["limits"]["nvidia.com/gpu"] = "1"
    elif gen.o.amd_gpu:
        # Vulkan (Mesa RADV) is already inside the ollama image; it only needs
        # /dev/dri. ROCm is not: this is the path for RDNA1 cards like the RX 5500 XT.
        c["env"].append({"name": "OLLAMA_VULKAN", "value": "1"})
        if gen.o.amd_gpu == "plugin":
            c["resources"]["limits"]["amd.com/gpu"] = "1"
        else:
            # runc's device cgroup refuses a hostPath-mounted /dev/dri without privileged.
            c["securityContext"] = {"privileged": True}
            for dev, kind in (("/dev/dri", "Directory"), ("/dev/kfd", "CharDevice")):
                if os.path.exists(dev):
                    spec["volumes"].append({"name": dev[5:], "hostPath": {"path": dev, "type": kind}})
                    c["volumeMounts"].append({"name": dev[5:], "mountPath": dev})
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
                            "volumeMounts": [{"name": "conf", "mountPath": "/etc/nginx/conf.d"}],
                            **probes_from_check({"httpGet": {"port": 8080, "path": "/"}, "timeoutSeconds": 3})}],
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


def db_backup(gen):
    """Nightly pg_dump of the database to a directory on the node.

    The pod runs the same digest-pinned postgres image as pgsql itself (so
    pg_dump matches the server) with pgsql's own env Secret, dumps over the
    network to a dated .gz file and keeps the newest BACKUPS_KEPT. The same
    pg_dump flags as database-backup/backup.sh, so either file restores with
    database-backup/restore.sh.
    """
    svc = gen.services.get(DB)
    if not svc or not svc.get("image"):
        return
    excludes = " ".join(f"--exclude-table={t}" for t in PG_DUMP_EXCLUDES)
    script = (
        'set -eu; f="/backups/harvis_backup_$(date +%Y%m%d_%H%M%S).sql.gz"; '
        f'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h {gen.fqdn(DB)} -U "$POSTGRES_USER" "$POSTGRES_DB" {excludes} '
        '| gzip > "$f"; [ "$(gzip -dc "$f" | head -c 1 | wc -c)" = 1 ] || { rm -f "$f"; echo "empty dump" >&2; exit 1; }; '
        f'ls -t /backups/harvis_backup_*.sql.gz | tail -n +{BACKUPS_KEPT + 1} | xargs -r rm -f; '
        'echo "backup written: $f ($(du -h "$f" | cut -f1))"'
    )
    labels = {"app.kubernetes.io/name": DB_BACKUP, "app.kubernetes.io/part-of": "harvis"}
    pod = {"restartPolicy": "OnFailure", "automountServiceAccountToken": False,
           "nodeSelector": {"kubernetes.io/hostname": gen.o.node_name},
           "containers": [{"name": "pg-dump", "image": svc["image"], "imagePullPolicy": "IfNotPresent",
                           "command": ["sh", "-c", script],
                           "envFrom": [{"secretRef": {"name": f"{DB}-env"}}],
                           "resources": {"requests": {"memory": "32Mi", "cpu": "10m"}, "limits": {"memory": "256Mi"}},
                           "volumeMounts": [{"name": "backups", "mountPath": "/backups"}]}],
           "volumes": [{"name": "backups", "hostPath": {"path": gen.o.backup_dir, "type": "DirectoryOrCreate"}}]}
    gen.objects.append({
        "apiVersion": "batch/v1", "kind": "CronJob", "metadata": gen.meta(DB_BACKUP, {"app.kubernetes.io/name": DB_BACKUP}),
        "spec": {"schedule": gen.o.backup_schedule, "concurrencyPolicy": "Forbid",
                 "successfulJobsHistoryLimit": 3, "failedJobsHistoryLimit": 3,
                 "jobTemplate": {"spec": {"backoffLimit": 2, "ttlSecondsAfterFinished": 7 * 86400,
                                          "template": {"metadata": {"labels": labels}, "spec": pod}}}},
    })


def add_all(gen):
    if "nginx" in gen.services:
        gen.objects.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": gen.meta("nginx-conf"),
                            "data": nginx_conf_data(gen)})
    public_services(gen)
    network_policies(gen)
    backend_rbac(gen)
    ollama(gen)
    lan_models(gen)
    db_backup(gen)
