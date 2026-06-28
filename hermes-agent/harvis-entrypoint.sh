#!/usr/bin/env bash
# Harvis Hermes Agent sidecar entrypoint (E4B.1).
#
# 1) Inject a local-Ollama provider config into the GATEWAY home (for the Chat /v1 API
#    server) if none exists — provider=custom → http://ollama:11434/v1, no cloud key.
# 2) Hand off to the official s6 init running the Hermes gateway (which serves the
#    OpenAI-compatible API server on :8642 when API_SERVER_ENABLED=true).
#
# Build runs do NOT go through here — the backend drives them per-clone via:
#   docker exec -u 1001 -w <clone> \
#     -e HERMES_HOME=<per-user-home> -e HERMES_WRITE_SAFE_ROOT=<clone> \
#     -e TERMINAL_CWD=<clone> -e TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE=true \
#     harvis-hermes-agent hermes -z "<task>" --yolo
# (HERMES_WRITE_SAFE_ROOT=<clone> confines Hermes's write_file to the clone — defense in
#  depth on top of the throwaway clone; verified in E4B.0.)
set -u

# The per-user Build profiles live on a named volume whose root is root-owned; the uid-1001
# Build exec (docker exec -u 1001 … hermes -z) must be able to create <homes>/<uid>. Chown
# it here while we're still root (before s6 drops privileges).
HOMES_DIR="${HARVIS_HERMES_HOMES_DIR:-/data/hermes-homes}"
mkdir -p "${HOMES_DIR}" 2>/dev/null || true
chown 1001:1001 "${HOMES_DIR}" 2>/dev/null || true

# Gateway (Chat) home — the shared API-server profile. Per-user Build homes are separate
# and created by the backend under the mounted hermes-homes volume.
GW_HOME="${HERMES_HOME:-/opt/data}"
CONF="${GW_HOME}/config.yaml"
if [ ! -f "${CONF}" ]; then
  mkdir -p "${GW_HOME}" 2>/dev/null || true
  cat > "${CONF}" <<YAML
model:
  provider: custom
  base_url: ${HARVIS_HERMES_OLLAMA_URL:-http://ollama:11434/v1}
  default: ${HARVIS_HERMES_AGENT_DEFAULT_MODEL:-qwen3:4b}
YAML
  echo "harvis-hermes-agent: wrote default local-Ollama config to ${CONF}"
fi

echo "harvis-hermes-agent: starting official gateway (Chat API on :8642 when API_SERVER_ENABLED); Build via docker exec -u 1001."
# Hand off to the official image's s6 init + main-wrapper with the requested command.
exec /init /opt/hermes/docker/main-wrapper.sh "$@"
