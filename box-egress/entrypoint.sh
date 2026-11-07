#!/bin/sh
# Start the two socket listeners, then squid in the foreground.
# HARVIS_BOX_EGRESS_EXTRA_DOMAINS: comma list added to the packages allowlist
# (a lab mirror, say). A leading dot means the domain and its subdomains.
# HARVIS_BOX_EGRESS_BLOCK_DOMAINS: comma list added to blocked.txt.
# HARVIS_BOX_EGRESS_BLOCKLIST=off: empty blocked.txt.
# HARVIS_BOX_EGRESS_MAX_UPLOAD_MB (10): largest plain-HTTP request body.
# HARVIS_BOX_EGRESS_MAX_CONNS (64): open connections per socket, all boxes.
set -eu

# A whole number from the environment, or the default when unset or malformed.
num() {
    case "${1:-}" in
        ''|*[!0-9]*) echo "$2" ;;
        *) echo "$1" ;;
    esac
}

# A comma list from the environment as one domain per line.
domains() {
    echo "${1:-}" | tr ',' '\n' | sed 's/[[:space:]]//g' | grep -v '^$' || true
}

cp /etc/squid/packages.base.txt /etc/squid/packages.txt
domains "${HARVIS_BOX_EGRESS_EXTRA_DOMAINS:-}" >> /etc/squid/packages.txt

if [ "${HARVIS_BOX_EGRESS_BLOCKLIST:-on}" = off ]; then
    : > /etc/squid/blocked.txt
else
    { grep -v '^#' /etc/squid/blocked.base.txt; domains "${HARVIS_BOX_EGRESS_BLOCK_DOMAINS:-}"; } \
        | grep -v '^$' | sort -u > /etc/squid/blocked.txt
fi

upload_mb=$(num "${HARVIS_BOX_EGRESS_MAX_UPLOAD_MB:-}" 10)
max_conns=$(num "${HARVIS_BOX_EGRESS_MAX_CONNS:-}" 64)
echo "request_body_max_size $upload_mb MB" > /etc/squid/limits.conf

for kind in web:3128 pkg:3129; do
    dir="/run/egress-${kind%%:*}"
    mkdir -p "$dir"
    chmod 0755 "$dir"
    socat "UNIX-LISTEN:$dir/proxy.sock,fork,max-children=$max_conns,backlog=128,mode=666,unlink-early" "TCP:127.0.0.1:${kind##*:}" &
done

mkdir -p /run/squid-log
for log in access cache; do
    [ -p /run/squid-log/$log.fifo ] || mkfifo -m 0600 /run/squid-log/$log.fifo
    chown proxy:proxy /run/squid-log/$log.fifo
done
while :; do cat /run/squid-log/access.fifo; done &
while :; do cat /run/squid-log/cache.fifo >&2; done &

exec squid -N -f /etc/squid/squid.conf
