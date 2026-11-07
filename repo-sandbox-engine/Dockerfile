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
# no host mounts. As a Repo Runner it runs on the `repo-sandbox` network; as a chat
# box it runs with no network at all and reaches the internet only through the
# box-egress proxy socket (socat below, HARVIS_BUILD_RUNNER_EGRESS).
#
# The same image is each Hermes chat's own computer (terminal_container's isolated
# runner), so it also carries the tools a cyber challenge reaches for (packet captures,
# hashes, file carving, metadata) and passwordless sudo for user `agent` (uid 1001):
# the agent installs whatever else it needs with `sudo apt-get install`. sudo only
# works where the runner grants the setuid capabilities (HARVIS_BUILD_RUNNER_SUDO);
# the repo runner keeps no-new-privileges, so there it is inert.
#
# Build:  docker build -t harvis-repo-sandbox:local ./repo-sandbox-engine
FROM node:20-bookworm

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip ca-certificates curl \
        sudo file xxd binutils bsdextrautils jq unzip p7zip-full \
        libimage-exiftool-perl binwalk foremost tshark tcpdump john nmap dnsutils \
        python3-scapy python3-pycryptodome socat \
    && rm -rf /var/lib/apt/lists/*

# uid 1001 matches the workspace owner; sudo needs it to have a passwd entry.
RUN useradd -m -u 1001 -s /bin/bash agent \
    && echo 'agent ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agent \
    && echo 'Defaults env_keep += "http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY"' >> /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent

# uv + uvx from the official Astral image (pinned by tag, no curl|sh needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Let repos that call bare `python` / `pip` work (Debian only ships python3/pip3).
RUN ln -sf /usr/bin/python3 /usr/local/bin/python \
    && ln -sf /usr/bin/pip3 /usr/local/bin/pip

# Keep-alive PID 1; the backend runs clone/install/start via `docker exec`.
CMD ["sh", "-c", "tail -f /dev/null"]
