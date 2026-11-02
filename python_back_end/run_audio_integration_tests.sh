#!/bin/bash
# Owner-bound audio integration tests — offline, disposable, no live services.
#
# Runs the audio security suite inside a throwaway container started with
# --network none (the TTS model is mocked, the database URL points at a closed
# loopback port, and the HTTP tests serve real sockets on 127.0.0.1, which
# works without a network). The repo is mounted READ-ONLY and the container is
# removed on exit; nothing persists and nothing touches a live deployment.
#
# Usage:
#   ./run_audio_integration_tests.sh [extra pytest args...]
#   HARVIS_TEST_IMAGE=harvis-backend:latest ./run_audio_integration_tests.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${HARVIS_TEST_IMAGE:-harvis-backend:latest}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "✗ Test image '$IMAGE' not found. Build the backend image first" >&2
    echo "  (docker compose build backend) or set HARVIS_TEST_IMAGE." >&2
    exit 1
fi

echo "Running audio integration tests offline (network: none, image: $IMAGE)…"

exec docker run --rm --network none \
    --entrypoint python \
    -e JWT_SECRET=audio-integration-test-secret \
    -e DATABASE_URL=postgresql://u:p@127.0.0.1:1/db \
    -e DISABLE_LOCAL_TTS_WORKERS=true \
    -e IMAGES_DIR=/tmp/images \
    -e OWUI_FILES_DIR=/tmp/owui_files \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$ROOT:/src:ro" \
    --tmpfs /tmp:rw,nosuid \
    -w /src/python_back_end \
    "$IMAGE" -m pytest -p no:cacheprovider -q \
        tests/test_audio_route_security.py \
        tests/test_audio_job_security.py \
        tests/test_private_audio_flow.py \
        tests/test_private_audio_store.py \
        tests/test_notebook_podcast_audio.py \
        tests/test_notebook_podcast_ownership.py \
        tests/test_nginx_audio_security.py \
        tests/test_audio_http_integration.py \
        "$@"
