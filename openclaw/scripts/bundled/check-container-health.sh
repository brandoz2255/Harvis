#!/usr/bin/env bash
# Bundled container health check — disk usage and session count.
# Silent success if everything is fine.
set -euo pipefail

DISK_USAGE=$(df -h /home/node/.openclaw 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')
SESSION_COUNT=$(find /home/node/workspaces/bundled -maxdepth 2 -mindepth 2 -type d 2>/dev/null | wc -l)
STALE_COUNT=$(find /home/node/workspaces/bundled -maxdepth 3 -type d -mtime +7 2>/dev/null | wc -l)

OUTPUT=""

if [ "${DISK_USAGE:-0}" -gt 80 ] 2>/dev/null; then
  OUTPUT="${OUTPUT}DISK_USAGE: ${DISK_USAGE}%\n"
fi

if [ "${SESSION_COUNT:-0}" -gt 0 ] 2>/dev/null; then
  OUTPUT="${OUTPUT}ACTIVE_SESSIONS: ${SESSION_COUNT}\n"
fi

if [ "${STALE_COUNT:-0}" -gt 10 ] 2>/dev/null; then
  OUTPUT="${OUTPUT}STALE_SESSIONS: ${STALE_COUNT}\n"
fi

[ -z "$OUTPUT" ] && exit 0

printf "%b" "$OUTPUT"
