"""Compose network checks that the firewall scripts depend on.

The backend sits on ollama-n8n-network and, in docker-compose.yaml, on repo-sandbox
too. Docker chooses the default route by network name unless gw_priority says
otherwise, and "harvis_repo-sandbox" sorts first. Without the pin, the backend's
traffic to host Ollama and LAN model servers leaves from the repo-sandbox subnet,
which scripts/browser-egress-lock.sh and scripts/ollama-lan-lock.sh drop.

HARVIS_TEST_COMPOSE_ROOT points the test at another directory holding copies of the
two compose files; the mutation check in the review notes uses it.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(os.environ.get("HARVIS_TEST_COMPOSE_ROOT") or Path(__file__).resolve().parents[1])
DUMMY = {"JWT_SECRET": "test-jwt-only", "POSTGRES_PASSWORD": "test-password-only", "HARVIS_GATEWAY_TOKEN": "test-gateway-only"}
FILES = ("docker-compose.yaml", "docker-compose.prebuilt.yml")


def render(name):
    # Empty env file and a clean environment: never read the real .env.
    with tempfile.TemporaryDirectory() as tmp:
        env = {"PATH": os.environ["PATH"], "HOME": tmp, **DUMMY}
        proc = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", str(ROOT / name), "config", "--format", "json"],
                              env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


class BackendDefaultRoute(unittest.TestCase):
    def test_backend_default_route_is_pinned_to_ollama_n8n_network(self):
        for name in FILES:
            with self.subTest(file=name):
                cfg = render(name)
                backend_nets = cfg["services"]["backend"]["networks"]
                self.assertEqual((backend_nets["ollama-n8n-network"] or {}).get("gw_priority"), 1)

    def test_no_other_network_with_a_gateway_outranks_it_on_the_backend(self):
        for name in FILES:
            with self.subTest(file=name):
                cfg = render(name)
                with_gateway = {n for n, v in cfg["networks"].items() if not v.get("internal")}
                nets = cfg["services"]["backend"]["networks"]
                pinned = (nets["ollama-n8n-network"] or {}).get("gw_priority", 0)
                for net in with_gateway - {"ollama-n8n-network"}:
                    if net in nets:
                        self.assertLess((nets[net] or {}).get("gw_priority", 0), pinned, net)

    def test_backend_keeps_the_repo_sandbox_network_in_the_main_file(self):
        # The pin matters because of this attachment: if it goes away the test above
        # is guarding nothing, so say so rather than pass silently.
        cfg = render("docker-compose.yaml")
        self.assertIn("repo-sandbox", cfg["services"]["backend"]["networks"])

    def test_bundled_openclaw_network_and_services_are_gone(self):
        # Retired 2026-10-30: OpenClaw is an optional external link, not a service here.
        for name in FILES:
            with self.subTest(file=name):
                cfg = render(name)
                self.assertNotIn("openclaw-internal", cfg["networks"])
                for svc in ("openclaw", "openclaw-db-init"):
                    self.assertNotIn(svc, cfg["services"])
                for svc_name, svc in cfg["services"].items():
                    self.assertNotIn("openclaw-internal", svc.get("networks", {}), svc_name)


if __name__ == "__main__":
    unittest.main()
