"""Chat boxes as pods, for a Kubernetes install without Build Space.

The backend starts each chat's box as a pod (python_back_end/workspace/k8s_box.py).
This file makes everything it needs that the backend itself must not be able to make:

- Namespace ``<ns>-boxes`` with Pod Security "restricted" enforced: no privileged
  pods, host paths, host network or root. Being allowed to create pods there does
  not add up to owning the node, which is what Docker access would be.
- A NetworkPolicy that denies every pod there all ingress and egress.
- One PersistentVolume over the host folder that holds the chat folders, bound to a
  claim in that namespace. Each box mounts only its own chat's folder (subPath).
- A ResourceQuota on the number of pods.
- A Role for the backend's service account in that namespace only: pods
  (create/get/list/watch/delete) and pods/exec. Nothing in the Harvis namespace.

With Build Space on, the Docker path is used and none of this is made.
"""

BOX_PVC = "harvis-box-sandboxes"
DEFAULT_ROOT = "/data/artifacts/sandboxes"
MAX_BOXES = 25
PART = {"app.kubernetes.io/part-of": "harvis"}


def namespace(gen):
    return f"{gen.ns}-boxes"


def pv_name(gen):
    return f"harvis-{gen.ns}-box-sandboxes"


def sandbox_root(gen):
    env = (gen.c["services"].get("backend") or {}).get("environment") or {}
    return str(env.get("HARVIS_SANDBOX_ROOT") or DEFAULT_ROOT).rstrip("/")


def host_root(gen):
    """The host folder behind the backend's sandbox root, from the backend's own
    hostPath mounts (longest mountPath that covers it). None when nothing does."""
    root = sandbox_root(gen)
    vols, mounts = gen.mounts("backend", gen.c["services"]["backend"])
    host = {v["name"]: v["hostPath"]["path"] for v in vols if "hostPath" in v}
    best = None
    for m in mounts:
        dst = m["mountPath"].rstrip("/")
        if m["name"] in host and (root == dst or root.startswith(dst + "/")):
            if best is None or len(dst) > len(best[0]):
                best = (dst, host[m["name"]])
    if best is None:
        return None
    dst, src = best
    return src.rstrip("/") + root[len(dst):]


def enabled(gen):
    return "backend" in gen.services and not gen.o.build_space and host_root(gen) is not None


def backend_env(gen):
    if not enabled(gen):
        return {}
    return {
        "HARVIS_K8S_BOXES": "1",
        "HARVIS_K8S_BOX_NAMESPACE": namespace(gen),
        "HARVIS_K8S_BOX_PVC": BOX_PVC,
        "HARVIS_K8S_BOX_ROOT": sandbox_root(gen),
        "HARVIS_K8S_BOX_NODE": gen.o.node_name,
        # Pod Security "restricted" drops every capability, so sudo cannot work.
        "HARVIS_BUILD_RUNNER_SUDO": "false",
    }


def add(gen, backend_sa):
    if not enabled(gen):
        return
    ns, size = namespace(gen), "100Gi"
    psa = {f"pod-security.kubernetes.io/{m}": "restricted" for m in ("enforce", "audit", "warn")}
    psa["pod-security.kubernetes.io/enforce-version"] = "latest"

    def meta(name):
        return {"name": name, "namespace": ns, "labels": dict(PART)}

    gen.objects += [
        {"apiVersion": "v1", "kind": "Namespace",
         "metadata": {"name": ns, "labels": {**PART, **psa}}},
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
         "metadata": meta("boxes-deny-all"),
         "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}},
        {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": meta("boxes"),
         "spec": {"hard": {"pods": str(MAX_BOXES)}}},
        {"apiVersion": "v1", "kind": "PersistentVolume",
         "metadata": {"name": pv_name(gen), "labels": dict(PART)},
         "spec": {"capacity": {"storage": size}, "accessModes": ["ReadWriteMany"],
                  "persistentVolumeReclaimPolicy": "Retain", "storageClassName": BOX_PVC,
                  "claimRef": {"namespace": ns, "name": BOX_PVC},
                  "hostPath": {"path": host_root(gen), "type": "DirectoryOrCreate"},
                  "nodeAffinity": {"required": {"nodeSelectorTerms": [{"matchExpressions": [
                      {"key": "kubernetes.io/hostname", "operator": "In", "values": [gen.o.node_name]}]}]}}}},
        {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": meta(BOX_PVC),
         "spec": {"accessModes": ["ReadWriteMany"], "storageClassName": BOX_PVC,
                  "volumeName": pv_name(gen), "resources": {"requests": {"storage": size}}}},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": meta("harvis-box-runner"),
         "rules": [{"apiGroups": [""], "resources": ["pods"],
                    "verbs": ["create", "get", "list", "watch", "delete"]},
                   # WebSocket exec is authorized as get on older servers and create on newer.
                   {"apiGroups": [""], "resources": ["pods/exec"], "verbs": ["create", "get"]}]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
         "metadata": meta("harvis-box-runner"),
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "harvis-box-runner"},
         "subjects": [{"kind": "ServiceAccount", "name": backend_sa, "namespace": gen.ns}]},
    ]
