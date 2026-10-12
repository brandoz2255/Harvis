# The lab profile for --expose tunnel and lan+tunnel — sourced by scripts/exposure.sh.
#
#   --tunnel-networks lab-wifi,lab-wired the tunnel runs only while every network
#                                        this computer uses is on the list
#                                        (scripts/tunnel-guard.sh, a systemd
#                                        service); Linux with NetworkManager
#   --allow-emails a@x.edu,b@x.edu       only these people get through, even if the
#                                        Access policy in Cloudflare is wider
#                                        (@x.edu allows a whole domain)
#
# Either takes "off" to remove it. Without them the tunnel is the regular
# profile: Cloudflare Access decides who gets in, and an eduroam warning.
# Either can be used alone; the network lock is the lab profile.

TUNNEL_NETWORKS_ARG=""
ALLOW_EMAILS_ARG=""

valid_networks() { # names: no quotes, backslashes, $ or backticks — they end up in .env
  [[ -n "$1" && "$1" != *[\"\'\\\$\`]* && "$1" != *$'\n'* ]]
}

valid_emails() {
  local item items
  [[ "$1" != *$'\n'* ]] || return 1
  IFS=, read -ra items <<< "$1"
  [ "${#items[@]}" -gt 0 ] || return 1
  for item in "${items[@]}"; do
    item="${item// /}"
    [[ "$item" =~ ^([A-Za-z0-9._%+-]+)?@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$ ]] || return 1
  done
}

normalise_list() { # trim each comma-separated item, drop empties
  local item items out=""
  IFS=, read -ra items <<< "$1"
  for item in "${items[@]}"; do
    item="$(printf '%s' "$item" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [ -n "$item" ] && out="${out:+$out,}$item"
  done
  printf '%s' "$out"
}

# What .env will hold after this run.
tunnel_networks() {
  case "$TUNNEL_NETWORKS_ARG" in
    off) ;; "") env_value HARVIS_TUNNEL_NETWORKS ;; *) normalise_list "$TUNNEL_NETWORKS_ARG" ;;
  esac
}
allow_emails() {
  case "$ALLOW_EMAILS_ARG" in
    off) ;; "") env_value HARVIS_CF_ACCESS_ALLOWED_EMAILS ;; *) lower "$(normalise_list "${ALLOW_EMAILS_ARG// /}")" ;;
  esac
}

validate_lock_args() {
  if [ -n "$ALLOW_EMAILS_ARG" ] && [ "$ALLOW_EMAILS_ARG" != off ] && { ! valid_emails "$ALLOW_EMAILS_ARG" || [ -z "$(allow_emails)" ]; }; then
    echo "✗ --allow-emails takes emails or @domain, comma-separated (or off)"; exit 1
  fi
  [ -n "$TUNNEL_NETWORKS_ARG" ] || return 0
  if [ "$TUNNEL_NETWORKS_ARG" != off ] && { ! valid_networks "$TUNNEL_NETWORKS_ARG" || [ -z "$(tunnel_networks)" ]; }; then
    echo "✗ --tunnel-networks takes network names, comma-separated (or off)"; exit 1
  fi
  # Re-apply a recorded tunnel so the change reaches COMPOSE_PROFILES even without
  # --expose. Any other recorded mode is left alone: re-applying it would rewrite
  # its bind (an open legacy install would close).
  if [ -z "$EXPOSE_MODE" ] && { [ "$TUNNEL_NETWORKS_ARG" != off ] || is_tunnel_mode "$(current_exposure)"; }; then
    EXPOSE_MODE="$(current_exposure)"
  fi
  if [ "$TUNNEL_NETWORKS_ARG" != off ] && ! is_tunnel_mode "$EXPOSE_MODE"; then
    echo "✗ --tunnel-networks goes with --expose tunnel or lan+tunnel (it limits where the tunnel runs)"; exit 1
  fi
}

# ── Preflight rows ──────────────────────────────────────────────────────────

check_access_list() {
  local n
  n="$(allow_emails)"
  if [ -z "$n" ]; then
    add_row WARN access "anyone your Cloudflare Access policy lets in can open the Harvis sign-in"
    add_hint "Name the people Harvis accepts, even if the Access policy is wider:
      --allow-emails you@school.edu,colleague@school.edu   (or @school.edu for a whole domain)"
    return 0
  fi
  n="$(tr ',' '\n' <<< "$n" | grep -c .)"
  add_row PASS access "named people only — ${n} on HARVIS_CF_ACCESS_ALLOWED_EMAILS"
}

check_network_lock() {
  local nets verdict linger
  nets="$(tunnel_networks)"
  if [ "$(uname -s)" != Linux ] || ! command -v nmcli >/dev/null 2>&1 || ! command -v systemctl >/dev/null 2>&1; then
    add_row FAIL lock "the network lock (--tunnel-networks) needs Linux with NetworkManager and systemd"
    add_hint "Drop the lock with --tunnel-networks off (the regular profile), or run the tunnel on a Linux machine."
    return 0
  fi
  if verdict="$(HARVIS_TUNNEL_NETWORKS="$nets" bash scripts/tunnel-guard.sh check 2>&1)"; then
    add_row PASS lock "tunnel only on ${nets} — ${verdict} now"
  else
    add_row WARN lock "tunnel only on ${nets} — not here: ${verdict}"
    add_hint "Nothing to fix: the tunnel stays off and starts by itself once this computer is on ${nets}."
  fi
  wired_names_warning "$nets"
  # Kubernetes runs the guard as a system service, which needs no sign-in.
  [ "$K8S_ACTION" = up ] && return 0
  linger="$(loginctl show-user "${USER:-$(id -un)}" -p Linger --value 2>/dev/null || true)"
  if [ "$linger" != yes ]; then
    add_row WARN lock "the tunnel runs only while you are signed in to this computer"
    add_hint "To keep it up after sign-out and from boot: loginctl enable-linger ${USER:-\$USER}"
  fi
}

# A wired network is known only by the name of its saved profile, and a profile
# with no MAC or interface binding connects on any jack, a campus one included.
wired_names_warning() {
  local item items type mac
  IFS=, read -ra items <<< "$1"
  for item in "${items[@]}"; do
    item="$(trim_value "$item")"
    type="$(nmcli -g connection.type connection show "$item" 2>/dev/null)" || continue
    [ "$type" = 802-3-ethernet ] || continue
    mac="$(nmcli -g 802-3-ethernet.mac-address connection show "$item" 2>/dev/null)"
    [ -z "$mac" ] || continue
    add_row WARN lock "'${item}' is a wired profile; it would also connect on any other Ethernet jack"
    add_hint "Plug only into the ${item} network, or tie the profile to one adapter: nmcli connection modify '${item}' 802-3-ethernet.mac-address <adapter MAC>"
  done
}

trim_value() { printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

# ── .env and the guard service ──────────────────────────────────────────────

write_lock_env() { # before anything else in write_exposure_env
  case "$ALLOW_EMAILS_ARG" in
    "") ;;
    off) if [ -n "$(env_value HARVIS_CF_ACCESS_ALLOWED_EMAILS)" ]; then
           drop_env_key HARVIS_CF_ACCESS_ALLOWED_EMAILS
           echo "✓ Removed the named-people list (Cloudflare Access alone decides who gets in)"
         fi ;;
    *) set_env_value HARVIS_CF_ACCESS_ALLOWED_EMAILS "$(allow_emails)"
       echo "✓ Only the named people get through the tunnel (HARVIS_CF_ACCESS_ALLOWED_EMAILS)" ;;
  esac
  case "$TUNNEL_NETWORKS_ARG" in
    "") ;;
    off) drop_env_key HARVIS_TUNNEL_NETWORKS ;;
    *) set_env_value HARVIS_TUNNEL_NETWORKS "$(tunnel_networks)" ;;
  esac
}

lock_tunnel_profile() { # tunnel mode: who starts cloudflared
  if [ -n "$(env_value HARVIS_TUNNEL_NETWORKS)" ]; then
    # The guard starts it; compose and Docker must not. A tunnel already up
    # from the regular profile stops now if this network is not on the list,
    # not after the rebuild.
    set_tunnel_profile off
    set_env_value HARVIS_TUNNEL_RESTART no
    bash scripts/tunnel-guard.sh hold || true
  else
    drop_env_key HARVIS_TUNNEL_RESTART
    set_tunnel_profile on
    remove_tunnel_guard
  fi
}

remove_tunnel_guard() {
  bash scripts/tunnel-guard.sh installed 2>/dev/null || return 0
  # uninstall also removes the container: it was made with restart policy "no",
  # which compose would keep, so the regular profile would not survive a reboot.
  bash scripts/tunnel-guard.sh uninstall || true
  drop_env_key HARVIS_TUNNEL_RESTART
}

# After launch, tunnel mode with a network list: hand the tunnel to the guard.
start_tunnel_guard() {
  [ -n "$(env_value HARVIS_TUNNEL_NETWORKS)" ] || return 1
  if [ "${HARVIS_LAUNCHED:-0}" -ne 1 ]; then
    if bash scripts/tunnel-guard.sh installed 2>/dev/null; then
      echo "Network lock: the running guard now uses $(env_value HARVIS_TUNNEL_NETWORKS)."
    else
      echo "Network lock: start it once the stack is up:  scripts/tunnel-guard.sh install"
    fi
    return 0
  fi
  bash scripts/tunnel-guard.sh install || return 0
  local verdict i
  if verdict="$(bash scripts/tunnel-guard.sh check 2>&1)"; then
    for i in $(seq 1 15); do
      [ "$(bash scripts/tunnel-guard.sh status 2>/dev/null | sed -n 's/^tunnel: *//p')" = running ] && break
      sleep 1
    done
  else
    echo "Tunnel: off for now — ${verdict}."
    echo "  It starts by itself on $(env_value HARVIS_TUNNEL_NETWORKS). Check with: scripts/tunnel-guard.sh status"
  fi
  return 0
}
