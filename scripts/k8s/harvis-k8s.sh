#!/usr/bin/env bash
# Harvis Kubernetes hosting mode — install k3s on this machine and run Harvis
# in it. Called by ./install.sh --k8s*, or directly:
#
#   scripts/k8s/harvis-k8s.sh up             install k3s if needed, move Harvis into it
#   scripts/k8s/harvis-k8s.sh status         nodes, pods and the addresses Harvis is on
#   scripts/k8s/harvis-k8s.sh stop           stop Harvis and k3s, off after reboots too; all data kept
#   scripts/k8s/harvis-k8s.sh start          start them again
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
#   HARVIS_K8S_BUILD_SPACE   1 = give the backend the Docker socket (Build Space). Default off:
#                            with it, a taken-over backend controls this machine
#   HARVIS_K8S_REUSE_HOST_OLLAMA  0 = do not offer the Ollama already on this machine to Harvis
#   HARVIS_PULL_MODELS       comma-separated models to download into the cluster's Ollama after install
#   HARVIS_SKIP_EMBEDDER     1 = do not download nomic-embed-text (the Notebooks embedder)
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
TUNNEL=0
BUILD_SPACE=0
NO_CHAT_MODEL=0
kc() { $SUDO k3s kubectl "$@"; }
# The last assignment in .env wins, as it does for compose.
env_get() { grep "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"' \r" || true; }
say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }
# Like env_get, but keeps spaces and quotes-inside (a label such as "Mac Studio").
env_get_raw() { grep "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/\r$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\\(.*\\)'\$/\\1/" || true; }
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
k8s_mode_on() { [ "$($SUDO cat "$STATE_DIR/mode" 2>/dev/null || true)" = "k8s" ]; }
# shellcheck source=k8s-firewall.sh
. "$HERE/k8s-firewall.sh"
# shellcheck source=k8s-host-ollama.sh
. "$HERE/k8s-host-ollama.sh"

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
  local img id stamp ids
  # Every image's content id, changed or not, goes to the generator: a rebuilt image
  # keeps its tag, and only this id in the pod template makes k8s restart its pods.
  IMAGE_IDS_FILE="$(mktemp)"; ids="$(mktemp)"
  while IFS= read -r img; do
    [ -n "$img" ] || continue
    # Not .Id: with Docker's containerd image store every rebuild gets a new Id
    # (fresh provenance timestamp) even when nothing in the image changed. Compose's
    # own labels are left out too: two services that build one tag (browser-runner,
    # preview-runner) stamp it with whichever finished last, which flips run to run.
    id="$(docker image inspect "$img" 2>/dev/null | python3 -c '
import hashlib, json, sys
d = json.load(sys.stdin)[0]
c = dict(d["Config"])
c["Labels"] = {k: v for k, v in (c.get("Labels") or {}).items() if not k.startswith("com.docker.compose.")}
print(hashlib.sha256(json.dumps([d["RootFS"]["Layers"], c], sort_keys=True).encode()).hexdigest())' 2>/dev/null)" \
      || die "image $img is missing — run: docker compose build"
    printf '%s\t%s\n' "$img" "$id" >> "$ids"
    stamp="$STATE_DIR/images/$(printf '%s' "$img" | tr '/:@' '___').id"
    if [ "$($SUDO cat "$stamp" 2>/dev/null || true)" = "$id" ]; then continue; fi
    say "  importing $img into k3s ..."
    docker save "$img" | $SUDO k3s ctr images import - >/dev/null
    printf '%s' "$id" | $SUDO tee "$stamp" >/dev/null
  done < <(docker compose config --format json | python3 -c '
import json, sys
d = json.load(sys.stdin)
proj = d.get("name") or "harvis"
needed = {dep for s in d["services"].values() for dep in (s.get("depends_on") or {})}
for n, s in sorted(d["services"].items()):
    # Same rule as compose_to_k8s.py: a one-shot nothing waits on is not rendered.
    if str(s.get("restart", "")).strip("\"") in ("no", "") and n not in needed:
        continue
    if s.get("build"):
        print(s.get("image") or f"{proj}-{n}:latest")' | sort -u)
  python3 -c 'import json, sys; print(json.dumps(dict(l.rstrip("\n").split("\t", 1) for l in open(sys.argv[1]) if l.strip())))' \
    "$ids" > "$IMAGE_IDS_FILE"
  rm -f "$ids"
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
    gen_args+=(--ollama-image "$OLLAMA_IMAGE"
      --node-memory "$(kc get node "$1" -o jsonpath='{.status.allocatable.memory}')"
      --node-cpu "$(kc get node "$1" -o jsonpath='{.status.allocatable.cpu}')")
    if [ "$LAN_PORT" != "0" ]; then
      gen_args+=(--lan-models-port "$LAN_PORT" --lan-models-url "http://$2:$LAN_PORT")
    fi
  fi
  [ "$GPU" = "1" ] && gen_args+=(--gpu)
  [ "$BUILD_SPACE" = "1" ] && gen_args+=(--build-space)
  if [ -n "$HOST_OLLAMA_ENTRY" ]; then
    llm_env+=(HARVIS_OLLAMA_HOSTS="$(hosts_with_entry "$(existing_hosts)" "$HOST_OLLAMA_ENTRY")")
  fi
  # Comma-separated private ranges the agent browser may still open (e.g. a lab wiki).
  local cidr
  for cidr in $(env_get HARVIS_BROWSER_ALLOW_CIDRS | tr ',' ' '); do gen_args+=(--browser-allow-cidr "$cidr"); done
  if [ "$TUNNEL" = "1" ]; then
    # cloudflared comes from compose's tunnel profile. --profile would replace
    # COMPOSE_PROFILES, so the profile is added to it instead. Under the network
    # lock .env keeps the profile off and the restart policy at "no" (Docker must
    # not start it); here it is rendered with 0 copies and the guard scales it.
    local profiles="${COMPOSE_PROFILES-$(env_get COMPOSE_PROFILES)}"
    case ",$profiles," in *,tunnel,*) ;; *) profiles="${profiles:+$profiles,}tunnel" ;; esac
    llm_env+=(COMPOSE_PROFILES="$profiles" HARVIS_TUNNEL_RESTART=unless-stopped)
    if [ -n "$(env_get HARVIS_TUNNEL_NETWORKS)" ]; then gen_args+=(--tunnel-replicas 0); fi
  fi
  env "${llm_env[@]+"${llm_env[@]}"}" docker compose config --format json \
    | python3 "$HERE/compose_to_k8s.py" --namespace "$NS" --node-name "$1" --node-ip "$2" \
        --dns-ip "$3" --repo "$REPO" \
        --volume-root "$(docker info -f '{{.DockerRootDir}}')/volumes" \
        ${IMAGE_IDS_FILE:+--image-ids "$IMAGE_IDS_FILE"} "${gen_args[@]}"
}

# The Docker socket is host root for whoever controls the backend, so it is opt-in here.
choose_build_space() {
  BUILD_SPACE=0
  if [ "${HARVIS_K8S_BUILD_SPACE-$(env_get HARVIS_K8S_BUILD_SPACE)}" = "1" ]; then
    BUILD_SPACE=1
    say "⚠ Build Space is ON for Kubernetes (HARVIS_K8S_BUILD_SPACE=1): the backend can control this machine through Docker."
  else
    say "• Build Space is off on Kubernetes; to turn it on set HARVIS_K8S_BUILD_SPACE=1 in .env and re-run ./install.sh --k8s (on means the backend can control this machine)."
  fi
}

pick_lan_port() {
  local cur
  # The shell wins over .env, as for the other settings; .env makes a choice such as 0 stick.
  local want="${HARVIS_LAN_MODELS_PORT:-$(env_get HARVIS_LAN_MODELS_PORT)}"
  LAN_PORT="${want:-11434}"
  [ "$LAN_PORT" = "0" ] && return 0
  # A re-run keeps the port we already serve on, even if that was the 11435 fallback.
  cur="$(kc -n "$NS" get svc lan-models -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || true)"
  if [ -n "$cur" ] && { [ -z "$want" ] || [ "$cur" = "$LAN_PORT" ]; }; then
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
    [ "$d" = cloudflared ] && continue # report_tunnel: Harvis is up without it
    if kc -n "$NS" rollout status "deploy/$d" --timeout=600s >/dev/null 2>&1; then printf '  ✓ %-16s ready\n' "$d"
    else printf '  ✗ %-16s not ready\n' "$d"; failed="$failed $d"; fi
  done
  [ -z "$failed" ] || { say "✗ Not ready:$failed — see: sudo k3s kubectl -n $NS describe pod -l app.kubernetes.io/name=<name>"; return 1; }
}

# ── models and first-run checks ─────────────────────────────────────────────
# Nothing here is fatal: offline or blocked DNS costs the downloads only, and
# Settings → Models and the Notebooks page still offer them.
ollama_exec() { kc -n "$NS" exec deploy/ollama -- "$@"; }
# Same marks as the backend's notebooks.embedder_status.is_embedder.
EMBEDDER_MARKS='embed|minilm|bge-'

pull_model() { # $1 name
  case "$1" in
    "" | -* | *[!A-Za-z0-9._:/@-]*) say "  ⚠ skipped '$1': not a model name"; return 0 ;;
  esac
  say "  pulling $1 ..."
  if ollama_exec ollama pull "$1" >/dev/null 2>&1; then say "  ✓ $1"
  else say "  ⚠ could not download $1 (offline, or DNS blocked?)"; fi
}

post_install_checks() {
  local m listing names pull_list skip_embedder vh
  local -a pulls=()
  if [ "${HARVIS_K8S_OLLAMA:-1}" = "1" ]; then
    pull_list="${HARVIS_PULL_MODELS-$(env_get HARVIS_PULL_MODELS)}"
    IFS=', ' read -r -a pulls <<< "$pull_list" || true
    for m in ${pulls[@]+"${pulls[@]}"}; do pull_model "$m"; done
    if listing="$(ollama_exec ollama list 2>/dev/null)"; then
      names="$(printf '%s\n' "$listing" | awk 'NR > 1 { print $1 }')"
      skip_embedder="${HARVIS_SKIP_EMBEDDER-$(env_get HARVIS_SKIP_EMBEDDER)}"
      if [ "$skip_embedder" != "1" ] && [ -z "$(printf '%s\n' "$names" | grep -iE "$EMBEDDER_MARKS" || true)" ]; then
        pull_model nomic-embed-text
      fi
      # Models on a reused host Ollama count as models too.
      if [ -z "$HOST_OLLAMA_ENTRY" ] && [ -z "$(printf '%s\n' "$names" | grep -viE "$EMBEDDER_MARKS" | grep . || true)" ]; then
        NO_CHAT_MODEL=1
      fi
    fi
    if [ "$GPU" = "1" ] && ! ollama_exec sh -c 'ls /dev/nvidia[0-9]* >/dev/null 2>&1 || nvidia-smi -L >/dev/null 2>&1' >/dev/null 2>&1; then
      say "  ⚠ The Ollama pod cannot see the GPU, so models run on the CPU — check: sudo k3s kubectl -n $NS describe pod -l app.kubernetes.io/name=ollama"
    fi
  fi
  # /health answers while the models are still downloading, so ask for their state.
  if kc -n "$NS" get deploy voice-onnx >/dev/null 2>&1; then
    vh="$(kc -n "$NS" exec deploy/voice-onnx -- curl -s --max-time 5 http://localhost:8000/health 2>/dev/null || true)"
    case "$(printf '%s' "$vh" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("prefetch", {}).get("status", ""))' 2>/dev/null || true)" in
      ready | disabled) ;;
      *) say "  ⚠ Voice models are not ready yet (still downloading, or blocked); speech fails until they are — check: sudo k3s kubectl -n $NS exec deploy/voice-onnx -- curl -s localhost:8000/health" ;;
    esac
  fi
  return 0
}

# Same reason as install.sh's sync_db_password: an old data directory keeps the
# password it was created with. The backend opens its pool once, so if it
# already failed against the old password it is restarted.
sync_db_password() {
  local i
  kc -n "$NS" rollout status deploy/pgsql --timeout=300s >/dev/null 2>&1 || { say "⚠ Database not ready; skipped the password check"; return 0; }
  for i in $(seq 1 30); do
    if printf "ALTER ROLE pguser WITH PASSWORD :'pw';\n" | kc -n "$NS" exec -i deploy/pgsql -- \
        sh -c 'psql -q -v ON_ERROR_STOP=1 -v pw="$POSTGRES_PASSWORD" -U pguser -d postgres' >/dev/null 2>&1; then
      say "  ✓ Database password matches .env"
      if kc -n "$NS" logs deploy/backend --all-containers 2>/dev/null | grep -q 'password authentication failed'; then
        kc -n "$NS" rollout restart deploy/backend >/dev/null
      fi
      return 0
    fi
    sleep 2
  done
  say "⚠ Could not confirm the database password; if sign-in fails, run ./install.sh --k8s again"
}

report_tunnel() {
  [ "$TUNNEL" = "1" ] || return 0
  local verdict
  if [ -n "$(env_get HARVIS_TUNNEL_NETWORKS)" ] && ! verdict="$(bash scripts/tunnel-guard.sh check 2>&1)"; then
    say "  • cloudflared      off here — ${verdict}; it starts by itself on $(env_get HARVIS_TUNNEL_NETWORKS)"
    return 0
  fi
  # Ready means a live connection to Cloudflare (its /ready check).
  # A rollout of 0 copies also "succeeds", so a ready copy is what counts.
  if kc -n "$NS" rollout status deploy/cloudflared --timeout=120s >/dev/null 2>&1 &&
    [ "$(kc -n "$NS" get deploy cloudflared -o jsonpath='{.status.readyReplicas}' 2>/dev/null)" -ge 1 ] 2>/dev/null; then
    say "  ✓ cloudflared      connected to Cloudflare"
  else
    say "  ✗ cloudflared      not connected — see: sudo k3s kubectl -n $NS logs deploy/cloudflared"
  fi
}

cmd_up() {
  command -v docker >/dev/null || die "Docker is required (Harvis builds its images and runs workspace sandboxes with it)"
  # "local" binds port 9000 to 127.0.0.1, which Kubernetes never publishes, and
  # tunnel-only has no LAN listener to put in front of a LoadBalancer.
  local exposure
  exposure="$(env_get HARVIS_EXPOSURE | tr "[:upper:]" "[:lower:]")"
  case "$exposure" in
    local) die "HARVIS_EXPOSURE=local works with plain Docker only. Run ./install.sh --k8s --expose lan to switch it." ;;
    tunnel) die "HARVIS_EXPOSURE=tunnel works with plain Docker only. Run ./install.sh --k8s --expose lan+tunnel for the LAN and the tunnel together." ;;
    lan+tunnel) TUNNEL=1 ;;
    "") say "⚠ HARVIS_EXPOSURE is not set, so the first sign-up becomes admin. ./install.sh --k8s sets the lan rules." ;;
  esac
  # Compose binds port 9000 to 127.0.0.1 unless told otherwise, and Kubernetes
  # publishes it only when it is bound to every address. The shell wins over .env.
  export HARVIS_BIND_ADDR_PUBLIC=0.0.0.0
  export HARVIS_CONTROL_DIR=/var/lib/harvis/control
  install_k3s
  # After ./install.sh --stop k3s is installed but disabled; start it like --start does.
  if ! svc is-active --quiet "$(k3s_unit)"; then
    bash scripts/power-button.sh clear 2>/dev/null || true
    svc enable --now "$(k3s_unit)" >/dev/null 2>&1 || die "k3s did not start — see: sudo journalctl -u $(k3s_unit) -n 100"
  fi
  wait_node_ready
  setup_gpu
  check_dns
  import_images
  local node ip dns
  node="$(server_node)"; ip="$(node_ip "$node")"
  dns="$(kc -n kube-system get svc kube-dns -o jsonpath='{.spec.clusterIP}')"
  pick_lan_port
  detect_host_ollama "$ip"
  choose_build_space
  # A Docker-mode guard would keep restarting a container that no longer exists;
  # the Kubernetes one is installed fresh below so it runs this checkout's copy.
  if bash scripts/tunnel-guard.sh installed 2>/dev/null; then bash scripts/tunnel-guard.sh uninstall >/dev/null || true; fi
  docker_hand_over
  $SUDO mkdir -p /var/lib/harvis/ollama
  bash scripts/power-button.sh install || true
  say "Applying Harvis to the cluster (namespace $NS) ..."
  render "$node" "$ip" "$dns" | kc apply -f - >/dev/null
  # apply never deletes: with sharing turned off, remove what an earlier run made.
  if [ "$LAN_PORT" = "0" ] || [ "${HARVIS_K8S_OLLAMA:-1}" != "1" ]; then
    kc -n "$NS" delete svc/lan-models deploy/lan-models configmap/lan-models \
      networkpolicy/public-lan-models networkpolicy/ollama-from-lan-models \
      --ignore-not-found >/dev/null 2>&1 || true
  fi
  # From here Kubernetes holds the ports, ready or not. Marked now, not after the
  # rollout: a run that failed on one pod left no mark, and the next ./install.sh
  # --k8s then found its own ports "taken" by the cluster it had just made.
  printf 'k8s\n' | $SUDO tee "$STATE_DIR/mode" >/dev/null
  apply_kubelet_firewall
  if [ "$TUNNEL" = "1" ]; then
    if [ -n "$(env_get HARVIS_TUNNEL_NETWORKS)" ] && ! bash scripts/tunnel-guard.sh install; then
      say "  ⚠ The network lock did not start, so the tunnel stays at 0 copies until it does."
    fi
  else
    # apply never removes objects, so a tunnel from an earlier lan+tunnel run would stay.
    kc -n "$NS" delete deploy,secret,svc,networkpolicy -l app.kubernetes.io/name=cloudflared \
      --ignore-not-found >/dev/null
  fi
  rm -f "${IMAGE_IDS_FILE:-}"
  sync_db_password
  say "Waiting for Harvis to start in Kubernetes:"
  wait_rollout
  report_tunnel
  post_install_checks
  say ""
  say "✓ Harvis runs on Kubernetes → http://$ip:9000  (and http://localhost:9000)"
  if [ "$TUNNEL" = "1" ]; then
    if [ "$(env_get HARVIS_TUNNEL_AUTH)" = harvis ]; then
      say "  From the internet: your Cloudflare hostname; new sign-ups wait for you in Settings → People"
    else
      say "  From the internet: your Cloudflare hostname, behind Cloudflare Access"
    fi
  fi
  if [ "${HARVIS_K8S_OLLAMA:-1}" = "1" ]; then
    [ "$LAN_PORT" = "0" ] || say "  Models shared on your network at http://$ip:$LAN_PORT (chat and model listing only)"
    if [ "$NO_CHAT_MODEL" = "1" ]; then
      say "  ⚠ No chat model is installed yet, so chat has nothing to answer with. Add one:  sudo k3s kubectl -n $NS exec deploy/ollama -- ollama pull gemma4:e2b"
    else
      say "  Add a model:  sudo k3s kubectl -n $NS exec deploy/ollama -- ollama pull gemma4:e2b"
    fi
  fi
}

cmd_status() {
  k3s_installed || { say "Kubernetes mode is off (k3s is not installed). Harvis runs on Docker."; return 0; }
  if k8s_mode_on; then apply_kubelet_firewall quiet; fi
  say "Nodes:"; kc get nodes -o wide
  say ""; say "Harvis pods ($NS):"; kc -n "$NS" get pods -o wide 2>/dev/null || say "  none — Kubernetes mode is off"
  say ""; say "Addresses:"; kc -n "$NS" get svc --field-selector spec.type=LoadBalancer 2>/dev/null || true
}

cmd_off() {
  remove_kubelet_firewall
  # Docker mode installs its own guard, a user service, on the way back.
  if bash scripts/tunnel-guard.sh installed 2>/dev/null; then bash scripts/tunnel-guard.sh uninstall >/dev/null || true; fi
  if k3s_installed && kc get ns "$NS" >/dev/null 2>&1; then
    say "Removing Harvis from Kubernetes (data stays on this machine) ..."
    kc delete ns "$NS" --wait=true --timeout=300s >/dev/null
    kc delete clusterrole,clusterrolebinding "harvis-$NS-node-reader" --ignore-not-found >/dev/null
    say "✓ Kubernetes namespace $NS removed"
  fi
  $SUDO rm -f "$STATE_DIR/mode"
  # install.sh --k8s-off sets this and runs its own full launch next.
  [ "${HARVIS_K8S_OFF_SKIP_START:-0}" = "1" ] && return 0
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

# ── Stop / start ────────────────────────────────────────────────────────────
svc() { $SUDO systemctl "$@"; }
# A server runs the k3s unit, a joined worker k3s-agent.
k3s_unit() { if svc cat k3s >/dev/null 2>&1; then echo k3s; else echo k3s-agent; fi; }
# Stopping the k3s service leaves the pods' containers (and their ports) running.
k3s_killall() { if [ -x /usr/local/bin/k3s-killall.sh ]; then $SUDO /usr/local/bin/k3s-killall.sh >/dev/null 2>&1; fi; }
# A tunnel started by hand (docker run cloudflare/cloudflared …) is outside k3s and the
# network lock, so Stop takes it down too, whatever its tag.
stop_stray_tunnels() {
  command -v docker >/dev/null 2>&1 || return 0
  local ids
  ids="$(docker ps --format '{{.ID}} {{.Image}}' 2>/dev/null | awk '$2 ~ /(^|\/)cloudflare\/cloudflared([:@]|$)/ {print $1}')"
  [ -n "$ids" ] || return 0
  # shellcheck disable=SC2086
  docker stop $ids >/dev/null && say "✓ Stopped a Cloudflare tunnel running in Docker outside Harvis"
}

cmd_stop() {
  command -v k3s >/dev/null 2>&1 || { say "Kubernetes mode is off here (k3s is not installed) — nothing to stop."; return 0; }
  local unit
  unit="$(k3s_unit)"
  say "Stopping Harvis and Kubernetes ($unit) ..."
  # Disabled too, so a reboot does not bring Harvis back onto the network.
  svc disable --now "$unit" >/dev/null 2>&1 || true
  k3s_killall || true
  stop_stray_tunnels || true
  if port_busy 9000; then die "something still answers on port 9000 — see: sudo ss -tlnp 'sport = :9000'"; fi
  say "✓ Harvis is stopped and stays off after a reboot. Nothing was deleted."
  say "  Start it again: ./install.sh --start"
}

cmd_start() {
  command -v k3s >/dev/null 2>&1 || die "Kubernetes mode is off here — start Harvis with ./install.sh"
  local unit
  unit="$(k3s_unit)"
  say "Starting Kubernetes ($unit) and Harvis ..."
  # A Shut down press that was never picked up would stop it again at once.
  bash scripts/power-button.sh clear 2>/dev/null || true
  svc enable --now "$unit" >/dev/null 2>&1 || die "k3s did not start — see: sudo journalctl -u $unit -n 100"
  if [ "$unit" = k3s-agent ]; then say "✓ This worker is back in the cluster"; return 0; fi
  wait_node_ready
  apply_kubelet_firewall
  wait_rollout || return 1
  say "✓ Harvis is back → http://$(node_ip "$(server_node)"):9000"
}

cmd_join_command() {
  k3s_installed || die "Kubernetes mode is not on here — run ./install.sh --k8s first"
  if k8s_mode_on; then apply_kubelet_firewall quiet; fi
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

# Sourced (by the tests) only to get the functions.
[ "${BASH_SOURCE[0]}" = "$0" ] || return 0
case "${1:-}" in
  up) cmd_up ;;
  status) cmd_status ;;
  stop) cmd_stop ;;
  start) cmd_start ;;
  off) cmd_off ;;
  uninstall) cmd_uninstall ;;
  join-command) cmd_join_command ;;
  join) shift; cmd_join "$@" ;;
  *) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
