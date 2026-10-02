#!/usr/bin/env python3
"""Turn the rendered Harvis compose file into Kubernetes objects for k3s.

    docker compose config --format json | python3 compose_to_k8s.py [opts] | k3s kubectl apply -f -

Kubernetes mode is generated from docker-compose.yaml on every run instead of
being a second, hand-kept copy of the stack, so the two cannot drift apart.
Output goes to stdout only: the rendered env holds the generated secrets, and
they are never written to disk here.

Mapping, in short:
  service              -> Deployment (1 replica, pinned to the server node)
  service name, container_name, network aliases
                       -> headless Services, so names resolve the way Docker DNS did
  named volume         -> hostPath of the SAME Docker volume directory, so Docker
                          mode and Kubernetes mode share one copy of the data
  bind mount           -> hostPath
  environment          -> a Secret per service (envFrom)
  one-shot services    -> initContainers of the services that wait on them
  healthy/started deps -> an initContainer that waits for the dependency's DNS name
  healthcheck          -> readiness + liveness probes (+ startup when start_period is set);
                          services without one get the probe k8s_extras.DEFAULT_PROBES names
  deploy.resources     -> resources.limits (limits) and resources.requests (reservations)
  compose networks     -> NetworkPolicies (see k8s_extras.network_policies)

Standard library only: this runs on a machine that has nothing but python3.
"""

import argparse
import hashlib
import json
import re
import sys

import k8s_extras as extras

LABEL_APP = "app.kubernetes.io/name"
LABEL_PART = "app.kubernetes.io/part-of"
BUSYBOX_FALLBACK = "busybox:1.37.0"
DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def dns_name(value):
    """Kubernetes object names: lower-case, [-a-z0-9], at most 63 chars."""
    out = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return out[:63].rstrip("-")


def parse_bytes(value):
    """Compose renders memory limits as a byte count string ("67108864")."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_duration(value, default):
    """'10s' / '1m30s' / '500ms' -> whole seconds (at least 1)."""
    if not value:
        return default
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|s|m|h)", str(value)):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return max(1, int(round(total))) if total else default


def cpu_quantity(value):
    """Compose renders `cpus: '0.25'` as the number 0.25; Kubernetes wants '250m'."""
    try:
        cores = float(value)
    except (TypeError, ValueError):
        return None
    if cores <= 0:
        return None
    milli = int(round(cores * 1000))
    return str(milli // 1000) if milli % 1000 == 0 else f"{milli}m"


def resources_for(svc):
    """deploy.resources -> {limits, requests}; empty when compose says nothing."""
    res = (svc.get("deploy") or {}).get("resources") or {}
    out = {}
    for src, dst in (("limits", "limits"), ("reservations", "requests")):
        part = {}
        mem = parse_bytes((res.get(src) or {}).get("memory"))
        cpu = cpu_quantity((res.get(src) or {}).get("cpus"))
        if mem:
            part["memory"] = str(mem)
        if cpu:
            part["cpu"] = cpu
        if part:
            out[dst] = part
    return out


def image_for(name, svc, project):
    if svc.get("image"):
        return svc["image"]
    # Compose names an image it builds without an `image:` key <project>-<service>.
    return f"{project}-{name}:latest"


def is_local_build(svc):
    return bool(svc.get("build"))


def is_one_shot(svc):
    return str(svc.get("restart", "")).strip('"') in ("no", "")


class Generator:
    def __init__(self, compose, opts):
        self.c = compose
        self.o = opts
        self.project = compose.get("name") or "harvis"
        self.ns = opts.namespace
        self.services = compose.get("services", {})
        self.networks = compose.get("networks", {}) or {}
        self.objects = []
        self.busybox = self._find_busybox()
        self.image_ids = {}
        if opts.image_ids:
            with open(opts.image_ids) as fh:
                self.image_ids = json.load(fh)

    # ── helpers ──────────────────────────────────────────────────────────
    def _find_busybox(self):
        for svc in self.services.values():
            img = svc.get("image") or ""
            if img.startswith("busybox"):
                return img
        return BUSYBOX_FALLBACK

    def meta(self, name, labels=None, kind_labels=True):
        m = {"name": name, "namespace": self.ns}
        lab = {LABEL_PART: "harvis"}
        if labels:
            lab.update(labels)
        if kind_labels:
            m["labels"] = lab
        return m

    def fqdn(self, name):
        return f"{name}.{self.ns}.svc.cluster.local"

    def pull_policy(self, svc):
        # Locally built images were imported into k3s' containerd; there is no
        # registry to pull them from, so never try.
        return "Never" if is_local_build(svc) else "IfNotPresent"

    def volume_host_path(self, volname):
        spec = (self.c.get("volumes") or {}).get(volname) or {}
        real = spec.get("name") or f"{self.project}_{volname}"
        return f"{self.o.volume_root}/{real}/_data"

    # ── pod pieces ───────────────────────────────────────────────────────
    def mounts(self, name, svc):
        """(volumes, volumeMounts) for one service."""
        vols, mounts, seen = [], [], {}
        for i, v in enumerate(svc.get("volumes") or []):
            vtype, target = v.get("type"), v.get("target")
            if vtype == "volume":
                path, htype = self.volume_host_path(v["source"]), "DirectoryOrCreate"
            elif vtype == "bind":
                path = v["source"]
                htype = extras.bind_host_path_type(path, target)
            elif vtype == "tmpfs":
                vname = f"tmpfs-{i}"
                vols.append({"name": vname, "emptyDir": {"medium": "Memory"}})
                mounts.append({"name": vname, "mountPath": target})
                continue
            else:
                raise SystemExit(f"{name}: unsupported volume type {vtype!r}")
            override = extras.config_override(self, name, target)
            if override:
                vols_extra, mount = override
                vols.extend(x for x in vols_extra if x["name"] not in seen)
                for x in vols_extra:
                    seen[x["name"]] = True
                mounts.append(mount)
                continue
            # Named by source, so an initContainer and the main container that
            # mount the same directory share one volume entry.
            digest = hashlib.sha1(f"{path}|{htype}".encode()).hexdigest()[:8]
            vname = f"h{digest}-{dns_name(path.rsplit('/', 1)[-1] or 'root')}"[:63].rstrip("-")
            if vname not in seen:
                seen[vname] = True
                vols.append({"name": vname, "hostPath": {"path": path, "type": htype}})
            m = {"name": vname, "mountPath": target}
            if v.get("read_only"):
                m["readOnly"] = True
            mounts.append(m)
        for t in svc.get("tmpfs") or []:
            vname = f"tmpfs-{len(vols)}"
            vols.append({"name": vname, "emptyDir": {"medium": "Memory"}})
            mounts.append({"name": vname, "mountPath": t.split(":")[0]})
        return vols, mounts

    def probes(self, name, svc):
        """{readinessProbe, livenessProbe[, startupProbe]} from the compose healthcheck.

        Readiness keeps compose's own cadence. Liveness is the same check with
        more patience (six misses, 30 s apart) because its failure restarts the
        container: a slow reply must not become an outage. start_period becomes
        a startupProbe, which holds both others off until the first success and
        allows twice compose's grace, instead of a fixed initial delay.
        """
        hc = svc.get("healthcheck") or {}
        test = hc.get("test")
        if hc.get("disable") or (test and test[0] == "NONE"):
            return {}
        if not test:
            return extras.default_probes(name, svc)
        if test[0] == "CMD-SHELL":
            cmd = ["sh", "-c", " ".join(test[1:])]
        elif test[0] == "CMD":
            cmd = list(test[1:])
        else:
            cmd = ["sh", "-c", " ".join(test)]
        check = {"exec": {"command": cmd}, "timeoutSeconds": parse_duration(hc.get("timeout"), 5)}
        period = min(parse_duration(hc.get("interval"), 30), 15)
        start = parse_duration(hc.get("start_period"), 0)
        out = {
            "readinessProbe": {**check, "periodSeconds": period, "failureThreshold": int(hc.get("retries") or 3)},
            "livenessProbe": {**check, "periodSeconds": 30, "failureThreshold": 6},
        }
        if start:
            out["startupProbe"] = {**check, "periodSeconds": 5, "failureThreshold": max(12, (2 * start + 4) // 5)}
        return out

    def container(self, name, svc):
        vols, mounts = self.mounts(name, svc)
        c = {
            "name": dns_name(name),
            "image": image_for(name, svc, self.project),
            "imagePullPolicy": self.pull_policy(svc),
        }
        if svc.get("entrypoint"):
            c["command"] = list(svc["entrypoint"])
        if svc.get("command"):
            c["args"] = list(svc["command"])
        if svc.get("working_dir"):
            c["workingDir"] = svc["working_dir"]
        if svc.get("environment") or self.extra_env(name):
            c["envFrom"] = [{"secretRef": {"name": f"{dns_name(name)}-env"}}]
        if mounts:
            c["volumeMounts"] = mounts
        ports = self.container_ports(svc)
        if ports:
            c["ports"] = [{"containerPort": p} for p in ports]
        c.update(self.probes(name, svc))
        res = resources_for(svc) or extras.default_resources(name)
        if res:
            c["resources"] = res
        # No nvidia.com/gpu request here: compose's `runtime: nvidia` shares the card
        # (NVIDIA_VISIBLE_DEVICES), and on a one-GPU box a request would leave this
        # pod or Ollama Pending forever. The runtime class alone gives the same view.
        return c, vols

    def container_ports(self, svc):
        found = set()
        for p in svc.get("ports") or []:
            if isinstance(p, dict) and p.get("target"):
                found.add(int(p["target"]))
        for e in svc.get("expose") or []:
            m = re.match(r"^(\d+)", str(e))
            if m:
                found.add(int(m.group(1)))
        return sorted(found)

    def security_context(self, svc):
        sc = {}
        user = str(svc.get("user") or "")
        if user and user != "root":
            uid, _, gid = user.partition(":")
            if uid.isdigit():
                sc["runAsUser"] = int(uid)
            if gid.isdigit():
                sc["runAsGroup"] = int(gid)
        groups = [int(g) for g in svc.get("group_add") or [] if str(g).isdigit()]
        if groups:
            sc["supplementalGroups"] = groups
        return sc

    def wait_containers(self, name, svc):
        """initContainers: one-shot deps run in-pod; long-running deps are waited on."""
        inits, extra_vols = [], []
        for dep, cond in (svc.get("depends_on") or {}).items():
            if dep not in self.services:
                continue
            dsvc = self.services[dep]
            condition = (cond or {}).get("condition", "service_started")
            if condition == "service_completed_successfully" or is_one_shot(dsvc):
                c, vols = self.container(dep, dsvc)
                # An initContainer may not carry probes; the API server rejects them.
                for k in ("readinessProbe", "livenessProbe", "startupProbe", "ports"):
                    c.pop(k, None)
                sc = self.security_context(dsvc)
                if sc:
                    c["securityContext"] = sc
                inits.append(c)
                extra_vols.extend(vols)
            else:
                target = self.fqdn(dns_name(dep))
                inits.append({
                    "name": f"wait-{dns_name(dep)}"[:63],
                    "image": self.busybox,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["sh", "-c",
                                f"until nslookup {target} >/dev/null 2>&1; do "
                                f"echo waiting for {dep}; sleep 2; done"],
                })
        return inits, extra_vols

    def pod_labels(self, name, svc):
        labels = {LABEL_APP: dns_name(name), LABEL_PART: "harvis"}
        if name in extras.ISOLATED:
            # Reached only through its own allowlist policy, never the network-wide one.
            return labels
        for net in (svc.get("networks") or {}):
            labels[extras.net_label(net)] = "1"
        return labels

    def extra_env(self, name):
        return extras.extra_env(self, name)

    # ── objects ──────────────────────────────────────────────────────────
    def env_secret(self, name, svc):
        env = {k: ("" if v is None else str(v)) for k, v in (svc.get("environment") or {}).items()}
        env.update(self.extra_env(name))
        if not env:
            return
        self.objects.append({
            "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
            "metadata": self.meta(f"{dns_name(name)}-env", {LABEL_APP: dns_name(name)}),
            "stringData": env,
        })

    def deployment(self, name, svc):
        c, vols = self.container(name, svc)
        inits, init_vols = self.wait_containers(name, svc)
        names = {v["name"] for v in vols}
        for v in init_vols:
            if v["name"] not in names:
                vols.append(v)
                names.add(v["name"])
        labels = self.pod_labels(name, svc)
        spec = {
            "containers": [c],
            "nodeSelector": {"kubernetes.io/hostname": self.o.node_name},
            "enableServiceLinks": False,
        }
        if inits:
            spec["initContainers"] = inits
        if vols:
            spec["volumes"] = vols
        sc = self.security_context(svc)
        if sc:
            spec["securityContext"] = sc
        hosts = extras.host_aliases(self, svc)
        if hosts:
            spec["hostAliases"] = hosts
        if svc.get("runtime") == "nvidia" and self.o.gpu:
            spec["runtimeClassName"] = "nvidia"
        extras.pod_tweaks(self, name, spec)
        self.objects.append({
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": self.meta(dns_name(name), {LABEL_APP: dns_name(name)}),
            "spec": {
                "replicas": 1,
                # Recreate, not RollingUpdate: several services hold hostPath data
                # (postgres above all) that two copies must never share.
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {LABEL_APP: dns_name(name)}},
                "template": {"metadata": {"labels": labels, "annotations": {
                    "harvis.dev/config-hash": extras.config_hash(self, name, svc),
                    **self.image_hash(spec)}}, "spec": spec},
            },
        })

    def image_hash(self, spec):
        # A rebuilt image keeps its tag, so the pod spec alone never changes and k8s
        # keeps the old process. Its content id does change; carry it into the template.
        used = sorted({c["image"] for c in spec["containers"] + spec.get("initContainers", [])
                       if c["image"] in self.image_ids})
        if not used:
            return {}
        h = hashlib.sha256("".join(f"{i}={self.image_ids[i]}\n" for i in used).encode())
        return {"harvis.dev/image-hash": h.hexdigest()[:16]}

    def services_for(self, name, svc):
        aliases = {dns_name(name)}
        if svc.get("container_name"):
            aliases.add(dns_name(svc["container_name"]))
        for net in (svc.get("networks") or {}).values():
            for a in (net or {}).get("aliases") or []:
                aliases.add(dns_name(a))
        ports = self.container_ports(svc)
        for alias in sorted(a for a in aliases if DNS_LABEL.match(a)):
            spec = {"clusterIP": "None", "selector": {LABEL_APP: dns_name(name)},
                    "publishNotReadyAddresses": False}
            if ports:
                spec["ports"] = [{"name": f"p{p}", "port": p, "targetPort": p} for p in ports]
            self.objects.append({"apiVersion": "v1", "kind": "Service",
                                 "metadata": self.meta(alias, {LABEL_APP: dns_name(name)}),
                                 "spec": spec})

    def build(self):
        self.objects.append({"apiVersion": "v1", "kind": "Namespace",
                             "metadata": {"name": self.ns, "labels": {LABEL_PART: "harvis"}}})
        consumed = set()
        for name, svc in self.services.items():
            for dep, cond in (svc.get("depends_on") or {}).items():
                dsvc = self.services.get(dep) or {}
                if (cond or {}).get("condition") == "service_completed_successfully" or is_one_shot(dsvc):
                    consumed.add(dep)
        for name, svc in sorted(self.services.items()):
            if name in consumed:
                continue  # runs as an initContainer of whoever waited on it
            if is_one_shot(svc):
                sys.stderr.write(f"note: one-shot service {name} has no dependents; skipped\n")
                continue
            self.env_secret(name, svc)
            self.deployment(name, svc)
            self.services_for(name, svc)
        for name in consumed:
            self.env_secret(name, self.services[name])
        extras.add_all(self)
        return {"apiVersion": "v1", "kind": "List", "items": self.objects}


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--namespace", default="harvis")
    p.add_argument("--node-name", required=True, help="server node; every Harvis pod is pinned to it")
    p.add_argument("--node-ip", required=True, help="what host.docker.internal resolves to")
    p.add_argument("--volume-root", default="/var/lib/docker/volumes")
    p.add_argument("--dns-ip", default="10.43.0.10", help="cluster DNS service IP (nginx resolver)")
    p.add_argument("--repo", required=True, help="repo root (to read nginx configs)")
    p.add_argument("--gpu", action="store_true", help="an NVIDIA GPU is schedulable")
    p.add_argument("--amd-gpu", choices=("plugin", "privileged"), default="",
                   help="give Ollama an AMD GPU over Vulkan: via the amd.com/gpu device plugin, "
                        "or by handing it /dev/dri directly (privileged)")
    p.add_argument("--ollama-image", default="", help="run Ollama in the cluster with this image")
    p.add_argument("--ollama-dir", default="/var/lib/harvis/ollama")
    # Defaults sized for a 14 GB / 8 core box; harvis-k8s.sh scales them from the node.
    p.add_argument("--ollama-memory-request", default="6Gi")
    p.add_argument("--ollama-memory-limit", default="10Gi")
    p.add_argument("--ollama-cpu-request", default="2")
    p.add_argument("--backup-dir", default="/var/lib/harvis/backups", help="where the nightly pg_dump lands")
    p.add_argument("--backup-schedule", default="0 3 * * *", help="cron schedule of the database backup")
    p.add_argument("--lan-models-port", type=int, default=0, help="0 = do not share models on the LAN")
    p.add_argument("--lan-models-url", default="")
    p.add_argument("--image-ids", default="", help="JSON {image: content id}; a changed id restarts its pods")
    return p.parse_args(argv)


def main(argv=None):
    opts = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        compose = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"stdin is not `docker compose config --format json` output: {exc}")
    out = Generator(compose, opts).build()
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
