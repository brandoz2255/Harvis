"""scripts/enable-https.sh on plain Docker and on Kubernetes, and the HTTPS guidance install.sh prints."""

import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

REPO = os.path.dirname(os.path.dirname(HERE))
ENABLE_HTTPS = os.path.join(REPO, "scripts", "enable-https.sh")


class EnableHttpsTest(unittest.TestCase):
    """enable-https.sh in a scratch checkout, with fake sudo, k3s, docker and ip on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        self.root = os.path.join(t, "repo")
        self.rec = os.path.join(t, "rec")
        self.pod_tls = os.path.join(t, "pod-tls")
        for d in (os.path.join(self.root, "scripts"), os.path.join(self.root, "nginx", "tls"), self.rec, self.pod_tls, os.path.join(t, "bin")):
            os.makedirs(d)
        shutil.copy(ENABLE_HTTPS, os.path.join(self.root, "scripts", "enable-https.sh"))
        with open(os.path.join(self.root, "nginx", "tls", "harvis-tls.conf.template"), "w") as fh:
            fh.write("server { listen 443 ssl; }\n")
        for name, body in (
            ("sudo", 'exec "$@"'),
            ("k3s", 'echo "$*" >> "$REC/k3s.log"\ncase "$*" in\n'
                    '  *"volumeMounts[?"*) printf %s "${FAKE_MOUNT_NAME-tls}" ;;\n'
                    '  *"volumes[?"*) printf %s "${FAKE_HOST_TLS-}" ;;\n'
                    '  *"nginx -t"*) echo "nginx: test output"; exit "${FAKE_NGINX_T_RC:-0}" ;;\n'
                    '  *"rollout status"*) exit "${FAKE_STATUS_RC:-0}" ;;\nesac'),
            ("docker", 'echo "$*" >> "$REC/docker.log"'),
            # eth0 is a real address; the k3s bridge and flannel are not ones anyone types.
            ("ip", 'printf "2: eth0    inet 192.168.1.50/24 brd 192.168.1.255 scope global eth0\\n'
                   '5: cni0    inet 10.42.0.1/24 brd 10.42.0.255 scope global cni0\\n'
                   '6: flannel.1    inet 10.42.0.0/32 scope global flannel.1\\n"'),
        ):
            path = os.path.join(t, "bin", name)
            with open(path, "w") as fh:
                fh.write("#!/bin/sh\n" + body + "\n")
            os.chmod(path, 0o755)
        self.mode_file = os.path.join(t, "mode")

    def run_script(self, k8s, env=None, args=()):
        if k8s:
            with open(self.mode_file, "w") as fh:
                fh.write("k8s\n")
        full = {k: v for k, v in os.environ.items() if not k.startswith("HARVIS_")}
        full.update({"PATH": os.path.join(self.tmp.name, "bin") + os.pathsep + os.environ["PATH"], "REC": self.rec,
                     "HARVIS_K8S_MODE_FILE": self.mode_file, **(env or {})})
        proc = subprocess.run(["bash", os.path.join(self.root, "scripts", "enable-https.sh"), *args],
                              capture_output=True, text=True, env=full, cwd=self.root, stdin=subprocess.DEVNULL, timeout=120)
        return proc.stdout + proc.stderr, proc.returncode

    def log(self, name):
        path = os.path.join(self.rec, name)
        return open(path).read() if os.path.exists(path) else ""

    def test_k8s_writes_into_the_directory_the_pod_mounts_and_restarts_nginx(self):
        out, rc = self.run_script(True, {"FAKE_HOST_TLS": self.pod_tls})
        self.assertEqual(rc, 0, out)
        for name in ("harvis.crt", "harvis.key", "harvis-tls.conf"):
            self.assertTrue(os.path.exists(os.path.join(self.pod_tls, name)), name)
        self.assertEqual(os.listdir(os.path.join(self.root, "nginx", "tls")), ["harvis-tls.conf.template"])
        calls = self.log("k3s.log").splitlines()
        restart = "kubectl -n harvis rollout restart deploy/nginx"
        status = "kubectl -n harvis rollout status deploy/nginx --timeout=120s"
        self.assertIn(restart, calls)
        self.assertIn(status, calls)
        self.assertLess(calls.index(restart), calls.index(status))
        self.assertIn("HTTPS is on.", out)
        self.assertIn("https://192.168.1.50:9443", out)

    def test_k8s_never_touches_docker_compose(self):
        out, rc = self.run_script(True, {"FAKE_HOST_TLS": self.pod_tls})
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.log("docker.log"), "")

    def test_k8s_falls_back_to_this_checkouts_directory_when_the_mount_cannot_be_read(self):
        out, rc = self.run_script(True, {"FAKE_MOUNT_NAME": ""})
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.root, "nginx", "tls", "harvis.crt")))
        self.assertIn("rollout restart deploy/nginx", self.log("k3s.log"))

    def test_k8s_honours_the_namespace_knob(self):
        out, rc = self.run_script(True, {"FAKE_HOST_TLS": self.pod_tls, "HARVIS_K8S_NAMESPACE": "lab"})
        self.assertEqual(rc, 0, out)
        self.assertIn("kubectl -n lab rollout restart deploy/nginx", self.log("k3s.log"))
        self.assertNotIn("-n harvis ", self.log("k3s.log"))

    def test_k8s_pod_that_never_gets_ready_is_a_failure_not_a_success_message(self):
        out, rc = self.run_script(True, {"FAKE_HOST_TLS": self.pod_tls, "FAKE_STATUS_RC": "1"})
        self.assertNotEqual(rc, 0, out)
        self.assertIn("nginx pod did not become ready", out)
        self.assertNotIn("HTTPS is on.", out)

    def test_k8s_config_nginx_rejects_is_removed_and_the_pod_is_not_restarted(self):
        out, rc = self.run_script(True, {"FAKE_HOST_TLS": self.pod_tls, "FAKE_NGINX_T_RC": "1"})
        self.assertNotEqual(rc, 0, out)
        self.assertIn("nginx rejected the new configuration", out)
        self.assertIn("nginx: test output", out)
        self.assertFalse(os.path.exists(os.path.join(self.pod_tls, "harvis-tls.conf")))
        self.assertNotIn("rollout restart", self.log("k3s.log"))
        self.assertNotIn("HTTPS is on.", out)

    def test_k8s_checks_the_config_in_the_running_pod_before_restarting(self):
        out, rc = self.run_script(True, {"FAKE_HOST_TLS": self.pod_tls})
        self.assertEqual(rc, 0, out)
        calls = self.log("k3s.log").splitlines()
        check = "kubectl -n harvis exec deploy/nginx -- nginx -t"
        self.assertIn(check, calls)
        self.assertLess(calls.index(check), calls.index("kubectl -n harvis rollout restart deploy/nginx"))

    def test_k8s_bridge_and_flannel_addresses_are_not_put_in_the_certificate(self):
        out, rc = self.run_script(True, {"FAKE_HOST_TLS": self.pod_tls})
        self.assertEqual(rc, 0, out)
        valid = next(l for l in out.splitlines() if l.startswith("Certificate will be valid for:"))
        self.assertIn("IP:192.168.1.50", valid)
        self.assertNotIn("10.42.", valid)
        self.assertNotIn("10.42.", out)

    def test_plain_docker_still_goes_through_compose_and_never_kubectl(self):
        out, rc = self.run_script(False)
        self.assertEqual(rc, 0, out)
        self.assertIn("compose up -d nginx", self.log("docker.log"))
        self.assertEqual(self.log("k3s.log"), "")
        self.assertTrue(os.path.exists(os.path.join(self.root, "nginx", "tls", "harvis-tls.conf")))


class InstallSummaryTest(unittest.TestCase):
    """The closing guidance in install.sh, checked on its text: the script runs its installer when sourced."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "install.sh")) as fh:
            cls.src = fh.read()

    def test_k8s_gets_https_guidance_that_names_the_script(self):
        block = self.src.split("    k8s)\n", 1)[1].split("  esac\n", 1)[0]
        self.assertIn("./scripts/enable-https.sh", block)
        self.assertIn("nginx pod", block)

    def test_lan_plus_tunnel_does_not_claim_sign_up_is_closed_when_public_access_is_harvis(self):
        block = self.src.split("    lan+tunnel)\n", 1)[1].split("    k8s)\n", 1)[0]
        branch = block.split('tunnel_auth_choice)" = harvis ]; then\n', 1)[1].split("      else\n", 1)[0]
        self.assertIn("wait in Settings", branch)
        self.assertIn("there and through", branch)
        self.assertNotIn("closed", branch)
        self.assertIn("sign-up is closed", block.split("      else\n", 1)[1])

    def test_installer_syntax_is_valid(self):
        proc = subprocess.run(["bash", "-n", os.path.join(REPO, "install.sh")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
