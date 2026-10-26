#!/usr/bin/env bash
# The "Shut down Harvis" button in Command Center → Maintenance (admins only).
#
#   scripts/power-button.sh install    watch for the button (systemd, needs sudo)
#   scripts/power-button.sh uninstall  remove the watcher; the button disappears
#   scripts/power-button.sh installed  is the watcher installed? (exit 0 = yes)
#   scripts/power-button.sh clear      forget a press nobody picked up (--start)
#   scripts/power-button.sh fire       what the watcher runs: stop Harvis now
#
# The backend cannot stop the machine it runs on, and it is not given the power to.
# It only creates the file inbox/stop in CONTROL_DIR, which is mounted into it as
# /harvis-control. A systemd path unit sees the file and runs a root-owned copy of
# this script, which ignores what the file says and does what ./install.sh --stop
# does: Kubernetes mode disables k3s and kills its containers, Docker mode stops
# this checkout's containers. Both stay off after a reboot; nothing is deleted.
# Start again on the server with ./install.sh --start. Linux with systemd only;
# elsewhere the button is not shown.
set -uo pipefail

CONTROL_DIR="${HARVIS_CONTROL_DIR:-/var/lib/harvis/control}"
# CONTROL_DIR and "ready" are root's; only inbox/ is the backend's, so root never
# writes through a path the backend could have pointed somewhere else.
INBOX="$CONTROL_DIR/inbox"
BACKEND_UID="${HARVIS_BACKEND_UID:-1001}"  # docker-compose.yaml runs the backend as 1001:1001
UNIT=harvis-power
ROOT_COPY=/usr/local/lib/harvis/power-button.sh
K8S_MODE_FILE="${HARVIS_K8S_MODE_FILE:-/var/lib/harvis/k8s/mode}"
K3S_KILLALL="${HARVIS_K3S_KILLALL:-/usr/local/bin/k3s-killall.sh}"
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="${HARVIS_POWER_SUDO:-sudo}"

# Empty the inbox whatever was put in it (a file, a folder, a link).
clear_inbox() {
  $SUDO rm -rf "$INBOX" && $SUDO install -d -o "$BACKEND_UID" -g "$BACKEND_UID" -m 0700 "$INBOX"
}

# A tunnel started by hand (docker run cloudflare/cloudflared …) is outside Harvis and
# the network lock; the button takes it down too, whatever its tag.
stop_stray_tunnels() {
  command -v docker >/dev/null 2>&1 || return 0
  local ids
  ids="$(docker ps --format '{{.ID}} {{.Image}}' 2>/dev/null | awk '$2 ~ /(^|\/)cloudflare\/cloudflared([:@]|$)/ {print $1}')"
  [ -n "$ids" ] || return 0
  echo "Shut down from the Harvis button: stopping Cloudflare tunnels running in Docker"
  # shellcheck disable=SC2086
  docker stop $ids >/dev/null
}

fire() {
  clear_inbox
  # Lets the button's answer reach the browser before the backend goes away.
  sleep "${HARVIS_POWER_GRACE:-2}"
  stop_stray_tunnels
  if [ "$(cat "$K8S_MODE_FILE" 2>/dev/null)" = k8s ] && systemctl cat k3s >/dev/null 2>&1; then
    echo "Shut down from the Harvis button: stopping k3s"
    systemctl disable --now k3s
    # Stopping the k3s service leaves the pods' containers (and their ports) running.
    if [ -x "$K3S_KILLALL" ]; then "$K3S_KILLALL" >/dev/null 2>&1; fi
    return 0
  fi
  cd "${HARVIS_REPO:-.}" || { echo "Shut down from the Harvis button: checkout ${HARVIS_REPO:-.} is gone"; return 1; }
  local ids
  ids="$(docker ps -q --filter "label=com.docker.compose.project.working_dir=$(pwd)" 2>/dev/null)"
  [ -n "$ids" ] || { echo "Shut down from the Harvis button: no running containers from $(pwd)"; return 0; }
  echo "Shut down from the Harvis button: stopping the containers from $(pwd)"
  # Stopped, not removed: "unless-stopped" containers then stay down across reboots.
  # shellcheck disable=SC2086
  docker stop $ids >/dev/null
}

install_watcher() {
  # systemctl alone is not enough: WSL and containers ship it without systemd running.
  [ -d /run/systemd/system ] || { echo "  The Shut down button needs systemd; it stays hidden."; return 1; }
  cd "$(dirname "$0")/.." || return 1
  # chown/chmod as well: a folder from an older install was the backend's own.
  $SUDO install -d -o root -g root -m 0755 "$CONTROL_DIR" &&
    $SUDO chown root:root "$CONTROL_DIR" && $SUDO chmod 0755 "$CONTROL_DIR" &&
    $SUDO rm -f "$CONTROL_DIR/ready" "$CONTROL_DIR/stop" &&
    clear_inbox &&
    $SUDO install -D -o root -g root -m 0755 scripts/power-button.sh "$ROOT_COPY" || {
    echo "  ✗ Could not set up the Shut down button (needs sudo)"; return 1; }
  $SUDO tee "/etc/systemd/system/$UNIT.path" >/dev/null <<EOF
[Unit]
Description=Harvis: the Shut down button

[Path]
PathExists=$INBOX/stop
Unit=$UNIT.service

[Install]
WantedBy=multi-user.target
EOF
  $SUDO tee "/etc/systemd/system/$UNIT.service" >/dev/null <<EOF
[Unit]
Description=Harvis: shut down (pressed in Command Center)
After=docker.service

[Service]
Type=oneshot
Environment="HARVIS_REPO=$(pwd)"
Environment="HARVIS_CONTROL_DIR=$CONTROL_DIR"
ExecStart=$ROOT_COPY fire
EOF
  $SUDO systemctl daemon-reload && $SUDO systemctl enable --now "$UNIT.path" >/dev/null 2>&1 || {
    echo "  ✗ Could not start $UNIT.path"; return 1; }
  # The backend shows the button only while this marker is there.
  printf 'installed\n' | $SUDO tee "$CONTROL_DIR/ready" >/dev/null
  echo "  ✓ Shut down button on (Command Center → Maintenance, admins only)"
}

uninstall_watcher() {
  $SUDO systemctl disable --now "$UNIT.path" >/dev/null 2>&1 || true
  $SUDO rm -f "/etc/systemd/system/$UNIT.path" "/etc/systemd/system/$UNIT.service" "$ROOT_COPY" \
    "$CONTROL_DIR/ready"
  $SUDO rm -rf "$INBOX"
  $SUDO systemctl daemon-reload >/dev/null 2>&1 || true
  echo "✓ Shut down button off"
}

case "${1:-}" in
  fire) fire ;;
  install) install_watcher ;;
  uninstall) uninstall_watcher ;;
  installed) [ -f "/etc/systemd/system/$UNIT.path" ] ;;
  clear) if [ -f "/etc/systemd/system/$UNIT.path" ]; then clear_inbox; fi ;;
  *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
