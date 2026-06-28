#!/usr/bin/env bash
# Harvis Codex sidecar entrypoint: idle so the backend can `docker exec` per-turn
# `codex exec` invocations. The user's OpenAI API key is injected per-exec at run
# time (docker exec -e OPENAI_API_KEY=…) — never stored here. Cloud-only.
set -u
mkdir -p "${HOME}/.codex" 2>/dev/null || true
echo "harvis-codex sidecar ready (idle; invoked via docker exec)."
exec tail -f /dev/null
