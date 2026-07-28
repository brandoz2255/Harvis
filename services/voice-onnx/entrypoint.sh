#!/bin/sh
set -e

case "${1:-app}" in
  download-models)
    # Optional warm-up: fetch (and load) the configured bundles so the first
    # real request doesn't pay for the download. Safe to run repeatedly.
    exec python -c "
from app import browser_assets, engines
engines.get_vad()
engines.get_recognizer()
engines.get_synthesizer()
# Same trip fetches the browser-side Kokoro mirror, so an install that finishes
# here leaves both playback paths working with the network off.
m = browser_assets.sync()
print('voice-onnx: models ready; browser mirror', 'complete' if m['complete'] else m['sync']['status'])
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
