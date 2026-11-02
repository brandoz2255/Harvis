#!/usr/bin/env bash
# Opt-in firewall for a host Ollama that listens on 0.0.0.0 so containers can
# reach it. Ollama has no sign-in: anything that can connect can list, pull,
# delete and run models. Listening on 0.0.0.0 puts that on every network the
# machine is on, so run this BEFORE you set OLLAMA_HOST=0.0.0.0 (install.sh says
# the same when it finds Ollama unreachable from Docker).
#
#   scripts/ollama-lan-lock.sh apply    install the rules (idempotent)
#   scripts/ollama-lan-lock.sh remove   take the rules and the chain away
#   scripts/ollama-lan-lock.sh status   show what is installed
#   scripts/ollama-lan-lock.sh print    show the iptables commands, run nothing
#   --dry-run on apply/remove is the same as print.
#
# Port 11434 stays open on the loopback and on Docker's bridges (docker0 and
# every br-*), which is what the stack's containers use. It is closed to:
#   - the repo-sandbox and browser-egress networks, where untrusted code runs,
#     even though they are Docker bridges;
#   - everything else, the LAN included.
# One chain, ours (HARVIS-OLLAMA-IN), hooked from INPUT for this port only, so
# `remove` leaves nothing behind. Not applied by install.sh: you run it.
#
# Environment (also read from .env, the process environment wins):
#   HARVIS_OLLAMA_PORT          the port Ollama listens on (default 11434)
#   HARVIS_OLLAMA_ALLOW_CIDRS   comma list of LAN hosts or ranges that may still
#                               reach it, e.g. 192.168.1.50 or 192.168.1.0/24
#   HARVIS_REPO_SANDBOX_SUBNET  must equal what compose uses (default 10.213.84.0/24)
#   HARVIS_BROWSER_SUBNET       must equal what compose uses (default 10.213.83.0/28)
#
# Needs root. Without iptables, or root / passwordless sudo, it says so and
# exits 0. It refuses (exit 3) when the repo-sandbox network is on another subnet
# or the backend's default route runs through it; see scripts/lock-preflight.sh.
# HARVIS_LOCK_SKIP_PREFLIGHT=1 applies anyway. IPv4 only: with OLLAMA_HOST=0.0.0.0 Ollama does not listen on IPv6.
set -uo pipefail

CHAIN="HARVIS-OLLAMA-IN"

LP_NAME="ollama-lan-lock"
# shellcheck source=scripts/lock-preflight.sh
_lp_dir="${BASH_SOURCE[0]}"; case "$_lp_dir" in */*) _lp_dir="${_lp_dir%/*}" ;; *) _lp_dir=. ;; esac
. "$_lp_dir/lock-preflight.sh"

MODE="${1:-apply}"
DRY=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
[ "$MODE" = "print" ] && { MODE=apply; DRY=1; }
[ "$MODE" = "--dry-run" ] && MODE=apply

say()  { printf 'ollama-lan-lock: %s\n' "$*"; }
warn() { printf 'ollama-lan-lock: WARNING: %s\n' "$*" >&2; }

env_file_get() {
  local f
  f="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env"
  [ -f "$f" ] || return 0
  grep -E "^$1=" "$f" | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}
PORT="${HARVIS_OLLAMA_PORT:-$(env_file_get HARVIS_OLLAMA_PORT)}"
PORT="${PORT:-11434}"
ALLOW="${HARVIS_OLLAMA_ALLOW_CIDRS:-$(env_file_get HARVIS_OLLAMA_ALLOW_CIDRS)}"
SBX_SUBNETS="${HARVIS_REPO_SANDBOX_SUBNET:-$(env_file_get HARVIS_REPO_SANDBOX_SUBNET)}"
SBX_SUBNETS="${SBX_SUBNETS:-10.213.84.0/24}"
BROWSER_SUBNETS="${HARVIS_BROWSER_SUBNET:-$(env_file_get HARVIS_BROWSER_SUBNET)}"
BROWSER_SUBNETS="${BROWSER_SUBNETS:-10.213.83.0/28}"

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
  [[ "$PORT" =~ ^[0-9]{1,5}$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || { warn "HARVIS_OLLAMA_PORT: '$PORT' is not a port number"; return 1; }
  for c in $(split_list "$SBX_SUBNETS"); do
    valid_cidr "$c" && [[ "$c" == */* ]] || { warn "HARVIS_REPO_SANDBOX_SUBNET: '$c' is not an IPv4 range like 10.213.84.0/24"; return 1; }
  done
  for c in $(split_list "$BROWSER_SUBNETS"); do
    valid_cidr "$c" && [[ "$c" == */* ]] || { warn "HARVIS_BROWSER_SUBNET: '$c' is not an IPv4 range like 10.213.83.0/28"; return 1; }
  done
  for c in $(split_list "$ALLOW"); do
    valid_cidr "$c" || { warn "HARVIS_OLLAMA_ALLOW_CIDRS: '$c' is not an IPv4 range like 192.168.1.0/24"; return 1; }
  done
}

# Verb lines, one per line, so dry-run shows exactly what runs: ENSURE_CHAIN,
# FLUSH, HOOK (jump, deduped), APPEND, UNHOOK, DELETE_CHAIN.
rules() {
  local c
  echo "ENSURE_CHAIN $CHAIN"
  echo "FLUSH $CHAIN"
  # Untrusted networks first: they are Docker bridges, so the br-+ accept below
  # would otherwise let them in.
  for c in $(split_list "$BROWSER_SUBNETS") $(split_list "$SBX_SUBNETS"); do
    echo "APPEND $CHAIN -s $c -j DROP"
  done
  echo "APPEND $CHAIN -i lo -j ACCEPT"
  echo "APPEND $CHAIN -i docker0 -j ACCEPT"
  echo "APPEND $CHAIN -i br-+ -j ACCEPT"
  for c in $(split_list "$ALLOW"); do
    [[ "$c" == */* ]] || c="$c/32"
    echo "APPEND $CHAIN -s $c -j ACCEPT"
  done
  echo "APPEND $CHAIN -j DROP"
  echo "HOOK INPUT -p tcp --dport $PORT -j $CHAIN"
}

unhook_lines() {
  echo "UNHOOK INPUT $CHAIN"
  echo "FLUSH $CHAIN"
  echo "DELETE_CHAIN $CHAIN"
}

IPT=(iptables -w 5)
SUDO=""

can_run() {
  command -v iptables >/dev/null 2>&1 || { warn "iptables not found; port $PORT is not firewalled. Install iptables and re-run: scripts/ollama-lan-lock.sh apply"; return 1; }
  if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then SUDO="sudo -n"
    else warn "needs root (no passwordless sudo); port $PORT is not firewalled. Run: sudo scripts/ollama-lan-lock.sh apply"; return 1; fi
  fi
  $SUDO "${IPT[@]}" -S INPUT >/dev/null 2>&1 || { warn "cannot read the INPUT chain (is the kernel firewall available?); nothing installed"; return 1; }
}

run() {
  if [ "$DRY" = 1 ]; then printf 'iptables -w 5 %s\n' "$*"; else $SUDO "${IPT[@]}" "$@"; fi
}
quiet_ok() { [ "$DRY" = 1 ] || $SUDO "${IPT[@]}" "$@" >/dev/null 2>&1; }

execute() { # read verb lines on stdin
  local verb a rest spec
  while read -r verb a rest; do
    case "$verb" in
      ENSURE_CHAIN) [ "$DRY" = 1 ] && run -N "$a" || { quiet_ok -L "$a" -n || run -N "$a"; } ;;
      FLUSH)        if [ "$DRY" = 1 ]; then run -F "$a"; else quiet_ok -L "$a" -n && run -F "$a"; fi ;;
      APPEND)       # shellcheck disable=SC2086
                    run -A "$a" $rest ;;
      HOOK)         # shellcheck disable=SC2086
                    if [ "$DRY" = 1 ]; then run -I "$a" 1 $rest
                    else quiet_ok -C "$a" $rest || run -I "$a" 1 $rest; fi ;;
      UNHOOK)       # a = parent chain, rest = our chain; delete every jump to it
                    if [ "$DRY" = 1 ]; then printf 'iptables -w 5 -D %s <each jump to %s>\n' "$a" "$rest"
                    else
                      while read -r spec; do
                        # shellcheck disable=SC2086
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
    # Same refusal as browser-egress-lock.sh: it drops the repo-sandbox subnet, so a
    # network on another subnet is left out, and a backend routed through
    # repo-sandbox would lose its own Ollama. Exit 3, nothing installed.
    [ "$DRY" = 1 ] || lock_preflight "$SBX_SUBNETS" "$BROWSER_SUBNETS" || exit 3
    # Unhook first so a changed port does not leave a stale jump behind.
    { unhook_lines | grep -v DELETE_CHAIN; rules; } | execute
    [ "$DRY" = 1 ] || say "port $PORT is open on loopback and Docker bridges only (repo-sandbox and browser-egress excluded; LAN allowed: ${ALLOW:-none})"
    ;;
  remove)
    if [ "$DRY" != 1 ]; then can_run || exit 0; fi
    unhook_lines | execute
    [ "$DRY" = 1 ] || say "removed"
    ;;
  status)
    can_run || exit 0
    for ch in INPUT "$CHAIN"; do
      echo "== $ch"; $SUDO "${IPT[@]}" -S "$ch" 2>&1 | grep -E "HARVIS-OLLAMA|^-N $ch|-A $ch" || true
    done
    ;;
  *) echo "usage: $0 apply|remove|status|print [--dry-run]" >&2; exit 2 ;;
esac
exit 0
