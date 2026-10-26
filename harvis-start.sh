#!/usr/bin/env bash
# Start Harvis in Kubernetes mode, on a home network only.
#
#   ./harvis-start.sh lan      Harvis on this machine's LAN address (http://<node IP>:9000)
#                              only; the Cloudflare tunnel stays off, even on a home network
#   ./harvis-start.sh tunnel   the LAN address, plus the public hostname through the
#                              Cloudflare tunnel; the tunnel guard keeps it on the
#                              networks in HARVIS_TUNNEL_NETWORKS and off everywhere else
#   ./harvis-start.sh status   network, mode, tunnel and pods
#   ./harvis-start.sh stop     same as ./install.sh --stop
#
# Both modes refuse to start unless every network carrying traffic is in
# HARVIS_TUNNEL_NETWORKS (the same check as the tunnel guard), so Harvis never comes
# up on a campus network. k3s is started for this session only and left disabled at
# boot: after a reboot nothing runs until this script is run again.
#
# The tunnel itself stays the cloudflared pod (non-root, read-only, network policy:
# nginx:8081, DNS and Cloudflare only). What runs under systemd is the guard,
# harvis-tunnel-guard.service, which scales that pod; the mode is HARVIS_TUNNEL_PAUSED
# in .env, which the guard reads on every check.
#
# Needs: ./install.sh --k8s --expose lan+tunnel --tunnel-networks <names> run once.
set -uo pipefail
cd "$(dirname "$0")" || exit 1

NS="${HARVIS_K8S_NAMESPACE:-harvis}"
GUARD_UNIT="harvis-tunnel-guard.service"

say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }
env_value() { # same reading as scripts/exposure.sh; values are never printed
  [ -f .env ] || return 0
  grep "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/" || true
}
drop_env_key() { [ -f .env ] && sed -i "/^$1=/d" .env; }
set_env_value() { drop_env_key "$1"; printf '%s=%s\n' "$1" "$2" >> .env; }
kc() { # your own copy of the k3s kubeconfig when there is one, so status needs no sudo
  if [ -r "$HOME/.kube/config" ] && command -v kubectl >/dev/null 2>&1; then
    KUBECONFIG="$HOME/.kube/config" kubectl --request-timeout=10s -n "$NS" "$@"
  else
    sudo k3s kubectl --request-timeout=10s -n "$NS" "$@"
  fi
}

# A tunnel started by hand (docker run cloudflare/cloudflared …) is outside the lock.
stop_stray_tunnels() {
  command -v docker >/dev/null 2>&1 || return 0
  local ids
  ids="$(docker ps --format '{{.ID}} {{.Image}}' 2>/dev/null | awk '$2 ~ /(^|\/)cloudflare\/cloudflared([:@]|$)/ {print $1}')"
  [ -n "$ids" ] || return 0
  # shellcheck disable=SC2086
  docker stop $ids >/dev/null && say "✓ Stopped a Cloudflare tunnel running in Docker outside Harvis"
}

preflight() { # $1 = lan | tunnel
  [ "$(cat /var/lib/harvis/k8s/mode 2>/dev/null)" = k8s ] && command -v k3s >/dev/null 2>&1 ||
    die "Kubernetes mode is not set up here — run ./install.sh --k8s first"
  local nets verdict
  nets="$(env_value HARVIS_TUNNEL_NETWORKS)"
  [ -n "$nets" ] || die "No home networks in .env — run: ./install.sh --k8s --tunnel-networks <your Wi-Fi name>"
  verdict="$(bash scripts/tunnel-guard.sh check 2>&1)" ||
    die "Not starting: ${verdict}. Harvis starts only on ${nets}, so it stays off other networks."
  say "✓ Network: ${verdict}"
  if [ "$1" = tunnel ]; then
    [ "$(env_value HARVIS_EXPOSURE)" = lan+tunnel ] ||
      die "The tunnel is not set up — run: ./install.sh --k8s --expose lan+tunnel --tunnel-networks ${nets}"
    [ -n "$(env_value HARVIS_TUNNEL_TOKEN)" ] || die "HARVIS_TUNNEL_TOKEN is empty in .env"
  fi
}

wait_ready() {
  local i
  for i in $(seq 1 90); do
    kc get nodes --no-headers 2>/dev/null | grep -q ' Ready' && break
    [ "$i" = 90 ] && die "the k3s node never became Ready — see: sudo journalctl -u k3s -n 100"
    sleep 2
  done
  local d
  for d in pgsql backend nginx; do
    kc rollout status "deploy/$d" --timeout=600s >/dev/null || die "deploy/$d did not come up — see: sudo k3s kubectl -n $NS get pods"
  done
}

start() { # $1 = lan | tunnel
  preflight "$1"
  sudo -v || die "sudo is needed to start k3s"
  stop_stray_tunnels
  if [ "$1" = lan ]; then set_env_value HARVIS_TUNNEL_PAUSED 1; else drop_env_key HARVIS_TUNNEL_PAUSED; fi

  # A Shut down press that was never picked up would stop it again at once.
  bash scripts/power-button.sh clear 2>/dev/null || true
  say "Starting k3s ..."
  sudo systemctl start k3s || die "k3s did not start — see: sudo journalctl -u k3s -n 100"
  # Off at boot: the machine may boot onto another network before anything checks it.
  sudo systemctl disable k3s >/dev/null 2>&1 || true

  # Refreshes the guard's root-owned copy and restarts it, so it applies the mode now.
  if [ "$(env_value HARVIS_EXPOSURE)" = lan+tunnel ]; then
    bash scripts/tunnel-guard.sh install >/dev/null || die "could not start ${GUARD_UNIT}"
  fi

  say "Waiting for Harvis ..."
  wait_ready
  local node_ip
  node_ip="$(kc get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')"
  if ! ip -4 -o addr show 2>/dev/null | grep -q " ${node_ip}/"; then
    say "⚠ k3s reports node IP ${node_ip}, which this machine no longer has — run: sudo systemctl restart k3s"
  fi
  if curl -fsS --max-time 10 "http://${node_ip}:9000/api/health/services" >/dev/null 2>&1; then
    say "✓ Harvis → http://${node_ip}:9000/harvis/"
  else
    say "⚠ http://${node_ip}:9000 is not answering yet — check: ./harvis-start.sh status"
  fi

  if [ "$1" = tunnel ]; then
    kc rollout status deploy/cloudflared --timeout=180s >/dev/null 2>&1 &&
      say "✓ Cloudflare tunnel connected (only while on $(env_value HARVIS_TUNNEL_NETWORKS))" ||
      say "⚠ The tunnel is not up yet — check: sudo k3s kubectl -n $NS logs deploy/cloudflared"
  else
    say "✓ Tunnel off (LAN only). For the public hostname: ./harvis-start.sh tunnel"
  fi
  say "  k3s stays off after a reboot; run this script again to start."
}

status() {
  # The guard's own tunnel line needs sudo; the pod count below says the same.
  bash scripts/tunnel-guard.sh status | grep -v '^tunnel:'
  if systemctl is-active --quiet k3s; then
    say "k3s:     running"
    kc get deploy --no-headers 2>/dev/null | awk '{printf "  %-26s %s\n", $1, $2}'
  else
    say "k3s:     stopped"
  fi
}

case "${1:-}" in
  lan|tunnel) start "$1" ;;
  status) status ;;
  stop) exec ./install.sh --stop ;;
  *) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
