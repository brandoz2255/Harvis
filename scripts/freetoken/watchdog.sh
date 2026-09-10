#!/usr/bin/env bash
# Restart FreeToken when it is up but not actually serving.
#
# The failure this exists for: FreeToken's scheduler subprocess dies (a CUDA OOM
# during prefill is the way we have seen it), the API process keeps the port open
# and systemd keeps the unit `active`, so nothing notices. Harvis then routes chats
# to a node that answers nothing. `Restart=on-failure` never fires because the main
# process never exits.
#
# Three checks, cheapest first. Two consecutive failures restart the unit; one
# failure is a blip (a slow prefill, a hiccup) and only arms the next check.
#
#   1. /health answers 200 and says maintenance=serving.
#      A warming node (status=loading) is healthy — it resets the strike count.
#   2. The scheduler worker is still in the unit's cgroup. This is the signal that
#      catches the OOM case within one tick, before anyone sends a request.
#   3. A real one-token completion, at most every FT_WATCHDOG_PROBE_MIN minutes and
#      only while the node is idle. This is the check that cannot be fooled: a
#      dead scheduler accepts the request and never answers, so it times out.
#
# Restarts are budgeted (FT_WATCHDOG_MAX_RESTARTS per hour). Past the budget the
# watchdog stops restarting and keeps logging, because a node that dies four times
# an hour has a configuration problem that another restart will not fix.
set -uo pipefail

FT_HOST="${FT_HOST:-127.0.0.1}"
FT_PORT="${FT_PORT:-1919}"
PROBE_MIN="${FT_WATCHDOG_PROBE_MIN:-10}"
MAX_RESTARTS="${FT_WATCHDOG_MAX_RESTARTS:-3}"
PROBE_TIMEOUT="${FT_WATCHDOG_PROBE_TIMEOUT:-45}"
STATE_DIR="${XDG_RUNTIME_DIR:-/tmp}"
STRIKES="$STATE_DIR/freetoken-watchdog.strikes"
LAST_PROBE="$STATE_DIR/freetoken-watchdog.lastprobe"
RESTARTS="$STATE_DIR/freetoken-watchdog.restarts"
BASE="http://$FT_HOST:$FT_PORT"

log() { echo "freetoken-watchdog: $*"; }

# A unit that is not running is not the watchdog's business: the idle timer may have
# stopped it on purpose, and starting it again would defeat that.
systemctl --user is-active --quiet freetoken.service || exit 0

strike() {
  local why="$1" n
  n=$(( $(cat "$STRIKES" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$STRIKES"
  if [ "$n" -lt 2 ]; then
    log "unhealthy ($why) — strike $n, rechecking next tick"
    exit 0
  fi

  # Rolling-hour restart budget.
  local now cutoff kept=""
  now="$(date +%s)"; cutoff=$(( now - 3600 ))
  if [ -f "$RESTARTS" ]; then
    while read -r t; do [ -n "$t" ] && [ "$t" -gt "$cutoff" ] 2>/dev/null && kept="$kept$t"$'\n'; done < "$RESTARTS"
  fi
  local count; count="$(printf '%s' "$kept" | grep -c . || true)"
  if [ "${count:-0}" -ge "$MAX_RESTARTS" ]; then
    log "unhealthy ($why) but already restarted $count times this hour — NOT restarting."
    log "look at: journalctl --user -u freetoken -n 200   (OOM during prefill? lower FT_MEMORY_RATIO or FT_MAX_PREFILL)"
    exit 1
  fi
  printf '%s%s\n' "$kept" "$now" > "$RESTARTS"
  rm -f "$STRIKES" "$LAST_PROBE"
  log "unhealthy ($why) on two consecutive checks — restarting freetoken.service"
  systemctl --user restart freetoken.service
  exit 0
}

health="$(curl -fsS --max-time 5 "$BASE/health" 2>/dev/null)" || strike "no answer from /health"
[ -n "$health" ] || strike "/health returned an empty body"

state="$(printf '%s' "$health" | python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: print("unparseable"); raise SystemExit
print(d.get("maintenance") or d.get("status") or "unknown")' 2>/dev/null)"
case "$state" in
  serving) ;;
  loading|warmup|starting) rm -f "$STRIKES"; log "still loading ($state) — nothing to do"; exit 0 ;;
  *) strike "/health says '$state'" ;;
esac

# The scheduler runs as a multiprocessing spawn child of the API process. If it is
# gone the port still answers and /health still says serving — this is the tell.
workers="$(pgrep -c -P "$(systemctl --user show freetoken -p MainPID --value)" -f 'multiprocessing.spawn' 2>/dev/null || echo 0)"
[ "${workers:-0}" -ge 1 ] || strike "no scheduler worker under the main process"

active="$(curl -fsS --max-time 5 "$BASE/v1/stats" 2>/dev/null | python3 -c 'import json,sys
try: print(int((json.load(sys.stdin).get("requests") or {}).get("active") or 0))
except Exception: print(0)' 2>/dev/null || echo 0)"
if [ "${active:-0}" -gt 0 ]; then rm -f "$STRIKES"; exit 0; fi

now="$(date +%s)"
last="$(cat "$LAST_PROBE" 2>/dev/null || echo 0)"
if [ $(( now - last )) -lt $(( PROBE_MIN * 60 )) ]; then rm -f "$STRIKES"; exit 0; fi

model="$(printf '%s' "$health" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("model") or "")
except Exception: print("")' 2>/dev/null)"
[ -n "$model" ] || { rm -f "$STRIKES"; exit 0; }

# One token, thinking off: the smallest request that still needs a live scheduler.
body="$(python3 -c 'import json,sys; print(json.dumps({
  "model": sys.argv[1], "max_tokens": 1, "stream": False,
  "messages": [{"role": "user", "content": "ok"}],
  "chat_template_kwargs": {"enable_thinking": False}}))' "$model")"
echo "$now" > "$LAST_PROBE"
if curl -fsS --max-time "$PROBE_TIMEOUT" -H 'Content-Type: application/json' \
     -d "$body" "$BASE/v1/chat/completions" >/dev/null 2>&1; then
  rm -f "$STRIKES"
  exit 0
fi
strike "one-token probe did not complete in ${PROBE_TIMEOUT}s"
