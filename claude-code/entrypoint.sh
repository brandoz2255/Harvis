#!/usr/bin/env bash
# Harvis Claude Code sidecar entrypoint: idle so the backend can `docker exec` per-turn
# `claude -p` invocations. The user's Anthropic API key is injected per-exec at run time
# (docker exec -e ANTHROPIC_API_KEY=…) — never stored here. Cloud-only.
set -u
echo "harvis-claude-code sidecar ready (idle; invoked via docker exec)."
exec tail -f /dev/null
