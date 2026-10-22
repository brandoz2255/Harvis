# Cloudflare Tunnel parts of scripts/exposure.sh (tunnel and lan+tunnel) —
# sourced by it: preflight rows, the three values asked for, and the report
# after launch. Kubernetes reports its own tunnel (scripts/k8s/harvis-k8s.sh).

is_tunnel_mode() { case "$1" in tunnel|lan+tunnel) return 0 ;; esac; return 1; }

# --public-access access|harvis: who checks people arriving through the tunnel.
# access (default): Cloudflare Access, then Harvis re-checks its token.
# harvis: no Cloudflare login; Harvis sign-in, and new accounts wait for the
# admin's approval (python_back_end/plugins/people/approval.py).
PUBLIC_ACCESS="${PUBLIC_ACCESS:-}"

tunnel_auth_choice() {
  local v="${PUBLIC_ACCESS:-$(env_value HARVIS_TUNNEL_AUTH)}"
  v="$(lower "$v")"
  [ "$v" = harvis ] && { printf harvis; return 0; }
  printf access
}

validate_public_access() {
  [ -n "$PUBLIC_ACCESS" ] || return 0
  PUBLIC_ACCESS="$(lower "$PUBLIC_ACCESS")"
  case "$PUBLIC_ACCESS" in
    access|harvis) : ;;
    *) echo "✗ --public-access takes access or harvis (got '$PUBLIC_ACCESS')"; exit 1 ;;
  esac
  if ! is_tunnel_mode "${EXPOSE_MODE:-$(current_exposure)}"; then
    echo "✗ --public-access is about the tunnel; add --expose tunnel or --expose lan+tunnel"
    exit 1
  fi
}

check_public_access() { # preflight rows for HARVIS_TUNNEL_AUTH=harvis
  [ "$(tunnel_auth_choice)" = harvis ] || { check_access_list; return 0; }
  add_row PASS access "Harvis sign-in — new people wait until you approve them (Settings → People)"
  if [ "$(lower "$(env_value HARVIS_SIGNUP_APPROVAL)")" = false ]; then
    add_row FAIL access "HARVIS_SIGNUP_APPROVAL=false would let anyone on the internet straight in"
    add_hint "Remove HARVIS_SIGNUP_APPROVAL from .env; --public-access harvis turns approval on."
  fi
  if [ "$(lower "$(env_value HARVIS_BUILD_SPACE_ACCESS)")" = everyone ]; then
    add_row FAIL access "HARVIS_BUILD_SPACE_ACCESS=everyone would let approved visitors run code on this computer"
    add_hint "Remove HARVIS_BUILD_SPACE_ACCESS from .env (Build Space stays admin-only)."
  fi
  if [ "$K8S_ACTION" = "up" ] && [ "${HARVIS_K8S_BUILD_SPACE-$(env_value HARVIS_K8S_BUILD_SPACE)}" = "1" ]; then
    add_row FAIL access "HARVIS_K8S_BUILD_SPACE=1 gives the internet-facing backend this computer's Docker"
    add_hint "Remove HARVIS_K8S_BUILD_SPACE from .env for --public-access harvis."
  fi
}

# .env for the chosen check; runs after write_exposure_env's per-mode lines.
write_public_access_env() {
  if [ "$(tunnel_auth_choice)" = harvis ]; then
    set_env_value HARVIS_TUNNEL_AUTH harvis
    set_env_value HARVIS_SIGNUP_APPROVAL true
    drop_env_key HARVIS_CF_ACCESS_TEAM_DOMAIN
    drop_env_key HARVIS_CF_ACCESS_AUD
    # Sign-up open, into the waiting room. The marker lets a later mode close it again.
    if [ "$(lower "$(env_value HARVIS_OWUI_ENABLE_SIGNUP)")" != true ]; then
      set_env_value HARVIS_OWUI_ENABLE_SIGNUP true
      set_env_value HARVIS_SIGNUP_OPENED_FOR_APPROVAL 1
    fi
    drop_env_key HARVIS_SIGNUP_CLOSED_BY_EXPOSE
    echo "✓ Public access: Harvis sign-in; new people wait for you in Settings → People"
  else
    drop_env_key HARVIS_TUNNEL_AUTH
    set_env_value HARVIS_CF_ACCESS_TEAM_DOMAIN "$EXPOSE_TEAM"
    set_env_value HARVIS_CF_ACCESS_AUD "$EXPOSE_AUD"
    forget_public_access_signup
  fi
}

# Undo what write_public_access_env opened, leaving the operator's own choices.
forget_public_access_signup() {
  if [ -n "$(env_value HARVIS_SIGNUP_OPENED_FOR_APPROVAL)" ]; then
    drop_env_key HARVIS_OWUI_ENABLE_SIGNUP
    drop_env_key HARVIS_SIGNUP_OPENED_FOR_APPROVAL
    drop_env_key HARVIS_SIGNUP_APPROVAL
    close_signup
  fi
}

# ── Preflight rows ──────────────────────────────────────────────────────────

check_eduroam() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local active
  active="$(nmcli -t -f NAME connection show --active 2>/dev/null || true)"
  if grep -qi '^eduroam' <<< "$active"; then
    add_row WARN wifi "eduroam is connected — the tunnel would leave through it"
    add_hint "Disconnect eduroam and use the lab network (wired, or the lab's own Wi-Fi) before
  starting the tunnel, so Harvis traffic does not cross the campus network."
  fi
}

check_tunnel_reach() {
  # cloudflared dials Cloudflare on port 7844. A network that blocks it leaves
  # the tunnel down with no hint in the browser beyond Cloudflare's error page.
  if command -v timeout >/dev/null 2>&1 &&
     timeout 5 bash -c 'exec 3<>/dev/tcp/region1.v2.argotunnel.com/7844' 2>/dev/null; then
    add_row PASS tunnel "Cloudflare reachable on port 7844"
  else
    add_row WARN tunnel "could not reach Cloudflare on port 7844"
    add_hint "This network may block the tunnel. cloudflared needs outbound port 7844
  (UDP, falling back to TCP). Try the wired lab network, or ask whoever runs it."
  fi
}

# ── Tunnel settings (asked after preflight, before anything is written) ─────

valid_token() { [[ "$1" =~ ^[A-Za-z0-9+/=_-]{40,}$ ]]; }
valid_team() { [[ "$1" =~ ^[a-z0-9-]+(\.[a-z0-9-]+)+$ ]]; }
valid_aud() { [[ "$1" =~ ^[A-Za-z0-9]{16,}$ ]]; }

clean_team() { # accept a pasted URL: https://team.cloudflareaccess.com/...
  local t
  t="$(lower "$1")"
  t="${t#https://}"; t="${t#http://}"
  printf '%s' "${t%%/*}"
}

tunnel_inputs_known() {
  if [ "$(tunnel_auth_choice)" = harvis ]; then
    [ -n "${EXPOSE_TOKEN:-${HARVIS_TUNNEL_TOKEN:-$(env_value HARVIS_TUNNEL_TOKEN)}}" ]
    return
  fi
  [ -n "$EXPOSE_TOKEN" ] && [ -n "$EXPOSE_TEAM" ] && [ -n "$EXPOSE_AUD" ] && return 0
  [ -n "${HARVIS_TUNNEL_TOKEN:-$(env_value HARVIS_TUNNEL_TOKEN)}" ] &&
  [ -n "${HARVIS_CF_ACCESS_TEAM_DOMAIN:-$(env_value HARVIS_CF_ACCESS_TEAM_DOMAIN)}" ] &&
  [ -n "${HARVIS_CF_ACCESS_AUD:-$(env_value HARVIS_CF_ACCESS_AUD)}" ]
}

collect_exposure_inputs() {
  is_tunnel_mode "$EXPOSE_MODE" || return 0
  if [ "$(tunnel_auth_choice)" = harvis ]; then
    # No Cloudflare Access app: the tunnel token is the only value.
    [ -n "$EXPOSE_TOKEN" ] || EXPOSE_TOKEN="${HARVIS_TUNNEL_TOKEN:-$(env_value HARVIS_TUNNEL_TOKEN)}"
    if [ -z "$EXPOSE_TOKEN" ]; then
      if [ "$ASSUME_YES" -eq 1 ]; then
        echo "✗ --public-access harvis with --yes needs HARVIS_TUNNEL_TOKEN in the environment or .env"
        echo "  (Zero Trust → Networks → Tunnels → your tunnel). Nothing was changed."
        exit 1
      fi
      echo ""
      echo "Cloudflare Tunnel setup — the token from Zero Trust → Networks → Tunnels."
      read -rsp "  Tunnel token (input hidden): " EXPOSE_TOKEN || true; echo ""
      EXPOSE_TOKEN="$(printf '%s' "$EXPOSE_TOKEN" | tr -d '[:space:]')"
    fi
    valid_token "$EXPOSE_TOKEN" || { echo "✗ That tunnel token does not look right (it is a long base64 string). Nothing was changed."; exit 1; }
    return 0
  fi
  # Already asked (--k8s-off asks before tearing Kubernetes down).
  [ -n "$EXPOSE_TOKEN" ] && [ -n "$EXPOSE_TEAM" ] && [ -n "$EXPOSE_AUD" ] && return 0
  # Explicit environment wins, then .env, then a prompt.
  EXPOSE_TOKEN="${HARVIS_TUNNEL_TOKEN:-$(env_value HARVIS_TUNNEL_TOKEN)}"
  EXPOSE_TEAM="$(clean_team "${HARVIS_CF_ACCESS_TEAM_DOMAIN:-$(env_value HARVIS_CF_ACCESS_TEAM_DOMAIN)}")"
  EXPOSE_AUD="${HARVIS_CF_ACCESS_AUD:-$(env_value HARVIS_CF_ACCESS_AUD)}"
  if [ -z "$EXPOSE_TOKEN" ] || [ -z "$EXPOSE_TEAM" ] || [ -z "$EXPOSE_AUD" ]; then
    if [ "$ASSUME_YES" -eq 1 ]; then
      echo "✗ --expose ${EXPOSE_MODE} with --yes needs three values, from the environment or .env:"
      echo "    HARVIS_TUNNEL_TOKEN           Zero Trust → Networks → Tunnels → your tunnel"
      echo "    HARVIS_CF_ACCESS_TEAM_DOMAIN  <team>.cloudflareaccess.com"
      echo "    HARVIS_CF_ACCESS_AUD          Access → Applications → your app → AUD tag"
      echo "  Nothing was changed."
      exit 1
    fi
    echo ""
    echo "Cloudflare Tunnel setup — values from the Cloudflare Zero Trust dashboard."
  fi
  if [ -z "$EXPOSE_TOKEN" ]; then
    read -rsp "  Tunnel token (input hidden): " EXPOSE_TOKEN || true; echo ""
    EXPOSE_TOKEN="$(printf '%s' "$EXPOSE_TOKEN" | tr -d '[:space:]')"
  fi
  if [ -z "$EXPOSE_TEAM" ]; then
    read -rp "  Access team domain (<team>.cloudflareaccess.com): " EXPOSE_TEAM || true
    EXPOSE_TEAM="$(clean_team "$(printf '%s' "$EXPOSE_TEAM" | tr -d '[:space:]')")"
  fi
  if [ -z "$EXPOSE_AUD" ]; then
    read -rp "  Access application AUD tag: " EXPOSE_AUD || true
    EXPOSE_AUD="$(printf '%s' "$EXPOSE_AUD" | tr -d '[:space:]')"
  fi
  # Checked before writing: a stray newline or quote here would corrupt .env.
  valid_token "$EXPOSE_TOKEN" || { echo "✗ That tunnel token does not look right (it is a long base64 string). Nothing was changed."; exit 1; }
  valid_team "$EXPOSE_TEAM" || { echo "✗ The team domain should look like myteam.cloudflareaccess.com. Nothing was changed."; exit 1; }
  valid_aud "$EXPOSE_AUD" || { echo "✗ The AUD tag should be letters and digits only. Nothing was changed."; exit 1; }
  case "$EXPOSE_TEAM" in
    *.cloudflareaccess.com) : ;;
    *) echo "⚠ Team domains normally end in .cloudflareaccess.com; using '${EXPOSE_TEAM}' as given." ;;
  esac
}

# ── After launch ────────────────────────────────────────────────────────────

report_exposure() {
  is_tunnel_mode "$(current_exposure)" || return 0
  echo ""
  local name="${HARVIS_CONTAINER_PREFIX:-$(env_value HARVIS_CONTAINER_PREFIX)}harvis-cloudflared" i logs connected=0 locked=0
  start_tunnel_guard && locked=1
  if [ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" != "true" ]; then
    [ "$locked" -eq 1 ] || echo "Tunnel: not running yet. It starts with the stack (docker compose up -d)."
  else
    for i in $(seq 1 15); do
      # Captured first: `docker logs | grep -q` under pipefail loses the match
      # when grep exits early and docker dies of SIGPIPE.
      logs="$(docker logs --tail 50 "$name" 2>&1 || true)"
      if [[ "$logs" == *'Registered tunnel connection'* ]]; then
        connected=1; break
      fi
      sleep 2
    done
    if [ "$connected" -eq 1 ]; then
      echo "✓ Tunnel connected to Cloudflare"
    else
      echo "⚠ Tunnel not connected yet — see: docker logs ${name}"
    fi
  fi
  echo "  In Cloudflare, the public hostname must point to  http://nginx:8081"
  if [ "$(tunnel_auth_choice)" = harvis ]; then
    echo "  and needs no Access application: visitors get the Harvis sign-in page,"
    echo "  and new accounts wait until you approve them in Settings → People."
    return 0
  fi
  echo "  and have an Access application in front of it. Without Access, every"
  echo "  request gets 403 — that is the safe default, not a fault."
}
