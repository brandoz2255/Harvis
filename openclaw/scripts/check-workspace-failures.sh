#!/usr/bin/env bash
# Query backend for failed workspace runs in last N hours.
# Silent success if no failures.
set -euo pipefail

HOURS="${1:-1}"
BACKEND="${BACKEND_URL:-http://backend:8000}"

RESPONSE=$(curl -s -m 10 \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  "$BACKEND/api/workspace/recent-failures?hours=$HOURS" 2>/dev/null || echo '{}')

COUNT=$(echo "$RESPONSE" | jq -r '.count // 0' 2>/dev/null || echo 0)

[ "$COUNT" = "0" ] || [ -z "$COUNT" ] && exit 0

echo "FAILURE_COUNT: $COUNT"
echo ""
echo "FAILURES:"
echo "$RESPONSE" | jq -r '.failures[] | "- \(.workspace_id): \(.error_message // "unknown" | split("\n")[0])"'
