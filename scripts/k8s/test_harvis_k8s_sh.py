"""Function tests for harvis-k8s.sh. Nothing here touches iptables, k3s, docker or the network:
every outside call is replaced by a shell function or a fake program on PATH."""

import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "harvis-k8s.sh")


# The repo's own .env is never read by these tests: the .env readers are stubbed out
# unless a test points the real one at a fixture directory.
NO_ENV_FILE = "env_get() { return 0; }; env_get_raw() { return 0; }\n"


def bash(body, env=None, cwd=None, real_env_readers=False):
    """Source the script (functions only), then run `body`. Returns (stdout, returncode)."""
    full = {k: v for k, v in os.environ.items() if not k.startswith("HARVIS_")}
    full.update(env or {})
    proc = subprocess.run(["bash", "-c", f'source "{SCRIPT}"\n{"" if real_env_readers else NO_ENV_FILE}{body}'], capture_output=True, text=True,
                          env=full, cwd=cwd, timeout=60)
    return proc.stdout + proc.stderr, proc.returncode


# A recording stand-in for `sudo iptables`: -C succeeds only after an -I and before a -D.
FAKE_IPT = '''
LOG=$(mktemp); STATE=$(mktemp -u)
ipt() { echo "$*" >> "$LOG"; case "$1 $2" in "-C INPUT") [ -e "$STATE" ] ;; "-I INPUT") touch "$STATE" ;; "-D INPUT") rm -f "$STATE" ;; esac; }
have_iptables() { return 0; }
cluster_node_ips() { printf '192.168.1.10\\n192.168.1.11\\n'; }
'''


class KubeletFirewallTest(unittest.TestCase):
    def test_rules_allow_local_pods_services_and_nodes_then_drop(self):
        out, rc = bash('kubelet_rules 192.168.1.10 192.168.1.11 "10.0.0.1; reboot" 2001:db8::1')
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), [
            "-A HARVIS-K3S -s 127.0.0.0/8 -j RETURN",
            "-A HARVIS-K3S -s 10.42.0.0/16 -j RETURN",
            "-A HARVIS-K3S -s 10.43.0.0/16 -j RETURN",
            "-A HARVIS-K3S -s 192.168.1.10 -j RETURN",
            "-A HARVIS-K3S -s 192.168.1.11 -j RETURN",
            "-A HARVIS-K3S -j DROP"])

    def test_apply_twice_hooks_the_chain_once_and_remove_undoes_it(self):
        out, rc = bash(FAKE_IPT + 'apply_kubelet_firewall quiet; apply_kubelet_firewall quiet; cat "$LOG"; '
                       'echo ---; : > "$LOG"; remove_kubelet_firewall; cat "$LOG"')
        self.assertEqual(rc, 0, out)
        applied, removed = out.split("---\n")
        lines = applied.splitlines()
        self.assertEqual(lines.count("-I INPUT 1 -p tcp --dport 10250 -j HARVIS-K3S"), 1)
        self.assertEqual(lines.count("-F HARVIS-K3S"), 2)
        self.assertEqual(lines.count("-A HARVIS-K3S -j DROP"), 2)
        self.assertEqual(removed.splitlines()[:2], ["-C INPUT -p tcp --dport 10250 -j HARVIS-K3S",
                                                    "-D INPUT -p tcp --dport 10250 -j HARVIS-K3S"])
        self.assertIn("-X HARVIS-K3S", removed)

    def test_never_touches_6443(self):
        out, _ = bash(FAKE_IPT + 'apply_kubelet_firewall quiet; cat "$LOG"')
        self.assertNotIn("6443", out)

    def test_missing_iptables_warns_and_continues(self):
        out, rc = bash(FAKE_IPT + 'have_iptables() { return 1; }; apply_kubelet_firewall; echo rc=$?; cat "$LOG"; remove_kubelet_firewall; echo rc=$?')
        self.assertEqual(rc, 0, out)
        self.assertIn("iptables is not installed", out)
        self.assertEqual(out.count("rc=0"), 2)
        self.assertNotIn("HARVIS-K3S", out.replace("kubelet port", ""))

    def test_no_node_list_leaves_existing_rules_alone(self):
        out, rc = bash(FAKE_IPT + 'cluster_node_ips() { :; }; apply_kubelet_firewall; cat "$LOG"')
        self.assertEqual(rc, 0, out)
        self.assertIn("Could not list the cluster's nodes", out)
        self.assertNotIn("-F HARVIS-K3S", out)

    def test_a_failing_iptables_is_a_warning_not_an_abort(self):
        out, rc = bash(FAKE_IPT + 'ipt() { return 1; }; apply_kubelet_firewall; echo after')
        self.assertEqual(rc, 0, out)
        self.assertIn("Could not set the firewall", out)
        self.assertIn("after", out)


class HostOllamaTest(unittest.TestCase):
    FAKES = '''
host_ollama_answers() { return 0; }
lan_models_serves() { return 1; }
tcp_open() { return 0; }
'''

    def detect(self, fakes="", env=None):
        return bash(self.FAKES + fakes + '\ndetect_host_ollama 192.168.1.10; echo "ENTRY=$HOST_OLLAMA_ENTRY"', env)

    def test_reachable_host_ollama_becomes_a_named_host(self):
        out, rc = self.detect()
        self.assertEqual(rc, 0, out)
        self.assertIn("ENTRY=this-computer=http://192.168.1.10:11434|label=This computer", out)

    def test_loopback_only_ollama_prints_the_two_line_hint(self):
        out, rc = self.detect("tcp_open() { return 1; }")
        self.assertEqual(rc, 0, out)
        self.assertIn("ENTRY=\n", out + "\n")
        hint = [l for l in out.splitlines() if not l.startswith("ENTRY=")]
        self.assertEqual(len(hint), 2, out)
        self.assertIn("sudo systemctl edit ollama", hint[0])
        self.assertIn("OLLAMA_HOST=0.0.0.0", hint[1])

    def test_our_own_lan_models_service_is_not_a_host_ollama(self):
        out, _ = self.detect("lan_models_serves() { return 0; }")
        self.assertEqual(out.strip(), "ENTRY=")

    def test_nothing_listening_and_opt_outs_add_nothing(self):
        self.assertEqual(self.detect("host_ollama_answers() { return 1; }")[0].strip(), "ENTRY=")
        self.assertEqual(self.detect(env={"HARVIS_K8S_REUSE_HOST_OLLAMA": "0"})[0].strip(), "ENTRY=")
        self.assertEqual(self.detect(env={"HARVIS_K8S_OLLAMA": "0"})[0].strip(), "ENTRY=")

    def test_json_list_value_is_left_alone(self):
        out, _ = self.detect(env={"HARVIS_OLLAMA_HOSTS": '[{"name":"studio","url":"http://a:11434"}]'})
        self.assertIn("JSON list", out)
        self.assertIn("ENTRY=\n", out + "\n")

    def test_entry_is_appended_never_overwritten(self):
        entry = "this-computer=http://10.0.0.5:11434|label=This computer"
        script = f'''e='{entry}'
hosts_with_entry "" "$e"; echo
hosts_with_entry "studio=http://a:11434|label=Mac Studio" "$e"; echo
hosts_with_entry "studio=http://a:11434," "$e"; echo
hosts_with_entry "$e" "$e"; echo'''
        out, _ = bash(script)
        self.assertEqual(out.splitlines(), [
            entry,
            f"studio=http://a:11434|label=Mac Studio,{entry}",
            f"studio=http://a:11434,{entry}",
            entry])

    def test_env_get_raw_keeps_spaces_inside_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".env"), "w") as fh:
                fh.write('A="x=1|label=Mac Studio"\nB=\'q r\'\nC=plain\r\n')
            out, rc = bash(f'cd "{d}"; env_get_raw A; env_get_raw B; env_get_raw C | od -c | head -1',
                           real_env_readers=True)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.splitlines()[:2], ["x=1|label=Mac Studio", "q r"])
        self.assertNotIn("\\r", out)


class RenderPlumbingTest(unittest.TestCase):
    """render() with a fake docker and a fake python3 that only record what they were given."""

    def run_render(self, setup):
        with tempfile.TemporaryDirectory() as d:
            for name, body in (
                ("docker", 'case "$1" in compose) printf "%s" "${HARVIS_OLLAMA_HOSTS-<unset>}" > "$REC/hosts"; echo "{}" ;; '
                           'info) echo /var/lib/docker ;; esac'),
                ("python3", 'cat >/dev/null; printf "%s\\n" "$@" > "$REC/args"'),
            ):
                path = os.path.join(d, name)
                with open(path, "w") as fh:
                    fh.write("#!/bin/sh\n" + body + "\n")
                os.chmod(path, 0o755)
            env = {"PATH": d + os.pathsep + os.environ["PATH"], "REC": d, "HARVIS_K8S_NAMESPACE": "harvis"}
            out, rc = bash('kc() { echo 10Gi; }\n' + setup + '\nrender n1 10.0.0.5 10.43.0.10 >/dev/null', env)
            read = lambda n: open(os.path.join(d, n)).read() if os.path.exists(os.path.join(d, n)) else None  # noqa: E731
            return out, rc, read("hosts"), (read("args") or "").splitlines()

    def test_build_space_is_off_by_default_and_says_so(self):
        out, rc, _, args = self.run_render('choose_build_space; echo "BS=$BUILD_SPACE"')
        self.assertEqual(rc, 0, out)
        self.assertIn("BS=0", out)
        self.assertIn("Build Space is off on Kubernetes", out)
        self.assertIn("HARVIS_K8S_BUILD_SPACE=1", out)
        self.assertIn("backend can control this machine", out)
        self.assertNotIn("--build-space", args)

    def test_build_space_env_reaches_the_generator(self):
        out, rc, _, args = self.run_render('HARVIS_K8S_BUILD_SPACE=1; choose_build_space')
        self.assertEqual(rc, 0, out)
        self.assertIn("Build Space is ON", out)
        self.assertIn("--build-space", args)

    def test_host_ollama_is_appended_to_the_hosts_compose_sees(self):
        entry = "this-computer=http://10.0.0.5:11434|label=This computer"
        out, rc, hosts, _ = self.run_render(
            f'HARVIS_OLLAMA_HOSTS="studio=http://a:11434|label=Mac Studio"; HOST_OLLAMA_ENTRY="{entry}"')
        self.assertEqual(rc, 0, out)
        self.assertEqual(hosts, f"studio=http://a:11434|label=Mac Studio,{entry}")

    def test_without_a_host_ollama_compose_gets_no_override(self):
        _, rc, hosts, _ = self.run_render("")
        self.assertEqual((rc, hosts), (0, "<unset>"))


# Records systemctl and killall calls; `k3s` exists on PATH via a function.
FAKE_POWER = '''
LOG=$(mktemp)
k3s() { :; }
svc() { echo "systemctl $*" >> "$LOG"; case "$1" in cat) [ "$2" = "$UNIT" ] ;; *) return 0 ;; esac; }
k3s_killall() { echo killall >> "$LOG"; }
port_busy() { return 1; }
'''


class StopStartTest(unittest.TestCase):
    def test_stop_disables_the_server_and_kills_its_pods(self):
        out, rc = bash(FAKE_POWER + 'cmd_stop; cat "$LOG"', env={"UNIT": "k3s"})
        self.assertEqual(rc, 0, out)
        self.assertIn("systemctl disable --now k3s", out)
        self.assertIn("killall", out)
        self.assertIn("stays off after a reboot", out)

    def test_stop_on_a_worker_stops_the_agent(self):
        out, rc = bash(FAKE_POWER + 'cmd_stop; cat "$LOG"', env={"UNIT": "none"})
        self.assertEqual(rc, 0, out)
        self.assertIn("systemctl disable --now k3s-agent", out)

    def test_stop_fails_loudly_when_port_9000_still_answers(self):
        out, rc = bash(FAKE_POWER + 'port_busy() { return 0; }; cmd_stop', env={"UNIT": "k3s"})
        self.assertNotEqual(rc, 0, out)
        self.assertIn("still answers on port 9000", out)

    def test_stop_without_k3s_changes_nothing(self):
        out, rc = bash(FAKE_POWER + 'unset -f k3s; PATH=/nonexistent; cmd_stop; echo log=$(cat "$LOG")')
        self.assertEqual(rc, 0, out)
        self.assertIn("nothing to stop", out)
        self.assertIn("log=\n", out + "\n")

    def test_start_enables_the_server_then_reapplies_the_kubelet_firewall(self):
        out, rc = bash(FAKE_POWER + 'wait_node_ready() { echo ready >> "$LOG"; }; '
                       'apply_kubelet_firewall() { echo firewall >> "$LOG"; }; wait_rollout() { echo rollout >> "$LOG"; }; '
                       'server_node() { echo n; }; node_ip() { echo 192.168.1.10; }; cmd_start; cat "$LOG"',
                       env={"UNIT": "k3s"})
        self.assertEqual(rc, 0, out)
        log = [line for line in out.splitlines() if line in ("ready", "firewall", "rollout") or line.startswith("systemctl enable")]
        self.assertEqual(log, ["systemctl enable --now k3s", "ready", "firewall", "rollout"])
        self.assertIn("http://192.168.1.10:9000", out)


if __name__ == "__main__":
    unittest.main()
