#!/bin/sh
set -e

case "${1:-app}" in
  download-models)
    # Optional warm-up: fetch (and load) the configured bundles so the first
    # real request doesn't pay for the download. Safe to run repeatedly.
    exec python -c "
from app import engines
engines.get_vad()
engines.get_recognizer()
engines.get_synthesizer()
print('voice-onnx: models ready')
"
    ;;
  app)
    exec uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${VOICE_PORT:-8000}" \
      --workers "${VOICE_WORKERS:-1}" \
      --log-level "$(echo "${VOICE_LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
    ;;
  *)
    exec "$@"
    ;;
esac
