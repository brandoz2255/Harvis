"""Chat boxes as pods (k8s_boxes.py).  Run: python3 -m pytest scripts/k8s -q"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_compose_to_k8s import find, render  # noqa: E402


class BoxesTest(unittest.TestCase):
    def setUp(self):
        self.items = render()
        self.env = find(self.items, "Secret", "backend-env")["stringData"]

    def test_backend_is_told_to_run_boxes_as_pods(self):
        self.assertEqual(self.env["HARVIS_K8S_BOXES"], "1")
        self.assertEqual(self.env["HARVIS_K8S_BOX_NAMESPACE"], "harvis-boxes")
        self.assertEqual(self.env["HARVIS_K8S_BOX_ROOT"], "/data/artifacts/sandboxes")
        self.assertEqual(self.env["HARVIS_K8S_BOX_NODE"], "n1")
        self.assertEqual(self.env["HARVIS_BUILD_RUNNER_SUDO"], "false")

    def test_box_namespace_enforces_restricted_pod_security(self):
        ns = find(self.items, "Namespace", "harvis-boxes")
        self.assertEqual(ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"], "restricted")

    def test_every_box_pod_is_denied_all_traffic(self):
        pol = find(self.items, "NetworkPolicy", "boxes-deny-all")
        self.assertEqual(pol["metadata"]["namespace"], "harvis-boxes")
        self.assertEqual(pol["spec"], {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]})

    def test_volume_points_at_the_chat_folders_on_the_host(self):
        pv = find(self.items, "PersistentVolume", "harvis-harvis-box-sandboxes")
        self.assertEqual(pv["spec"]["hostPath"]["path"],
                         "/var/lib/docker/volumes/harvis_artifact_data/_data/sandboxes")
        self.assertEqual(pv["spec"]["persistentVolumeReclaimPolicy"], "Retain")
        self.assertEqual(pv["spec"]["claimRef"], {"namespace": "harvis-boxes", "name": "harvis-box-sandboxes"})

    def test_backend_may_only_manage_pods_in_the_box_namespace(self):
        role = find(self.items, "Role", "harvis-box-runner")
        self.assertEqual(role["metadata"]["namespace"], "harvis-boxes")
        resources = {r for rule in role["rules"] for r in rule["resources"]}
        self.assertEqual(resources, {"pods", "pods/exec"})
        binding = find(self.items, "RoleBinding", "harvis-box-runner")
        self.assertEqual(binding["subjects"][0]["namespace"], "harvis")

    def test_namespace_comes_before_its_objects(self):
        ns_at = next(i for i, o in enumerate(self.items)
                     if o["kind"] == "Namespace" and o["metadata"]["name"] == "harvis-boxes")
        for i, o in enumerate(self.items):
            if o["metadata"].get("namespace") == "harvis-boxes":
                self.assertGreater(i, ns_at)

    def test_build_space_uses_docker_and_makes_none_of_this(self):
        items = render("--build-space")
        env = find(items, "Secret", "backend-env")["stringData"]
        self.assertNotIn("HARVIS_K8S_BOXES", env)
        self.assertIsNone(find(items, "Namespace", "harvis-boxes"))
        self.assertIsNone(find(items, "PersistentVolume", "harvis-harvis-box-sandboxes"))


if __name__ == "__main__":
    unittest.main()


class BlockedNetworksTest(unittest.TestCase):
    def test_agent_browser_may_not_reach_a_blocked_public_range(self):
        items = render("--blocked-cidr", "203.0.113.0/24")
        pol = find(items, "NetworkPolicy", "browser-runner-public-only")
        excepts = [x for rule in pol["spec"]["egress"] for to in rule.get("to", [])
                   for x in (to.get("ipBlock") or {}).get("except", [])]
        self.assertIn("203.0.113.0/24", excepts)

    def test_a_typo_stops_the_install(self):
        with self.assertRaises(SystemExit):
            render("--blocked-cidr", "203.0.113/99")
