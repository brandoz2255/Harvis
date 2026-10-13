"""Tests for power-button.sh fire. Nothing here touches systemd, k3s or docker: each is a
fake program on PATH that records how it was called."""

import os
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "power-button.sh")


class FireTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "calls")
        self.bin = os.path.join(self.tmp, "bin")
        self.control = os.path.join(self.tmp, "control")
        os.makedirs(self.bin)
        self.inbox = os.path.join(self.control, "inbox")
        os.makedirs(self.inbox)
        self.fake("systemctl", 'echo "systemctl $*" >> "$LOG"')
        self.fake("killall", 'echo "killall" >> "$LOG"')
        self.fake("docker", 'echo "docker $*" >> "$LOG"; [ "$1" = ps ] && printf "c1\\nc2\\n"; true')
        with open(os.path.join(self.inbox, "stop"), "w") as fh:
            fh.write("rm -rf / ; ignored\n")

    def fake(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as fh:
            fh.write(f"#!/bin/sh\n{body}\n")
        os.chmod(path, 0o755)

    def fire(self, mode):
        mode_file = os.path.join(self.tmp, "mode")
        with open(mode_file, "w") as fh:
            fh.write(mode)
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "LOG": self.log, "HARVIS_REPO": self.tmp,
               "HARVIS_CONTROL_DIR": self.control, "HARVIS_POWER_GRACE": "0",
               "HARVIS_POWER_SUDO": "env", "HARVIS_BACKEND_UID": str(os.getuid()),
               "HARVIS_K8S_MODE_FILE": mode_file, "HARVIS_K3S_KILLALL": os.path.join(self.bin, "killall")}
        proc = subprocess.run(["bash", SCRIPT, "fire"], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(os.listdir(self.inbox), [], "the request is consumed")
        with open(self.log) as fh:
            return fh.read().splitlines()

    def test_kubernetes_mode_disables_k3s_and_kills_its_containers(self):
        self.assertEqual(self.fire("k8s\n"), ["systemctl cat k3s", "systemctl disable --now k3s", "killall"])

    def test_docker_mode_stops_only_this_checkouts_containers(self):
        calls = self.fire("")
        self.assertEqual(calls, [
            f"docker ps -q --filter label=com.docker.compose.project.working_dir={os.path.realpath(self.tmp)}",
            "docker stop c1 c2"])

    def test_a_folder_named_stop_is_cleared_too(self):
        # rm -f cannot remove it, and a stop that never goes away would stop Harvis on every start.
        os.remove(os.path.join(self.inbox, "stop"))
        os.makedirs(os.path.join(self.inbox, "stop", "deeper"))
        self.assertEqual(self.fire("k8s\n")[1], "systemctl disable --now k3s")
        self.assertEqual(oct(os.stat(self.inbox).st_mode & 0o777), "0o700")


if __name__ == "__main__":
    unittest.main()
