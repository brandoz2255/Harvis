# Harvis OpenCode engine sidecar — an external code-engine the VibeCode/Build
# runtime can drive (Phase E1). It shares the backend's /data/artifacts volume so
# it edits the session clone in place; the backend invokes `opencode run` here via
# `docker exec`. Runs as uid 1001 to match the artifact_data volume ownership.
FROM node:20-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates procps \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g opencode-ai@latest

# uid 1001 = appuser on the backend, which owns /data/artifacts (chowned by harvis-artifact-init).
RUN useradd -u 1001 -m -s /bin/bash opencode
USER 1001
ENV HOME=/home/opencode

# Ollama provider config (no cloud credentials). Lives at the per-user config path
# OpenCode reads by default. An entrypoint regenerates the model list from Ollama at
# startup so newly-pulled models are usable without an image rebuild.
COPY --chown=1001:1001 opencode.json /home/opencode/.config/opencode/opencode.json
COPY --chown=1001:1001 entrypoint.sh /home/opencode/entrypoint.sh

WORKDIR /data/artifacts
ENTRYPOINT ["/bin/bash", "/home/opencode/entrypoint.sh"]
