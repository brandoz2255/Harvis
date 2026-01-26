#!/bin/bash

set -e

# Entrypoint script for harvis-backend
# Can run in two modes:
#   1. download-models: Downloads ML models to cache (for init container)
#   2. app: Runs the main application (default)

MODE="${1:-app}"

case "$MODE" in
download-models)
  echo "🚀 Running in DOWNLOAD MODE - downloading models...."
  python3 /app/download_models.py
  ;;

app)
  echo "🚀 Running in APP MODE - starting uvicorn server..."
  shift
  exec uvicorn main:app --host 0.0.0.0 --port 8000 "$@"
  ;;

*)
  echo "❌ Unknown mode: $MODE"
  echo "Usage: $0 {download-models|app}"
  exit 1
  ;;
esac
