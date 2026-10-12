# Who can reach this Harvis — sourced by install.sh for --expose local|lan|tunnel|lan+tunnel.
#
#   local   only this computer (port 9000 on 127.0.0.1)
#   lan     anyone on the same network; the first sign-up becomes admin and
#           after that self-serve sign-up is closed (open it in Settings while
#           people register)
#   tunnel  from the internet through a Cloudflare Tunnel, behind Cloudflare
#           Access; port 9000 stays on 127.0.0.1 and nothing is opened on the
#           router
#   lan+tunnel  both: lan rules on your network, plus the tunnel. The one that
#           works with --k8s, where Kubernetes always publishes to the network
#
# With no --expose the installer picks for the host (choose_default_exposure):
# a first install is local, --k8s is lan unless lan+tunnel is recorded (Kubernetes
# puts Harvis on the network, so sign-up closes once the admin exists), and an install whose
# port 9000 is open to the network right now keeps it open rather than going
# dark on an upgrade.
# The backend reads HARVIS_EXPOSURE and applies the matching rules
# (python_back_end/plugins/exposure).
#
# Relies on install.sh's add_row, add_hint, rand_hex, drop_env_key,
# ensure_env_secret and its ASSUME_YES / K8S_ACTION globals.

EXPOSE_MODE=""
# Filled by collect_exposure_inputs for tunnel mode, written by write_exposure_env.
EXPOSE_TOKEN=""
EXPOSE_TEAM=""
EXPOSE_AUD=""
# Set by choose_default_exposure.
EXPOSE_DEFAULTED=0
PIN_LEGACY_PUBLIC=0

# The lab profile: --tunnel-networks and --allow-emails.
. scripts/exposure-lock.sh
# Preflight, inputs and report for the two tunnel modes.
. scripts/exposure-tunnel.sh

env_value() { # $1 = key — value from .env, empty if absent. Never printed.
  [ -f .env ] || return 0
  grep "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/" || true
}

set_env_value() { # $1 = key, $2 = value
  # Compared in bash, not with `grep -x "$1=$2"`: that would put the value (the
  # tunnel token) on a command line other users can read. A key set more than
  # once is rewritten, because compose uses the last line and we must not guess.
  local count raw
  count="$(grep -c "^$1=" .env || true)"
  raw="$(grep "^$1=" .env | tail -1 | cut -d= -f2- || true)"
  if [ "$count" != 1 ] || [ "$raw" != "$2" ]; then
    drop_env_key "$1"
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; } # macOS ships bash 3.2: no ${v,,}

current_exposure() {
  local m="${EXPOSE_MODE:-$(lower "$(env_value HARVIS_EXPOSURE)")}"
  printf '%s' "${m:-local}"
}

validate_expose_arg() {
  validate_lock_args
  [ -z "$EXPOSE_MODE" ] && return 0
  case "$EXPOSE_MODE" in
    local|lan|tunnel|lan+tunnel) : ;;
    *) echo "✗ --expose takes local, lan, tunnel or lan+tunnel (got '$EXPOSE_MODE')"; exit 1 ;;
  esac
  case "$EXPOSE_MODE" in
    tunnel|lan+tunnel)
      echo "! --expose $EXPOSE_MODE is experimental: the internet entrance through a Cloudflare"
      echo "  Tunnel has been tested against a stand-in, never against a real Cloudflare account."
      echo "  For a server people use today, choose lan." ;;
  esac
  if [ "$K8S_ACTION" = "up" ]; then
    case "$EXPOSE_MODE" in
      tunnel)
        # tunnel keeps port 9000 on 127.0.0.1, which Kubernetes never publishes.
        echo "✗ --expose tunnel does not work with --k8s: Kubernetes always puts Harvis on"
        echo "  your network. For your network plus the internet use --k8s --expose lan+tunnel."
        exit 1 ;;
      local)
        # Kubernetes publishes port 9000 only when it is bound to every address.
        echo "✗ --expose local does not work with --k8s: Kubernetes would publish nothing,"
        echo "  not even on this computer. Use --k8s --expose lan, or plain Docker for local."
        exit 1 ;;
    esac
  fi
}

# Is this stack's running nginx publishing port 9000 to the network? Only then does an
# upgrade keep it open: an install that predates the choice must not go dark
# under its users. A database volume or a copied .env says nothing about who
# can reach the box (a worktree or a re-clone shares the volume), so they don't
# count.
nginx_published_openly() {
  local stack ids binds
  stack="${HARVIS_STACK_NAME:-$(env_value HARVIS_STACK_NAME)}"
  ids="$(docker ps -q --filter "label=com.docker.compose.project=${stack:-harvis}" \
    --filter label=com.docker.compose.service=nginx 2>/dev/null)" || return 1
  [ -n "$ids" ] || return 1
  # shellcheck disable=SC2086  # one id per word
  binds="$(docker inspect -f '{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}[{{.HostIp}}] {{end}}{{end}}' $ids 2>/dev/null)" || return 1
  case " $(printf '%s' "$binds" | tr '\n' ' ') " in
    *"[]"*|*"[0.0.0.0]"*|*"[::]"*) return 0 ;;
  esac
  return 1
}

choose_default_exposure() {
  [ -z "$EXPOSE_MODE" ] || return 0
  local cur
  cur="$(lower "$(env_value HARVIS_EXPOSURE)")"
  if [ "$K8S_ACTION" = "up" ]; then
    # Kubernetes means lan, or lan+tunnel when that is recorded. A recorded
    # tunnel is left for check_exposure to refuse; anything else is (re)applied
    # so the bind and sign-up rules match what Kubernetes is about to publish.
    case "$cur" in tunnel|lan+tunnel) return 0 ;; esac
    EXPOSE_MODE=lan
    [ "$cur" = lan ] || EXPOSE_DEFAULTED=1
  elif [ "$cur" = lan ] && [ "$(env_value HARVIS_BIND_ADDR_PUBLIC)" != "0.0.0.0" ]; then
    # lan recorded but port 9000 would now come up on 127.0.0.1 (the compose
    # default changed): re-apply lan rather than silently going dark.
    EXPOSE_MODE=lan
  elif [ -n "$cur" ] || [ -n "$(env_value HARVIS_BIND_ADDR_PUBLIC)" ]; then
    return 0
  elif [ "${LEFT_K8S:-0}" -eq 1 ] || nginx_published_openly; then
    # Leaving Kubernetes: it published port 9000 to the network, and its nginx is
    # gone by now, so the running-container check cannot see that.
    PIN_LEGACY_PUBLIC=1
  else
    EXPOSE_MODE=local; EXPOSE_DEFAULTED=1
  fi
}

# ── Preflight rows (change nothing) ─────────────────────────────────────────

# A docker network whose subnet holds the default gateway hides the router from
# this machine. It happened here: a bridge took 192.168.0.1, the router's
# address, and the router's admin page vanished.
ip_to_int() {
  local IFS=. a b c d
  read -r a b c d <<< "$1"
  echo $(( (a << 24) + (b << 16) + (c << 8) + d ))
}

# True when two IPv4 CIDRs share any address.
cidr_overlap() {
  local bits mask
  bits=$(( ${1#*/} < ${2#*/} ? ${1#*/} : ${2#*/} ))
  mask=$(( bits == 0 ? 0 : (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF ))
  [ $(( $(ip_to_int "${1%/*}") & mask )) -eq $(( $(ip_to_int "${2%/*}") & mask )) ]
}

# tunnel-edge (docker-compose.yaml) gets a fixed /29 so Docker never hands it a
# range of its own choosing. Picked once per install, not hard-coded: a second
# stack on this machine would otherwise ask for the same /29 and fail to start.
choose_tunnel_subnet() { # $1 = compose project name
  local cand="" taken i net
  if [ -n "${HARVIS_TUNNEL_SUBNET:-}" ]; then
    set_env_value HARVIS_TUNNEL_SUBNET "$HARVIS_TUNNEL_SUBNET"; return 0
  fi
  [ -n "$(env_value HARVIS_TUNNEL_SUBNET)" ] && return 0
  # Already created: keep its range, or compose refuses the changed network.
  cand="$(docker network inspect "$1_tunnel-edge" \
            --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null || true)"
  if [ -z "$cand" ]; then
    # Every other Docker network, plus real host routes (LAN, VPN). Bridge
    # routes are the Docker networks again.
    taken="$(docker network inspect $(docker network ls -q 2>/dev/null) \
               --format '{{range .IPAM.Config}}{{.Subnet}}{{"\n"}}{{end}}' 2>/dev/null || true)
$(ip -4 route show 2>/dev/null | awk '$1 ~ /\// && $3 !~ /^(br-|docker)/ {print $1}' || true)"
    for i in $(seq 0 31); do
      cand="10.213.82.$(( i * 8 ))/29"
      while read -r net; do
        case "$net" in */*) : ;; *) continue ;; esac
        case "$net" in *:*) continue ;; esac
        if cidr_overlap "$cand" "$net"; then cand=""; break; fi
      done <<< "$taken"
      [ -n "$cand" ] && break
    done
  fi
  if [ -z "$cand" ]; then
    echo "⚠ No free /29 in 10.213.82.0/24 for the tunnel network; set HARVIS_TUNNEL_SUBNET in .env"
    return 0
  fi
  set_env_value HARVIS_TUNNEL_SUBNET "$cand"
}

check_gateway_overlap() {
  command -v ip >/dev/null 2>&1 || return 0
  local gw subnet net bits gwi neti mask
  # The address after "via"; a VPN or PPP default route ("default dev wg0") has none.
  gw="$(ip -4 route show default 2>/dev/null |
        awk '{for (i = 1; i < NF; i++) if ($i == "via") { print $(i + 1); exit }}')"
  [[ "$gw" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 0
  gwi="$(ip_to_int "$gw")"
  while read -r subnet; do
    case "$subnet" in */*) : ;; *) continue ;; esac
    net="${subnet%/*}"; bits="${subnet#*/}"
    case "$net" in *:*) continue ;; esac
    neti="$(ip_to_int "$net")"
    mask=$(( bits == 0 ? 0 : (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF ))
    if [ $(( gwi & mask )) -eq $(( neti & mask )) ]; then
      add_row WARN network "a Docker network uses ${subnet}, which holds your router (${gw})"
      add_hint "Your router at ${gw} is unreachable while that Docker network exists. Find it with
      docker network inspect \$(docker network ls -q) --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}}'
  and remove it (or set \"default-address-pools\" in /etc/docker/daemon.json)."
      return 0
    fi
  done < <(docker network inspect $(docker network ls -q 2>/dev/null) \
             --format '{{range .IPAM.Config}}{{.Subnet}}{{"\n"}}{{end}}' 2>/dev/null)
}

# The backend refuses to start a shared server on a guessable signing secret
# (plugins/exposure/mode.py: under 32 characters or a known placeholder).
weak_jwt_secret() {
  local v="${1// /}"
  case "$(lower "$v")" in
    ""|key|secret|changeme|change-me|your-secret-key|your_jwt_secret|jwt_secret) return 0 ;;
  esac
  [ "${#v}" -lt 32 ]
}

check_shared_secret() {
  if [ -n "${JWT_SECRET:-}" ]; then
    if weak_jwt_secret "$JWT_SECRET"; then
      add_row FAIL secret "JWT_SECRET in your shell is too weak to share Harvis"
      add_hint "Unset JWT_SECRET in your shell (Harvis keeps a strong one in .env), then run again."
    fi
  elif [ -f .env ] && grep -q '^JWT_SECRET=' .env && weak_jwt_secret "$(env_value JWT_SECRET)"; then
    if [ -n "$EXPOSE_MODE" ]; then
      add_row WARN secret "JWT_SECRET in .env is too weak to share; it will be replaced (everyone signs in again)"
    else
      add_row WARN secret "JWT_SECRET in .env is too weak to share; the backend will refuse to start"
      add_hint "Run ./install.sh --expose $1 to replace it with a strong one (everyone signs in again)."
    fi
  fi
}

check_exposure() {
  local mode bind
  mode="$(current_exposure)"
  bind="$(env_value HARVIS_BIND_ADDR_PUBLIC)"
  [ "$mode" = local ] || check_shared_secret "$mode"
  if [ "$(env_value HARVIS_BIND_ADDR)" = "0.0.0.0" ]; then
    if [ "$mode" = lan ]; then
      add_row WARN exposure "HARVIS_BIND_ADDR=0.0.0.0 opens the backend (8000), notebook and TTS ports with no sign-in"
      add_hint "Remove HARVIS_BIND_ADDR from .env (it defaults to 127.0.0.1) so only port 9000 leaves this machine."
    elif [ -n "$EXPOSE_MODE" ]; then
      add_row WARN exposure "HARVIS_BIND_ADDR=0.0.0.0 opens the backend (8000), notebook and TTS ports; it will be removed"
    else
      add_row WARN exposure "HARVIS_BIND_ADDR=0.0.0.0 opens the backend (8000), notebook and TTS ports with no sign-in"
      add_hint "Remove HARVIS_BIND_ADDR from .env, or run ./install.sh --expose local to do it for you."
    fi
  fi
  if [ "$K8S_ACTION" = "up" ] && [ "$mode" = tunnel ]; then
    add_row FAIL exposure ".env says HARVIS_EXPOSURE=tunnel, which keeps Harvis off the network; --k8s cannot"
    add_hint "Run ./install.sh --k8s --expose lan+tunnel (your network plus the tunnel), or --expose lan."
  fi
  if is_tunnel_mode "$EXPOSE_MODE" && [ "${ASSUME_YES:-0}" -eq 1 ] && ! tunnel_inputs_known; then
    add_row FAIL tunnel "--yes needs HARVIS_TUNNEL_TOKEN, HARVIS_CF_ACCESS_TEAM_DOMAIN and HARVIS_CF_ACCESS_AUD"
  fi
  case "$mode" in
    local)
      if [ -z "$EXPOSE_MODE" ] && { [ "$bind" = "0.0.0.0" ] || [ "$PIN_LEGACY_PUBLIC" -eq 1 ]; }; then
        add_row WARN exposure "port 9000 is open to your network and the first sign-up becomes admin"
        add_hint "Choose who can reach Harvis:
      ./install.sh --expose local    this computer only
      ./install.sh --expose lan      your network, sign-up closed once you are admin"
      else
        add_row PASS exposure "local — this computer only"
      fi ;;
    lan) add_row PASS exposure "lan — your network; sign-up closed once the admin exists" ;;
    tunnel|lan+tunnel)
      if [ "$mode" = tunnel ]; then
        [ "$K8S_ACTION" = "up" ] && return 0
        add_row PASS exposure "tunnel — internet through Cloudflare Access"
      else
        add_row PASS exposure "lan+tunnel — your network, plus the internet through Cloudflare Access"
      fi
      check_access_list
      if [ -n "$(tunnel_networks)" ]; then check_network_lock; else check_eduroam; fi
      check_tunnel_reach ;;
    *) add_row WARN exposure "HARVIS_EXPOSURE='${mode}' is not local, lan, tunnel or lan+tunnel; Harvis treats it as lan" ;;
  esac
  # close_signup keeps an operator's explicit choice, so say out loud what it means here.
  if [ "$mode" != local ] && [ "$(lower "$(env_value HARVIS_OWUI_ENABLE_SIGNUP)")" = true ]; then
    add_row WARN signup ".env keeps sign-up open: anyone who reaches port 9000 can make an account"
    add_hint "Remove HARVIS_OWUI_ENABLE_SIGNUP from .env, and check Settings → General, which can open it too."
  fi
  check_gateway_overlap
}

# ── .env ────────────────────────────────────────────────────────────────────

set_tunnel_profile() { # $1 = on|off — edit the comma list in COMPOSE_PROFILES
  local cur out="" p
  cur="$(env_value COMPOSE_PROFILES)"
  local IFS=,
  for p in $cur; do
    p="${p// /}"
    [ -z "$p" ] || [ "$p" = "tunnel" ] && continue
    out="${out:+$out,}$p"
  done
  unset IFS
  [ "$1" = "on" ] && out="${out:+$out,}tunnel"
  if [ "$out" = "$cur" ]; then return 0; fi
  if [ -z "$out" ]; then drop_env_key COMPOSE_PROFILES; else set_env_value COMPOSE_PROFILES "$out"; fi
}

close_signup() {
  # Only when unset: an operator who chose open sign-up keeps it. The marker
  # says the installer closed it, so going back to local can open it again.
  if [ -z "$(env_value HARVIS_OWUI_ENABLE_SIGNUP)" ]; then
    set_env_value HARVIS_OWUI_ENABLE_SIGNUP false
    set_env_value HARVIS_SIGNUP_CLOSED_BY_EXPOSE 1
    echo "✓ Closed self-serve sign-up (open it in Settings → General while people register)"
  fi
}

reopen_signup() {
  if [ -n "$(env_value HARVIS_SIGNUP_CLOSED_BY_EXPOSE)" ]; then
    drop_env_key HARVIS_OWUI_ENABLE_SIGNUP
    drop_env_key HARVIS_SIGNUP_CLOSED_BY_EXPOSE
    echo "✓ Reopened self-serve sign-up (closed when Harvis was shared)"
  fi
}

write_exposure_env() {
  write_lock_env
  if [ "$PIN_LEGACY_PUBLIC" -eq 1 ]; then
    # Compose now defaults port 9000 to 127.0.0.1; this install was reachable
    # from the network before, so keep it that way until its owner chooses.
    set_env_value HARVIS_BIND_ADDR_PUBLIC 0.0.0.0
    echo "• Kept port 9000 open to your network, as before. Close it with ./install.sh --expose local"
    return 0
  fi
  [ -n "$EXPOSE_MODE" ] || return 0
  local was
  if [ "$EXPOSE_DEFAULTED" -eq 1 ]; then
    case "$EXPOSE_MODE" in
      local) echo "✓ Harvis is reachable from this computer only. Share it with ./install.sh --expose lan" ;;
      lan)   echo "✓ Kubernetes puts Harvis on your network, so it uses the lan rules: the first sign-up becomes admin, then sign-up closes" ;;
    esac
  fi
  # Opening the side ports is never part of local or tunnel; lan keeps the warning.
  if [ "$EXPOSE_MODE" != lan ] && [ "$(env_value HARVIS_BIND_ADDR)" = "0.0.0.0" ]; then
    drop_env_key HARVIS_BIND_ADDR
    echo "✓ Removed HARVIS_BIND_ADDR=0.0.0.0 (backend, notebook and TTS ports back on 127.0.0.1)"
  fi
  was="$(lower "$(env_value HARVIS_EXPOSURE)")"
  set_env_value HARVIS_EXPOSURE "$EXPOSE_MODE"
  if [ "$EXPOSE_MODE" != local ] && [ -z "${JWT_SECRET:-}" ] && weak_jwt_secret "$(env_value JWT_SECRET)"; then
    set_env_value JWT_SECRET "$(rand_hex 32)"
    echo "✓ Replaced a weak JWT_SECRET (everyone signs in again)"
  fi
  case "$EXPOSE_MODE" in
    local)
      set_env_value HARVIS_BIND_ADDR_PUBLIC 127.0.0.1
      reopen_signup
      set_tunnel_profile off ;;
    lan)
      set_env_value HARVIS_BIND_ADDR_PUBLIC 0.0.0.0
      close_signup
      set_tunnel_profile off ;;
    tunnel)
      set_env_value HARVIS_BIND_ADDR_PUBLIC 127.0.0.1
      close_signup
      # Visitors arrive over HTTPS, so the sign-in cookie can insist on it.
      set_env_value HARVIS_COOKIE_SECURE true
      set_env_value HARVIS_TUNNEL_TOKEN "$EXPOSE_TOKEN"
      set_env_value HARVIS_CF_ACCESS_TEAM_DOMAIN "$EXPOSE_TEAM"
      set_env_value HARVIS_CF_ACCESS_AUD "$EXPOSE_AUD"
      lock_tunnel_profile ;;
    lan+tunnel)
      set_env_value HARVIS_BIND_ADDR_PUBLIC 0.0.0.0
      close_signup
      # Plain http on the LAN; nginx marks the cookie Secure on the tunnel entrance.
      drop_env_key HARVIS_COOKIE_SECURE
      set_env_value HARVIS_TUNNEL_TOKEN "$EXPOSE_TOKEN"
      set_env_value HARVIS_CF_ACCESS_TEAM_DOMAIN "$EXPOSE_TEAM"
      set_env_value HARVIS_CF_ACCESS_AUD "$EXPOSE_AUD"
      lock_tunnel_profile ;;
  esac
  # Leaving tunnel mode: the secure-only cookie would break sign-in over plain
  # http://<lan-ip>:9000, and the tunnel should close now, not at the next start.
  if is_tunnel_mode "$was" && ! is_tunnel_mode "$EXPOSE_MODE"; then
    drop_env_key HARVIS_COOKIE_SECURE
    remove_tunnel_guard
    if [ "$(cat /var/lib/harvis/k8s/mode 2>/dev/null)" = k8s ]; then
      # Now, not at the end of the Kubernetes run: that may build for minutes, or stop early.
      local ns="${HARVIS_K8S_NAMESPACE:-harvis}" sudo=""
      [ "$(id -u)" -eq 0 ] || sudo="sudo"
      if $sudo k3s kubectl --request-timeout=20s -n "$ns" delete deploy -l app.kubernetes.io/name=cloudflared \
          --ignore-not-found >/dev/null 2>&1; then
        $sudo k3s kubectl --request-timeout=20s -n "$ns" delete pod -l app.kubernetes.io/name=cloudflared \
          --grace-period=0 --force --ignore-not-found >/dev/null 2>&1
        echo "✓ Stopped the Cloudflare Tunnel"
      else
        echo "⚠ Could not stop the Cloudflare Tunnel; stop it with: sudo k3s kubectl -n ${ns} delete deploy cloudflared"
      fi
    elif docker compose --profile tunnel rm -sf cloudflared >/dev/null 2>&1; then
      echo "✓ Stopped the Cloudflare Tunnel"
    else
      echo "⚠ Could not stop the Cloudflare Tunnel; stop it with: docker compose --profile tunnel rm -sf cloudflared"
    fi
  fi
  echo "✓ Exposure set to ${EXPOSE_MODE}"
}

