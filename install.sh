#!/usr/bin/env bash
# Harvis installer — pick your inference backend (NVIDIA / AMD / CPU), preflight
# the host, write the compose selection + generated secrets into .env, create the
# docker network, and optionally bring the stack up. Re-run any time to switch
# backends — existing secrets are never regenerated.
#
#   ./install.sh                        # interactive
#   ./install.sh --backend cpu --yes    # non-interactive (nvidia|amd|cpu)
#   ./install.sh --check-only           # preflight only: changes NOTHING
#   ./install.sh --no-launch            # configure but don't start the stack
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKEND=""
ASSUME_YES=0
CHECK_ONLY=0
NO_LAUNCH=0
COMPOSE_FILE=""
COMPOSE_ARGS=()
HAS_OVERRIDE=0
MERGED_JSON=""
CHECK_FAILED=0
CHECK_ROWS=()

HEALTH_URL="http://localhost:9000/api/health/services"
SETUP_URL="http://localhost:9000/api/setup/status"

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --backend) BACKEND="${2:-}"; shift 2 ;;
      --backend=*) BACKEND="${1#*=}"; shift ;;
      --yes|-y) ASSUME_YES=1; shift ;;
      --check-only) CHECK_ONLY=1; shift ;;
      --no-launch) NO_LAUNCH=1; shift ;;
      -h|--help)
        echo "Usage: ./install.sh [--backend nvidia|amd|cpu] [--yes] [--check-only] [--no-launch]"
        exit 0 ;;
      *) echo "Unknown arg: $1"; exit 1 ;;
    esac
  done
  case "$BACKEND" in
    ""|nvidia|amd|cpu) : ;;
    *) echo "✗ --backend must be nvidia|amd|cpu (got '$BACKEND')"; exit 1 ;;
  esac
}

# ── Check table ─────────────────────────────────────────────────────────────
add_row() { # status name detail  (status: PASS|FAIL|WARN|SKIP; FAIL flips exit code)
  CHECK_ROWS+=("$(printf '%-4s  %-16s %s' "$1" "$2" "$3")")
  [ "$1" = "FAIL" ] && CHECK_FAILED=1 || true
}

print_check_table() {
  echo ""
  echo "Preflight checks (backend: ${BACKEND})"
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

# ── Backend detection / choice ──────────────────────────────────────────────
detect_backend() {
  DETECTED="cpu"
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    DETECTED="nvidia"
  elif [ -e /dev/kfd ] || command -v rocminfo >/dev/null 2>&1; then
    DETECTED="amd"
  fi
  echo "• Detected backend: ${DETECTED}"
  case "$(uname -s)" in
    Darwin) echo "  Note: on macOS, Docker can't use the Mac GPU — this picks CPU. For Metal speed,"
            echo "        run Ollama NATIVELY and set OLLAMA_URL=http://host.docker.internal:11434." ;;
  esac
}

choose_backend() {
  if [ -n "$BACKEND" ]; then return 0; fi
  if [ "$CHECK_ONLY" -eq 1 ] || [ "$ASSUME_YES" -eq 1 ]; then
    BACKEND="$DETECTED"
    return 0
  fi
  echo ""
  echo "Choose your inference backend:"
  echo "  1) nvidia   NVIDIA GPU + nvidia-container-toolkit (fastest)"
  echo "  2) amd      AMD GPU via ROCm — accelerates Ollama; TTS/STT stay CPU"
  echo "  3) cpu      No GPU — runs anywhere, much slower"
  read -rp "Backend [${DETECTED}]: " choice || true
  choice="${choice:-$DETECTED}"
  case "$choice" in
    1|nvidia) BACKEND=nvidia ;;
    2|amd)    BACKEND=amd ;;
    3|cpu)    BACKEND=cpu ;;
    *) echo "✗ Unknown choice '$choice'"; exit 1 ;;
  esac
}

# ── Compose file selection ──────────────────────────────────────────────────
select_compose_files() {
  case "$BACKEND" in
    nvidia) COMPOSE_FILE="docker-compose.yaml" ;;
    amd)    COMPOSE_FILE="docker-compose.yaml:docker-compose.amd.yml" ;;
    cpu)    COMPOSE_FILE="docker-compose.yaml:docker-compose.cpu.yml" ;;
  esac
  # Compose auto-loads docker-compose.override.yml ONLY when COMPOSE_FILE is unset.
  # The moment we set it above, a developer's gitignored override silently stops
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

# ── Compose merge gate (behavioral, NOT version-parsed) ─────────────────────
# The cpu/amd overrides rely on the `!reset` YAML tag to clear the base file's
# nvidia device reservations. Old Compose releases silently IGNORE the tag and
# keep the reservation — `up` then fails on machines with no nvidia runtime.
# Version-string parsing can't catch this reliably (5.x is current), so render
# the actual merge and assert on the result instead.
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
  local nv
  nv="$(grep -c '"driver": *"nvidia"' "$MERGED_JSON" || true)"
  case "$BACKEND" in
    nvidia)
      if [ "$nv" -gt 0 ]; then
        add_row PASS "compose merge" "nvidia profile keeps ${nv} GPU device reservation(s)"
      else
        add_row FAIL "compose merge" "nvidia profile lost its GPU device reservations"
      fi ;;
    amd|cpu)
      if [ "$nv" -eq 0 ]; then
        add_row PASS "compose merge" "${BACKEND} profile: 0 nvidia device reservations (\`!reset\` honoured)"
      else
        add_row FAIL "compose merge" "${nv} nvidia reservation(s) survived the ${BACKEND} merge — your Compose ignores \`!reset\` (fixed in ≥ 2.19); upgrade Compose"
      fi ;;
  esac
}

# ── Host port preflight ─────────────────────────────────────────────────────
port_listening() { # /dev/tcp probe: succeeds iff something accepts on 127.0.0.1:$1
  ( exec 3<>"/dev/tcp/127.0.0.1/$1" ) 2>/dev/null
}

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
    if [ "$disk_gib" -lt 20 ]; then
      # No download-size estimate: it depends on backend images + which models you
      # pull, and a made-up number would just be a differently-shaped lie.
      add_row WARN disk "${disk_gib} GiB free — Docker images + models may not fit (exact size not estimated)"
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

write_env() {
  touch .env
  # COMPOSE_FILE — docker compose auto-reads this, so `docker compose up` uses the
  # right files. Rewrite only when the value actually changed, so a same-backend
  # re-run leaves .env byte-identical.
  if ! grep -qxF "COMPOSE_FILE=${COMPOSE_FILE}" .env; then
    if grep -q '^COMPOSE_FILE=' .env; then
      tmp="$(mktemp)"; grep -v '^COMPOSE_FILE=' .env > "$tmp"; mv "$tmp" .env
    fi
    printf 'COMPOSE_FILE=%s\n' "$COMPOSE_FILE" >> .env
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
  echo "✓ Wrote .env  (COMPOSE_FILE=${COMPOSE_FILE})"
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
    local needs
    needs="$(curl -s -m 8 "$SETUP_URL" 2>/dev/null | sed -n 's/^{"needs_setup":\(true\|false\)}$/\1/p')"
    case "$needs" in
      true)  print_setup_code ;;
      false) echo "  Instance already has an admin — no setup code needed." ;;
      *)     echo "  Could not confirm setup state (${SETUP_URL} unreachable) — if this is a"
             echo "  fresh install, the first signup will ask for the setup code from .env." ;;
    esac
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
  echo "Backend selected: ${BACKEND}"
  case "$BACKEND" in
    amd) echo "  Note: AMD accelerates Ollama (chat/agents); voice (TTS + Whisper STT) runs on CPU." ;;
    cpu) echo "  Note: everything runs on CPU — inference is slower and voice (TTS/STT) may lag." ;;
  esac
  if [ "$NO_LAUNCH" -eq 1 ]; then
    echo ""
    echo "When ready, run:  docker compose up --build -d   (.env selects the ${BACKEND} backend)"
    return 0
  fi
  local run
  if [ "$ASSUME_YES" -eq 1 ]; then run="y"; else read -rp "Build and start the stack now? [y/N]: " run || true; fi
  if [[ "${run:-N}" =~ ^[Yy]$ ]]; then
    docker compose up --build -d
    poll_health
  else
    echo ""
    echo "When ready, run:  docker compose up --build -d   (.env selects the ${BACKEND} backend)"
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
  detect_backend
  choose_backend
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
