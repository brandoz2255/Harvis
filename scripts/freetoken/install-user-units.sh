#!/usr/bin/env bash
# Install FreeToken as a systemd --user service on this machine. Idempotent.
#
#   scripts/freetoken/install-user-units.sh            install + start freetoken.service
#   scripts/freetoken/install-user-units.sh --idle     also enable the idle-stop timer
#
# Expects ~/.config/freetoken.env to exist (see freetoken.env.example); it is created
# from the example on first run and the script stops so you can edit FT_HOME/FT_MODEL.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin"
units="$HOME/.config/systemd/user"
envf="$HOME/.config/freetoken.env"

mkdir -p "$bin" "$units" "$HOME/.config"
if [ ! -f "$envf" ]; then
  cp "$here/freetoken.env.example" "$envf"
  echo "created $envf from the example — set FT_HOME and FT_MODEL, then re-run."
  exit 2
fi

install -m 0755 "$here/serve.sh" "$bin/freetoken-serve"
install -m 0755 "$here/idle-stop.sh" "$bin/freetoken-idle-stop"
install -m 0644 "$here/freetoken.service" "$units/freetoken.service"
install -m 0644 "$here/freetoken-idle.service" "$units/freetoken-idle.service"
install -m 0644 "$here/freetoken-idle.timer" "$units/freetoken-idle.timer"

systemctl --user daemon-reload
systemctl --user enable --now freetoken.service
if [ "${1:-}" = "--idle" ]; then
  systemctl --user enable --now freetoken-idle.timer
else
  systemctl --user disable --now freetoken-idle.timer 2>/dev/null || true
fi

# shellcheck disable=SC1090
set -a; . "$envf"; set +a
echo "freetoken.service: $(systemctl --user is-active freetoken.service)"
echo "logs:   journalctl --user -u freetoken -f"
echo "health: curl http://${FT_HOST:-127.0.0.1}:${FT_PORT:-1919}/health"
echo "note:   user services stop at logout unless: loginctl enable-linger $USER"
