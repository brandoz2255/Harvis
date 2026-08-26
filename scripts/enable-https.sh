#!/usr/bin/env bash
#
# Turn on the HTTPS front door.
#
# Why you want this: browsers hand out the microphone, the camera and the
# clipboard only to a "secure context". http://localhost counts as one, which is
# why the mic works on the machine running Docker and fails on every phone,
# laptop and tablet on the same network — those reach Harvis at
# http://<ip>:9000, which does not. Serving the same app over HTTPS fixes it.
#
# Usage:
#   ./scripts/enable-https.sh                 # cert for this machine's LAN address
#   ./scripts/enable-https.sh harvis.local    # plus an extra hostname or IP
#   ./scripts/enable-https.sh 192.168.1.50 harvis.local
#
# The certificate is self-signed, so the first visit shows a browser warning.
# That is expected and it is not a failure: click through once ("Advanced" ->
# "Proceed"), and the connection is encrypted and counts as secure from then on.
# For a warning-free certificate you need a real domain name and a public CA,
# which most home installs do not have.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

# Certificate and listener share one directory on purpose: `certs/` is a blanket
# rule in the repository's .gitignore, so a nginx/certs/ would not survive a
# fresh clone — and Docker creates a missing bind-mount source as root, leaving
# a directory this script could not write into.
TLS_DIR="$ROOT/nginx/tls"
CERT_DIR="$TLS_DIR"
CRT="$CERT_DIR/harvis.crt"
KEY="$CERT_DIR/harvis.key"
TEMPLATE="$TLS_DIR/harvis-tls.conf.template"
ACTIVE="$TLS_DIR/harvis-tls.conf"

HTTPS_PORT="${HARVIS_HTTPS_PORT:-9443}"

say()  { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v openssl >/dev/null 2>&1 || fail "openssl is not installed. Install it and run this again."
[ -f "$TEMPLATE" ] || fail "missing $TEMPLATE — is this the Harvis repository root?"

mkdir -p "$CERT_DIR" "$TLS_DIR"

# ── Work out what names the certificate should cover ────────────────────────
# A certificate is only accepted for the exact name typed into the address bar,
# so every address anyone might use has to be listed up front. Guessing wrong
# here is the single most common reason a self-signed setup still shows an
# error after the user clicks through.
NAMES=(localhost)
IPS=(127.0.0.1)

# Only real network interfaces. `hostname -I` looks tempting but it returns
# every address the machine holds, and on a box running Docker that is a dozen
# bridge gateways (172.17.0.1 and friends) plus link-local IPv6 — none of which
# anyone will ever type into an address bar. Walking interfaces and dropping the
# virtual ones is what keeps the certificate, and the instructions printed at
# the end, down to addresses that are actually reachable.
detected=""
if command -v ip >/dev/null 2>&1; then
    detected="$(ip -o -4 addr show scope global 2>/dev/null | awk '
        $2 ~ /^(docker|br-|veth|virbr|tailscale|tun|wg|lo)/ { next }
        { split($4, a, "/"); print a[1] }
    ')"
elif command -v hostname >/dev/null 2>&1; then
    # No `ip` command: take what hostname gives and filter by address instead.
    detected="$(hostname -I 2>/dev/null || true)"
fi

for ip in $detected; do
    case "$ip" in
        127.*|169.254.*)                  ;;   # loopback, link-local
        172.1[6-9].*|172.2?.*|172.3[01].*) ;;  # Docker's default bridge pool
        *:*)                              ;;   # IPv6 — not what people type
        *) IPS+=("$ip") ;;
    esac
done

host_name="$(hostname 2>/dev/null || true)"
[ -n "$host_name" ] && NAMES+=("$host_name")

# Anything passed on the command line: an all-digits-and-dots argument is an IP,
# everything else is a hostname. They go in different SAN fields and a hostname
# in the IP slot makes openssl refuse the whole request.
for arg in "$@"; do
    case "$arg" in
        *[!0-9.]*) NAMES+=("$arg") ;;
        *)         IPS+=("$arg") ;;
    esac
done

# ── Build the SAN list ──────────────────────────────────────────────────────
san=""
seen=""
add_san() {
    case " $seen " in *" $1 "*) return ;; esac
    seen="$seen $1"
    [ -n "$san" ] && san="$san,"
    san="$san$2:$1"
}
for n in "${NAMES[@]}"; do [ -n "$n" ] && add_san "$n" DNS; done
for i in "${IPS[@]}"; do [ -n "$i" ] && add_san "$i" IP; done

say "Certificate will be valid for: $san"
if [ ${#IPS[@]} -le 1 ]; then
    say ""
    say "Note: no LAN address was detected, so the certificate covers localhost only."
    say "If you reach Harvis from another device, re-run this with that address:"
    say "    ./scripts/enable-https.sh 192.168.x.x"
fi
say ""

# ── Generate ────────────────────────────────────────────────────────────────
if [ -f "$CRT" ] && [ -f "$KEY" ]; then
    say "A certificate already exists at $CRT."
    printf 'Replace it? [y/N] '
    # `|| reply=""` so a non-interactive run (a pipe, cron, an installer) keeps
    # the existing certificate instead of dying on EOF under `set -e`.
    read -r reply || reply=""
    case "$reply" in
        [yY]*) ;;
        *) say "Keeping the existing certificate."; REUSE=1 ;;
    esac
fi

if [ -z "${REUSE:-}" ]; then
    openssl req -x509 -nodes -newkey rsa:2048 \
        -days 825 \
        -keyout "$KEY" \
        -out "$CRT" \
        -subj "/CN=harvis" \
        -addext "subjectAltName=$san" \
        -addext "basicConstraints=critical,CA:FALSE" \
        -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
        -addext "extendedKeyUsage=serverAuth" \
        >/dev/null 2>&1 || fail "openssl could not generate the certificate."

    # The nginx worker runs unprivileged and reads the key through a read-only
    # bind mount, so it needs to be world-readable inside the container. 0644 on
    # a key is normally wrong; it is acceptable only because this key protects a
    # LAN listener and is regenerable in one command. Do not reuse it elsewhere.
    chmod 0644 "$CRT"
    chmod 0644 "$KEY"
    say "Generated $CRT"
fi

# ── Activate the listener ───────────────────────────────────────────────────
cp "$TEMPLATE" "$ACTIVE"
say "Enabled the HTTPS listener ($ACTIVE)"
say ""

# ── Bring it up ─────────────────────────────────────────────────────────────
# `restart` is not enough: this adds a published port and two bind mounts, and
# neither reaches a container that is only restarted.
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    say "Applying to the running stack..."
    if docker compose up -d nginx; then
        say ""
        say "HTTPS is on."
    else
        fail "docker compose up -d nginx failed. Fix the error above and run it again."
    fi
else
    say "Docker Compose was not found. Apply it yourself with:"
    say ""
    say "    docker compose up -d nginx"
fi

say ""
say "Reach Harvis at:"
for i in "${IPS[@]}"; do
    [ "$i" = "127.0.0.1" ] && continue
    say "    https://$i:$HTTPS_PORT"
done
say "    https://localhost:$HTTPS_PORT"
say ""
say "The first visit shows a certificate warning because the certificate signed"
say "itself. Click Advanced, then Proceed. After that the microphone will work"
say "from other devices, which it cannot over plain http."
say ""
say "Plain http on port 9000 keeps working. Nothing was taken away."
