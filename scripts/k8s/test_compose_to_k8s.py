"""Tests for the compose → Kubernetes generator.  Run: python3 -m pytest scripts/k8s -q"""

import hashlib
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import compose_to_k8s as gen  # noqa: E402
import k8s_common  # noqa: E402
import k8s_extras  # noqa: E402

NGINX_CONF = ("http {\n    resolver 127.0.0.11 valid=10s ipv6=off;\n    include /etc/nginx/harvis.conf;\n"
              "    server {\n        listen 8081;\n"
              "        set $tunnel_auth http://backend:8000/api/tunnel/verify;\n    }\n}\n")
HARVIS_CONF = "    set $backend_upstream  http://backend:8000;\n    set $voice_upstream    http://voice-onnx:8000;\n"

COMPOSE = {
    "name": "harvis",
    "networks": {
        "ollama-n8n-network": {"name": "ollama-n8n-network", "external": True},
        "preview-net": {"name": "harvis_preview-net", "internal": True},
    },
    "volumes": {"pgsql_data": {"name": "harvis_pgsql_data"}, "artifact_data": {"name": "harvis_artifact_data"}},
    "services": {
        "artifact-init": {
            "image": "busybox:1.37.0@sha256:abc", "restart": "no", "user": "root",
            "command": ["sh", "-c", "chown 1001 /data"],
            "volumes": [{"type": "volume", "source": "artifact_data", "target": "/data"}],
            "networks": {"ollama-n8n-network": None},
        },
        "pgsql": {
            "image": "pgvector/pgvector:pg15", "restart": "unless-stopped", "container_name": "pgsql-db",
            "environment": {"POSTGRES_PASSWORD": "s3cret"},
            "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U pguser"], "interval": "10s", "retries": 5},
            "ports": [{"host_ip": "127.0.0.1", "target": 5432, "published": "5432"}],
            "volumes": [{"type": "volume", "source": "pgsql_data", "target": "/var/lib/postgresql/data"}],
            "networks": {"ollama-n8n-network": None},
        },
        "backend": {
            "build": {"context": "."}, "restart": "unless-stopped", "user": "1001:1001", "group_add": ["984"],
            "container_name": "harvis-backend", "extra_hosts": ["host.docker.internal=host-gateway"],
            "environment": {"JWT_SECRET": "jwt"},
            "depends_on": {"artifact-init": {"condition": "service_completed_successfully"},
                           "pgsql": {"condition": "service_healthy"}},
            "volumes": [{"type": "volume", "source": "artifact_data", "target": "/data/artifacts"},
                        {"type": "bind", "source": "/tmp", "target": "/tmp"},
                        {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}],
            "networks": {"ollama-n8n-network": None, "preview-net": None},
        },
        "browser-runner": {
            "image": "harvis-browser-runner:latest", "restart": "unless-stopped",
            "expose": ["8765"], "networks": {"ollama-n8n-network": None},
        },
        "preview-runner": {
            "image": "harvis-browser-runner:latest", "build": {"context": "."}, "restart": "unless-stopped",
            "expose": ["8765"], "networks": {"preview-net": None},
        },
        "llmfit": {"image": "llmfit:1", "restart": "unless-stopped", "runtime": "nvidia",
                   "networks": {"ollama-n8n-network": None}},
        "nginx": {
            "image": "nginx:1.29", "restart": "unless-stopped",
            "depends_on": {"backend": {"condition": "service_started"}},
            "ports": [{"host_ip": "0.0.0.0", "target": 80, "published": "9000"},
                      {"host_ip": "127.0.0.1", "target": 9002, "published": "9002"}],
            "volumes": [{"type": "bind", "source": "REPO/nginx.conf", "target": "/etc/nginx/nginx.conf", "read_only": True},
                        {"type": "bind", "source": "REPO/nginx-harvis.conf", "target": "/etc/nginx/harvis.conf", "read_only": True},
                        {"type": "bind", "source": "/tmp", "target": "/tmp", "read_only": True}],
            "networks": {"ollama-n8n-network": None},
        },
    },
}


def render(*extra):
    with tempfile.TemporaryDirectory() as repo:
        for name, body in (("nginx.conf", NGINX_CONF), ("nginx-harvis.conf", HARVIS_CONF)):
            with open(os.path.join(repo, name), "w") as fh:
                fh.write(body)
        compose = json.loads(json.dumps(COMPOSE).replace("REPO", repo))
        opts = gen.parse_args(["--node-name", "n1", "--node-ip", "10.0.0.5", "--repo", repo,
                               "--volume-root", "/var/lib/docker/volumes", *extra])
        return gen.Generator(compose, opts).build()["items"]


def find(items, kind, name):
    return next((o for o in items if o["kind"] == kind and o["metadata"]["name"] == name), None)


def pod(items, name):
    return find(items, "Deployment", name)["spec"]["template"]["spec"]


class GeneratorTest(unittest.TestCase):
    def setUp(self):
        self.items = render()

    def test_one_shot_dependency_runs_as_init_container(self):
        spec = pod(self.items, "backend")
        names = [c["name"] for c in spec["initContainers"]]
        self.assertEqual(names, ["artifact-init", "wait-pgsql"])
        self.assertIsNone(find(self.items, "Deployment", "artifact-init"))
        wait = spec["initContainers"][1]["command"][2]
        self.assertIn("pgsql.harvis.svc.cluster.local", wait)

    def test_named_volume_is_the_docker_volume_directory(self):
        vols = pod(self.items, "pgsql")["volumes"]
        self.assertEqual(vols[0]["hostPath"]["path"], "/var/lib/docker/volumes/harvis_pgsql_data/_data")

    def test_init_and_main_container_share_one_volume_entry(self):
        spec = pod(self.items, "backend")
        paths = [v["hostPath"]["path"] for v in spec["volumes"] if "hostPath" in v]
        self.assertEqual(paths.count("/var/lib/docker/volumes/harvis_artifact_data/_data"), 1)

    def test_env_lives_in_a_secret_not_the_deployment(self):
        self.assertEqual(find(self.items, "Secret", "pgsql-env")["stringData"]["POSTGRES_PASSWORD"], "s3cret")
        self.assertNotIn("s3cret", json.dumps(find(self.items, "Deployment", "pgsql")))

    def test_backend_knows_it_is_in_kubernetes(self):
        env = find(self.items, "Secret", "backend-env")["stringData"]
        self.assertEqual(env["HARVIS_HOSTING_MODE"], "kubernetes")
        self.assertEqual(pod(self.items, "backend")["serviceAccountName"], "harvis-backend")
        self.assertFalse(pod(self.items, "nginx")["automountServiceAccountToken"])

    def test_backend_can_only_read_its_own_namespace(self):
        role = find(self.items, "Role", "harvis-backend-viewer")
        self.assertEqual(role["metadata"]["namespace"], "harvis")
        verbs = {v for rule in role["rules"] for v in rule["verbs"]}
        self.assertEqual(verbs, {"get", "list"})
        resources = {r for rule in role["rules"] for r in rule["resources"]}
        self.assertEqual(resources, {"pods", "pods/log", "events", "deployments"})
        self.assertNotIn("secrets", json.dumps(role))
        binding = find(self.items, "RoleBinding", "harvis-backend-viewer")
        self.assertEqual(binding["subjects"], [{"kind": "ServiceAccount", "name": "harvis-backend", "namespace": "harvis"}])

    def test_backend_gets_its_host_mount_table(self):
        table = json.loads(find(render("--build-space"), "Secret", "backend-env")["stringData"]["HARVIS_HOST_MOUNTS"])
        self.assertIn({"Destination": "/data/artifacts",
                       "Source": "/var/lib/docker/volumes/harvis_artifact_data/_data"}, table)
        self.assertIn({"Destination": "/var/run/docker.sock", "Source": "/var/run/docker.sock"}, table)

    def test_user_groups_and_host_gateway(self):
        spec = pod(render("--build-space"), "backend")
        self.assertEqual(spec["securityContext"], {"runAsUser": 1001, "runAsGroup": 1001, "supplementalGroups": [984],
                                                  "seccompProfile": {"type": "RuntimeDefault"}})
        self.assertEqual(spec["hostAliases"], [{"ip": "10.0.0.5", "hostnames": ["host.docker.internal"]}])
        self.assertEqual(find(self.items, "Deployment", "backend")["spec"]["template"]["spec"]["containers"][0]
                         ["imagePullPolicy"], "Never")

    def test_container_name_is_a_dns_alias(self):
        svc = find(self.items, "Service", "pgsql-db")
        self.assertEqual(svc["spec"]["clusterIP"], "None")
        self.assertEqual(svc["spec"]["selector"], {"app.kubernetes.io/name": "pgsql"})

    def test_only_public_ports_get_a_load_balancer(self):
        lbs = [o for o in self.items if o["kind"] == "Service" and o["spec"].get("type") == "LoadBalancer"]
        self.assertEqual([o["metadata"]["name"] for o in lbs], ["nginx-public"])
        self.assertEqual([p["port"] for p in lbs[0]["spec"]["ports"]], [9000])

    def test_healthcheck_becomes_readiness_probe(self):
        probe = pod(self.items, "pgsql")["containers"][0]["readinessProbe"]
        self.assertEqual(probe["exec"]["command"], ["sh", "-c", "pg_isready -U pguser"])
        self.assertEqual(probe["failureThreshold"], 5)

    def test_nginx_config_is_patched_for_cluster_dns(self):
        data = find(self.items, "ConfigMap", "nginx-conf")["data"]
        self.assertIn("resolver 10.43.0.10 valid=10s", data["nginx.conf"])
        self.assertIn("http://backend.harvis.svc.cluster.local:8000;", data["harvis.conf"])
        # The tunnel entrance's Access check (a path after the port) resolves too.
        self.assertIn("http://backend.harvis.svc.cluster.local:8000/api/tunnel/verify;", data["nginx.conf"])
        self.assertNotIn("http://backend:", data["nginx.conf"] + data["harvis.conf"])
        mounts = pod(self.items, "nginx")["containers"][0]["volumeMounts"]
        self.assertEqual({m.get("subPath") for m in mounts if m.get("subPath")}, {"nginx.conf", "harvis.conf"})

    def test_internal_only_service_cannot_reach_out(self):
        pol = find(self.items, "NetworkPolicy", "internal-only-preview-runner")
        self.assertEqual(pol["spec"]["policyTypes"], ["Egress"])
        self.assertIsNone(find(self.items, "NetworkPolicy", "internal-only-backend"))
        labels = find(self.items, "Deployment", "preview-runner")["spec"]["template"]["metadata"]["labels"]
        self.assertEqual(labels.get("harvis.net/preview-net"), "1")

    def test_gpu_only_when_asked(self):
        self.assertNotIn("runtimeClassName", pod(self.items, "llmfit"))
        self.assertEqual(pod(render("--gpu"), "llmfit")["runtimeClassName"], "nvidia")

    def test_one_gpu_box_requests_the_card_once(self):
        items = render("--gpu", "--ollama-image", "ollama/ollama:0.20.2")
        wants = [d["metadata"]["name"] for d in items if d.get("kind") == "Deployment"
                 for c in d["spec"]["template"]["spec"]["containers"]
                 if "nvidia.com/gpu" in (c.get("resources") or {}).get("limits", {})]
        self.assertEqual(wants, ["ollama"])

    def test_model_server_fits_beside_the_rest_on_a_small_machine(self):
        # A limit-only service, like voice-onnx's 2 GB: the scheduler counts it in full.
        COMPOSE["services"]["pgsql"]["deploy"] = {"resources": {"limits": {"memory": str(2 * 2**30)}}}
        try:
            items = render("--ollama-image", "ollama/ollama:0.20.2",
                           "--node-memory", "4Gi", "--node-cpu", "2")
        finally:
            del COMPOSE["services"]["pgsql"]["deploy"]
        res = pod(items, "ollama")["containers"][0]["resources"]
        # What the scheduler counts: the request, or the limit when only that is set.
        others = sum(k8s_common.quantity({**c.get("resources", {}).get("limits", {}),
                                          **c.get("resources", {}).get("requests", {})}.get("memory")) or 0
                     for d in items if d.get("kind") == "Deployment" and d["metadata"]["name"] != "ollama"
                     for c in d["spec"]["template"]["spec"]["containers"])
        need = k8s_common.quantity(res["requests"]["memory"])
        self.assertLessEqual(others + need, 4 * 2**30)
        self.assertLess(need, 6 * 2**30)
        self.assertLessEqual(k8s_common.quantity(res["limits"]["memory"]), 4 * 2**30)

    def test_model_server_keeps_its_ceiling_on_a_big_machine(self):
        res = pod(render("--ollama-image", "ollama/ollama:0.20.2", "--node-memory", "64Gi", "--node-cpu", "16"),
                  "ollama")["containers"][0]["resources"]
        self.assertEqual(res["requests"], {"memory": "6144Mi", "cpu": "2000m"})
        self.assertEqual(res["limits"], {"memory": "10240Mi"})

    def test_quantity_reads_kubernetes_units(self):
        self.assertEqual(k8s_common.quantity("6Gi"), 6 * 2**30)
        self.assertEqual(k8s_common.quantity("3500m"), 3.5)
        self.assertEqual(k8s_common.quantity("4"), 4)
        self.assertIsNone(k8s_common.quantity(""))

    def test_no_ollama_or_lan_endpoint_by_default(self):
        self.assertIsNone(find(self.items, "Deployment", "ollama"))
        self.assertIsNone(find(self.items, "Deployment", "lan-models"))

    def test_lan_endpoint_allows_chat_and_listing_only(self):
        items = render("--ollama-image", "ollama/ollama:0.20.2", "--lan-models-port", "11434",
                       "--lan-models-url", "http://10.0.0.5:11434")
        conf = find(items, "ConfigMap", "lan-models")["data"]["default.conf"]
        allowed = re.search(r"location ~ \^\((.*)\)\$", conf).group(1)
        rx = re.compile(f"^({allowed})$")
        for path in ("/v1/chat/completions", "/v1/models", "/api/chat", "/api/tags"):
            self.assertTrue(rx.match(path), path)
        for path in ("/api/pull", "/api/delete", "/api/create", "/api/push", "/api/copy", "/api/chat/x"):
            self.assertFalse(rx.match(path), path)
        self.assertIn("return 403", conf)
        self.assertEqual(find(items, "Service", "lan-models")["spec"]["ports"][0]["port"], 11434)
        env = find(items, "Secret", "backend-env")["stringData"]
        self.assertEqual(env["HARVIS_LAN_MODELS_URL"], "http://10.0.0.5:11434")

    def test_shared_models_are_rate_limited_per_visitor(self):
        items = render("--ollama-image", "ollama/ollama:0.20.2", "--lan-models-port", "11434",
                       "--lan-models-url", "http://10.0.0.5:11434")
        conf = find(items, "ConfigMap", "lan-models")["data"]["default.conf"]
        for line in ("limit_req zone=lan_models", "limit_conn lan_models_conn 4", "proxy_read_timeout 300s",
                     "client_max_body_size 16m", "server_tokens off"):
            self.assertIn(line, conf)
        env = {e["name"]: e["value"] for e in pod(items, "ollama")["containers"][0]["env"]}
        self.assertEqual(env["OLLAMA_NO_CLOUD"], "1")
        self.assertEqual(env["OLLAMA_NUM_PARALLEL"], "2")
        self.assertEqual(env["OLLAMA_HOST"], "0.0.0.0")

    def test_config_change_rolls_the_pod(self):
        before = find(self.items, "Deployment", "pgsql")["spec"]["template"]["metadata"]["annotations"]
        COMPOSE["services"]["pgsql"]["environment"]["POSTGRES_PASSWORD"] = "other"
        try:
            after = find(render(), "Deployment", "pgsql")["spec"]["template"]["metadata"]["annotations"]
        finally:
            COMPOSE["services"]["pgsql"]["environment"]["POSTGRES_PASSWORD"] = "s3cret"
        self.assertNotEqual(before, after)

    def test_rebuilt_image_rolls_only_the_pods_that_run_it(self):
        # Images keep their tag when rebuilt, so only a changed content id tells k8s to restart.
        backend_image = pod(self.items, "backend")["containers"][0]["image"]

        def hashes(ids):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                json.dump(ids, fh)
            try:
                items = render("--image-ids", fh.name)
            finally:
                os.unlink(fh.name)
            return {n: find(items, "Deployment", n)["spec"]["template"]["metadata"]["annotations"]
                    for n in ("backend", "pgsql")}

        first = hashes({backend_image: "id-1"})
        rebuilt = hashes({backend_image: "id-2"})
        self.assertNotEqual(first["backend"], rebuilt["backend"])
        self.assertEqual(first["pgsql"], rebuilt["pgsql"])
        self.assertEqual(hashes({backend_image: "id-1"}), first)

    def test_backend_is_health_checked_and_never_best_effort(self):
        c = pod(self.items, "backend")["containers"][0]
        self.assertEqual(c["livenessProbe"]["httpGet"], {"port": 8000, "path": "/health"})
        self.assertGreaterEqual(c["startupProbe"]["periodSeconds"] * c["startupProbe"]["failureThreshold"], 600)
        self.assertTrue(c["resources"]["requests"])

    def test_net_label_is_a_valid_label_key(self):
        self.assertEqual(k8s_extras.net_label("ollama-n8n-network"), "harvis.net/ollama-n8n-network")


def with_tunnel(compose):
    c = json.loads(json.dumps(compose))
    c["networks"]["tunnel-edge"] = {"name": "harvis_tunnel-edge"}
    c["services"]["nginx"]["networks"]["tunnel-edge"] = None
    c["services"]["cloudflared"] = {
        "image": "cloudflare/cloudflared:1@sha256:abc", "restart": "unless-stopped",
        "command": ["tunnel", "--no-autoupdate", "run"], "environment": {"TUNNEL_TOKEN": "t"},
        "depends_on": {"nginx": {"condition": "service_started"}}, "networks": {"tunnel-edge": None}}
    return c


class TunnelTest(unittest.TestCase):
    def render(self, *extra):
        global COMPOSE
        saved, COMPOSE = COMPOSE, with_tunnel(COMPOSE)
        try:
            return render(*extra)
        finally:
            COMPOSE = saved

    def test_nginx_tunnel_entrance_is_only_for_cloudflared(self):
        for items in (render(), self.render()):
            rules = find(items, "NetworkPolicy", "public-nginx")["spec"]["ingress"]
            open_ports = {p["port"] for r in rules if "from" not in r for p in r["ports"]}
            self.assertEqual(open_ports, {80, 443})
            entrance = [r for r in rules if "from" in r]
            self.assertEqual(entrance[0]["from"], [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "cloudflared"}}}])
            self.assertEqual(entrance[0]["ports"], [{"protocol": "TCP", "port": 8081}])

    def test_shared_networks_do_not_open_nginx(self):
        # Policies add up: a net-* rule selecting nginx would open 8081 to every pod on that network.
        for items in (render(), self.render()):
            for o in items:
                if o["kind"] == "NetworkPolicy" and o["metadata"]["name"].startswith("net-"):
                    self.assertIn({"key": "app.kubernetes.io/name", "operator": "NotIn", "values": ["nginx"]},
                                  o["spec"]["podSelector"]["matchExpressions"])

    def test_cloudflared_reaches_only_nginx_8081_dns_and_the_internet(self):
        items = self.render()
        self.assertEqual(set(pod(items, "cloudflared")["nodeSelector"]), {"kubernetes.io/hostname"})
        labels = find(items, "Deployment", "cloudflared")["spec"]["template"]["metadata"]["labels"]
        self.assertFalse([k for k in labels if k.startswith("harvis.net/")])
        egress = find(items, "NetworkPolicy", "cloudflared-egress")["spec"]["egress"]
        self.assertEqual(egress[0]["ports"], [{"protocol": "TCP", "port": 8081}])
        internet = egress[2]["to"][0]["ipBlock"]
        self.assertEqual(internet["cidr"], "0.0.0.0/0")
        for private in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"):
            self.assertIn(private, internet["except"])
        self.assertEqual(find(items, "NetworkPolicy", "cloudflared-no-ingress")["spec"]["ingress"], [])

    def test_cloudflared_runs_locked_down_with_readiness(self):
        items = self.render()
        dep = find(items, "Deployment", "cloudflared")
        self.assertEqual(dep["spec"]["replicas"], 2)
        c = dep["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(c["args"][:3], ["tunnel", "--metrics", "0.0.0.0:2000"])
        self.assertEqual(c["readinessProbe"]["httpGet"], {"port": 2000, "path": "/ready"})
        sc = c["securityContext"]
        self.assertTrue(sc["runAsNonRoot"] and sc["readOnlyRootFilesystem"])
        self.assertFalse(sc["allowPrivilegeEscalation"])
        self.assertNotIn("TUNNEL_TOKEN", json.dumps(c))  # from the Secret, not the spec

    def test_network_lock_renders_it_stopped(self):
        self.assertEqual(find(self.render("--tunnel-replicas", "0"), "Deployment", "cloudflared")["spec"]["replicas"], 0)

    def test_no_tunnel_objects_without_the_profile(self):
        self.assertFalse([o for o in render() if "cloudflared" in o["metadata"]["name"]])

    def test_backups_are_private(self):
        script = find(render(), "CronJob", "pgsql-backup")
        cmd = script["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["command"][2]
        self.assertIn("umask 077", cmd)
        self.assertLess(cmd.index("pg_isready"), cmd.index("pg_dump"))  # boot catch-up waits for pgsql

    def test_public_ports_keep_the_visitor_address(self):
        for o in render():
            if o["kind"] == "Service" and o["spec"].get("type") == "LoadBalancer":
                self.assertEqual(o["spec"]["externalTrafficPolicy"], "Local", o["metadata"]["name"])
                self.assertFalse(o["spec"]["allocateLoadBalancerNodePorts"], o["metadata"]["name"])

    def test_agent_browser_reaches_public_addresses_only(self):
        pol = find(render(), "NetworkPolicy", "browser-runner-public-only")
        self.assertEqual(pol["spec"]["podSelector"]["matchLabels"], {"app.kubernetes.io/name": "browser-runner"})
        public = [r for r in pol["spec"]["egress"] if r["to"][0].get("ipBlock")]
        self.assertEqual(len(public), 1)
        self.assertIn("192.168.0.0/16", public[0]["to"][0]["ipBlock"]["except"])
        self.assertIn("10.0.0.0/8", public[0]["to"][0]["ipBlock"]["except"])
        opened = find(render("--browser-allow-cidr", "192.168.50.7/24"), "NetworkPolicy", "browser-runner-public-only")
        self.assertIn({"to": [{"ipBlock": {"cidr": "192.168.50.0/24"}}]}, opened["spec"]["egress"])
        with self.assertRaises(SystemExit):
            render("--browser-allow-cidr", "not-a-range")

    def test_every_pod_is_hardened(self):
        pods = [o for o in render() if o["kind"] in ("Deployment", "CronJob")]
        self.assertTrue(pods)
        for o in pods:
            spec = (o["spec"]["jobTemplate"]["spec"] if o["kind"] == "CronJob" else o["spec"])["template"]["spec"]
            self.assertEqual(spec["securityContext"]["seccompProfile"], {"type": "RuntimeDefault"})
            for c in spec["containers"] + spec.get("initContainers", []):
                sc = c["securityContext"]
                if sc.get("privileged"):
                    self.assertNotIn("allowPrivilegeEscalation", sc)
                    continue
                self.assertIs(sc["allowPrivilegeEscalation"], False, c["name"])
                self.assertTrue(sc["capabilities"]["drop"], c["name"])


def host_paths(items, name):
    return {v["hostPath"]["path"] for v in pod(items, name)["volumes"] if "hostPath" in v}


class HostAccessTest(unittest.TestCase):
    """The backend's docker.sock and host /tmp mounts (see k8s_build_space)."""

    def test_docker_socket_is_not_mounted_unless_asked(self):
        items = render()
        spec = pod(items, "backend")
        self.assertNotIn("/var/run/docker.sock", host_paths(items, "backend"))
        self.assertNotIn("/var/run/docker.sock", [m["mountPath"] for m in spec["containers"][0]["volumeMounts"]])
        self.assertNotIn("supplementalGroups", spec["securityContext"])
        self.assertEqual(spec["securityContext"]["runAsUser"], 1001)
        env = find(items, "Secret", "backend-env")["stringData"]
        self.assertEqual(env["HARVIS_BUILD_SPACE_DOCKER"], "0")
        self.assertNotIn("docker.sock", env["HARVIS_HOST_MOUNTS"])

    def test_build_space_option_keeps_the_socket_and_its_group(self):
        items = render("--build-space")
        spec = pod(items, "backend")
        self.assertIn("/var/run/docker.sock", host_paths(items, "backend"))
        self.assertIn("/var/run/docker.sock", [m["mountPath"] for m in spec["containers"][0]["volumeMounts"]])
        self.assertEqual(spec["securityContext"]["supplementalGroups"], [984])
        self.assertNotIn("HARVIS_BUILD_SPACE_DOCKER", find(items, "Secret", "backend-env")["stringData"])

    def test_turning_build_space_on_rolls_the_backend(self):
        def annotations(*extra):
            return find(render(*extra), "Deployment", "backend")["spec"]["template"]["metadata"]["annotations"]
        self.assertNotEqual(annotations(), annotations("--build-space"))

    def test_the_rendered_compose_config_is_not_edited_in_place(self):
        render()
        backend = COMPOSE["services"]["backend"]
        self.assertIn("/var/run/docker.sock", [v["source"] for v in backend["volumes"]])
        self.assertEqual(backend["group_add"], ["984"])

    def test_backend_tmp_is_a_private_scratch_directory(self):
        for extra in ((), ("--build-space",)):
            items = render(*extra)
            spec = pod(items, "backend")
            self.assertNotIn("/tmp", host_paths(items, "backend"))
            mount = next(m for m in spec["containers"][0]["volumeMounts"] if m["mountPath"] == "/tmp")
            vol = next(v for v in spec["volumes"] if v["name"] == mount["name"])
            self.assertEqual(vol, {"name": mount["name"], "emptyDir": {}})
            self.assertNotIn('"/tmp"', find(items, "Secret", "backend-env")["stringData"]["HARVIS_HOST_MOUNTS"])

    def test_read_only_tmp_for_other_services_is_left_alone(self):
        items = render()
        self.assertIn("/tmp", host_paths(items, "nginx"))
        mount = next(m for m in pod(items, "nginx")["containers"][0]["volumeMounts"] if m["mountPath"] == "/tmp")
        self.assertTrue(mount["readOnly"])


class SplitModulesTest(unittest.TestCase):
    """k8s_extras was split into k8s_common / k8s_models; the output must not move."""

    OLLAMA = ("--ollama-image", "ollama/ollama:0.20.2", "--lan-models-port", "11434",
              "--lan-models-url", "http://10.0.0.5:11434", "--node-memory", "10161480Ki", "--node-cpu", "4")

    def test_every_module_stays_under_500_lines(self):
        here = os.path.dirname(os.path.abspath(__file__))
        for name in sorted(f for f in os.listdir(here) if f.endswith(".py")):
            with open(os.path.join(here, name)) as fh:
                self.assertLess(len(fh.readlines()), 500, name)

    def test_model_server_and_lan_endpoint_objects(self):
        items = render(*self.OLLAMA)
        added = {(o["kind"], o["metadata"]["name"]) for o in items
                 if o["metadata"]["name"] in ("ollama", "lan-models", "public-lan-models", "ollama-from-lan-models")}
        self.assertEqual(added, {("Deployment", "ollama"), ("Service", "ollama"), ("ConfigMap", "lan-models"),
                                 ("Deployment", "lan-models"), ("Service", "lan-models"),
                                 ("NetworkPolicy", "public-lan-models"), ("NetworkPolicy", "ollama-from-lan-models")})
        c = pod(items, "ollama")["containers"][0]
        self.assertEqual(c["readinessProbe"]["exec"]["command"], ["ollama", "list"])
        self.assertEqual(c["startupProbe"]["httpGet"], {"port": 11434, "path": "/"})
        self.assertEqual(c["volumeMounts"], [{"name": "models", "mountPath": "/root/.ollama"}])
        self.assertEqual(find(items, "Deployment", "ollama")["spec"]["template"]["metadata"]["labels"]
                         ["harvis.net/ollama-n8n-network"], "1")
        lan = find(items, "Service", "lan-models")["spec"]
        self.assertEqual((lan["type"], lan["externalTrafficPolicy"], lan["allocateLoadBalancerNodePorts"]),
                         ("LoadBalancer", "Local", False))
        self.assertEqual(lan["ports"], [{"name": "http", "port": 11434, "targetPort": 8080}])
        proxy = pod(items, "lan-models")["containers"][0]
        self.assertEqual(proxy["image"], "nginx:1.29")
        self.assertEqual(proxy["readinessProbe"]["httpGet"], {"port": 8080, "path": "/"})
        conf = find(items, "ConfigMap", "lan-models")["data"]["default.conf"]
        self.assertIn("resolver 10.43.0.10 valid=10s ipv6=off;", conf)
        self.assertIn("set $ollama http://ollama.harvis.svc.cluster.local:11434;", conf)
        hashed = find(items, "Deployment", "lan-models")["spec"]["template"]["metadata"]["annotations"]
        self.assertEqual(hashed["harvis.dev/config-hash"], hashlib.sha256(conf.encode()).hexdigest()[:16])


if __name__ == "__main__":
    unittest.main()
