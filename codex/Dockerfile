# Harvis Codex engine sidecar (Phase E2) — runs OpenAI's Codex CLI against a Build
# session clone using the requesting user's OpenAI API key, injected per-exec at run
# time (NEVER baked in). Cloud-only: talks to api.openai.com over the bridge network.
# Shares /data/artifacts so it edits the session clone in place; the backend invokes
# `codex exec` here via `docker exec`. uid 1001 = artifact_data owner.
FROM node:20-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates procps \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @openai/codex@latest

RUN useradd -u 1001 -m -s /bin/bash codex
USER 1001
ENV HOME=/home/codex

COPY --chown=1001:1001 entrypoint.sh /home/codex/entrypoint.sh

WORKDIR /data/artifacts
ENTRYPOINT ["/bin/bash", "/home/codex/entrypoint.sh"]
