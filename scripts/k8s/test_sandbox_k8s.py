"""The document sandbox must come out of the generator walled in.  Run: python3 -m pytest scripts/k8s -q"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_compose_to_k8s as base  # noqa: E402
from k8s_common import tmpfs_volume  # noqa: E402

SANDBOX = {
    "image": "harvis-sandbox:latest", "restart": "unless-stopped", "user": "1001:1001",
    "read_only": True, "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
    "tmpfs": ["/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777"],
    "pids_limit": 256, "mem_limit": 2147483648,
    "deploy": {"resources": {"limits": {"memory": "2147483648", "cpus": 2.0, "pids": 256}}},
    "networks": {"sandbox-net": None},
}


def render_with_sandbox():
    compose = copy.deepcopy(base.COMPOSE)
    compose["networks"]["sandbox-net"] = {"name": "harvis_sandbox-net", "internal": True}
    compose["services"]["sandbox"] = copy.deepcopy(SANDBOX)
    compose["services"]["backend"]["networks"]["sandbox-net"] = None
    compose["services"]["document-worker"] = {
        "image": "harvis-document-worker:latest", "restart": "unless-stopped",
        "networks": {"ollama-n8n-network": None, "sandbox-net": None},
    }
    with mock.patch.object(base, "COMPOSE", compose):
        return base.render()


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.items = render_with_sandbox()
        self.spec = base.pod(self.items, "sandbox")
        self.main = self.spec["containers"][0]

    def test_no_host_path_anywhere(self):
        self.assertFalse([v for v in self.spec.get("volumes", []) if "hostPath" in v])

    def test_container_is_locked_down(self):
        ctx = self.main["securityContext"]
        self.assertTrue(ctx["readOnlyRootFilesystem"])
        self.assertEqual(ctx["capabilities"]["drop"], ["ALL"])
        self.assertFalse(ctx.get("privileged", False))

    def test_scratch_space_is_memory_backed_and_capped(self):
        mount = next(m for m in self.main["volumeMounts"] if m["mountPath"] == "/tmp")
        vol = next(v for v in self.spec["volumes"] if v["name"] == mount["name"])
        self.assertEqual(vol["emptyDir"]["medium"], "Memory")
        self.assertEqual(vol["emptyDir"]["sizeLimit"], "512Mi")

    def test_resources_carry_the_compose_limits(self):
        limits = self.main["resources"]["limits"]
        self.assertEqual(limits["memory"], "2147483648")
        self.assertEqual(str(limits["cpu"]), "2")

    def test_policy_denies_all_egress_and_admits_only_the_two_callers(self):
        policy = base.find(self.items, "NetworkPolicy", "sandbox-isolated")
        spec = policy["spec"]
        self.assertEqual(set(spec["policyTypes"]), {"Ingress", "Egress"})
        self.assertEqual(spec["egress"], [])
        callers = {v for r in spec["ingress"] for peer in r["from"]
                   for e in peer["podSelector"]["matchExpressions"] for v in e["values"]}
        self.assertEqual(callers, {"backend", "document-worker"})
        self.assertEqual({p["port"] for r in spec["ingress"] for p in r["ports"]}, {8080})

    def test_no_internal_only_policy_that_would_leave_a_hole(self):
        self.assertIsNone(base.find(self.items, "NetworkPolicy", "internal-only-sandbox"))


class TmpfsSizeTest(unittest.TestCase):
    def test_docker_sizes_become_kubernetes_quantities(self):
        for given, want in (("512m", "512Mi"), ("1g", "1Gi"), ("64k", "64Ki"), (1048576, "1048576")):
            self.assertEqual(tmpfs_volume("t", given)["emptyDir"]["sizeLimit"], want)
        self.assertNotIn("sizeLimit", tmpfs_volume("t", None)["emptyDir"])
        self.assertNotIn("sizeLimit", tmpfs_volume("t", "junk")["emptyDir"])


if __name__ == "__main__":
    unittest.main()
