# =============================================================================
# OpenClaw + Chromium — Browser-enabled agent image
# =============================================================================
# Installs OpenClaw v2026.5.22 (current npm latest, has `defineToolPlugin` SDK)
# directly via npm rather than depending on dulc3/openclaw:latest, which is
# frozen at 2026-04-26 by an external maintainer. This gives us full control
# over the OpenClaw version and unblocks Path B7 (custom MCP tool plugins).
#
# Build:
#   docker build -t dulc3/openclaw-browser:latest -f openclaw-browser/Dockerfile .
#
# Or let docker-compose build it via the openclaw service's `build:` key.
# =============================================================================

FROM node:22-bookworm-slim

# -----------------------------------------------------------------------------
# System packages: Chromium for the native browser tool + a few build/runtime
# essentials for npm-installed Node packages.
# -----------------------------------------------------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium \
        chromium-sandbox \
        fonts-liberation \
        fonts-noto-color-emoji \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdrm2 \
        libgbm1 \
        libnss3 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        xdg-utils \
        dbus \
        ca-certificates \
        curl \
        git \
        ripgrep \
        jq \
        python3 \
        python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# Install OpenClaw globally via npm. Pinned to a specific version for
# reproducible builds; bump deliberately when upgrading.
# -----------------------------------------------------------------------------
RUN npm install -g openclaw@2026.5.22 && \
    npm cache clean --force

# -----------------------------------------------------------------------------
# Environment variables for browser discovery (Chromium / Puppeteer).
# -----------------------------------------------------------------------------
ENV CHROME_BIN=/usr/bin/chromium \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    CHROMIUM_PATH=/usr/bin/chromium \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_CHROMIUM_REVISION=skip \
    CHROME_FLAGS="--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-gpu"

# Symlink so both 'chromium' and 'chromium-browser' resolve (puppeteer probes
# both names depending on its config).
RUN if [ ! -f /usr/bin/chromium ] && [ -f /usr/bin/chromium-browser ]; then \
        ln -s /usr/bin/chromium-browser /usr/bin/chromium; \
    fi; \
    if [ ! -f /usr/bin/chromium-browser ] && [ -f /usr/bin/chromium ]; then \
        ln -s /usr/bin/chromium /usr/bin/chromium-browser; \
    fi

# -----------------------------------------------------------------------------
# Filesystem setup for the `node` user (UID 1000, pre-created by the Node
# base image).
# -----------------------------------------------------------------------------
RUN mkdir -p /home/node/.openclaw/browser \
             /home/node/.openclaw/workspace \
             /home/node/projects && \
    chown -R node:node /home/node/.openclaw /home/node/projects

# tmpfs-friendly /tmp area for Chromium crash dumps and temp profiles
RUN mkdir -p /tmp/.chromium && chmod 1777 /tmp/.chromium

# -----------------------------------------------------------------------------
# Smoke test — verify chromium + openclaw both resolve.
# -----------------------------------------------------------------------------
RUN chromium --version || chromium-browser --version || echo "WARN: chromium version check failed (may work at runtime)"
RUN openclaw --version || node /usr/local/lib/node_modules/openclaw/openclaw.mjs --version

# Switch to the node user for runtime.
USER node
WORKDIR /home/node

# Default command — gateway mode. docker-compose overrides this with the
# explicit `command:` field for clarity, but having it here documents the
# intended entrypoint and makes `docker run` standalone usable.
EXPOSE 18789
CMD ["openclaw", "gateway", "--bind", "lan", "--port", "18789", "--allow-unconfigured"]
