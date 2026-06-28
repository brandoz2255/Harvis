# Harvis Claude Code engine sidecar (Phase E2) — runs Anthropic's Claude Code CLI
# against a Build session clone using the requesting user's Anthropic API key,
# injected per-exec at run time (docker exec -e ANTHROPIC_API_KEY=…; NEVER baked in).
# Cloud-only: talks to api.anthropic.com over the bridge network. Shares
# /data/artifacts so it edits the session clone in place; the backend invokes
# `claude -p` here via `docker exec`. uid 1001 = artifact_data owner.
FROM node:20-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates procps \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code@latest

RUN useradd -u 1001 -m -s /bin/bash claude
USER 1001
ENV HOME=/home/claude
# Claude Code bare mode reads auth STRICTLY from ANTHROPIC_API_KEY (no OAuth/keychain).
ENV CLAUDE_CODE_SIMPLE=1

COPY --chown=1001:1001 entrypoint.sh /home/claude/entrypoint.sh

WORKDIR /data/artifacts
ENTRYPOINT ["/bin/bash", "/home/claude/entrypoint.sh"]
