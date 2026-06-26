#!/usr/bin/env bash
# Quick archive of the Harvis repo (excludes heavy/generated dirs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$(dirname "$ROOT")/Harvis-$(date +%Y%m%d).zip}"

cd "$ROOT"
zip -r "$OUT" . \
  -x '*/node_modules/*' \
  -x '*/.git/*' \
  -x '*__pycache__/*' \
  -x '*/.venv/*' \
  -x '*/dist/*' \
  -x '*/.next/*' \
  -x '*/graphify-out/*' \
  -x '*/ml-models-cache/*'

ls -lh "$OUT"
echo "Created: $OUT"
