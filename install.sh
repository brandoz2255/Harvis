#!/usr/bin/env bash
# Harvis installer — preflight the host, find a model server, write generated
# secrets into .env, create the docker network, and bring the stack up.
#
# There is no backend question any more. Harvis ships the workspace (UI, API,
# routing, auth, ONNX speech, embeddings) and you plug in the intelligence: the
# stack itself needs no GPU, so nvidia/amd/cpu stopped being a thing to choose.
# Whatever OpenAI-compatible server you already run is what it talks to, and if
# none is running it still comes up and says so.
#
#   ./install.sh                        # detect a local model server, install
#   ./install.sh --yes                  # non-interactive
#   ./install.sh --check-only           # preflight only: changes NOTHING
#   ./install.sh --no-launch            # configure but don't start the stack
#   ./install.sh --llm-url URL          # skip detection, use this server
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ASSUME_YES=0
CHECK_ONLY=0
NO_LAUNCH=0
# Where inference happens. "auto" probes the host for a running server; "manual"
# means --llm-url settled it and detection is skipped entirely.
LLM_MODE="auto"
LLM_ENDPOINT=""
LLM_PROVIDER=""
COMPOSE_FILE=""
COMPOSE_ARGS=()
HAS_OVERRIDE=0
MERGED_JSON=""
CHECK_FAILED=0
CHECK_ROWS=()

# Servers we know how to recognise, probed in this order. Each entry is
# port|name|path — the path is what distinguishes "something is listening on
# 1234" from "LM Studio is listening on 1234".
KNOWN_PROVIDERS=(
  "11434|Ollama|/api/tags"
  "1234|LM Studio|/v1/models"
  "8080|llama.cpp|/v1/models"
  "8000|vLLM|/v1/models"
)

HEALTH_URL="http://localhost:9000/api/health/services"
SETUP_URL="http://localhost:9000/api/setup/status"

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes|-y) ASSUME_YES=1; shift ;;
      --check-only) CHECK_ONLY=1; shift ;;
      --no-launch) NO_LAUNCH=1; shift ;;
      --llm-url|--ollama-url) LLM_ENDPOINT="${2:-}"; LLM_MODE="manual"; shift 2 ;;
      --llm-url=*|--ollama-url=*) LLM_ENDPOINT="${1#*=}"; LLM_MODE="manual"; shift ;;
      # Accepted and ignored: the stack no longer needs a GPU, so there is no
      # backend to pick. Warn rather than exit 1 — scripts and docs from before
      # this change shouldn't hard-fail on an argument that is simply moot now.
      --backend) echo "⚠ --backend is no longer used (the stack needs no GPU) — ignoring '${2:-}'"; shift 2 ;;
      --backend=*) echo "⚠ --backend is no longer used (the stack needs no GPU) — ignoring '${1#*=}'"; shift ;;
      -h|--help)
        echo "Usage: ./install.sh [--llm-url URL] [--yes] [--check-only] [--no-launch]"
        echo ""
        echo "  With no arguments, this looks for a model server already running on"
        echo "  this machine (Ollama, LM Studio, llama.cpp, vLLM) and uses it."
        echo ""
        echo "  --llm-url URL   Skip detection and use this OpenAI-compatible server."
        echo "                  From inside a container 'localhost' is the container,"
        echo "                  not your machine — use host.docker.internal or a LAN IP:"
        echo "                    ./install.sh --llm-url http://host.docker.internal:11434"
        exit 0 ;;
      *) echo "Unknown arg: $1"; exit 1 ;;
    esac
  done
  if [ "$LLM_MODE" = "manual" ]; then
    case "$LLM_ENDPOINT" in
      http://*|https://*) : ;;
      "") echo "✗ --llm-url needs a URL, e.g. http://host.docker.internal:11434"; exit 1 ;;
      *)  echo "✗ --llm-url must start with http:// or https:// (got '$LLM_ENDPOINT')"; exit 1 ;;
    esac
    # localhost inside the backend container is the CONTAINER, not the host. This
    # is the single most likely way this fails, and it fails at first chat rather
    # than at install time — so refuse it here where it's obvious.
    case "$LLM_ENDPOINT" in
      *://localhost*|*://127.0.0.1*)
        echo "✗ '$LLM_ENDPOINT' points at the container itself, not your machine."
        echo "  Use http://host.docker.internal:11434, or this box's LAN IP."
        exit 1 ;;
    esac
    LLM_PROVIDER="the server you specified"
  fi
}

# ── Check table ─────────────────────────────────────────────────────────────
add_row() { # status name detail  (status: PASS|FAIL|WARN|SKIP; FAIL flips exit code)
  CHECK_ROWS+=("$(printf '%-4s  %-16s %s' "$1" "$2" "$3")")
  [ "$1" = "FAIL" ] && CHECK_FAILED=1 || true
}

print_check_table() {
  echo ""
  echo "Preflight checks"
  local row
  for row in "${CHECK_ROWS[@]}"; do echo "  $row"; done
  echo ""
}

# ── Prerequisites ───────────────────────────────────────────────────────────
check_prereqs() {
  if command -v docker >/dev/null 2>&1; then
    add_row PASS docker "$(docker --version 2>/dev/null || echo present)"
  else
    add_row FAIL docker "not found — install Docker first"
    return 1
  fi
  if docker compose version >/dev/null 2>&1; then
    add_row PASS "docker compose" "$(docker compose version --short 2>/dev/null || echo present)"
  else
    add_row FAIL "docker compose" "v2 plugin ('docker compose') not found"
    return 1
  fi
}

# ── Model-server detection ──────────────────────────────────────────────────
port_listening() { # /dev/tcp probe: succeeds iff something accepts on 127.0.0.1:$1
  ( exec 3<>"/dev/tcp/127.0.0.1/$1" ) 2>/dev/null
}

# Probe from THIS shell (127.0.0.1) but record the URL a CONTAINER will use
# (host.docker.internal). Those are the same listener seen from two sides, and
# conflating them is the classic way a working install can't reach its model.
detect_provider() {
  if [ "$LLM_MODE" = "manual" ]; then
    add_row PASS "model server" "using ${LLM_ENDPOINT} (--llm-url)"
    return 0
  fi
  local entry port name path body count
  for entry in "${KNOWN_PROVIDERS[@]}"; do
    IFS='|' read -r port name path <<<"$entry"
    port_listening "$port" || continue
    if ! command -v curl >/dev/null 2>&1; then
      # No curl to confirm what it is, but something is listening on a port we
      # know. Say exactly that rather than claiming a positive identification.
      LLM_ENDPOINT="http://host.docker.internal:${port}"
      LLM_PROVIDER="${name}"
      add_row WARN "model server" "port ${port} is open but curl is missing — assuming ${name}"
      return 0
    fi
    body="$(curl -s -m 4 "http://127.0.0.1:${port}${path}" 2>/dev/null || true)"
    [ -n "$body" ] || continue
    LLM_ENDPOINT="http://host.docker.internal:${port}"
    LLM_PROVIDER="$name"
    count="$(printf '%s' "$body" | grep -o '"id"\|"name"' | wc -l | tr -d ' ')"
    if [ "${count:-0}" -gt 0 ]; then
      add_row PASS "model server" "${name} on :${port}, ${count} model(s)"
    else
      add_row WARN "model server" "${name} on :${port} but 0 models — chat fails until you load one"
    fi
    return 0
  done
  # Not an error. The stack comes up, the UI loads, and it reports that no
  # provider was found — which is a far better first run than refusing to start.
  add_row WARN "model server" "none found on :11434 :1234 :8080 :8000 — connect one later in Settings"
}

# ── Compose file selection ──────────────────────────────────────────────────
# One compose file. The nvidia/amd/cpu overlays are gone: with no bundled model
# server and a torch-free backend, nothing in the default set wants a GPU, so
# there was nothing left for them to override.
select_compose_files() {
  COMPOSE_FILE="docker-compose.yaml"
  # Compose auto-loads docker-compose.override.yml ONLY when COMPOSE_FILE is unset.
  # The moment we set it, a developer's gitignored override silently stops
  # applying — and the symptom (dead host services, untuned GPU) looks nothing like
  # the cause. Re-add it explicitly, last so it still wins. Clean installs don't
  # have the file, so their behaviour is unchanged.
  if [ -f docker-compose.override.yml ]; then
    COMPOSE_FILE="${COMPOSE_FILE}:docker-compose.override.yml"
    HAS_OVERRIDE=1
  else
    HAS_OVERRIDE=0
  fi
  COMPOSE_ARGS=()
  local f IFS=':'
  for f in $COMPOSE_FILE; do COMPOSE_ARGS+=(-f "$f"); done
}

# ── Compose merge gate ──────────────────────────────────────────────────────
# Renders the actual merge and reports the default service set — which is also
# the `up -d` set, since compose only emits services whose profiles are active.
check_compose_merge() {
  MERGED_JSON="$(mktemp)"
  local errs; errs="$(mktemp)"
  # JWT_SECRET is ${JWT_SECRET:?} in the compose file, which aborts `config`
  # itself when unset — feed a dummy for rendering only if .env doesn't have one.
  local -a envprefix=()
  if [ -z "${JWT_SECRET:-}" ] && ! grep -q '^JWT_SECRET=' .env 2>/dev/null; then
    envprefix=(env JWT_SECRET=preflight-only-dummy)
  fi
  if ! "${envprefix[@]}" docker compose "${COMPOSE_ARGS[@]}" config --format json \
      >"$MERGED_JSON" 2>"$errs"; then
    add_row FAIL "compose merge" "config failed: $(tail -1 "$errs" | cut -c1-120)"
    rm -f "$errs"
    return 0
  fi
  rm -f "$errs"
  local svcs count
  svcs="$("${envprefix[@]}" docker compose "${COMPOSE_ARGS[@]}" config --services 2>/dev/null || true)"
  count="$(printf '%s\n' "$svcs" | grep -c . || true)"
  add_row PASS "compose merge" "${count} service(s) in the default set"
  # A GPU device reservation in the default set is the one thing that makes
  # `up -d` fail outright on a host without the nvidia container runtime — which
  # would undo the whole point of this installer. Assert it, don't assume it.
  local nv
  nv="$(grep -c '"driver": *"nvidia"' "$MERGED_JSON" || true)"
  if [ "$nv" -eq 0 ]; then
    add_row PASS "gpu independence" "0 GPU device reservations — starts on any host"
  else
    add_row FAIL "gpu independence" "${nv} nvidia device reservation(s) in the default set — this will fail on a host without the nvidia container runtime"
  fi
}

# ── Host port preflight ─────────────────────────────────────────────────────
check_ports() {
  if [ ! -s "${MERGED_JSON:-}" ]; then
    add_row SKIP "host ports" "skipped (compose merge unavailable)"
    return 0
  fi
  local ports project own_ports p conflicts=() checked=0
  ports="$(grep -o '"published": *"[0-9]*"' "$MERGED_JSON" | grep -o '[0-9]*' | sort -un)"
  project="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_-]//g')}"
  # Ports already published by THIS compose project are a re-run, not a conflict.
  own_ports="$(docker ps --filter "label=com.docker.compose.project=${project}" \
      --format '{{.Ports}}' 2>/dev/null | grep -oE ':[0-9]+->' | grep -oE '[0-9]+' | sort -un || true)"
  for p in $ports; do
    checked=$((checked + 1))
    if printf '%s\n' "$own_ports" | grep -qx "$p"; then continue; fi
    if port_listening "$p"; then conflicts+=("$p"); fi
  done
  if [ "${#conflicts[@]}" -eq 0 ]; then
    add_row PASS "host ports" "${checked} published port(s) free or already ours"
  else
    add_row FAIL "host ports" "in use by another process: ${conflicts[*]}"
  fi
}

# ── RAM / disk (soft warnings only — unreliable signals never hard-fail) ────
check_resources() {
  local mem_kb=""
  if [ -r /proc/meminfo ]; then
    mem_kb="$(awk '/^MemTotal:/{print $2}' /proc/meminfo)"
  elif command -v sysctl >/dev/null 2>&1; then
    mem_kb="$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 ))"
    [ "$mem_kb" -eq 0 ] && mem_kb=""
  fi
  if [ -n "$mem_kb" ]; then
    local mem_gib=$((mem_kb / 1024 / 1024))
    if [ "$mem_gib" -lt 8 ]; then
      add_row WARN memory "${mem_gib} GiB detected — under 8 GiB the full stack is unlikely to fit"
    else
      add_row PASS memory "${mem_gib} GiB detected"
    fi
  else
    add_row WARN memory "could not determine total RAM on this platform"
  fi
  local disk_kb
  disk_kb="$(df -Pk . 2>/dev/null | awk 'NR==2{print $4}')"
  if [ -n "${disk_kb:-}" ]; then
    local disk_gib=$((disk_kb / 1024 / 1024))
    if [ "$disk_gib" -lt 10 ]; then
      add_row WARN disk "${disk_gib} GiB free — the images alone need roughly 7 GiB"
    else
      add_row PASS disk "${disk_gib} GiB free"
    fi
  else
    add_row WARN disk "could not determine free disk space"
  fi
}

# ── .env (preserve existing values; secrets generate-if-absent) ─────────────
rand_hex() { # $1 = bytes
  openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
}

ensure_env_secret() { # $1 = key, $2 = value, $3 = human label
  if ! grep -q "^$1=" .env; then
    printf '%s=%s\n' "$1" "$2" >> .env
    echo "✓ Generated $3"
  fi
}

drop_env_key() { # $1 = key — remove every assignment of it from .env
  if grep -q "^$1=" .env; then
    tmp="$(mktemp)"; grep -v "^$1=" .env > "$tmp"; mv "$tmp" .env
  fi
}

write_env() {
  touch .env
  # COMPOSE_FILE is only needed to re-add a local override, since setting it is
  # what suppresses compose's own auto-load. Otherwise strip it: an .env from
  # before the overlays were deleted still pins docker-compose.cpu.yml, and a
  # stale pin makes EVERY `docker compose` command fail on a missing file.
  if [ "$HAS_OVERRIDE" -eq 1 ]; then
    if ! grep -qxF "COMPOSE_FILE=${COMPOSE_FILE}" .env; then
      drop_env_key COMPOSE_FILE
      printf 'COMPOSE_FILE=%s\n' "$COMPOSE_FILE" >> .env
    fi
  elif grep -q '^COMPOSE_FILE=' .env; then
    drop_env_key COMPOSE_FILE
    echo "✓ Removed a stale COMPOSE_FILE pin (the backend overlays no longer exist)"
  fi
  # HARVIS_LLM_BASE_URL — the canonical name every service resolves against,
  # with OLLAMA_URL kept as a lower-priority fallback for existing deployments.
  # Written only when we actually know where the server is; with none found, the
  # compose default applies and Harvis reports no provider rather than guessing.
  if [ -n "$LLM_ENDPOINT" ]; then
    if ! grep -qxF "HARVIS_LLM_BASE_URL=${LLM_ENDPOINT}" .env; then
      drop_env_key HARVIS_LLM_BASE_URL
      printf 'HARVIS_LLM_BASE_URL=%s\n' "$LLM_ENDPOINT" >> .env
    fi
    # A leftover OLLAMA_URL is shadowed by the line above, not obeyed — but it
    # will confuse the next person who reads this file, so say it's inert.
    stale="$(grep '^OLLAMA_URL=' .env | head -1 | cut -d= -f2- || true)"
    if [ -n "${stale:-}" ] && [ "$stale" != "$LLM_ENDPOINT" ]; then
      echo "⚠ .env still sets OLLAMA_URL=${stale}; HARVIS_LLM_BASE_URL overrides it."
      echo "  Remove that line unless you set it deliberately."
    fi
  fi
  ensure_env_secret JWT_SECRET "$(rand_hex 32)" "a JWT_SECRET"
  # FERNET_KEY — encrypts stored GitHub OAuth tokens. Compose defaults it to empty
  # and the backend only logs a warning, so without this GitHub sign-in fails in a
  # way that looks like a broken button rather than missing config.
  # Fernet requires 32 bytes as URL-SAFE base64 (-_ not +/), NOT hex like the others.
  if ! grep -q '^FERNET_KEY=' .env; then
    fkey="$(openssl rand -base64 32 2>/dev/null | tr '+/' '-_' || head -c 32 /dev/urandom | base64 | tr '+/' '-_')"
    printf 'FERNET_KEY=%s\n' "$fkey" >> .env
    echo "✓ Generated a FERNET_KEY (GitHub OAuth token encryption)"
  fi
  # HARVIS_SETUP_CODE — one-time first-signup gate: the first (admin) account can
  # only be created by whoever holds this code.
  setup_code="$(rand_hex 6 | sed 's/\(....\)/\1-/g; s/-$//')"
  ensure_env_secret HARVIS_SETUP_CODE "$setup_code" "a HARVIS_SETUP_CODE (first-admin signup gate)"
  # OPENCLAW_GATEWAY_TOKEN — SHARED across backend/openclaw/harvis-mcp; a running
  # stack authenticated with the old value breaks if this ever regenerates.
  ensure_env_secret OPENCLAW_GATEWAY_TOKEN "$(rand_hex 32)" "an OPENCLAW_GATEWAY_TOKEN"
  if [ -n "$LLM_ENDPOINT" ]; then
    echo "✓ Wrote .env  (HARVIS_LLM_BASE_URL=${LLM_ENDPOINT})"
  else
    echo "✓ Wrote .env  (no model server set — connect one from Settings after first login)"
  fi
  [ "$HAS_OVERRIDE" -eq 1 ] && echo "  ↳ including your local docker-compose.override.yml" || true
}

# ── Network ─────────────────────────────────────────────────────────────────
# The compose file declares ollama-n8n-network as external:true — `up` fails
# outright if it doesn't exist.
ensure_network() {
  docker network inspect ollama-n8n-network >/dev/null 2>&1 || docker network create ollama-n8n-network >/dev/null
  echo "✓ docker network 'ollama-n8n-network' ready"
}

# ── Startup poll — report what was OBSERVED, not what was hoped ─────────────
print_setup_code() {
  # The setup code must never land in captured output (tee'd logs, CI transcripts),
  # so it is written to the terminal directly; with no terminal, point at .env.
  local code_line="HARVIS_SETUP_CODE is in .env — view it with:  grep '^HARVIS_SETUP_CODE=' .env"
  # `-w /dev/tty` only checks permission bits; actually opening it is the real
  # "do we have a controlling terminal" probe.
  if ( : > /dev/tty ) 2>/dev/null; then
    code="$(grep '^HARVIS_SETUP_CODE=' .env | head -1 | cut -d= -f2-)"
    printf '  First-admin setup code: %s\n' "$code" > /dev/tty
    echo "  (setup code printed to your terminal only — it is also in .env)"
  else
    echo "  $code_line"
  fi
}

# Modest default for stranger boxes (incl. 8 GB GPUs). Larger models can be pulled later.
DEFAULT_OLLAMA_MODEL="${HARVIS_DEFAULT_OLLAMA_MODEL:-llama3.2:3b}"

report_models() {
  # The model server belongs to the host, not to this stack — there is no
  # container to `docker exec` into and nothing here can pull on its behalf.
  # So: point at the machine that owns it, and say what to run there.
  echo ""
  if [ -z "$LLM_ENDPOINT" ]; then
    echo "  No model server was found on this machine, so chat has nothing to talk to yet."
    echo "  Start one and re-run ./install.sh, or set it from Settings → Integrations."
    echo "  The quickest option:  ollama serve   (then: ollama pull ${DEFAULT_OLLAMA_MODEL})"
    return 0
  fi
  echo "  Models come from ${LLM_PROVIDER:-your server} at ${LLM_ENDPOINT}."
  case "$LLM_PROVIDER" in
    Ollama) echo "  Pull one there, e.g.:  ollama pull ${DEFAULT_OLLAMA_MODEL}" ;;
    *)      echo "  Load a model there, then pick it in Harvis." ;;
  esac
}

poll_health() {
  echo ""
  echo "Waiting for the stack to come up (polling ${HEALTH_URL}) ..."
  local deadline=$((SECONDS + 180)) body="" overall=""
  while [ $SECONDS -lt $deadline ]; do
    body="$(curl -s -m 8 "$HEALTH_URL" 2>/dev/null || true)"
    overall="$(printf '%s' "$body" | sed -n 's/^{"status":"\([a-z]*\)".*/\1/p')"
    [ "$overall" = "healthy" ] && break
    sleep 5
  done
  echo ""
  if [ -n "$body" ]; then
    echo "Service status (from /api/health/services):"
    printf '%s' "$body" \
      | grep -oE '"[a-z0-9-]+":\{"status":"[a-z]+"' \
      | sed 's/":{"status":"/ /; s/"//g' \
      | while read -r name state; do
          case "$state" in
            up) printf '  ✓ %-16s up\n' "$name" ;;
            *)  printf '  ✗ %-16s %s\n' "$name" "$state" ;;
          esac
        done
  fi
  if [ "$overall" = "healthy" ]; then
    echo ""
    echo "✓ Harvis is up → http://localhost:9000"
    # The endpoint returns {"needs_setup":..,"setup_complete":..} — extract the
    # one field we need without anchoring to the whole body (a second key was
    # added later, and an anchored match silently yields empty → a false
    # "unreachable" claim right after a 200).
    local setup_body needs
    setup_body="$(curl -s -m 8 "$SETUP_URL" 2>/dev/null)"
    needs="$(printf '%s' "$setup_body" | grep -o '"needs_setup" *: *\(true\|false\)' | grep -o 'true\|false' | head -1)"
    case "$needs" in
      true)  print_setup_code ;;
      false) echo "  Instance already has an admin — no setup code needed." ;;
      *)     if [ -z "$setup_body" ]; then
               echo "  Could not reach ${SETUP_URL} — if this is a fresh install, the first"
               echo "  signup will ask for the setup code from .env (HARVIS_SETUP_CODE)."
             else
               echo "  ${SETUP_URL} answered but its state was unrecognised — if this is a"
               echo "  fresh install, the first signup will ask for the setup code from .env."
             fi ;;
    esac
    echo ""
    echo "  Auth cookie: HARVIS_COOKIE_SECURE defaults to false (localhost/LAN HTTP)."
    echo "  Behind HTTPS, set HARVIS_COOKIE_SECURE=true in .env and recreate the backend."
    report_models
    return 0
  fi
  echo ""
  if [ -z "$body" ]; then
    echo "✗ No response from ${HEALTH_URL} after 180s — nginx (or the backend behind it) never came up."
  else
    echo "✗ Stack did not reach 'healthy' within 180s — see per-service status above."
  fi
  echo "  Inspect with:  docker compose ps"
  echo "                 docker compose logs --tail=100 backend nginx pgsql"
  return 1
}

launch() {
  echo ""
  if [ -n "$LLM_ENDPOINT" ]; then
    echo "Model server: ${LLM_PROVIDER:-configured} at ${LLM_ENDPOINT}"
  else
    echo "Model server: none detected — Harvis will start and report no provider."
  fi
  if [ "$NO_LAUNCH" -eq 1 ]; then
    echo ""
    echo "When ready, run:  docker compose up --build -d"
    return 0
  fi
  local run
  if [ "$ASSUME_YES" -eq 1 ]; then run="y"; else read -rp "Build and start the stack now? [y/N]: " run || true; fi
  if [[ "${run:-N}" =~ ^[Yy]$ ]]; then
    docker compose up --build -d
    poll_health
  else
    echo ""
    echo "When ready, run:  docker compose up --build -d"
  fi
}

# ── Main ────────────────────────────────────────────────────────────────────
main() {
  parse_args "$@"
  echo "Harvis installer"
  echo "================"
  if ! check_prereqs; then
    print_check_table
    exit 1
  fi
  detect_provider
  select_compose_files
  check_compose_merge
  check_ports
  check_resources
  print_check_table
  [ -n "${MERGED_JSON:-}" ] && rm -f "$MERGED_JSON"
  if [ "$CHECK_FAILED" -eq 1 ]; then
    echo "✗ Preflight failed — nothing was changed."
    exit 1
  fi
  if [ "$CHECK_ONLY" -eq 1 ]; then
    echo "✓ All preflight checks passed — nothing was changed (--check-only)."
    exit 0
  fi
  write_env
  ensure_network
  launch
}

main "$@"
