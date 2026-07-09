# Polyglot sandbox image for the Adaptive Workspace Repo Runner.
#
# The Repo Runner spawns ONE of these per space to clone + install + run an
# untrusted repo's dev server, then previews it (host-port-per-preview). It must
# carry the runtimes Harvis knows how to run so it can ADAPT to a repo's stack:
#   - Node 20 + npm + corepack (pnpm/yarn) + git   (from the base image)
#   - Python 3.11 + pip + venv
#   - uv (Astral) — the modern Python package manager many repos now use
#
# It is deliberately a plain user image: no docker socket, no privileged flags,
# no host mounts. It only ever runs on the isolated `repo-sandbox` network.
#
# Build:  docker build -t harvis-repo-sandbox:local ./repo-sandbox-engine
FROM node:20-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# uv + uvx from the official Astral image (pinned by tag, no curl|sh needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Let repos that call bare `python` / `pip` work (Debian only ships python3/pip3).
RUN ln -sf /usr/bin/python3 /usr/local/bin/python \
    && ln -sf /usr/bin/pip3 /usr/local/bin/pip

# Keep-alive PID 1; the backend runs clone/install/start via `docker exec`.
CMD ["sh", "-c", "tail -f /dev/null"]
