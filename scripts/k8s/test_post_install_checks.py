"""Function tests for the install-time model, GPU and voice checks in harvis-k8s.sh and for
cmd_up's closing hints. `kc` is a shell function that answers like the cluster."""

import unittest

from test_harvis_k8s_sh import bash


# `kc` answers like the cluster: MODELS is what `ollama list` prints (after its header row),
# VOICE what the voice-onnx /health call returns, and PULL_FAIL names a model whose pull fails.
FAKE_CLUSTER = '''
LOG=$(mktemp)
kc() {
  echo "$*" >> "$LOG"
  case "$*" in
    *"get deploy voice-onnx"*) [ "${VOICE_DEPLOY-1}" = 1 ] ;;
    *"exec deploy/voice-onnx"*) printf '%s' "${VOICE-}" ;;
    *"ollama list"*) [ "${LIST_FAILS-0}" = 1 ] && return 1; printf 'NAME ID SIZE MODIFIED\\n%b' "${MODELS-}" ;;
    *"ollama pull ${PULL_FAIL:-@none@}"*) return 1 ;;
    *"nvidia"*) [ "${GPU_VISIBLE-1}" = 1 ] ;;
  esac
}
VOICE_READY='{"status":"ok","prefetch":{"status":"ready","done":["tts","asr","vad"],"failed":{}}}'
'''


class PostInstallChecksTest(unittest.TestCase):
    def run_checks(self, env=None, setup=""):
        env = {"VOICE": '{"status":"ok","prefetch":{"status":"ready"}}', **(env or {})}
        out, rc = bash(FAKE_CLUSTER + "GPU=0\n" + setup + '\npost_install_checks; echo "NO_CHAT=$NO_CHAT_MODEL"; cat "$LOG"', env)
        self.assertEqual(rc, 0, out)
        return out

    def pulls(self, out):
        return [l.split("ollama pull ")[1] for l in out.splitlines() if "ollama pull " in l]

    def test_empty_ollama_gets_the_embedder_and_is_flagged_as_having_no_chat_model(self):
        out = self.run_checks()
        self.assertEqual(self.pulls(out), ["nomic-embed-text"])
        self.assertIn("✓ nomic-embed-text", out)
        self.assertIn("NO_CHAT=1", out)

    def test_an_installed_embedder_is_not_pulled_again_and_a_chat_model_clears_the_flag(self):
        out = self.run_checks({"MODELS": "gemma4:e2b x 1GB now\\nmxbai-embed-large x 1GB now\\n"})
        self.assertEqual(self.pulls(out), [])
        self.assertIn("NO_CHAT=0", out)

    def test_an_embedder_alone_is_not_a_chat_model(self):
        out = self.run_checks({"MODELS": "nomic-embed-text:latest x 274MB now\\n"})
        self.assertEqual(self.pulls(out), [])
        self.assertIn("NO_CHAT=1", out)

    def test_a_chat_model_alone_does_not_stand_in_for_the_embedder(self):
        out = self.run_checks({"MODELS": "gemma4:e2b x 1GB now\\n"})
        self.assertEqual(self.pulls(out), ["nomic-embed-text"])
        self.assertIn("NO_CHAT=0", out)

    def test_skip_embedder_pulls_nothing(self):
        out = self.run_checks({"HARVIS_SKIP_EMBEDDER": "1", "MODELS": "gemma4:e2b x 1GB now\\n"})
        self.assertEqual(self.pulls(out), [])

    def test_pull_models_list_is_pulled_in_order_and_bad_names_are_skipped(self):
        out = self.run_checks({"HARVIS_PULL_MODELS": "qwen3:4b,-x,a;b,gemma4:e2b", "HARVIS_SKIP_EMBEDDER": "1"})
        self.assertEqual(self.pulls(out), ["qwen3:4b", "gemma4:e2b"])
        self.assertIn("skipped '-x'", out)
        self.assertIn("skipped 'a;b'", out)

    def test_pull_list_is_never_glob_expanded(self):
        out = self.run_checks({"HARVIS_PULL_MODELS": "*, qwen3:4b", "HARVIS_SKIP_EMBEDDER": "1"})
        self.assertEqual(self.pulls(out), ["qwen3:4b"])
        self.assertIn("skipped '*'", out)

    def test_a_failed_pull_is_a_warning_and_the_rest_still_run(self):
        out = self.run_checks({"HARVIS_PULL_MODELS": "big:70b,qwen3:4b", "PULL_FAIL": "big:70b"})
        self.assertIn("⚠ could not download big:70b", out)
        self.assertIn("✓ qwen3:4b", out)
        self.assertEqual(self.pulls(out), ["big:70b", "qwen3:4b", "nomic-embed-text"])

    def test_an_unreadable_model_list_makes_no_claim_about_chat_models(self):
        out = self.run_checks({"LIST_FAILS": "1"})
        self.assertEqual(self.pulls(out), [])
        self.assertIn("NO_CHAT=0", out)

    def test_models_on_a_reused_host_ollama_count(self):
        out = self.run_checks(setup='HOST_OLLAMA_ENTRY="this-computer=http://10.0.0.5:11434"')
        self.assertIn("NO_CHAT=0", out)

    def test_own_model_server_skips_every_ollama_step_but_still_checks_voice(self):
        out = self.run_checks({"HARVIS_K8S_OLLAMA": "0", "VOICE": ""})
        self.assertNotIn("deploy/ollama", out)
        self.assertIn("Voice models are not ready", out)

    def test_gpu_warning_only_when_the_gpu_is_on_and_the_pod_cannot_see_it(self):
        blind = self.run_checks({"GPU_VISIBLE": "0"}, setup="GPU=1")
        self.assertIn("Ollama pod cannot see the GPU", blind)
        self.assertNotIn("cannot see the GPU", self.run_checks({"GPU_VISIBLE": "1"}, setup="GPU=1"))
        cpu = self.run_checks({"GPU_VISIBLE": "0"})
        self.assertNotIn("cannot see the GPU", cpu)
        self.assertNotIn("nvidia", cpu)

    def test_voice_warning_unless_models_are_ready_or_prefetch_is_off(self):
        for body in ('{"status":"ok","prefetch":{"status":"ready"}}', '{"status":"ok","prefetch":{"status":"disabled"}}'):
            self.assertNotIn("Voice models", self.run_checks({"VOICE": body}))
        for body in ('{"status":"ok","prefetch":{"status":"partial"}}',
                     '{"status":"ok","prefetch":{"status":"running"}}', "", "not json"):
            self.assertIn("Voice models are not ready yet", self.run_checks({"VOICE": body}), body)

    def test_no_voice_deployment_is_not_a_warning(self):
        out = self.run_checks({"VOICE_DEPLOY": "0", "VOICE": ""})
        self.assertNotIn("Voice models", out)

    def test_nothing_here_ever_fails_the_install(self):
        out, rc = bash('kc() { return 1; }; GPU=1; post_install_checks')
        self.assertEqual(rc, 0, out)


class FinalHintTest(unittest.TestCase):
    """cmd_up's closing lines, with every step before them replaced."""

    STUBS = '''
LOG=$(mktemp); SUDO=fakesudo
fakesudo() { [ -t 0 ] || cat >/dev/null; }
bash() { return 1; }
docker() { :; }
kc() { echo 10.0.0.5; }
env_get() { [ "$1" = HARVIS_EXPOSURE ] && echo lan || true; }
install_k3s() { :; }; wait_node_ready() { :; }; setup_gpu() { :; }; check_dns() { :; }; import_images() { :; }
server_node() { echo n1; }; node_ip() { echo 10.0.0.5; }; pick_lan_port() { :; }; detect_host_ollama() { :; }
choose_build_space() { :; }; docker_hand_over() { :; }; render() { :; }; apply_kubelet_firewall() { :; }
sync_db_password() { :; }; wait_rollout() { :; }; report_tunnel() { :; }
'''

    def up(self, body=""):
        out, rc = bash(self.STUBS + body + "\ncmd_up", {"HARVIS_K8S_OLLAMA": "1"})
        self.assertEqual(rc, 0, out)
        return out

    def test_add_a_model_hint_shows_even_when_the_lan_model_port_is_off(self):
        out = self.up("post_install_checks() { :; }; LAN_PORT=0")
        self.assertIn("Add a model:  sudo k3s kubectl -n harvis exec deploy/ollama -- ollama pull ", out)
        self.assertNotIn("Models shared on your network", out)

    def test_lan_port_adds_the_sharing_line_to_the_hint(self):
        out = self.up("post_install_checks() { :; }; pick_lan_port() { LAN_PORT=11434; }")
        self.assertIn("Models shared on your network at http://10.0.0.5:11434", out)
        self.assertIn("Add a model:", out)

    def test_no_chat_model_prints_one_clear_line_with_the_exact_command(self):
        out = self.up("post_install_checks() { NO_CHAT_MODEL=1; }")
        lines = [l for l in out.splitlines() if "No chat model" in l]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("sudo k3s kubectl -n harvis exec deploy/ollama -- ollama pull gemma4:e2b", lines[0])
        self.assertNotIn("Add a model:", out)

    def test_checks_run_after_the_rollout_and_before_the_success_line(self):
        out = self.up('wait_rollout() { echo ROLLOUT; }; post_install_checks() { echo CHECKS; }')
        self.assertEqual([l for l in out.splitlines() if l in ("ROLLOUT", "CHECKS") or "Harvis runs on Kubernetes" in l][:3],
                         ["ROLLOUT", "CHECKS", "✓ Harvis runs on Kubernetes → http://10.0.0.5:9000  (and http://localhost:9000)"])

    def test_own_model_server_prints_no_ollama_hint(self):
        out, rc = bash(self.STUBS + "post_install_checks() { :; }\ncmd_up", {"HARVIS_K8S_OLLAMA": "0"})
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Add a model", out)



if __name__ == "__main__":
    unittest.main()
