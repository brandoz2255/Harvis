#!/usr/bin/env bash
# Keeps the Cloudflare Tunnel on the networks named in HARVIS_TUNNEL_NETWORKS
# (.env, set by ./install.sh --tunnel-networks). That is the lab profile: the
# tunnel runs on, say, the lab Wi-Fi or wired network and never on eduroam or anywhere
# else, including for a moment after boot.
#
#   scripts/tunnel-guard.sh check      is this network allowed? (exit 0 = yes)
#   scripts/tunnel-guard.sh enforce    start or stop the tunnel once to match
#   scripts/tunnel-guard.sh hold       like enforce, but never starts it
#   scripts/tunnel-guard.sh watch      enforce on every network change (the service)
#   scripts/tunnel-guard.sh install    run watch as a systemd service
#   scripts/tunnel-guard.sh uninstall  remove that service (stops the tunnel)
#   scripts/tunnel-guard.sh status     network, tunnel and service in one look
#   scripts/tunnel-guard.sh installed  is the service installed? (exit 0 = yes)
#
# A network is allowed only when EVERY interface holding a default route is on
# the list: Wi-Fi by the SSID it is connected to, anything else by its
# NetworkManager connection name. No list, no NetworkManager, no default route,
# or an interface still connecting all count as not allowed. Linux only.
# HARVIS_TUNNEL_PAUSED=1 in .env keeps it off everywhere (./harvis-start.sh lan).
#
# Under the lock the tunnel container has restart policy "no" and is not in
# COMPOSE_PROFILES, so Docker never starts it by itself; this script does.
#
# In Kubernetes mode (scripts/k8s/harvis-k8s.sh) the tunnel is the cloudflared
# Deployment, rendered with 0 copies; this script scales it. The service is a
# system one there (kubectl needs root on k3s) and runs a root-owned copy of
# this file, so nothing a user can edit runs as root. It starts after k3s and
# stops before it, and stopping scales the tunnel to 0, so it is down at boot
# until the network has been checked.
set -uo pipefail

cd "${HARVIS_REPO:-$(dirname "$0")/..}" || exit 1

env_value() { # same reading as scripts/exposure.sh; values are never printed
  [ -f .env ] || return 0
  grep "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/" || true
}
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
trim() { local s="$1"; s="${s#"${s%%[![:space:]]*}"}"; printf '%s' "${s%"${s##*[![:space:]]}"}"; }

PREFIX="${HARVIS_CONTAINER_PREFIX:-$(env_value HARVIS_CONTAINER_PREFIX)}"
STACK="${HARVIS_STACK_NAME:-$(env_value HARVIS_STACK_NAME)}"
CONTAINER="${PREFIX}harvis-cloudflared"
UNIT="${STACK:-harvis}-tunnel-guard.service"
UNIT_DIR="${XDG_CONFIG_HOME:-${HOME:-/nonexistent}/.config}/systemd/user"  # no HOME under the system unit
SYSTEM_UNIT="/etc/systemd/system/$UNIT"
ROOT_COPY="/usr/local/lib/harvis/${STACK:-harvis}-tunnel-guard.sh"
K8S_NS="${HARVIS_K8S_NAMESPACE:-harvis}"
K8S_REPLICAS=2
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
k8s_mode() { [ "$(cat /var/lib/harvis/k8s/mode 2>/dev/null)" = k8s ]; }
kc() { $SUDO k3s kubectl --request-timeout=10s -n "$K8S_NS" "$@"; }
# One quick request: a down API otherwise costs a timeout per discovery call (~50 s).
api_up() { $SUDO k3s kubectl --request-timeout=5s get --raw /readyz >/dev/null 2>&1; }
REASON=""
NETWORKS=""
# Read on every check, so a running guard follows ./install.sh --tunnel-networks.
# The installer's preflight passes the list it is about to write instead.
load_networks() { NETWORKS="${HARVIS_TUNNEL_NETWORKS:-$(env_value HARVIS_TUNNEL_NETWORKS)}"; }
load_networks

on_list() { # $1 = a network name; HARVIS_TUNNEL_NETWORKS is comma-separated
  local want item items
  want="$(lower "$(trim "$1")")"
  [ -n "$want" ] || return 1
  IFS=, read -ra items <<< "$NETWORKS"
  for item in "${items[@]}"; do
    [ "$(lower "$(trim "$item")")" = "$want" ] && return 0
  done
  return 1
}

default_devices() {
  # Default routes, plus whatever carries traffic to Cloudflare's tunnel edge:
  # a VPN's 0.0.0.0/1 halves or a pushed static route are not "default".
  { ip -4 route show default 2>/dev/null; ip -6 route show default 2>/dev/null
    ip -4 route get 198.41.192.7 2>/dev/null; ip -6 route get 2606:4700:a0::1 2>/dev/null; } |
    awk '{for (i = 1; i < NF; i++) if ($i == "dev") print $(i + 1)}' | sort -u
}

network_of() { # $1 = device — the SSID for Wi-Fi, else the connection name
  local dev="$1" type
  type="$(nmcli -g GENERAL.TYPE device show "$dev" 2>/dev/null)"
  if [ "$type" = wifi ]; then
    # The SSID the radio is on now, not the saved profile's name.
    nmcli -t -f IN-USE,SSID device wifi list ifname "$dev" --rescan no 2>/dev/null |
      sed -n 's/^\*://p' | head -1 | sed 's/\\:/:/g'
  else
    nmcli -g GENERAL.CONNECTION device show "$dev" 2>/dev/null
  fi
}

# Sets REASON either way; returns 0 only when the tunnel may run here.
network_allowed() {
  local devs dev net seen=""
  load_networks
  if [ -z "$(trim "$NETWORKS")" ]; then
    REASON="HARVIS_TUNNEL_NETWORKS is empty"; return 1
  fi
  if ! command -v nmcli >/dev/null 2>&1 || ! command -v ip >/dev/null 2>&1; then
    REASON="the network lock needs Linux with NetworkManager (nmcli)"; return 1
  fi
  # Mid-switch the old default route can still be up while the next network
  # comes in; stop first rather than let cloudflared reconnect through it.
  if nmcli -t -f STATE device 2>/dev/null | grep -q '^connecting'; then
    REASON="a network is connecting"; return 1
  fi
  devs="$(default_devices)"
  if [ -z "$devs" ]; then
    REASON="no network (no default route)"; return 1
  fi
  for dev in $devs; do
    net="$(network_of "$dev")"
    if [ -z "$net" ] || [ "$net" = "--" ]; then
      REASON="${dev} carries traffic but NetworkManager cannot name its network"; return 1
    fi
    if ! on_list "$net"; then
      REASON="${dev} is on '${net}', which is not in HARVIS_TUNNEL_NETWORKS"; return 1
    fi
    seen="${seen:+$seen, }${net}"
  done
  REASON="on ${seen}"
  return 0
}

tunnel_state() { # running | stopped | missing
  local s
  if k8s_mode; then
    # Missing also while k3s is still starting; the watch then checks every 3 s.
    api_up || { echo missing; return; }
    s="$(kc get deploy cloudflared -o jsonpath='{.spec.replicas}' 2>/dev/null)" || { echo missing; return; }
    [ -n "$s" ] && [ "$s" != 0 ] && echo running || echo stopped
    return
  fi
  s="$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" || { echo missing; return; }
  [ "$s" = true ] && echo running || echo stopped
}

# While the API is down (k3s starting, or stuck), the kubelet still runs the pods
# it last had, and a boot after a crash brings back the replicas stored then.
# With k3s up the runtime stops them, though the kubelet may start them again; with
# k3s stopped its containers keep running and nothing answers, so the process is
# killed by its bundle. The watch repeats this every 3 s until the API answers and
# the scale to 0 sticks. Pods are pinned to this node.
K3S_TASKS=/run/k3s/containerd/io.containerd.runtime.v2.task/k8s.io
stop_tunnel_containers() {
  local ids b pid n=0
  if ids="$($SUDO k3s crictl ps -q --name '^cloudflared$' --label "io.kubernetes.pod.namespace=${K8S_NS}" 2>/dev/null)"; then
    [ -n "$ids" ] || return 0
    # shellcheck disable=SC2086
    if $SUDO k3s crictl stop --timeout 0 $ids >/dev/null 2>&1; then
      echo "tunnel stopped without the Kubernetes API: ${REASON}"; return 0
    fi
    echo "could not stop the cloudflared containers (${REASON})"; return 1
  fi
  for b in $($SUDO find "$K3S_TASKS" -mindepth 1 -maxdepth 1 -type d 2>/dev/null); do
    $SUDO grep -q '"io.kubernetes.cri.container-name":"cloudflared"' "$b/config.json" 2>/dev/null || continue
    $SUDO grep -q "\"io.kubernetes.cri.sandbox-namespace\":\"${K8S_NS}\"" "$b/config.json" 2>/dev/null || continue
    pid="$($SUDO cat "$b/init.pid" 2>/dev/null)"
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    # A stale pid may now belong to something else: it must sit in this container's cgroup.
    $SUDO grep -q "${b##*/}" "/proc/$pid/cgroup" 2>/dev/null || continue
    $SUDO kill -KILL "$pid" 2>/dev/null && n=$((n + 1))
  done
  [ "$n" -eq 0 ] || echo "tunnel stopped while k3s is down: ${REASON}"
}

stop_tunnel() {
  local state
  state="$(tunnel_state)"
  if [ "$state" = missing ] && k8s_mode; then stop_tunnel_containers; return; fi
  [ "$state" = running ] || return 0
  if k8s_mode; then
    # Pods go at once: cloudflared drains for seconds on SIGTERM, still serving.
    if kc scale deploy/cloudflared --replicas=0 >/dev/null 2>&1; then
      kc delete pod -l app.kubernetes.io/name=cloudflared --grace-period=0 --force --wait=false >/dev/null 2>&1
      echo "tunnel stopped: ${REASON}"
    else
      echo "could not scale cloudflared to 0 (${REASON})"; return 1
    fi
    return 0
  fi
  # kill, not stop: cloudflared drains for seconds on SIGTERM, still serving.
  if docker kill "$CONTAINER" >/dev/null 2>&1; then
    echo "tunnel stopped: ${REASON}"
  else
    echo "could not stop ${CONTAINER} (${REASON})"; return 1
  fi
}

start_tunnel() {
  [ "$(tunnel_state)" = running ] && return 0
  if k8s_mode; then
    kc scale deploy/cloudflared --replicas="$K8S_REPLICAS" >/dev/null 2>&1 && echo "tunnel started: ${REASON}"
    return 0
  fi
  # Through compose, not docker start, so a new token or image in .env is applied
  # (compose recreates only when the config changed). --no-deps: only the tunnel.
  HARVIS_TUNNEL_RESTART=no docker compose --profile tunnel up -d --no-deps cloudflared >/dev/null 2>&1 &&
    echo "tunnel started: ${REASON}"
}

# HARVIS_TUNNEL_PAUSED=1 (.env, set by ./harvis-start.sh lan) keeps the tunnel off on
# every network, allowed ones included, without touching the lock list.
paused() { [ "${HARVIS_TUNNEL_PAUSED:-$(env_value HARVIS_TUNNEL_PAUSED)}" = 1 ]; }

enforce() { # $1 = nostart: only ever stop
  if paused; then
    REASON="tunnel switched off (LAN-only mode)"; stop_tunnel
  elif network_allowed; then
    [ "${1:-}" = nostart ] || start_tunnel
  else
    stop_tunnel
  fi
  k8s_mode && return 0
  # Docker must never bring it back by itself (boot, daemon restart), whoever created it.
  local policy
  policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$CONTAINER" 2>/dev/null)" || return 0
  [ "$policy" = no ] || docker update --restart no "$CONTAINER" >/dev/null 2>&1
  return 0
}

watch_networks() {
  command -v nmcli >/dev/null 2>&1 || { echo "nmcli not found; the tunnel stays off"; stop_tunnel; exit 1; }
  local last="" wait
  if k8s_mode; then echo "guarding deploy/cloudflared in ${K8S_NS}; allowed networks: ${NETWORKS}"
  else echo "guarding ${CONTAINER}; allowed networks: ${NETWORKS}"; fi
  enforce
  # One line per NetworkManager event. A quiet minute re-checks anyway, so a
  # lost event or a container started by hand is corrected within 30 seconds.
  nmcli monitor 2>/dev/null | while :; do
    wait=30
    k8s_mode && [ "$(tunnel_state)" = missing ] && wait=3
    if read -r -t "$wait" _; then
      local n=0  # take a burst of events as one, but never wait more than ~3 s
      while [ "$n" -lt 10 ] && read -r -t 0.3 _; do n=$((n + 1)); done
    elif [ $? -le 128 ]; then
      exit 1  # nmcli monitor ended; systemd restarts the guard
    fi
    enforce
    [ "$REASON" = "$last" ] || { echo "network: ${REASON}"; last="$REASON"; }
  done
  exit 1
}

install_service_k8s() {
  $SUDO install -D -o root -g root -m 0755 scripts/tunnel-guard.sh "$ROOT_COPY" || { echo "✗ Could not copy the guard to ${ROOT_COPY}"; return 1; }
  $SUDO tee "$SYSTEM_UNIT" >/dev/null <<EOF
[Unit]
Description=Harvis: Cloudflare Tunnel only on ${NETWORKS} (Kubernetes)
After=k3s.service NetworkManager.service network.target

[Service]
Environment="HARVIS_REPO=$(pwd)"
Environment="HOME=/root"
Environment="HARVIS_K8S_NAMESPACE=${K8S_NS}"
ExecStart=${ROOT_COPY} watch
# Whenever the guard is not running, neither is the tunnel. At shutdown this
# runs before k3s stops, so the tunnel is at 0 copies on the next boot.
ExecStopPost=${ROOT_COPY} stop
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload && $SUDO systemctl enable "$UNIT" >/dev/null 2>&1 &&
    $SUDO systemctl restart "$UNIT" || { echo "✗ Could not start ${UNIT}"; return 1; }
  echo "✓ Network lock on: the tunnel runs only on ${NETWORKS} (${UNIT}, system service)"
}

install_service() {
  command -v systemctl >/dev/null 2>&1 || { echo "✗ systemd not found; the network lock needs it"; return 1; }
  if k8s_mode; then install_service_k8s; return; fi
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/$UNIT" <<EOF
[Unit]
Description=Harvis: Cloudflare Tunnel only on ${NETWORKS}
After=network.target

[Service]
ExecStart="$(pwd)/scripts/tunnel-guard.sh" watch
# Whenever the guard is not running, neither is the tunnel.
ExecStopPost="$(pwd)/scripts/tunnel-guard.sh" stop
${DOCKER_HOST:+Environment="DOCKER_HOST=${DOCKER_HOST}"}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload &&
    systemctl --user enable "$UNIT" >/dev/null 2>&1 &&
    systemctl --user restart "$UNIT" || { echo "✗ Could not start ${UNIT} (systemctl --user)"; return 1; }
  echo "✓ Network lock on: the tunnel runs only on ${NETWORKS} (${UNIT})"
}

uninstall_service() {
  if [ -f "$SYSTEM_UNIT" ]; then
    $SUDO systemctl disable --now "$UNIT" >/dev/null 2>&1 || true
    $SUDO rm -f "$SYSTEM_UNIT" "$ROOT_COPY"
    $SUDO systemctl daemon-reload >/dev/null 2>&1 || true
    echo "✓ Network lock off (${UNIT} removed)"
  fi
  if [ -f "$UNIT_DIR/$UNIT" ]; then
    systemctl --user disable --now "$UNIT" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$UNIT"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    echo "✓ Network lock off (${UNIT} removed)"
  fi
  REASON="network lock removed"; stop_tunnel
  # Made with restart policy "no"; compose recreates it for the regular profile.
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}

status() {
  if network_allowed; then echo "network: allowed — ${REASON}"; else echo "network: not allowed — ${REASON}"; fi
  if paused; then echo "mode:    LAN only (HARVIS_TUNNEL_PAUSED=1)"; else echo "mode:    LAN + tunnel"; fi
  echo "tunnel:  $(tunnel_state)"
  if [ -f "$SYSTEM_UNIT" ]; then echo "guard:   $(systemctl is-active "$UNIT" 2>/dev/null || echo inactive) (system)"
  else echo "guard:   $(systemctl --user is-active "$UNIT" 2>/dev/null || echo inactive)"; fi
}

case "${1:-}" in
  check) network_allowed; rc=$?; echo "$REASON"; exit $rc ;;
  enforce) enforce ;;
  hold) enforce nostart ;;
  watch) watch_networks ;;
  stop) REASON="guard stopped"; stop_tunnel ;;
  install) install_service ;;
  uninstall) uninstall_service ;;
  status) status ;;
  installed) [ -f "$UNIT_DIR/$UNIT" ] || [ -f "$SYSTEM_UNIT" ] ;;
  *) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
