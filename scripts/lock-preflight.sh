#!/usr/bin/env bash
# Sourced by scripts/browser-egress-lock.sh and scripts/ollama-lan-lock.sh. Not run on its own.
#
# Both scripts key their firewall rules on the pinned subnet of the repo-sandbox
# network and drop everything from it that reaches the host or the LAN. Two things
# make that wrong, and both are silent until chat loses its model or a sandbox
# keeps its LAN access:
#
#   1. The network already exists on another subnet. Compose never changes the
#      subnet of an existing network, so an install made before the subnet was
#      pinned keeps the one Docker handed out, and the rules target a range
#      nobody is on.
#   2. The backend's default route runs through repo-sandbox (docker-compose.yaml
#      pins ollama-n8n-network with gw_priority: 1 to prevent it). Its traffic to
#      host Ollama and to LAN model servers would then come from the sandbox
#      subnet and be dropped with the sandboxes' own.
#
# lock_preflight <sandbox-subnets> <browser-subnets>  -> 0 safe to apply, 1 refuse.
# It prints the reason and a one-line fix on stderr. With no usable docker, or no
# such network or container, there is nothing to contradict and it returns 0.
# HARVIS_LOCK_SKIP_PREFLIGHT=1 skips it.

_lp_warn() { printf '%s: WARNING: %s\n' "${LP_NAME:-lock}" "$*" >&2; }

_lp_ip2int() { local IFS=.; set -- $1; echo $(( ($1 << 24) + ($2 << 16) + ($3 << 8) + $4 )); }

_lp_in_cidr() { # $1 = ip, $2 = a.b.c.d/n
  local ip net n mask
  ip="$(_lp_ip2int "$1")"; net="$(_lp_ip2int "${2%/*}")"; n="${2#*/}"
  mask=$(( n == 0 ? 0 : (0xFFFFFFFF << (32 - n)) & 0xFFFFFFFF ))
  [ $(( ip & mask )) -eq $(( net & mask )) ]
}

_lp_list() { printf '%s' "$1" | tr ',;' '  '; }

# The default gateway inside a container, from /proc/net/route (always there, no
# iproute2 needed). Little-endian hex, e.g. 0140D50A is 10.213.64.1.
_lp_default_gw() { # $1 = container id
  local g
  g="$(docker exec "$1" cat /proc/net/route 2>/dev/null | awk 'NR>1 && $2=="00000000"{print $3; exit}')"
  [[ "$g" =~ ^[0-9A-Fa-f]{8}$ ]] || return 1
  printf '%d.%d.%d.%d\n' "$((16#${g:6:2}))" "$((16#${g:4:2}))" "$((16#${g:2:2}))" "$((16#${g:0:2}))"
}

# A compose network (by its compose key) that exists on a subnet the lock does
# not cover. Prints the fix and returns 1 for the first one found.
_lp_net_subnets() { # $1 = compose network key, $2 = pinned list, $3 = env var name
  local key="$1" pinned="$2" var="$3" name subnets s ok bad=0
  while read -r name; do
    [ -n "$name" ] || continue
    subnets="$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' "$name" 2>/dev/null)"
    [ -n "${subnets// /}" ] || continue
    ok=0
    for s in $subnets; do
      case " $(_lp_list "$pinned") " in *" $s "*) ok=1 ;; esac
    done
    if [ "$ok" = 0 ]; then
      bad=1
      _lp_warn "Docker network '$name' is on ${subnets% }, but the lock covers $(_lp_list "$pinned"), so its containers would be left outside the rules. Compose does not change an existing network's subnet. Nothing was applied."
      _lp_warn "Fix: docker compose down && docker network rm $name && ./install.sh   (or set $var to ${subnets% } and re-run this script)"
    fi
  done < <(docker ps >/dev/null 2>&1 && docker network ls --filter "label=com.docker.compose.network=$key" --format '{{.Name}}' 2>/dev/null)
  [ "$bad" = 0 ]
}

_lp_backend_route() { # $1 = sandbox subnets
  local id gw sn bad=0 name
  command -v docker >/dev/null 2>&1 || return 0
  while read -r id; do
    [ -n "$id" ] || continue
    gw="$(_lp_default_gw "$id")" || continue
    for sn in $(_lp_list "$1"); do
      if _lp_in_cidr "$gw" "$sn"; then
        name="$(docker inspect -f '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')"
        _lp_warn "the running backend (${name:-$id}) has its default route through the repo-sandbox network ($sn). Once the rules are in, its traffic to host Ollama and to LAN model servers comes from that subnet and is dropped, and chat loses its model. Nothing was applied."
        _lp_warn "Fix: docker compose up -d backend   (docker-compose.yaml gives ollama-n8n-network gw_priority: 1; then check: docker exec ${name:-backend} cat /proc/net/route)"
        bad=1
      fi
    done
  done < <(docker ps -q --filter 'label=com.docker.compose.service=backend' 2>/dev/null)
  [ "$bad" = 0 ]
}

lock_preflight() { # $1 = repo-sandbox subnets, $2 = browser-egress subnets
  [ "${HARVIS_LOCK_SKIP_PREFLIGHT:-0}" = 1 ] && return 0
  command -v docker >/dev/null 2>&1 || return 0
  local rc=0
  _lp_net_subnets repo-sandbox "$1" HARVIS_REPO_SANDBOX_SUBNET || rc=1
  [ -n "${2:-}" ] && { _lp_net_subnets browser-egress "$2" HARVIS_BROWSER_SUBNET || rc=1; }
  _lp_backend_route "$1" || rc=1
  return "$rc"
}
