#!/usr/bin/env bash
# Harvis Kubernetes hosting mode — install k3s on this machine and run Harvis
# in it. Called by ./install.sh --k8s*, or directly:
#
#   scripts/k8s/harvis-k8s.sh up             install k3s if needed, move Harvis into it
#   scripts/k8s/harvis-k8s.sh status         nodes, pods and the addresses Harvis is on
#   scripts/k8s/harvis-k8s.sh off            back to plain Docker; all data kept
#   scripts/k8s/harvis-k8s.sh uninstall      off, then remove k3s from this machine
#   scripts/k8s/harvis-k8s.sh join-command   print the command another machine runs to join
#   scripts/k8s/harvis-k8s.sh join URL TOKEN make THIS machine a worker of that server
#
# The Kubernetes objects are generated from docker-compose.yaml on every `up`
# (compose_to_k8s.py), so the two modes cannot drift. Both modes read the same
# Docker volume directories, so switching either way moves no data.
#
# Environment knobs:
#   HARVIS_K8S_NAMESPACE     default harvis
#   HARVIS_K3S_VERSION       pin a k3s version (default: the stable channel)
#   HARVIS_K8S_OLLAMA        1 (default) run Ollama in the cluster; 0 = keep HARVIS_LLM_BASE_URL
#   HARVIS_OLLAMA_IMAGE      default ollama/ollama:0.20.2
#   HARVIS_LAN_MODELS_PORT   default 11434 (11435 when 11434 is taken); 0 = don't share models
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$REPO/scripts/k8s"
cd "$REPO"

NS="${HARVIS_K8S_NAMESPACE:-harvis}"
OLLAMA_IMAGE="${HARVIS_OLLAMA_IMAGE:-ollama/ollama:0.20.2}"
STATE_DIR=/var/lib/harvis/k8s
LAN_PORT=0
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
kc() { $SUDO k3s kubectl "$@"; }
say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# ── k3s ─────────────────────────────────────────────────────────────────────
k3s_installed() { command -v k3s >/dev/null 2>&1 && [ -f /etc/rancher/k3s/k3s.yaml ]; }

install_k3s() {
  if k3s_installed; then say "✓ k3s already installed ($(k3s --version | head -1 | awk '{print $3}'))"; return 0; fi
  command -v curl >/dev/null || die "curl is needed to install k3s"
  say "Installing k3s (a small Kubernetes) — this needs sudo ..."
  local env=(INSTALL_K3S_EXEC="server --disable traefik --write-kubeconfig-mode 600")
  if [ -n "${HARVIS_K3S_VERSION:-}" ]; then env+=(INSTALL_K3S_VERSION="$HARVIS_K3S_VERSION")
  else env+=(INSTALL_K3S_CHANNEL=stable); fi
  curl -sfL https://get.k3s.io | $SUDO env "${env[@]}" sh - >/dev/null
  say "✓ k3s installed"
}

wait_node_ready() {
  local i
  for i in $(seq 1 90); do
    if kc get nodes --no-headers 2>/dev/null | grep -q ' Ready'; then return 0; fi
    python3 -c 'import time; time.sleep(2)'
  done
  die "the k3s node never became Ready — see: sudo journalctl -u k3s -n 100"
}

server_node() {
  kc get nodes -l node-role.kubernetes.io/control-plane=true -o jsonpath='{.items[0].metadata.name}'
}

node_ip() {
  kc get node "$1" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'
}

# ── GPU ─────────────────────────────────────────────────────────────────────
GPU=0
setup_gpu() {
  if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi -L >/dev/null 2>&1; then
    say "• no NVIDIA GPU found — models will run on the CPU"
    return 0
  fi
  if ! command -v nvidia-container-runtime >/dev/null 2>&1; then
    command -v apt-get >/dev/null || die "NVIDIA GPU found but nvidia-container-toolkit is missing; install it, then re-run"
    say "Installing nvidia-container-toolkit ..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | $SUDO gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      | $SUDO tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    $SUDO apt-get update -qq && $SUDO apt-get install -y -qq nvidia-container-toolkit >/dev/null
  fi
  # k3s finds the nvidia runtime when it starts; restart once so it does.
  if ! $SUDO grep -q nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml 2>/dev/null; then
    $SUDO systemctl restart k3s
    wait_node_ready
  fi
  kc apply -f - >/dev/null <<'EOF'
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata: {name: nvidia}
handler: nvidia
---
apiVersion: apps/v1
kind: DaemonSet
metadata: {name: nvidia-device-plugin, namespace: kube-system}
spec:
  selector: {matchLabels: {name: nvidia-device-plugin}}
  template:
    metadata: {labels: {name: nvidia-device-plugin}}
    spec:
      runtimeClassName: nvidia
      priorityClassName: system-node-critical
      tolerations: [{key: nvidia.com/gpu, operator: Exists, effect: NoSchedule}]
      containers:
        - name: nvidia-device-plugin
          image: nvcr.io/nvidia/k8s-device-plugin:v0.17.1
          env: [{name: FAIL_ON_INIT_ERROR, value: "false"}]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
          volumeMounts: [{name: device-plugin, mountPath: /var/lib/kubelet/device-plugins}]
      volumes: [{name: device-plugin, hostPath: {path: /var/lib/kubelet/device-plugins}}]
EOF
  local i n=""
  for i in $(seq 1 45); do
    n="$(kc get nodes -o jsonpath='{range .items[*]}{.status.allocatable.nvidia\.com/gpu}{" "}{end}' | tr -s ' ')"
    [ -n "${n// /}" ] && [ "${n// /}" != "0" ] && break
    python3 -c 'import time; time.sleep(2)'
  done
  if [ -n "${n// /}" ] && [ "${n// /}" != "0" ]; then GPU=1; say "✓ NVIDIA GPU available to the cluster"
  else say "⚠ NVIDIA GPU found but Kubernetes cannot schedule it yet — models will run on the CPU"; fi
}

# ── DNS ─────────────────────────────────────────────────────────────────────
# Some networks (campus Wi-Fi above all) drop or mangle DNS from the cluster's
# resolver. Test it; if names don't resolve, send lookups over TCP instead.
dns_probe() {
  kc delete pod harvis-dnstest -n default --ignore-not-found --wait=true >/dev/null 2>&1 || true
  kc run harvis-dnstest -n default --image="$1" --restart=Never --command -- \
    nslookup -timeout=5 registry.ollama.ai >/dev/null 2>&1 || return 1
  local i phase=""
  for i in $(seq 1 45); do
    phase="$(kc get pod harvis-dnstest -n default -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    case "$phase" in Succeeded|Failed) break ;; esac
    python3 -c 'import time; time.sleep(2)'
  done
  kc delete pod harvis-dnstest -n default --wait=false >/dev/null 2>&1 || true
  [ "$phase" = "Succeeded" ]
}

coredns_ready() {
  local i
  for i in $(seq 1 60); do
    kc -n kube-system get deploy/coredns >/dev/null 2>&1 && break
    python3 -c 'import time; time.sleep(2)'
  done
  kc -n kube-system rollout status deploy/coredns --timeout=120s >/dev/null 2>&1
}

# A node turns Ready before CoreDNS does, so a probe right after install fails
# for no network reason. Wait for CoreDNS, and try twice before switching.
check_dns() {
  local img="busybox:1.37.0"
  coredns_ready || say "⚠ CoreDNS is slow to start"
  if dns_probe "$img" || dns_probe "$img"; then say "✓ cluster DNS resolves outside names"; return 0; fi
  say "⚠ cluster DNS could not resolve outside names — switching lookups to TCP"
  local data="" tld
  for tld in com net org io ai dev app co me gg sh xyz edu gov; do
    data+="  ${tld}.server: |\n    ${tld}:53 {\n      forward . /etc/resolv.conf {\n        force_tcp\n      }\n      cache 30\n    }\n"
  done
  printf 'apiVersion: v1\nkind: ConfigMap\nmetadata: {name: coredns-custom, namespace: kube-system}\ndata:\n%b' "$data" \
    | kc apply -f - >/dev/null
  kc -n kube-system rollout restart deploy/coredns >/dev/null
  if coredns_ready && dns_probe "$img"; then say "✓ cluster DNS works over TCP"; return 0; fi
  # The TCP switch did not help (or CoreDNS rejected it): put DNS back as it was.
  kc -n kube-system delete cm coredns-custom --ignore-not-found >/dev/null
  kc -n kube-system rollout restart deploy/coredns >/dev/null
  coredns_ready || true
  say "⚠ cluster DNS still failing — model downloads from inside the cluster may not work"
}

# ── images ──────────────────────────────────────────────────────────────────
# Images Harvis builds itself are copied from Docker into k3s' own image store,
# so no registry is needed. A stamp per image skips the copy when unchanged.
import_images() {
  $SUDO mkdir -p "$STATE_DIR/images"
  local img id stamp
  while IFS= read -r img; do
    [ -n "$img" ] || continue
    # Not .Id: with Docker's containerd image store every rebuild gets a new Id
    # (fresh provenance timestamp) even when nothing in the image changed.
    id="$(docker image inspect -f '{{json .RootFS.Layers}}{{json .Config}}' "$img" 2>/dev/null)" \
      || die "image $img is missing — run: docker compose build"
    id="$(printf '%s' "$id" | sha256sum | cut -d' ' -f1)"
    stamp="$STATE_DIR/images/$(printf '%s' "$img" | tr '/:@' '___').id"
    if [ "$($SUDO cat "$stamp" 2>/dev/null || true)" = "$id" ]; then continue; fi
    say "  importing $img into k3s ..."
    docker save "$img" | $SUDO k3s ctr images import - >/dev/null
    printf '%s' "$id" | $SUDO tee "$stamp" >/dev/null
  done < <(docker compose config --format json | python3 -c '
import json, sys
d = json.load(sys.stdin)
proj = d.get("name") or "harvis"
for n, s in sorted(d["services"].items()):
    if s.get("build"):
        print(s.get("image") or f"{proj}-{n}:latest")' | sort -u)
  say "✓ Harvis images available to k3s"
}

# ── compose ↔ cluster hand-over ─────────────────────────────────────────────
# `create` makes every named volume (and fills it from the image, as Docker
# does on first use) plus the docker networks the backend's sandboxes join.
# `rm -sf` then stops the Docker containers while keeping all of that.
docker_hand_over() {
  docker network inspect ollama-n8n-network >/dev/null 2>&1 || docker network create ollama-n8n-network >/dev/null
  docker compose create --no-build >/dev/null 2>&1 || docker compose create >/dev/null
  docker compose rm -sf >/dev/null
  say "✓ Docker containers stopped (volumes and networks kept)"
}

render() { # $1 node  $2 node ip  $3 dns ip
  local llm_env=() gen_args=()
  if [ "${HARVIS_K8S_OLLAMA:-1}" = "1" ]; then
    llm_env=(HARVIS_LLM_BASE_URL=http://ollama:11434)
    gen_args+=(--ollama-image "$OLLAMA_IMAGE")
    if [ "$LAN_PORT" != "0" ]; then
      gen_args+=(--lan-models-port "$LAN_PORT" --lan-models-url "http://$2:$LAN_PORT")
    fi
  fi
  [ "$GPU" = "1" ] && gen_args+=(--gpu)
  env "${llm_env[@]+"${llm_env[@]}"}" docker compose config --format json \
    | python3 "$HERE/compose_to_k8s.py" --namespace "$NS" --node-name "$1" --node-ip "$2" \
        --dns-ip "$3" --repo "$REPO" \
        --volume-root "$(docker info -f '{{.DockerRootDir}}')/volumes" "${gen_args[@]}"
}

pick_lan_port() {
  local cur
  LAN_PORT="${HARVIS_LAN_MODELS_PORT:-11434}"
  [ "$LAN_PORT" = "0" ] && return 0
  # A re-run keeps the port we already serve on, even if that was the 11435 fallback.
  cur="$(kc -n "$NS" get svc lan-models -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || true)"
  if [ -n "$cur" ] && { [ -z "${HARVIS_LAN_MODELS_PORT:-}" ] || [ "$cur" = "$LAN_PORT" ]; }; then
    LAN_PORT="$cur"; return 0
  fi
  if port_busy "$LAN_PORT"; then
    say "• port $LAN_PORT is taken on this machine (a local Ollama?) — sharing models on 11435 instead"
    LAN_PORT=11435
    port_busy 11435 && { say "⚠ 11435 is taken too — not sharing models on the network"; LAN_PORT=0; }
  fi
  return 0
}

wait_rollout() {
  local d failed=""
  for d in $(kc -n "$NS" get deploy -o jsonpath='{.items[*].metadata.name}'); do
    if kc -n "$NS" rollout status "deploy/$d" --timeout=600s >/dev/null 2>&1; then printf '  ✓ %-16s ready\n' "$d"
    else printf '  ✗ %-16s not ready\n' "$d"; failed="$failed $d"; fi
  done
  [ -z "$failed" ] || { say "✗ Not ready:$failed — see: sudo k3s kubectl -n $NS describe pod -l app.kubernetes.io/name=<name>"; return 1; }
}

cmd_up() {
  command -v docker >/dev/null || die "Docker is required (Harvis builds its images and runs workspace sandboxes with it)"
  install_k3s
  wait_node_ready
  setup_gpu
  check_dns
  import_images
  local node ip dns
  node="$(server_node)"; ip="$(node_ip "$node")"
  dns="$(kc -n kube-system get svc kube-dns -o jsonpath='{.spec.clusterIP}')"
  pick_lan_port
  docker_hand_over
  $SUDO mkdir -p /var/lib/harvis/ollama
  say "Applying Harvis to the cluster (namespace $NS) ..."
  render "$node" "$ip" "$dns" | kc apply -f - >/dev/null
  say "Waiting for Harvis to start in Kubernetes:"
  wait_rollout
  printf 'k8s\n' | $SUDO tee "$STATE_DIR/mode" >/dev/null
  say ""
  say "✓ Harvis runs on Kubernetes → http://$ip:9000  (and http://localhost:9000)"
  if [ "${HARVIS_K8S_OLLAMA:-1}" = "1" ] && [ "$LAN_PORT" != "0" ]; then
    say "  Models shared on your network at http://$ip:$LAN_PORT (chat and model listing only)"
    say "  Add a model:  sudo k3s kubectl -n $NS exec deploy/ollama -- ollama pull gemma4:e2b"
  fi
}

cmd_status() {
  k3s_installed || { say "Kubernetes mode is off (k3s is not installed). Harvis runs on Docker."; return 0; }
  say "Nodes:"; kc get nodes -o wide
  say ""; say "Harvis pods ($NS):"; kc -n "$NS" get pods -o wide 2>/dev/null || say "  none — Kubernetes mode is off"
  say ""; say "Addresses:"; kc -n "$NS" get svc --field-selector spec.type=LoadBalancer 2>/dev/null || true
}

cmd_off() {
  if k3s_installed && kc get ns "$NS" >/dev/null 2>&1; then
    say "Removing Harvis from Kubernetes (data stays on this machine) ..."
    kc delete ns "$NS" --wait=true --timeout=300s >/dev/null
    kc delete clusterrole,clusterrolebinding "harvis-$NS-node-reader" --ignore-not-found >/dev/null
    say "✓ Kubernetes namespace $NS removed"
  fi
  $SUDO rm -f "$STATE_DIR/mode"
  say "Starting Harvis on Docker again ..."
  docker compose up -d
}

cmd_uninstall() {
  cmd_off
  if [ -x /usr/local/bin/k3s-uninstall.sh ]; then $SUDO /usr/local/bin/k3s-uninstall.sh >/dev/null 2>&1; say "✓ k3s removed"
  elif [ -x /usr/local/bin/k3s-agent-uninstall.sh ]; then $SUDO /usr/local/bin/k3s-agent-uninstall.sh >/dev/null 2>&1; say "✓ k3s agent removed"; fi
  # The image stamps describe k3s' image store, which the uninstaller just wiped.
  $SUDO rm -rf "$STATE_DIR/images"
}

cmd_join_command() {
  k3s_installed || die "Kubernetes mode is not on here — run ./install.sh --k8s first"
  local ip token
  ip="$(node_ip "$(server_node)")"
  token="$($SUDO cat /var/lib/rancher/k3s/server/node-token)"
  say "On the machine that should join, from its Harvis checkout, run:"
  say ""
  say "  ./install.sh --k8s-join https://$ip:6443 $token"
  say ""
  say "Treat that token like a password: anyone holding it can add machines to this cluster."
}

cmd_join() {
  local url="${1:-}" token="${2:-}"
  [ -n "$url" ] && [ -n "$token" ] || die "usage: harvis-k8s.sh join https://SERVER:6443 TOKEN"
  case "$url" in https://*) ;; *) die "the server URL must look like https://192.168.1.10:6443" ;; esac
  command -v curl >/dev/null || die "curl is needed to install k3s"
  say "Joining $url as a worker ..."
  local env=(K3S_URL="$url" K3S_TOKEN="$token" INSTALL_K3S_EXEC="agent --node-label harvis.dev/role=worker")
  if [ -n "${HARVIS_K3S_VERSION:-}" ]; then env+=(INSTALL_K3S_VERSION="$HARVIS_K3S_VERSION")
  else env+=(INSTALL_K3S_CHANNEL=stable); fi
  curl -sfL https://get.k3s.io | $SUDO env "${env[@]}" sh - >/dev/null
  say "✓ This machine joined. Check from the server with: ./install.sh --k8s-status"
}

case "${1:-}" in
  up) cmd_up ;;
  status) cmd_status ;;
  off) cmd_off ;;
  uninstall) cmd_uninstall ;;
  join-command) cmd_join_command ;;
  join) shift; cmd_join "$@" ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
