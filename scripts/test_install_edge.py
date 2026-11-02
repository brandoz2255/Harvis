"""install.sh pieces that sit on the edge of the host: how it reads the health report, and the repo-sandbox subnet.

install.sh runs its installer when sourced, so the functions under test are cut out of the
file by name and run in a throwaway shell with docker, k3s, sudo and curl stubbed on PATH.
Nothing here touches Docker or the network. HARVIS_TEST_INSTALL_SH points the test at
another copy of install.sh; the fail-before check uses the version from git HEAD.
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.environ.get("HARVIS_TEST_INSTALL_SH") or os.path.join(REPO, "install.sh")

FUNCS = ("health_blockers", "fetch_health", "poll_health", "reconcile_repo_sandbox_subnet")

FULL_DOWN = ('{"status":"degraded","timestamp":1.0,"services":{"database":{"status":"down"},'
             '"model_provider":{"status":"not_configured"},"sandbox":{"status":"up","code":200}}}')
FULL_UP = ('{"status":"healthy","timestamp":1.0,"services":{"database":{"status":"up","code":200},'
           '"model_provider":{"status":"up"}}}')
BRIEF = '{"status":"degraded"}'


def cut(src, name):
    m = re.search(r"^%s\(\) \{.*?^\}\n" % re.escape(name), src, re.S | re.M)
    return m.group(0) if m else ""


def top_level(src, name):
    m = re.search(r"^%s=.*$" % re.escape(name), src, re.M)
    return m.group(0) if m else ""


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = os.path.join(self.tmp.name, "bin")
        self.rec = os.path.join(self.tmp.name, "rec")
        os.makedirs(self.bin)
        os.makedirs(self.rec)
        with open(INSTALL) as fh:
            src = fh.read()
        self.lib = "\n".join(
            [top_level(src, v) for v in ("HEALTH_URL", "HEALTH_INNER_URL", "SETUP_URL", "PROVIDER_HEALTH_KEY",
                                         "K8S_ACTION", "K8S_MODE_FILE", "REPO_SANDBOX_STALE")]
            + [cut(src, f) for f in FUNCS]
        ).replace("SECONDS + 180", "SECONDS + 2")  # the 180 s wait, shortened
        self.stub("sudo", 'exec "$@"')

    def stub(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def sh(self, script, env=None):
        full = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "REC": self.rec, "HOME": self.tmp.name,
                "HARVIS_HEALTH_POLL_INTERVAL": "0", **(env or {})}
        proc = subprocess.run(["bash", "-c", self.lib + "\n" + script], capture_output=True, text=True, env=full,
                              cwd=self.tmp.name, stdin=subprocess.DEVNULL, timeout=60)
        return proc.stdout + proc.stderr, proc.returncode

    def log(self, name):
        path = os.path.join(self.rec, name)
        return open(path).read() if os.path.exists(path) else ""


class HealthReadTest(Harness):
    """A shared install answers outside callers with just {"status":..}; the installer must ask from inside."""

    def docker_answers(self, body, rc=0):
        self.stub("docker", 'echo "$*" >> "$REC/docker.log"\n'
                            f'[ {rc} -eq 0 ] && printf %s \'{body}\'\nexit {rc}')

    def curl_answers(self, body):
        self.stub("curl", f'echo "$*" >> "$REC/curl.log"\nprintf %s \'{body}\'')

    def test_it_reads_the_full_report_from_inside_the_backend_not_through_nginx(self):
        self.docker_answers(FULL_DOWN)
        self.curl_answers(BRIEF)
        out, rc = self.sh('K8S_ACTION=""; K8S_MODE_FILE=/nonexistent; fetch_health; '
                          'echo "detail=$HEALTH_DETAIL"; health_blockers "$HEALTH_BODY"')
        self.assertEqual(rc, 0, out)
        self.assertIn("detail=1", out)
        self.assertIn("database", out.splitlines())
        self.assertIn("compose exec -T backend curl -s -m 8 http://127.0.0.1:8000/api/health/services", self.log("docker.log"))
        self.assertEqual(self.log("curl.log"), "")

    def test_it_falls_back_to_the_nginx_url_only_when_the_exec_fails(self):
        self.docker_answers("", rc=1)
        self.curl_answers(BRIEF)
        out, rc = self.sh('K8S_ACTION=""; K8S_MODE_FILE=/nonexistent; fetch_health; echo "detail=$HEALTH_DETAIL body=$HEALTH_BODY"')
        self.assertEqual(rc, 0, out)
        self.assertIn('detail=0 body={"status":"degraded"}', out)
        self.assertIn("http://localhost:9000/api/health/services", self.log("curl.log"))

    def test_a_full_report_through_nginx_still_counts_as_detail(self):
        # A local install (nginx hands out the whole report) when the exec is unavailable.
        self.docker_answers("", rc=1)
        self.curl_answers(FULL_UP)
        out, rc = self.sh('K8S_ACTION=""; K8S_MODE_FILE=/nonexistent; fetch_health; echo "detail=$HEALTH_DETAIL"')
        self.assertIn("detail=1", out)

    def test_kubernetes_mode_asks_the_backend_pod_with_kubectl_exec(self):
        self.stub("k3s", 'echo "$*" >> "$REC/k3s.log"\nprintf %s \'' + FULL_DOWN + "'")
        self.stub("docker", 'echo "$*" >> "$REC/docker.log"')
        self.curl_answers(BRIEF)
        out, rc = self.sh('K8S_ACTION=up; fetch_health; echo "detail=$HEALTH_DETAIL"; health_blockers "$HEALTH_BODY"')
        self.assertEqual(rc, 0, out)
        self.assertIn("detail=1", out)
        self.assertIn("database", out.splitlines())
        self.assertIn("kubectl -n harvis exec deploy/backend -- curl -s -m 8 http://127.0.0.1:8000/api/health/services",
                      self.log("k3s.log"))
        self.assertEqual(self.log("docker.log"), "")

    def test_kubernetes_mode_is_also_detected_from_the_mode_file(self):
        mode = os.path.join(self.tmp.name, "mode")
        open(mode, "w").write("k8s\n")
        self.stub("k3s", 'echo "$*" >> "$REC/k3s.log"\nprintf %s \'' + FULL_UP + "'")
        self.stub("docker", 'echo "$*" >> "$REC/docker.log"')
        out, rc = self.sh(f'K8S_ACTION=""; K8S_MODE_FILE={mode}; fetch_health; echo "detail=$HEALTH_DETAIL"')
        self.assertIn("detail=1", out)
        self.assertIn("deploy/backend", self.log("k3s.log"))
        self.assertEqual(self.log("docker.log"), "")

    # The reported failure: nginx says only {"status":"degraded"}, a service is down, and the
    # installer called it a success. poll_health must now fail and name the service.
    POLL = ('STACK_DOWN=""; check_stack_containers() { :; }; print_first_admin() { echo FIRST_ADMIN; }; '
            'LLM_ENDPOINT=""; poll_health; echo "rc=$?"')

    def test_poll_health_fails_and_names_the_service_when_nginx_only_gives_a_summary(self):
        self.docker_answers(FULL_DOWN)
        self.curl_answers(BRIEF)
        out, rc = self.sh('K8S_ACTION=""; K8S_MODE_FILE=/nonexistent; ' + self.POLL)
        self.assertIn("rc=1", out, out)
        self.assertIn("The backend reports trouble with: database", out)
        self.assertNotIn("Harvis is up", out)

    def test_poll_health_does_not_call_a_summary_only_degraded_stack_a_success(self):
        # Neither read path can list the services: not "up", not "nothing wrong".
        self.docker_answers("", rc=1)
        self.curl_answers(BRIEF)
        out, rc = self.sh('K8S_ACTION=""; K8S_MODE_FILE=/nonexistent; ' + self.POLL)
        self.assertIn("rc=1", out, out)
        self.assertNotIn("Harvis is up", out)

    def test_poll_health_succeeds_on_a_healthy_full_report(self):
        self.docker_answers(FULL_UP)
        self.stub("curl", 'echo "$*" >> "$REC/curl.log"\ncase "$*" in *setup/status*) printf %s \'{"needs_setup":false}\' ;; esac')
        out, rc = self.sh('K8S_ACTION=""; K8S_MODE_FILE=/nonexistent; ' + self.POLL)
        self.assertIn("rc=0", out, out)
        self.assertIn("Harvis is up", out)


class RepoSandboxSubnetTest(Harness):
    """An existing repo-sandbox network keeps the subnet it was made with; the firewall rules name the pinned one."""

    def docker(self, subnet, attached=""):
        self.stub("docker", 'echo "$*" >> "$REC/docker.log"\n'
                            'case "$*" in\n'
                            f'  "network inspect "*) [ -n "{subnet}" ] && printf "%s " "{subnet}" ;;\n'
                            f'  "ps -aq"*) printf %s "{attached}" ;;\n'
                            '  "network rm "*) exit 0 ;;\nesac')

    def run_it(self, env=None):
        self.stub_env = env or {}
        env_value = 'env_value() { :; }; '
        return self.sh(env_value + 'reconcile_repo_sandbox_subnet; echo "stale=$REPO_SANDBOX_STALE"', env)

    def test_a_network_on_the_old_subnet_with_nothing_attached_is_removed_so_compose_recreates_it(self):
        self.docker("172.19.0.0/16")
        out, rc = self.run_it()
        self.assertEqual(rc, 0, out)
        self.assertIn("network rm harvis_repo-sandbox", self.log("docker.log"))
        self.assertIn("ps -aq --filter network=harvis_repo-sandbox", self.log("docker.log"))
        self.assertIn("stale=0", out)
        self.assertIn("10.213.84.0/24", out)

    def test_a_network_with_containers_attached_is_left_alone_with_a_one_line_fix(self):
        self.docker("172.19.0.0/16", attached="abc123")
        out, rc = self.run_it()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("network rm", self.log("docker.log"))
        self.assertIn("stale=1", out)
        self.assertIn("docker compose down && docker network rm harvis_repo-sandbox && ./install.sh", out)

    def test_a_network_already_on_the_pinned_subnet_is_not_touched(self):
        self.docker("10.213.84.0/24")
        out, rc = self.run_it()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("network rm", self.log("docker.log"))
        self.assertIn("stale=0", out)

    def test_no_network_yet_means_nothing_to_do(self):
        self.docker("")
        out, rc = self.run_it()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("network rm", self.log("docker.log"))
        self.assertIn("stale=0", out)

    def test_it_follows_the_stack_name_and_the_configured_pin(self):
        self.docker("10.213.84.0/24")
        out, rc = self.run_it({"HARVIS_STACK_NAME": "lab", "HARVIS_REPO_SANDBOX_SUBNET": "10.213.90.0/24"})
        self.assertIn("network rm lab_repo-sandbox", self.log("docker.log"))
        self.assertIn("inspect lab_repo-sandbox", self.log("docker.log"))


class InstallFlowTest(unittest.TestCase):
    def test_the_subnet_is_reconciled_before_the_lock_is_applied_and_the_lock_is_retried_after_launch(self):
        with open(INSTALL) as fh:
            main = cut(fh.read(), "main")
        self.assertIn("reconcile_repo_sandbox_subnet", main)
        first_lock = main.index("browser-egress-lock.sh apply")
        self.assertLess(main.index("reconcile_repo_sandbox_subnet"), first_lock)
        self.assertGreater(main.rindex("browser-egress-lock.sh apply"), main.index("launch\n"))

    def test_installer_syntax_is_valid(self):
        proc = subprocess.run(["bash", "-n", INSTALL], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
