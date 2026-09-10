#!/usr/bin/env bash
# The host half of the FreeToken power switch.
#
# The Harvis backend runs in a container and FreeToken runs as a systemd --user service
# on this machine, so the backend cannot start it: no bus, no PID namespace, no way in.
# Rather than give the container SSH or docker.sock, the two sides pass notes in a
# shared directory:
#
#   desired.json   written by the container   {"state":"on"|"off","requested_at":…}
#   status.json    written by this agent      {"state":"active",…,"last_desired_at":…}
#   .applied       written by this agent      the requested_at it last acted on
#
# Triggered by freetoken-control.path on every write to desired.json, and run once at
# login to publish status. It only ever starts or stops one named unit — the container
# cannot ask this script to run anything else, because there is nothing in the protocol
# that says what to run.
#
#   FT_UNIT                          unit to control (default freetoken.service)
#   HARVIS_FREETOKEN_CONTROL_DIR     shared directory (default /tmp/harvis-freetoken)
#   FT_CONTROL_MAX_AGE_S             ignore a request older than this (default 300)
set -uo pipefail

dir="${HARVIS_FREETOKEN_CONTROL_DIR:-/tmp/harvis-freetoken}"
unit="${FT_UNIT:-freetoken.service}"
max_age="${FT_CONTROL_MAX_AGE_S:-300}"
desired="$dir/desired.json"
status="$dir/status.json"
applied="$dir/.applied"

mkdir -p "$dir" 2>/dev/null || true
# 1777 so the container's uid and this one can both write; the sticky bit still keeps
# each side from deleting the other's file. Only the creator's chmod succeeds.
chmod 1777 "$dir" 2>/dev/null || true

publish() {  # publish <error-message-or-empty>
  local err="${1:-}" state
  state="$(systemctl --user is-active "$unit" 2>/dev/null || true)"
  python3 - "$status" "$state" "$err" "${want_at:-0}" <<'PY'
import json, os, sys, time
path, state, err, want_at = sys.argv[1:5]
tmp = path + ".tmp.%d" % os.getpid()
with open(tmp, "w") as fh:
    json.dump({
        "state": state or "unknown",
        "applied_at": time.time(),
        "last_desired_at": float(want_at or 0),
        "error": err or None,
        "unit": os.environ.get("FT_UNIT", "freetoken.service"),
    }, fh)
os.replace(tmp, path)
os.chmod(path, 0o644)
PY
}

want=""
want_at=0
if [ -f "$desired" ]; then
  read -r want want_at <<<"$(python3 - "$desired" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        d = json.load(fh)
    state = d.get("state")
    print("%s %s" % (state if state in ("on", "off") else "",
                     float(d.get("requested_at") or 0)))
except Exception:
    print(" 0")
PY
)"
fi

# Nothing to act on: still publish, so the backend knows an agent is alive here and can
# draw a real switch instead of "no control agent".
if [ -z "$want" ]; then publish ""; exit 0; fi

last="$(cat "$applied" 2>/dev/null || echo 0)"
age="$(python3 -c "import sys,time;print(int(time.time()-float(sys.argv[1])))" "$want_at" 2>/dev/null || echo 0)"

# Already done. The path unit fires on every write, including ones that repeat an
# intent, and re-running start on a live unit is a no-op that still costs a journal line.
if python3 -c "import sys;sys.exit(0 if float(sys.argv[1])<=float(sys.argv[2]) else 1)" \
   "$want_at" "$last" 2>/dev/null; then publish ""; exit 0; fi

# Stale intent. /tmp is cleared on reboot so this is rare, but a desired=on left behind
# by a crashed session should not silently claim the GPU at next login.
if [ "$age" -gt "$max_age" ]; then
  echo "control-agent: ignoring a ${age}s-old '$want' request" >&2
  echo "$want_at" > "$applied"
  publish "request was ${age}s old and was ignored"
  exit 0
fi

echo "control-agent: $want $unit (requested ${age}s ago)"
err=""
if [ "$want" = "on" ]; then
  systemctl --user start "$unit" || err="systemctl start failed"
else
  systemctl --user stop "$unit" || err="systemctl stop failed"
fi
echo "$want_at" > "$applied"
publish "$err"
[ -z "$err" ]
