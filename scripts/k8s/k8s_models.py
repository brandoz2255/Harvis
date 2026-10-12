"""The in-cluster model server (Ollama) and the endpoint that shares it on the LAN."""

import hashlib
import os
import re
import sys

from k8s_common import LB_LOCAL, net_label, policy, probes_from_check, quantity

LAN_PROXY = "lan-models"

# The only model-server routes the LAN endpoint forwards. Everything else —
# pulling, deleting, copying, pushing or creating models — is refused, so a
# neighbour can use this machine's models but cannot change them.
LAN_ALLOWED = (
    "/v1/chat/completions", "/v1/completions", "/v1/models", "/v1/embeddings",
    "/api/chat", "/api/generate", "/api/tags", "/api/show", "/api/embed",
    "/api/embeddings", "/api/version",
)


def ollama_resources(gen):
    """The model server's requests and limit, shrunk to fit beside the rest of Harvis.

    The scheduler counts requests, not use: a 6Gi request on a node with 10 GB
    where the other pods already ask for 4.3 GB stays Pending forever. Whatever
    the other Harvis pods request comes off the node's allocatable, plus headroom
    for k3s' own pods, the LAN proxy and the backup job (all added after this);
    the defaults are only ceilings.
    """
    mem_req, mem_lim = quantity(gen.o.ollama_memory_request), quantity(gen.o.ollama_memory_limit)
    cpu_req = quantity(gen.o.ollama_cpu_request)
    node_mem, node_cpu = quantity(gen.o.node_memory), quantity(gen.o.node_cpu)
    used_mem = used_cpu = 0.0
    for o in gen.objects:
        if o.get("kind") != "Deployment":
            continue
        for c in o["spec"]["template"]["spec"]["containers"]:
            res = c.get("resources") or {}
            # A container with only a limit is scheduled as requesting that limit.
            req = {**(res.get("limits") or {}), **(res.get("requests") or {})}
            used_mem += quantity(req.get("memory")) or 0
            used_cpu += quantity(req.get("cpu")) or 0
    if node_mem:
        free = node_mem - used_mem - 512 * 2**20
        if free < 2**30:
            sys.stderr.write(f"warning: only {max(free, 0) / 2**30:.1f} GiB of memory is left for models "
                             "on this machine; the model server may not start\n")
        mem_req = min(mem_req, max(free, 2**30))
        mem_lim = max(mem_req, min(mem_lim, node_mem - 512 * 2**20))
    if node_cpu:
        cpu_req = min(cpu_req, max(node_cpu - used_cpu - 0.3, 0.25))
    return ({"memory": f"{int(mem_req // 2**20)}Mi", "cpu": f"{int(cpu_req * 1000)}m"},
            {"memory": f"{int(mem_lim // 2**20)}Mi"})


# Shared on the network, so: a short queue that answers "busy" instead of
# piling up, two answers at a time, two models in memory, and no Ollama cloud
# (a ":cloud" model would send people's prompts off this machine).
OLLAMA_LIMITS = [{"name": "OLLAMA_NUM_PARALLEL", "value": "2"},
                 {"name": "OLLAMA_MAX_QUEUE", "value": "32"},
                 {"name": "OLLAMA_MAX_LOADED_MODELS", "value": "2"},
                 {"name": "OLLAMA_NO_CLOUD", "value": "1"}]


def ollama(gen):
    if not gen.o.ollama_image:
        return
    requests, limits = ollama_resources(gen)
    c = {"name": "ollama", "image": gen.o.ollama_image, "imagePullPolicy": "IfNotPresent",
         "env": [{"name": "OLLAMA_HOST", "value": "0.0.0.0"}, *OLLAMA_LIMITS],
         "ports": [{"containerPort": 11434}],
         "volumeMounts": [{"name": "models", "mountPath": "/root/.ollama"}],
         # Memory request so the pod is Burstable (evicted after BestEffort ones),
         # a limit so one oversized model fails visibly instead of taking the
         # node down, and no CPU limit: inference should keep every core it gets.
         "resources": {"requests": requests, "limits": limits},
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
    # Per-visitor limits: the Service keeps the visitor's address (LB_LOCAL),
    # so one busy computer cannot fill Ollama's queue for everyone else.
    conf = f"""# Harvis LAN models endpoint: chat and model listing only.
limit_req_zone $binary_remote_addr zone=lan_models:1m rate=2r/s;
limit_conn_zone $binary_remote_addr zone=lan_models_conn:1m;
server {{
    listen 8080;
    server_tokens off;
    resolver {gen.o.dns_ip} valid=10s ipv6=off;
    set $ollama http://{gen.fqdn('ollama')}:11434;
    client_max_body_size 16m;
    proxy_read_timeout 300s;
    proxy_buffering off;
    limit_req_status 429;
    limit_conn_status 429;
    location = / {{ default_type text/plain; return 200 "Harvis models endpoint: /v1/chat/completions, /v1/models, /api/chat, /api/tags\\n"; }}
    location ~ ^({allowed})$ {{
        limit_req zone=lan_models burst=20 nodelay;
        limit_conn lan_models_conn 4;
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
         "spec": {"type": "LoadBalancer", **LB_LOCAL, "selector": {"app.kubernetes.io/name": LAN_PROXY},
                  "ports": [{"name": "http", "port": gen.o.lan_models_port, "targetPort": 8080}]}},
        policy(gen, "public-lan-models", {"matchLabels": {"app.kubernetes.io/name": LAN_PROXY}}, ingress=[{}]),
        policy(gen, "ollama-from-lan-models", {"matchLabels": {"app.kubernetes.io/name": "ollama"}},
               ingress=[{"from": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": LAN_PROXY}}}]}]),
    ]
