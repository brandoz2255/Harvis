"""Offline security regression checks for the prebuilt Compose configuration."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.prebuilt.yml"
DUMMY = {"JWT_SECRET": "test-jwt-only", "POSTGRES_PASSWORD": "test-password-only", "HARVIS_GATEWAY_TOKEN": "test-gateway-only"}


def render(values):
    # An explicit empty env file and a clean environment prevent reading real secrets.
    with tempfile.TemporaryDirectory() as tmp:
        env = {"PATH": os.environ["PATH"], "HOME": tmp, **values}
        return subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", str(COMPOSE), "config", "--format", "json"], env=env, text=True, capture_output=True)


class PrebuiltComposeSecurity(unittest.TestCase):
    def test_nginx_harvis_config_is_mounted_read_only(self):
        result = render(DUMMY)
        self.assertEqual(result.returncode, 0, result.stderr)
        volumes = json.loads(result.stdout)["services"]["nginx"]["volumes"]
        matching = [v for v in volumes if v.get("target") == "/etc/nginx/harvis.conf"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(Path(matching[0]["source"]), ROOT / "nginx-harvis.conf")
        self.assertTrue(matching[0].get("read_only"))

    def test_all_published_ports_default_to_loopback(self):
        result = render(DUMMY)
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual({name for name, service in services.items() if service.get("ports")},
                         {"ollama", "backend", "frontend", "nginx", "pgsql"})
        for name, service in services.items():
            for port in service.get("ports", []):
                with self.subTest(service=name, port=port):
                    self.assertEqual(port.get("host_ip"), "127.0.0.1")

    def test_missing_and_empty_credentials_fail_closed(self):
        for key in DUMMY:
            for value in (None, ""):
                env = dict(DUMMY)
                if value is None:
                    env.pop(key)
                else:
                    env[key] = value
                with self.subTest(key=key, value=value):
                    self.assertNotEqual(render(env).returncode, 0)

    def test_bundled_openclaw_is_retired(self):
        result = render(DUMMY)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        for name in ("openclaw", "openclaw-db-init"):
            self.assertNotIn(name, config["services"])
        self.assertNotIn("openclaw-internal", config.get("networks", {}))
        self.assertNotIn("openclaw-data", config.get("volumes", {}))
        for name, service in config["services"].items():
            with self.subTest(service=name):
                self.assertNotIn("openclaw-internal", service.get("networks", {}))

    def test_legacy_gateway_token_is_supported_and_shared(self):
        env = dict(DUMMY)
        env.pop("HARVIS_GATEWAY_TOKEN")
        env["OPENCLAW_GATEWAY_TOKEN"] = "test-legacy-only"
        result = render(env)
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(services["backend"]["environment"]["OPENCLAW_GATEWAY_TOKEN"], "test-legacy-only")

    def test_primary_gateway_token_takes_precedence(self):
        result = render({**DUMMY, "OPENCLAW_GATEWAY_TOKEN": "test-legacy-only"})
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(services["backend"]["environment"]["OPENCLAW_GATEWAY_TOKEN"], DUMMY["HARVIS_GATEWAY_TOKEN"])


if __name__ == "__main__":
    unittest.main()
