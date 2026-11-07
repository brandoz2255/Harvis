# The way out to the internet for every chat's box (python_back_end/workspace/
# terminal_container.py, HARVIS_BUILD_RUNNER_EGRESS). Boxes run with no network;
# each mounts one of this container's unix sockets read-only and sends HTTP(S)
# through it. Squid refuses private, LAN, tailnet, loopback and link-local
# destinations, so a box can reach the public web and nothing else.
#   /run/egress-web/proxy.sock  web: any public HTTP(S) site
#   /run/egress-pkg/proxy.sock  packages: only the registries in packages.txt
# Both refuse bare IP addresses and the tunnel, file-drop and callback sites in
# blocked.txt, and cap uploads (entrypoint.sh).
#
# Build:  docker build -t harvis-box-egress:local ./box-egress
FROM debian:bookworm-slim

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends squid socat \
    && rm -rf /var/lib/apt/lists/*

COPY squid.conf /etc/squid/squid.conf
COPY packages.txt /etc/squid/packages.base.txt
COPY blocked.txt /etc/squid/blocked.base.txt
COPY entrypoint.sh /usr/local/bin/box-egress
RUN chmod 0755 /usr/local/bin/box-egress

ENTRYPOINT ["/usr/local/bin/box-egress"]
