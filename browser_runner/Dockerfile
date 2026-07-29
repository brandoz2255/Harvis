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

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Non-root. This image had no USER at all, so it ran as root — and of every
# service in the default set this is the one that renders hostile input by
# design. Nothing here wants root: uvicorn binds 8765 (unprivileged) and
# Firefox actively prefers not to be root.
#
# The -m matters. app.py:70 calls GeckoDriverManager().install(), which writes
# the driver under ~/.wdm at first use; without a real home that fails at the
# first browse rather than at boot.
RUN useradd -m -u 1001 -s /bin/bash runner \
  && chown -R runner:runner /app
USER runner
ENV HOME=/home/runner

EXPOSE 8765

# OCI metadata, last so the per-commit VCS_REF does not invalidate the apt
# and pip layers above it.
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/brandoz2255/Harvis" \
  org.opencontainers.image.licenses="MIT" \
  org.opencontainers.image.revision="${VCS_REF}" \
  org.opencontainers.image.title="harvis-browser-runner" \
  org.opencontainers.image.description="Headless Firefox session service for browser automation and artifact rendering"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765"]

