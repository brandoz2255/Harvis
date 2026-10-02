"""Tests for the compose → Kubernetes generator.  Run: python3 -m pytest scripts/k8s -q"""

import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import compose_to_k8s as gen  # noqa: E402
import k8s_extras  # noqa: E402

NGINX_CONF = "http {\n    resolver 127.0.0.11 valid=10s ipv6=off;\n    include /etc/nginx/harvis.conf;\n}\n"
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
                        {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}],
            "networks": {"ollama-n8n-network": None, "preview-net": None},
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
                        {"type": "bind", "source": "REPO/nginx-harvis.conf", "target": "/etc/nginx/harvis.conf", "read_only": True}],
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

    def test_backend_gets_its_host_mount_table(self):
        table = json.loads(find(self.items, "Secret", "backend-env")["stringData"]["HARVIS_HOST_MOUNTS"])
        self.assertIn({"Destination": "/data/artifacts",
                       "Source": "/var/lib/docker/volumes/harvis_artifact_data/_data"}, table)
        self.assertIn({"Destination": "/var/run/docker.sock", "Source": "/var/run/docker.sock"}, table)

    def test_user_groups_and_host_gateway(self):
        spec = pod(self.items, "backend")
        self.assertEqual(spec["securityContext"], {"runAsUser": 1001, "runAsGroup": 1001, "supplementalGroups": [984]})
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
        mounts = pod(self.items, "nginx")["containers"][0]["volumeMounts"]
        self.assertEqual({m.get("subPath") for m in mounts}, {"nginx.conf", "harvis.conf"})

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


if __name__ == "__main__":
    unittest.main()
