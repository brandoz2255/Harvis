FROM python:3.11-slim

# firefox-esr, and it stays. This image is 864 MB and the two standard trims
# were both measured on Debian trixie before being rejected:
#
#   Swap to chromium. The usual assumption is that it is the smaller of the
#   two. It is not, here: chromium resolves to 724.5 MB against firefox-esr's
#   405.3 MB — 319 MB WORSE — and chromium-driver adds another 23 MB on top.
#
#   Profile-gate the service out of the default set. Saves the whole 864 MB
#   and breaks two shipped features on a fresh install: the browser tool
#   surface in tools/openclaw_proxy.py (session/navigate/act/screenshot) and
#   the Discord artifact preview renderer at
#   integrations/discord_workspace_bot.py:1275, which drives this service to
#   turn HTML/SVG artifacts into PNGs.
#
# The default set measures 6.53 GB on disk against a 7 GB target, so there is
# no size pressure that justifies paying either price.
RUN apt-get update && apt-get install -y --no-install-recommends \
  firefox-esr \
  ca-certificates \
  curl \
  && rm -rf /var/lib/apt/lists/*

# A watchable screen for Agent Teammates: Xvfb gives a headed session its own
# display, x11vnc serves that display, and websockify + noVNC put it behind the
# one HTTP port nginx already proxies. Dropping these packages leaves the service
# working headless — display.py degrades on its own — so this is a real choice,
# not a hard requirement.
#
# xvfb pulls the X server; x11vnc pulls libvnc. Neither needs root at runtime.
#
# THE BIG ONE: xvfb depends on libgl1, which drags in Mesa's llvmpipe software
# renderer and the 124 MB LLVM it is built on — about 173 MB, most of this
# image's growth. Deleting those files in this layer does shrink the image and
# a headed Firefox still renders ordinary pages. Measured, on 2026-09-04:
#
#   without them: webgl2 = false, webgl = false, 2D canvas = true
#   with them:    webgl2 = true, renderer "llvmpipe", and it actually draws
#
# We keep them. A teammate browses the real web, where WebGL is not decoration:
# maps and product viewers need it to render at all, and a browser reporting no
# WebGL whatsoever is a loud bot signal to the sites we most want to shop on.
# 173 MB is the honest price of the agent's browser behaving like a browser.
# Revisit only with a measurement, not a hunch.
RUN apt-get update && apt-get install -y --no-install-recommends \
  xvfb \
  x11vnc \
  && rm -rf /var/lib/apt/lists/* \
  && mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

# noVNC is the browser-side VNC client. Pinned and fetched at build time for the
# same reason geckodriver is: a DNS-blocked cluster must not need egress to show
# a screen. Only the files the client actually loads are kept.
ARG NOVNC_VERSION=1.5.0
RUN set -eux; \
  curl -fsSL -o /tmp/novnc.tgz \
    "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz"; \
  mkdir -p /opt/novnc; \
  tar -xzf /tmp/novnc.tgz -C /opt/novnc --strip-components=1 \
    "noVNC-${NOVNC_VERSION}/vnc.html" \
    "noVNC-${NOVNC_VERSION}/vnc_lite.html" \
    "noVNC-${NOVNC_VERSION}/app" \
    "noVNC-${NOVNC_VERSION}/core" \
    "noVNC-${NOVNC_VERSION}/vendor"; \
  ln -sf /opt/novnc/vnc.html /opt/novnc/index.html; \
  rm -f /tmp/novnc.tgz

# Bake geckodriver into the image so first browse does not egress to GitHub
# (DNS-blocked campus clusters, offline labs). Falls back to webdriver-manager
# only if this download fails at build time.
ARG GECKODRIVER_VERSION=v0.36.0
RUN set -eux; \
  arch="$(dpkg --print-architecture)"; \
  case "$arch" in \
    amd64) gd_arch=linux64 ;; \
    arm64) gd_arch=linux-aarch64 ;; \
    *) gd_arch=linux64 ;; \
  esac; \
  curl -fsSL -o /tmp/gd.tgz \
    "https://github.com/mozilla/geckodriver/releases/download/${GECKODRIVER_VERSION}/geckodriver-${GECKODRIVER_VERSION}-${gd_arch}.tar.gz" \
  && tar -xzf /tmp/gd.tgz -C /usr/local/bin geckodriver \
  && chmod +x /usr/local/bin/geckodriver \
  && rm -f /tmp/gd.tgz

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# websockify puts each watchable session's VNC behind one WebSocket port, with
# a token file so one port covers every session.
#
# --no-deps on purpose. Its declared dependencies are numpy, cryptography,
# jwcrypto and redis — about 104 MB — and none of them are reachable on the
# path this image uses: numpy only accelerates HyBi framing (it warns and falls
# back to pure Python), and the rest belong to auth and token plugins we do not
# load. The package itself is 308 KB. Verified by proxying with the TokenFile
# plugin and serving the noVNC web root with nothing but this installed.
# If a future version needs one of them, it will fail loudly at import, not
# silently — which is why this is a separate line and not a pinned edit to
# requirements.txt.
RUN pip install --no-cache-dir --no-deps websockify

COPY app.py display.py camofox_api.py ./

# Non-root. This image had no USER at all, so it ran as root — and of every
# service in the default set this is the one that renders hostile input by
# design. Nothing here wants root: uvicorn binds 8765 (unprivileged) and
# Firefox actively prefers not to be root.
#
# The -m matters. Without a real home, any residual webdriver-manager fallback
# that writes under ~/.wdm fails at the first browse rather than at boot.
RUN useradd -m -u 1001 -s /bin/bash runner \
  && chown -R runner:runner /app \
  && mkdir -p /profiles \
  && chown runner:runner /profiles
USER runner
ENV HOME=/home/runner
ENV GECKODRIVER_PATH=/usr/local/bin/geckodriver

# 8765 is the API; 6080 is the single websockify port every watchable session
# is multiplexed onto by token. Neither is published to the host — nginx proxies
# both on the app's existing port, which is what keeps Docker Desktop on
# Windows, macOS and Linux identical.
EXPOSE 8765 6080

# OCI metadata, last so the per-commit VCS_REF does not invalidate the apt
# and pip layers above it.
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/brandoz2255/Harvis" \
  org.opencontainers.image.licenses="MIT" \
  org.opencontainers.image.revision="${VCS_REF}" \
  org.opencontainers.image.title="harvis-browser-runner" \
  org.opencontainers.image.description="Firefox session service for browser automation, artifact rendering, and watchable agent sessions"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765"]

