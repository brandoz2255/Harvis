#!/usr/bin/env bash
# Stop the freetoken user service after FT_IDLE_MIN minutes with no completed
# request. Run from freetoken-idle.timer. Opt-in: the model takes ~40 s to load
# again, and nothing restarts it on demand yet (see docs/inference-nodes.md,
# "lazy start"), so a stopped node shows as unreachable in Harvis until
# `systemctl --user start freetoken`.
#
# Idle is judged from FreeToken's own counters (/v1/stats → requests.completed and
# requests.active), not from GPU load, so a long-running request never counts as idle.
set -uo pipefail

FT_HOST="${FT_HOST:-127.0.0.1}"
FT_PORT="${FT_PORT:-1919}"
FT_IDLE_MIN="${FT_IDLE_MIN:-30}"
STATE="${XDG_RUNTIME_DIR:-/tmp}/freetoken-idle.state"

systemctl --user is-active --quiet freetoken.service || exit 0

stats="$(curl -fsS --max-time 5 "http://$FT_HOST:$FT_PORT/v1/stats" 2>/dev/null)" || exit 0
read -r active completed < <(python3 - "$stats" <<'PY'
import json, sys
s = json.loads(sys.argv[1]).get("requests") or {}
print(int(s.get("active") or 0), int(s.get("completed") or 0))
PY
)
now="$(date +%s)"
if [ "$active" -gt 0 ]; then
  echo "$completed $now" > "$STATE"; exit 0
fi
if [ -f "$STATE" ]; then
  read -r last_completed last_ts < "$STATE"
else
  last_completed=-1; last_ts="$now"
fi
if [ "$completed" != "$last_completed" ]; then
  echo "$completed $now" > "$STATE"; exit 0
fi
idle_s=$(( now - last_ts ))
if [ "$idle_s" -ge $(( FT_IDLE_MIN * 60 )) ]; then
  echo "freetoken idle for ${idle_s}s (completed=$completed) — stopping"
  systemctl --user stop freetoken.service
  rm -f "$STATE"
fi
