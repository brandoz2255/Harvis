#!/usr/bin/env bash
# Install FreeToken as a systemd --user service on this machine. Idempotent.
#
#   scripts/freetoken/install-user-units.sh            install + start freetoken.service
#   scripts/freetoken/install-user-units.sh --idle     also enable the idle-stop timer
#   scripts/freetoken/install-user-units.sh --retune   re-measure this box first
#
# On a machine with no ~/.config/freetoken.env, autotune.sh measures the GPU, the RAM
# and the core count and writes one, then the script stops so you can point FT_HOME and
# FT_MODEL at your checkpoint. It does NOT copy another machine's numbers: the settings
# that keep FreeToken alive are a property of the box it runs on.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin"
units="$HOME/.config/systemd/user"
envf="$HOME/.config/freetoken.env"

mkdir -p "$bin" "$units" "$HOME/.config"
install -m 0755 "$here/autotune.sh" "$bin/freetoken-autotune"

if [ "${1:-}" = "--retune" ]; then
  "$here/autotune.sh" --write
  shift || true
fi

if [ ! -f "$envf" ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo "no $envf yet — measuring this machine"
    "$here/autotune.sh" --write
  else
    cp "$here/freetoken.env.example" "$envf"
    echo "no NVIDIA GPU visible, so nothing to measure — copied the example instead."
  fi
  echo "now check FT_HOME and FT_MODEL in $envf point at your venv and checkpoint, then re-run."
  exit 2
fi

install -m 0755 "$here/serve.sh" "$bin/freetoken-serve"
install -m 0755 "$here/idle-stop.sh" "$bin/freetoken-idle-stop"
install -m 0755 "$here/watchdog.sh" "$bin/freetoken-watchdog"
install -m 0755 "$here/control-agent.sh" "$bin/freetoken-control-agent"
install -m 0644 "$here/freetoken.service" "$units/freetoken.service"
install -m 0644 "$here/freetoken-idle.service" "$units/freetoken-idle.service"
install -m 0644 "$here/freetoken-idle.timer" "$units/freetoken-idle.timer"
install -m 0644 "$here/freetoken-watchdog.service" "$units/freetoken-watchdog.service"
install -m 0644 "$here/freetoken-watchdog.timer" "$units/freetoken-watchdog.timer"
install -m 0644 "$here/freetoken-control.service" "$units/freetoken-control.service"
install -m 0644 "$here/freetoken-control.path" "$units/freetoken-control.path"

systemctl --user daemon-reload
systemctl --user enable --now freetoken.service
# On by default: it only ever restarts a node that is up but not answering.
systemctl --user enable --now freetoken-watchdog.timer
# The power switch Harvis's settings pane writes to. Without this the backend can see
# the node but cannot start it — it is in a container and this is a host service.
systemctl --user enable --now freetoken-control.path
"$bin/freetoken-control-agent" >/dev/null 2>&1 || true   # publish status right away
if [ "${1:-}" = "--idle" ]; then
  systemctl --user enable --now freetoken-idle.timer
else
  systemctl --user disable --now freetoken-idle.timer 2>/dev/null || true
fi

# shellcheck disable=SC1090
set -a; . "$envf"; set +a
echo "freetoken.service: $(systemctl --user is-active freetoken.service)"
echo "watchdog: $(systemctl --user is-active freetoken-watchdog.timer) (journalctl --user -u freetoken-watchdog)"
echo "switch:   $(systemctl --user is-active freetoken-control.path) — Harvis can start/stop this node"
echo "logs:   journalctl --user -u freetoken -f"
echo "health: curl http://${FT_HOST:-127.0.0.1}:${FT_PORT:-1919}/health"
echo "note:   user services stop at logout unless: loginctl enable-linger $USER"
echo "retune: scripts/freetoken/install-user-units.sh --retune   (then scripts/freetoken/limits.sh)"
