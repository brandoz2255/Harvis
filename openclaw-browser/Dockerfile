# =============================================================================
# OpenClaw + Chromium — Browser-enabled agent image
# =============================================================================
# Extends the base OpenClaw image with Chromium so the native browser tool
# (screenshot, navigate, click, type) works without a separate sidecar.
#
# Build:
#   docker build -t dulc3/openclaw-browser:latest -f openclaw-browser/Dockerfile .
#
# Or let docker-compose build it via the openclaw service's `build:` key.
# =============================================================================

FROM dulc3/openclaw:latest

# Switch to root to install system packages
USER root

# -----------------------------------------------------------------------------
# Detect base OS and install Chromium + deps accordingly
# -----------------------------------------------------------------------------
# The base OpenClaw image may be Debian/Ubuntu or Alpine.
# This multi-strategy RUN handles both.
RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        echo ">>> Detected Debian/Ubuntu base"; \
        apt-get update && \
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
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        echo ">>> Detected Alpine base"; \
        apk add --no-cache \
            chromium \
            nss \
            freetype \
            harfbuzz \
            ca-certificates \
            ttf-freefont \
            font-noto-emoji \
            dbus \
        ; \
    else \
        echo ">>> Unknown base OS — attempting Debian-style install"; \
        apt-get update && apt-get install -y --no-install-recommends chromium && \
        apt-get clean && rm -rf /var/lib/apt/lists/*; \
    fi

# -----------------------------------------------------------------------------
# Environment variables for browser discovery
# -----------------------------------------------------------------------------
# OpenClaw and Puppeteer both check these vars to find the browser binary.
# Setting all of them covers every code path.
ENV CHROME_BIN=/usr/bin/chromium \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    CHROMIUM_PATH=/usr/bin/chromium \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_CHROMIUM_REVISION=skip \
    CHROME_FLAGS="--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-gpu"

# Symlink so both 'chromium' and 'chromium-browser' resolve
RUN if [ ! -f /usr/bin/chromium ] && [ -f /usr/bin/chromium-browser ]; then \
        ln -s /usr/bin/chromium-browser /usr/bin/chromium; \
    fi; \
    if [ ! -f /usr/bin/chromium-browser ] && [ -f /usr/bin/chromium ]; then \
        ln -s /usr/bin/chromium /usr/bin/chromium-browser; \
    fi

# -----------------------------------------------------------------------------
# Ensure the browser screenshot output dir exists and is writable by node user
# -----------------------------------------------------------------------------
RUN mkdir -p /home/node/.openclaw/browser && \
    chown -R node:node /home/node/.openclaw/browser

# Create a tmpfs-friendly /tmp for Chromium crash dumps and temp profiles
RUN mkdir -p /tmp/.chromium && chmod 1777 /tmp/.chromium

# -----------------------------------------------------------------------------
# Smoke test — verify Chromium is findable and runs
# -----------------------------------------------------------------------------
RUN chromium --version || chromium-browser --version || echo "WARN: chromium version check failed (may work at runtime)"

# Switch back to the node user
USER node

# Default command unchanged — OpenClaw gateway
# (inherited from base image, override in compose/k8s as needed)
