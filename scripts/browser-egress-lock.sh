#!/usr/bin/env bash
# Docker-mode twin of the Kubernetes `browser-runner-public-only` NetworkPolicy
# (scripts/k8s/k8s_harden.py, browser_egress): browser-runner may reach the
# public internet and nothing on this host's LAN or any private range.
#
#   scripts/browser-egress-lock.sh apply    install the rules (idempotent)
#   scripts/browser-egress-lock.sh remove   take every rule and chain away
#   scripts/browser-egress-lock.sh status   show what is installed
#   scripts/browser-egress-lock.sh print    show the iptables commands, run nothing
#   --dry-run on apply/remove is the same as print.
#
# Docker cannot say "internet but not the LAN", so this keys on the pinned
# subnet of the `browser-egress` network in docker-compose.yaml. Two chains, both
# ours, so `remove` leaves nothing behind:
#   HARVIS-BROWSER-FWD   hooked from DOCKER-USER (traffic leaving the host)
#   HARVIS-BROWSER-IN    hooked from INPUT (traffic aimed at the host itself:
#                        host services such as Ollama on the docker0 address,
#                        and the host's own LAN address, never touch FORWARD)
#
# Environment:
#   HARVIS_BROWSER_SUBNET       the network's subnet; must equal what compose
#                               uses (default 10.213.83.0/28). Comma list if
#                               several stacks share this host.
#   HARVIS_BROWSER_ALLOW_CIDRS  comma list of private IPv4 ranges the browser may
#                               reach anyway, e.g. 192.168.50.0/24. Same name and
#                               meaning as the Kubernetes setting.
#   HARVIS_BROWSER_DNS          extra resolver IPs to let through on port 53.
#                               The host's own non-loopback resolvers are found
#                               automatically: without them a LAN router that
#                               serves DNS would make every page fail to load.
#
# Needs root. Without iptables, without root or passwordless sudo, or without
# Docker's DOCKER-USER chain it says so and exits 0: the install carries on, the
# browser just is not walled off from the LAN, and the warning says that.
# IPv4 only; the compose network has no IPv6.
set -uo pipefail

PRIVATE_RANGES="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 127.0.0.0/8 0.0.0.0/8 224.0.0.0/4 240.0.0.0/4"
FWD_CHAIN="HARVIS-BROWSER-FWD"
IN_CHAIN="HARVIS-BROWSER-IN"

MODE="${1:-apply}"
DRY=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
[ "$MODE" = "print" ] && { MODE=apply; DRY=1; }
[ "$MODE" = "--dry-run" ] && MODE=apply

say()  { printf 'browser-egress-lock: %s\n' "$*"; }
warn() { printf 'browser-egress-lock: WARNING: %s\n' "$*" >&2; }

# Compose reads these from .env, so this script must too, or it locks a subnet the
# browser is not on. The process environment still wins.
env_file_get() {
  local f
  f="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env"
  [ -f "$f" ] || return 0
  grep -E "^$1=" "$f" | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}
SUBNETS="${HARVIS_BROWSER_SUBNET:-$(env_file_get HARVIS_BROWSER_SUBNET)}"
SUBNETS="${SUBNETS:-10.213.83.0/28}"
ALLOW="${HARVIS_BROWSER_ALLOW_CIDRS:-$(env_file_get HARVIS_BROWSER_ALLOW_CIDRS)}"

valid_cidr() { # IPv4 a.b.c.d or a.b.c.d/n, octets <=255, n <=32
  local c="$1" ip n o
  [[ "$c" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$ ]] || return 1
  ip="${c%%/*}"; n=32; [[ "$c" == */* ]] && n="${c#*/}"
  [ "$n" -le 32 ] || return 1
  local IFS=.; for o in $ip; do [ "$((10#$o))" -le 255 ] || return 1; done
}
split_list() { printf '%s' "$1" | tr ',;' '  '; }

validate_all() {
  local c
  for c in $(split_list "$SUBNETS"); do
    valid_cidr "$c" && [[ "$c" == */* ]] || { warn "HARVIS_BROWSER_SUBNET: '$c' is not an IPv4 range like 10.213.83.0/28"; return 1; }
  done
  [ -n "$(split_list "$SUBNETS")" ] || { warn "HARVIS_BROWSER_SUBNET is empty"; return 1; }
  for c in $(split_list "$ALLOW"); do
    valid_cidr "$c" || { warn "HARVIS_BROWSER_ALLOW_CIDRS: '$c' is not an IPv4 range like 192.168.1.0/24"; return 1; }
  done
}

# Non-loopback resolvers the host really uses (Docker forwards container DNS to
# them from the container's own network namespace, so a private one is blocked
# unless we let port 53 through). 127.x stub resolvers are forwarded by dockerd
# from the host and never hit these rules.
resolvers() {
  { for f in ${HARVIS_BROWSER_RESOLV_FILES:-/etc/resolv.conf /run/systemd/resolve/resolv.conf}; do
      [ -r "$f" ] && awk '$1=="nameserver"{print $2}' "$f"
    done
    printf '%s\n' $(split_list "${HARVIS_BROWSER_DNS:-}")
  } | while read -r ns; do
        valid_cidr "$ns" && [[ "$ns" != */* ]] && [[ "$ns" != 127.* ]] && printf '%s\n' "$ns"
      done | sort -u
}

# Emits the rule set as plain `iptables` argument lines, one per line, so the
# exact same text is what dry-run shows, what the test checks and what runs.
# Each line starts with a verb: ENSURE_CHAIN, FLUSH, HOOK (jump, deduped),
# APPEND (rule appended to a chain).
rules() {
  local sn c ns
  echo "ENSURE_CHAIN $FWD_CHAIN"; echo "ENSURE_CHAIN $IN_CHAIN"
  echo "FLUSH $FWD_CHAIN"; echo "FLUSH $IN_CHAIN"
  for ns in $(resolvers); do
    echo "APPEND $FWD_CHAIN -d $ns -p udp --dport 53 -j ACCEPT"
    echo "APPEND $FWD_CHAIN -d $ns -p tcp --dport 53 -j ACCEPT"
    echo "APPEND $IN_CHAIN -d $ns -p udp --dport 53 -j ACCEPT"
    echo "APPEND $IN_CHAIN -d $ns -p tcp --dport 53 -j ACCEPT"
  done
  for c in $(split_list "$ALLOW"); do
    [[ "$c" == */* ]] || c="$c/32"
    echo "APPEND $FWD_CHAIN -d $c -j ACCEPT"
    echo "APPEND $IN_CHAIN -d $c -j ACCEPT"
  done
  for c in $PRIVATE_RANGES; do echo "APPEND $FWD_CHAIN -d $c -j DROP"; done
  # INPUT: the container has no business talking to the host at all (host
  # services, the docker0 gateway, the host's public address alike).
  echo "APPEND $IN_CHAIN -j DROP"
  echo "APPEND $FWD_CHAIN -j RETURN"
  for sn in $(split_list "$SUBNETS"); do
    echo "HOOK DOCKER-USER -s $sn -j $FWD_CHAIN"
    echo "HOOK INPUT -s $sn -j $IN_CHAIN"
  done
}

unhook_lines() { # remove every jump to our chains, whatever subnet it was for
  echo "UNHOOK DOCKER-USER $FWD_CHAIN"; echo "UNHOOK INPUT $IN_CHAIN"
  echo "FLUSH $FWD_CHAIN"; echo "FLUSH $IN_CHAIN"
  echo "DELETE_CHAIN $FWD_CHAIN"; echo "DELETE_CHAIN $IN_CHAIN"
}

IPT=(iptables -w 5)
SUDO=""

can_run() {
  command -v iptables >/dev/null 2>&1 || { warn "iptables not found; the browser can still reach this host's LAN. Install iptables (or run on Linux) and re-run: scripts/browser-egress-lock.sh apply"; return 1; }
  if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then SUDO="sudo -n"
    else warn "needs root (no passwordless sudo); the browser can still reach this host's LAN. Run: sudo scripts/browser-egress-lock.sh apply"; return 1; fi
  fi
  $SUDO "${IPT[@]}" -S DOCKER-USER >/dev/null 2>&1 || { warn "Docker's DOCKER-USER chain is not there (is Docker running?); nothing installed. Start Docker and re-run: scripts/browser-egress-lock.sh apply"; return 1; }
}

run() { # run an iptables command line, or show it
  if [ "$DRY" = 1 ]; then printf 'iptables -w 5 %s\n' "$*"; else $SUDO "${IPT[@]}" "$@"; fi
}
quiet_ok() { [ "$DRY" = 1 ] || $SUDO "${IPT[@]}" "$@" >/dev/null 2>&1; }

execute() { # read verb lines on stdin
  local verb a b rest
  while read -r verb a rest; do
    case "$verb" in
      ENSURE_CHAIN) [ "$DRY" = 1 ] && run -N "$a" || { quiet_ok -L "$a" -n || run -N "$a"; } ;;
      FLUSH)        if [ "$DRY" = 1 ]; then run -F "$a"; else quiet_ok -L "$a" -n && run -F "$a"; fi ;;
      APPEND)       # shellcheck disable=SC2086
                    run -A "$a" $rest ;;
      HOOK)         # a = DOCKER-USER|INPUT ; rest = "-s SUBNET -j CHAIN"; dedupe then insert at top
                    if [ "$DRY" = 1 ]; then run -I "$a" 1 $rest
                    else quiet_ok -C "$a" $rest || run -I "$a" 1 $rest; fi ;;
      UNHOOK)       # a = parent chain, rest = our chain; delete every jump to it
                    if [ "$DRY" = 1 ]; then printf 'iptables -w 5 -D %s <each jump to %s>\n' "$a" "$rest"
                    else
                      while read -r spec; do
                        [ -n "$spec" ] && $SUDO "${IPT[@]}" ${spec/-A/-D} >/dev/null 2>&1
                      done < <($SUDO "${IPT[@]}" -S "$a" 2>/dev/null | grep -- "-j $rest\$")
                    fi ;;
      DELETE_CHAIN) if [ "$DRY" = 1 ]; then run -X "$a"; else quiet_ok -L "$a" -n && run -X "$a"; fi ;;
    esac
  done
}

case "$MODE" in
  apply)
    validate_all || exit 0
    [ "$DRY" = 1 ] || can_run || exit 0
    # Re-apply from scratch: unhook first so a changed HARVIS_BROWSER_SUBNET
    # does not leave a stale jump behind, then build and hook.
    { unhook_lines | grep -v DELETE_CHAIN; rules; } | execute
    [ "$DRY" = 1 ] || say "browser-runner egress locked to the public internet on $SUBNETS (allowed private ranges: ${ALLOW:-none})"
    ;;
  remove)
    if [ "$DRY" != 1 ]; then can_run || exit 0; fi
    unhook_lines | execute
    [ "$DRY" = 1 ] || say "removed"
    ;;
  status)
    can_run || exit 0
    for ch in "DOCKER-USER" "INPUT" "$FWD_CHAIN" "$IN_CHAIN"; do
      echo "== $ch"; $SUDO "${IPT[@]}" -S "$ch" 2>&1 | grep -E "HARVIS-BROWSER|^-N $ch|-A $ch" || true
    done
    ;;
  *) echo "usage: $0 apply|remove|status|print [--dry-run]" >&2; exit 2 ;;
esac
exit 0
