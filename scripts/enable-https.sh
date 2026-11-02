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
# On a Kubernetes install (./install.sh --k8s) the same command works: the
# certificate lands in the directory the nginx pod mounts and the pod is restarted.
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

# The port people type after the address, so the plain lane's redirect lands on it.
HTTPS_PORT="${HARVIS_HTTPS_PORT:-$( { grep '^HARVIS_HTTPS_PORT=' .env 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d "\"' \r")}"
HTTPS_PORT="${HTTPS_PORT:-9443}"

say()  { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

# ── Kubernetes install? ─────────────────────────────────────────────────────
# There the Docker containers are stopped, and `docker compose up -d nginx` would
# start a second nginx on the same ports. The nginx pod instead reads
# /etc/nginx/tls from a hostPath, so the files go there and the pod restarts.
NS="${HARVIS_K8S_NAMESPACE:-harvis}"
K8S_MODE_FILE="${HARVIS_K8S_MODE_FILE:-/var/lib/harvis/k8s/mode}"
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
kc() { $SUDO k3s kubectl "$@"; }
K8S=0
PUBLIC_BIND=""
if [ "$(cat "$K8S_MODE_FILE" 2>/dev/null || true)" = "k8s" ]; then
    K8S=1
    command -v k3s >/dev/null 2>&1 || fail "this machine runs Harvis on Kubernetes but k3s was not found."
    # The directory the pod really mounts, which is another checkout's if Harvis
    # was installed from a different folder than this one.
    mount_name="$(kc -n "$NS" get deploy nginx -o jsonpath='{.spec.template.spec.containers[0].volumeMounts[?(@.mountPath=="/etc/nginx/tls")].name}' 2>/dev/null || true)"
    if [ -n "$mount_name" ]; then
        host_tls="$(kc -n "$NS" get deploy nginx -o jsonpath="{.spec.template.spec.volumes[?(@.name==\"$mount_name\")].hostPath.path}" 2>/dev/null || true)"
        [ -n "$host_tls" ] && TLS_DIR="$host_tls"
    fi
    CERT_DIR="$TLS_DIR"
    CRT="$CERT_DIR/harvis.crt"
    KEY="$CERT_DIR/harvis.key"
    ACTIVE="$TLS_DIR/harvis-tls.conf"
fi
REDIRECT="$TLS_DIR/harvis-https.redirect"
# The .env that holds the cookie flag: this checkout's, or, on Kubernetes, the one
# beside the tls directory the pod mounts (the checkout Harvis was installed from).
ENV_FILE=".env"
if [ "$K8S" = "1" ] && [ "${TLS_DIR%/nginx/tls}" != "$TLS_DIR" ] && [ -f "${TLS_DIR%/nginx/tls}/.env" ]; then
    ENV_FILE="${TLS_DIR%/nginx/tls}/.env"
fi

command -v openssl >/dev/null 2>&1 || fail "openssl is not installed. Install it and run this again."
[ -f "$TEMPLATE" ] || fail "missing $TEMPLATE — is this the Harvis repository root?"

mkdir -p "$CERT_DIR" "$TLS_DIR" 2>/dev/null || true
[ -d "$TLS_DIR" ] && [ -w "$TLS_DIR" ] || fail "cannot write to $TLS_DIR. Run this script as the user who owns that folder."

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
        $2 ~ /^(docker|br-|veth|virbr|tailscale|tun|wg|lo|cni|flannel)/ { next }
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

# From here the plain http lane (:9000) only redirects to https, so a password or
# the session cookie never crosses the network in the clear. nginx.conf includes
# this file; only the crawler policy and the installer's two health probes stay
# on http. `rm` this file and reload nginx to put :9000 back to serving the app.
# The Kubernetes pod builds its config from the same nginx.conf and mounts this
# directory as a hostPath, so it reads the file too.
printf '%s\n' \
    '# Written by scripts/enable-https.sh. nginx.conf reads it in the port-80 server block.' \
    "set \$harvis_https_base \"https://\$host:${HTTPS_PORT}\";" > "$REDIRECT"
say "Plain http now redirects to https ($REDIRECT)"
say ""

# HARVIS_COOKIE_SECURE=true in the .env that the next start reads. Done only once
# https answers: a Secure cookie is never sent over plain http, so setting it
# earlier would lock sign-in out. Returns 1 when it was already set.
set_cookie_secure_env() {
    grep -qx 'HARVIS_COOKIE_SECURE=true' "$ENV_FILE" 2>/dev/null && return 1
    touch "$ENV_FILE"
    sed -i '/^HARVIS_COOKIE_SECURE=/d' "$ENV_FILE"
    [ -s "$ENV_FILE" ] && [ -n "$(tail -c1 "$ENV_FILE")" ] && printf '\n' >> "$ENV_FILE"
    printf 'HARVIS_COOKIE_SECURE=true\n' >> "$ENV_FILE"
    return 0
}

# ── Bring it up ─────────────────────────────────────────────────────────────
# `restart` is not enough: this adds a published port and two bind mounts, and
# neither reaches a container that is only restarted.
if [ "$K8S" = "1" ]; then
    # The running pod already sees the new files through its hostPath, and every
    # Deployment here uses Recreate: a config nginx rejects would take :9000 down too.
    if ! check="$(kc -n "$NS" exec deploy/nginx -- nginx -t 2>&1)"; then
        rm -f "$ACTIVE" "$REDIRECT"
        say "nginx rejected the new configuration, or its pod is not running. Details:"
        say "$check"
        fail "HTTPS was not enabled; the listener file was removed so nginx keeps starting."
    fi
    say "Restarting the nginx pod (namespace $NS)..."
    kc -n "$NS" rollout restart deploy/nginx >/dev/null || fail "could not restart the nginx pod. HTTPS was not enabled."
    kc -n "$NS" rollout status deploy/nginx --timeout=120s >/dev/null 2>&1 \
        || fail "the nginx pod did not become ready. See: sudo k3s kubectl -n $NS logs deploy/nginx"
    say ""
    say "HTTPS is on."
    # The backend's environment lives in the Secret backend-env, which harvis-k8s.sh
    # renders from .env on every `up`. Both are set: .env so a re-render keeps the
    # flag, the live Secret and a backend restart so it takes effect now.
    set_cookie_secure_env || true
    say "Set HARVIS_COOKIE_SECURE=true in $ENV_FILE; restarting the backend to apply it..."
    if ! kc -n "$NS" patch secret backend-env --type merge -p '{"stringData":{"HARVIS_COOKIE_SECURE":"true"}}' >/dev/null; then
        fail "HTTPS is on, but the session cookie could not be made Secure (the backend-env Secret was not patched). Run ./harvis-start.sh again, or: sudo k3s kubectl -n $NS patch secret backend-env --type merge -p '{\"stringData\":{\"HARVIS_COOKIE_SECURE\":\"true\"}}' && sudo k3s kubectl -n $NS rollout restart deploy/backend"
    fi
    kc -n "$NS" rollout restart deploy/backend >/dev/null || fail "could not restart the backend pod, so the Secure cookie is not applied yet. Run: sudo k3s kubectl -n $NS rollout restart deploy/backend"
    kc -n "$NS" rollout status deploy/backend --timeout=180s >/dev/null 2>&1 \
        || fail "the backend pod did not become ready. See: sudo k3s kubectl -n $NS logs deploy/backend"
    # Kubernetes publishes the front door on every address (./install.sh --k8s sets it).
    PUBLIC_BIND=0.0.0.0
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    say "Applying to the running stack..."
    if docker compose up -d nginx; then
        # `up -d` alone is not enough either. On a stack whose nginx container
        # already carries the tls bind mount — which every install on the current
        # compose file does — compose sees an unchanged spec and leaves the
        # container running untouched. The new listener file lands inside the
        # container through the mount but nginx never re-reads its config, so
        # HTTPS silently stays off and the script still says it is on. Reloading
        # afterwards costs nothing on a container that was just recreated and is
        # the only thing that turns it on for one that was not.
        if docker compose exec -T nginx nginx -t >/dev/null 2>&1; then
            docker compose exec -T nginx nginx -s reload >/dev/null 2>&1 || true
        else
            say ""
            say "nginx rejected the new configuration. Details:"
            docker compose exec -T nginx nginx -t || true
            rm -f "$ACTIVE" "$REDIRECT"
            fail "HTTPS was not enabled; the listener and redirect files were removed."
        fi
        say ""
        say "HTTPS is on."
        # Only now, with https answering: a Secure cookie is never sent over plain
        # http, so setting it before the listener works would lock sign-in out. The
        # backend reads it at start, so it is recreated alone to pick it up.
        if set_cookie_secure_env; then
            say "Set HARVIS_COOKIE_SECURE=true in .env; restarting the backend to apply it..."
            docker compose up -d --no-deps backend || say "Could not restart the backend; run: docker compose up -d backend"
        fi
    else
        fail "docker compose up -d nginx failed. Fix the error above and run it again."
    fi
else
    say "Docker Compose was not found. Apply it yourself with:"
    say ""
    say "    docker compose up -d nginx"
fi

# Ports 9000/9443 leave this machine only when .env binds them to every address
# (./install.sh --expose lan); compose defaults them to 127.0.0.1.
PUBLIC_BIND="${PUBLIC_BIND:-$( { grep '^HARVIS_BIND_ADDR_PUBLIC=' .env 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d "\"' \r")}"
EXPOSURE="$( { grep '^HARVIS_EXPOSURE=' .env 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d "\"' \r")"

say ""
say "Reach Harvis at:"
if [ "$PUBLIC_BIND" = "0.0.0.0" ]; then
    for i in "${IPS[@]}"; do
        [ "$i" = "127.0.0.1" ] && continue
        say "    https://$i:$HTTPS_PORT"
    done
fi
say "    https://localhost:$HTTPS_PORT"
say ""
say "The first visit shows a certificate warning because the certificate signed"
say "itself. Click Advanced, then Proceed."
say ""
if [ "$PUBLIC_BIND" = "0.0.0.0" ]; then
    say "After that the microphone works from other devices, which it cannot over"
    say "plain http. Port 9000 now sends people to https, and sign-ins are https-only."
elif [ "$EXPOSURE" = "tunnel" ]; then
    say "Visitors from the internet already get HTTPS from Cloudflare; this certificate"
    say "only matters on this computer."
else
    say "Harvis answers on this computer only, so other devices cannot reach it yet."
    say "Share it on your network with ./install.sh --expose lan; the certificate"
    say "already covers this machine's network addresses."
fi
