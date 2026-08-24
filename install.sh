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
# GID that owns /var/run/docker.sock on THIS host. Empty until detected.
DOCKER_GID=""
# Container runtime for the services that can use a GPU (today: llmfit). Empty
# means plain runc — the portable default. Set to "nvidia" only when this host
# actually has that runtime registered with dockerd.
GPU_RUNTIME=""

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
# The health report lists the model provider under this key. That server is the
# user's own (plug-and-play via HARVIS_LLM_BASE_URL), not a container of this
# stack — it being absent or down is information, never install failure.
PROVIDER_HEALTH_KEY="model_provider"

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
        echo "  this machine (Ollama, LM Studio, llama.cpp, vLLM), uses it, and then"
        echo "  builds and starts the stack. --no-launch stops after writing .env."
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

# Multi-line remedies for a failed check. Buffered rather than echoed on the
# spot, because a check that printed its advice immediately put the fix on
# screen BEFORE the table that says what failed — read top to bottom, that is
# an instruction with no visible cause.
CHECK_HINTS=()
add_hint() { CHECK_HINTS+=("$1"); }

print_check_table() {
  echo ""
  echo "Preflight checks"
  local row
  for row in "${CHECK_ROWS[@]}"; do echo "  $row"; done
  echo ""
  local hint
  for hint in "${CHECK_HINTS[@]+"${CHECK_HINTS[@]}"}"; do printf '%s\n\n' "$hint"; done
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

# ── Docker socket group ─────────────────────────────────────────────────────
# The backend mounts /var/run/docker.sock and runs as appuser (uid 1001), which
# is in no host group by default. `group_add` is what lets it open the socket,
# and the GID it needs is a property of the HOST, not of the image: Debian and
# Ubuntu usually land on 998 or 999, Fedora on 1001, this dev box on 984.
#
# Getting it wrong is silent. The container is healthy, the socket is mounted,
# and every feature built on it — the isolated runner, repo sandboxes, vibecode
# containers, integrations status — reports "docker client unavailable" with
# nothing else to go on. So read the real value and write it down.
detect_docker_gid() {
  if [ ! -S /var/run/docker.sock ]; then
    add_row WARN "docker socket" "/var/run/docker.sock not found — Build Space sandboxes will be unavailable"
    return 0
  fi
  DOCKER_GID="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || stat -f '%g' /var/run/docker.sock 2>/dev/null || true)"
  case "${DOCKER_GID:-}" in
    ''|*[!0-9]*)
      DOCKER_GID=""
      add_row WARN "docker socket" "could not read its group — leaving the compose default in place"
      return 0 ;;
  esac
  if [ "$DOCKER_GID" = "0" ]; then
    # Docker Desktop (macOS, and Windows via WSL2) presents the socket as
    # root:root. group_add: "0" is what actually works there, and it is not the
    # privilege escalation it looks like — mounting this socket at all already
    # grants host root, which is documented at the mount in docker-compose.yaml.
    add_row WARN "docker socket" "owned by root (Docker Desktop) — using group 0"
  else
    add_row PASS "docker socket" "group ${DOCKER_GID}"
  fi
}

# ── GPU runtime ─────────────────────────────────────────────────────────────
# llmfit (the model ranker) reads whatever hardware it can see. Under plain runc
# it still enumerates GPUs off the PCI bus and ranks the catalogue; the nvidia
# runtime only adds CUDA-reported VRAM, which sharpens the ranking. So this is a
# nice-to-have, never a requirement — asking dockerd is the only honest way to
# tell, since a driver on the host says nothing about the CONTAINER runtime.
detect_gpu_runtime() {
  local runtimes
  runtimes="$(docker info --format '{{json .Runtimes}}' 2>/dev/null || true)"
  case "$runtimes" in
    *'"nvidia"'*)
      GPU_RUNTIME="nvidia"
      add_row PASS "gpu runtime" "nvidia runtime present — llmfit will read CUDA VRAM" ;;
    *)
      GPU_RUNTIME=""
      add_row PASS "gpu runtime" "runc (no nvidia runtime) — llmfit reads the PCI bus instead" ;;
  esac
}

# ── Model-server detection ──────────────────────────────────────────────────
port_listening() { # /dev/tcp probe: succeeds iff something accepts on $1:$2
  ( exec 3<>"/dev/tcp/$1/$2" ) 2>/dev/null
}

# Which compose project, if any, publishes host port $1. Empty when the holder
# is not a compose container — then "another process" really is the truth.
port_owner() {
  docker ps --format '{{.Ports}}\t{{.Label "com.docker.compose.project"}}' 2>/dev/null \
    | grep -E ":$1->" | awk -F'\t' 'NF>1 && $2!="" {print $2; exit}'
}

# Where to look for a model server, most likely first.
#
# 127.0.0.1 alone is wrong on the platform most people install from. Under WSL2
# in its default NAT mode the distro has its own network namespace, so a server
# listening on the WINDOWS host's loopback is not reachable at 127.0.0.1 from
# here — it answers on the default gateway, which is the Windows host. Probing
# only loopback therefore reported "no model server found" to users running a
# perfectly healthy Ollama, and sent them off to fix a problem they did not have.
# (WSL2's newer mirrored mode does forward loopback, which is why 127.0.0.1
# stays first rather than being replaced.)
llm_probe_hosts() {
  printf '127.0.0.1\n'
  local gw
  gw="$(ip route show default 2>/dev/null | awk '/^default/{print $3; exit}')"
  if [ -n "$gw" ] && [ "$gw" != "127.0.0.1" ]; then printf '%s\n' "$gw"; fi
  # Docker Desktop publishes this name to the WSL distro too on some versions.
  # Harmless when it does not resolve: the /dev/tcp probe just fails.
  printf 'host.docker.internal\n'
}

# Probe from THIS shell (127.0.0.1) but record the URL a CONTAINER will use
# (host.docker.internal). Those are the same listener seen from two sides, and
# conflating them is the classic way a working install can't reach its model.
detect_provider() {
  if [ "$LLM_MODE" = "manual" ]; then
    add_row PASS "model server" "using ${LLM_ENDPOINT} (--llm-url)"
    return 0
  fi
  local entry port name path body count host
  local -a hosts=()
  while IFS= read -r host; do [ -n "$host" ] && hosts+=("$host"); done < <(llm_probe_hosts)
  for entry in "${KNOWN_PROVIDERS[@]}"; do
    IFS='|' read -r port name path <<<"$entry"
    for host in "${hosts[@]}"; do
    port_listening "$host" "$port" || continue
    if ! command -v curl >/dev/null 2>&1; then
      # No curl to confirm what it is, but something is listening on a port we
      # know. Say exactly that rather than claiming a positive identification.
      LLM_ENDPOINT="http://host.docker.internal:${port}"
      LLM_PROVIDER="${name}"
      add_row WARN "model server" "port ${port} is open but curl is missing — assuming ${name}"
      return 0
    fi
    body="$(curl -s -m 4 "http://${host}:${port}${path}" 2>/dev/null || true)"
    [ -n "$body" ] || continue
    # A reply is not an identification. Harvis's own backend publishes :8000 and
    # answers /v1/models with {"detail":"Not Found"} — accepting any non-empty
    # body made the installer point Harvis at itself. Demand the shape of a model
    # list: `models` (Ollama) or `data` (OpenAI-compatible). Anything else is
    # some other program on a port we happen to know, so keep looking.
    case "$body" in
      *'"models"'*|*'"data"'*) : ;;
      *) continue ;;
    esac
    LLM_ENDPOINT="http://host.docker.internal:${port}"
    LLM_PROVIDER="$name"
    # `|| true` is load-bearing: pipefail is on, and grep exits 1 on no match —
    # which is the ordinary "reachable but no models loaded" case, not a failure.
    count="$(printf '%s' "$body" | grep -o '"id"\|"name"' | wc -l | tr -d ' ' || true)"
    if [ "${count:-0}" -gt 0 ]; then
      add_row PASS "model server" "${name} at ${host}:${port}, ${count} model(s)"
    else
      add_row WARN "model server" "${name} at ${host}:${port} but 0 models — chat fails until you load one"
    fi
    return 0
    done
  done
  # Not an error. The stack comes up, the UI loads, and it reports that no
  # provider was found — which is a far better first run than refusing to start.
  add_row WARN "model server" "none found on :11434 :1234 :8080 :8000 (tried ${hosts[*]}) — connect one later in Settings"
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
  # Render with the runtime we just detected rather than whatever .env happens to
  # hold — write_env runs AFTER this, so on a first install .env doesn't have the
  # key yet, and on a re-run a stale value would render a merge that isn't the
  # one `up -d` gets. A real environment variable outranks the .env file.
  local -a envprefix=(env "HARVIS_GPU_RUNTIME=${GPU_RUNTIME:-runc}")
  if [ -z "${JWT_SECRET:-}" ] && ! grep -q '^JWT_SECRET=' .env 2>/dev/null; then
    envprefix+=(JWT_SECRET=preflight-only-dummy)
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
  # Demanding a GPU is what makes `up -d` fail outright on a host that has none,
  # which would undo the whole point of this installer. Assert it, don't assume
  # it. Two separate ways to demand one: a device reservation, and `runtime:`.
  # Reservations are never acceptable here (nothing in the default set needs one).
  # A rendered nvidia runtime is fine — but only on a host that actually has it,
  # which is why this reads the merge produced with the detected value above.
  local nv rt
  nv="$(grep -c '"driver": *"nvidia"' "$MERGED_JSON" || true)"
  rt="$(grep -c '"runtime": *"nvidia"' "$MERGED_JSON" || true)"
  if [ "$nv" -ne 0 ]; then
    add_row FAIL "gpu independence" "${nv} nvidia device reservation(s) in the default set — this will fail on a host without the nvidia container runtime"
  elif [ "$rt" -ne 0 ] && [ -z "$GPU_RUNTIME" ]; then
    add_row FAIL "gpu independence" "${rt} service(s) render runtime:nvidia but this host has no nvidia runtime — they would fail to create"
  elif [ "$rt" -ne 0 ]; then
    add_row PASS "gpu independence" "no device reservations; ${rt} service(s) opt into the nvidia runtime this host has"
  else
    add_row PASS "gpu independence" "0 GPU device reservations — starts on any host"
  fi
}

# The project name Compose will actually use. `docker-compose.yaml` pins
# `name: harvis` at the top precisely so every checkout and worktree shares one
# stack, and a top-level `name:` outranks $COMPOSE_PROJECT_NAME. Deriving it from
# $PWD instead — as this did — makes the port check look for containers under a
# project that does not exist, find none of its own, and fail a legitimate re-run
# as a port conflict. From a git worktree it was wrong every time. The rendered
# merge already carries the answer, so read it rather than guessing.
compose_project_name() {
  local n=""
  if [ -s "${MERGED_JSON:-}" ]; then
    n="$(sed -n 's/^[[:space:]]*"name":[[:space:]]*"\([^"]*\)".*/\1/p' "$MERGED_JSON" | head -1)"
  fi
  [ -n "$n" ] || n="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_-]//g')}"
  printf '%s' "$n"
}

# ── Host port preflight ─────────────────────────────────────────────────────
check_ports() {
  if [ ! -s "${MERGED_JSON:-}" ]; then
    add_row SKIP "host ports" "skipped (compose merge unavailable)"
    return 0
  fi
  local ports project own_ports p owner conflicts=() checked=0
  # `|| true`: a compose file that publishes nothing makes grep exit 1, which
  # under `set -euo pipefail` would kill the installer here with no message.
  ports="$(grep -o '"published": *"[0-9]*"' "$MERGED_JSON" | grep -o '[0-9]*' | sort -un || true)"
  project="$(compose_project_name)"
  # Ports already published by THIS compose project are a re-run, not a conflict.
  own_ports="$(docker ps --filter "label=com.docker.compose.project=${project}" \
      --format '{{.Ports}}' 2>/dev/null | grep -oE ':[0-9]+->' | grep -oE '[0-9]+' | sort -un || true)"
  for p in $ports; do
    checked=$((checked + 1))
    if printf '%s\n' "$own_ports" | grep -qx "$p"; then continue; fi
    # Loopback only here: this is about ports published on THIS host.
    if port_listening 127.0.0.1 "$p"; then
      # Name the stack that holds it. "another process" was misleading in the
      # one case that matters most: the holder is usually another Harvis.
      owner="$(port_owner "$p")"
      if [ -n "$owner" ]; then conflicts+=("${p} (project '${owner}')")
      else conflicts+=("$p"); fi
    fi
  done
  if [ "${#conflicts[@]}" -eq 0 ]; then
    add_row PASS "host ports" "${checked} published port(s) free or already ours"
  else
    add_row FAIL "host ports" "already published: ${conflicts[*]}"
    add_hint "  Free those ports, or give this stack its own. Every published port
  is overridable, so a second stack can sit beside the first:
      HARVIS_STACK_NAME=harvis2 HARVIS_CONTAINER_PREFIX=harvis2- \\
      HARVIS_PORT_BACKEND=28000 HARVIS_PORT_NGINX=29000 \\
      HARVIS_PORT_POSTGRES=25432 HARVIS_PORT_MCP=28010 ./install.sh
  The full list of HARVIS_PORT_* variables is in docker-compose.yaml's header."
  fi
}

# ── Container-name preflight ────────────────────────────────────────────────
# Every service pins an explicit `container_name:`, which is a daemon-global
# name — it deliberately ignores the compose project namespace so that
# `docker exec harvis-backend ...` works the same from any checkout, and ~260
# files in this repo rely on that. The cost is that a container left behind by
# some OTHER project holding one of those names makes `up` fail with a message
# about the name being "already in use by container <hash>", which says nothing
# about which stack owns it or what to do. Name the owner and the remedy.
check_container_names() {
  if [ ! -s "${MERGED_JSON:-}" ]; then
    add_row SKIP "container names" "skipped (compose merge unavailable)"
    return 0
  fi
  local project names n owner stale=() checked=0
  project="$(compose_project_name)"
  names="$(sed -n 's/^[[:space:]]*"container_name":[[:space:]]*"\([^"]*\)".*/\1/p' "$MERGED_JSON" | sort -u)"
  for n in $names; do
    checked=$((checked + 1))
    owner="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$n" 2>/dev/null || true)"
    # Not present, or present and ours: both fine. Ours is just a re-run.
    [ -z "$owner" ] && continue
    [ "$owner" = "$project" ] && continue
    stale+=("${n} (owned by '${owner}')")
  done
  if [ "${#stale[@]}" -eq 0 ]; then
    add_row PASS "container names" "${checked} name(s) free or already ours (project '${project}')"
  else
    add_row FAIL "container names" "held by another compose project: ${stale[*]}"
    add_hint "  Those container names belong to a different stack. Either remove them:
      docker rm -f ${names//$'\n'/ }
  or install this one beside it as a separate stack (give it free ports too):
      HARVIS_STACK_NAME=harvis2 HARVIS_CONTAINER_PREFIX=harvis2- ./install.sh"
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
    # MemTotal sits below the nominal size (the kernel and firmware reserve some
    # of it), so truncating division calls an 8 GB machine "7 GiB" and trips the
    # warning on hardware that is fine. Round to the NEAREST GiB instead: the
    # printed figure then matches the RAM the user knows they bought, and the
    # threshold compares against that same honest number.
    local mem_gib=$(( (mem_kb + 524288) / 1048576 ))
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
    # `|| true`: if that key is the ONLY line in .env, grep -v emits nothing and
    # exits 1, which under `set -e` would end the installer mid-rewrite.
    tmp="$(mktemp)"; grep -v "^$1=" .env > "$tmp" || true; mv "$tmp" .env
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
  # HARVIS_DOCKER_GID — the host's docker-socket group, read in detect_docker_gid.
  # Always rewritten rather than preserved: unlike a secret, a stale value here is
  # worse than none (the socket silently stops opening after a Docker reinstall
  # renumbers the group). With no socket, leave it unset so compose's default
  # applies and .env doesn't claim knowledge we don't have.
  if [ -n "$DOCKER_GID" ]; then
    if ! grep -qxF "HARVIS_DOCKER_GID=${DOCKER_GID}" .env; then
      drop_env_key HARVIS_DOCKER_GID
      printf 'HARVIS_DOCKER_GID=%s\n' "$DOCKER_GID" >> .env
      echo "✓ Set HARVIS_DOCKER_GID=${DOCKER_GID} (host docker socket group)"
    fi
  fi
  # HARVIS_GPU_RUNTIME — same reasoning as HARVIS_DOCKER_GID: always rewritten,
  # and dropped outright when this host has no nvidia runtime. A stale "nvidia"
  # here (card removed, runtime uninstalled, .env copied between machines) makes
  # llmfit fail at container-create rather than fall back, so absent beats wrong.
  if [ -n "$GPU_RUNTIME" ]; then
    if ! grep -qxF "HARVIS_GPU_RUNTIME=${GPU_RUNTIME}" .env; then
      drop_env_key HARVIS_GPU_RUNTIME
      printf 'HARVIS_GPU_RUNTIME=%s\n' "$GPU_RUNTIME" >> .env
      echo "✓ Set HARVIS_GPU_RUNTIME=${GPU_RUNTIME} (llmfit reads CUDA VRAM)"
    fi
  elif grep -q '^HARVIS_GPU_RUNTIME=' .env; then
    drop_env_key HARVIS_GPU_RUNTIME
    echo "✓ Removed a stale HARVIS_GPU_RUNTIME pin (this host has no nvidia runtime)"
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
  local code=""
  # `|| true`: no such key in .env means grep exits 1, and under `set -e` that
  # would end the installer on its very last useful line.
  code="$(grep '^HARVIS_SETUP_CODE=' .env | head -1 | cut -d= -f2- || true)"
  if [ -z "$code" ]; then
    echo "  No HARVIS_SETUP_CODE found in .env — the first signup will ask for one."
  # `-w /dev/tty` only checks permission bits; actually opening it is the real
  # "do we have a controlling terminal" probe.
  elif ( : > /dev/tty ) 2>/dev/null; then
    printf '  First-admin setup code: %s\n' "$code" > /dev/tty
    echo "  (setup code printed to your terminal only — it is also in .env)"
  else
    echo "  $code_line"
  fi
}

report_models() {
  # The model server belongs to the host, not to this stack — there is no
  # container to `docker exec` into and nothing here can pull on its behalf.
  # So: point at the machine that owns it, and say what to run there.
  #
  # Deliberately names no model. This script knows nothing about your hardware,
  # and a hardcoded suggestion is a guess dressed as advice; the setup wizard
  # asks llmfit (running in the default set) to rank real candidates for THIS
  # machine, which is a better answer than any constant could be.
  echo ""
  if [ -z "$LLM_ENDPOINT" ]; then
    echo "  No model server was found on this machine, so chat has nothing to talk to yet."
    echo "  Two ways forward, both offered in the setup wizard on first login:"
    echo "    • connect a cloud provider with an API key, or"
    echo "    • start a local server (ollama serve, LM Studio, llama.cpp, vLLM) and re-run this."
    return 0
  fi
  echo "  Models come from ${LLM_PROVIDER:-your server} at ${LLM_ENDPOINT}."
  case "$LLM_PROVIDER" in
    Ollama) echo "  It has none loaded yet — the setup wizard ranks what this machine can run." ;;
    *)      echo "  Load a model there, then pick it in Harvis." ;;
  esac
}

# Names in the health report that are genuinely wrong: not up, not merely
# absent because their compose profile is off, and not the model provider.
health_blockers() { # $1 = /api/health/services body
  printf '%s' "$1" \
    | grep -oE '"[a-z0-9_-]+":\{"status":"[a-z_]+"' \
    | sed 's/^"//; s/":{"status":"/ /; s/"$//' \
    | awk '$2!="up" && $2!="not_installed" && $2!="not_configured"{print $1}' \
    | grep -vxF "$PROVIDER_HEALTH_KEY" || true
}

# The status table the user sees, built from the ACTUAL default service set —
# not from the backend's capability report, which names the external provider
# alongside real containers. `ps` without -a hides exited containers, and two
# services (artifact-init, owui-builder) are one-shot jobs that SHOULD exit 0,
# so read states with -a and judge exited containers by their exit code.
# Failed services land in STACK_DOWN for the caller to act on.
STACK_DOWN=""
check_stack_containers() {
  STACK_DOWN=""
  local expected states svc line state code
  expected="$(docker compose config --services 2>/dev/null || true)"
  [ -n "$expected" ] || return 0  # can't render the set — don't invent a verdict
  states="$(docker compose ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' 2>/dev/null || true)"
  echo "Service status (docker compose ps):"
  for svc in $expected; do
    line="$(printf '%s\n' "$states" | awk -v s="$svc" '$1==s{print; exit}')"
    state="$(printf '%s' "$line" | awk '{print $2}')"
    code="$(printf '%s' "$line" | awk '{print $3}')"
    case "$state" in
      running) printf '  ✓ %-16s up\n' "$svc" ;;
      exited)
        if [ "${code:-1}" = "0" ]; then
          printf '  ✓ %-16s completed (one-shot)\n' "$svc"
        else
          printf '  ✗ %-16s exited (%s)\n' "$svc" "${code:-?}"
          STACK_DOWN="${STACK_DOWN} ${svc}"
        fi ;;
      "")
        printf '  ✗ %-16s no container\n' "$svc"
        STACK_DOWN="${STACK_DOWN} ${svc}" ;;
      *)
        printf '  ✗ %-16s %s\n' "$svc" "$state"
        STACK_DOWN="${STACK_DOWN} ${svc}" ;;
    esac
  done
}

poll_health() {
  echo ""
  echo "Waiting for the stack to come up (polling ${HEALTH_URL}) ..."
  local deadline=$((SECONDS + 180)) body="" overall=""
  while [ $SECONDS -lt $deadline ]; do
    body="$(curl -s -m 8 "$HEALTH_URL" 2>/dev/null || true)"
    overall="$(printf '%s' "$body" | sed -n 's/^{"status":"\([a-z]*\)".*/\1/p')"
    [ "$overall" = "healthy" ] && break
    # "degraded" with nothing wrong but the model provider IS the healthy state
    # of a no-provider install — waiting the full 180s won't change it.
    if [ -n "$body" ] && [ -z "$(health_blockers "$body")" ]; then break; fi
    sleep 5
  done
  echo ""
  check_stack_containers
  if [ -z "$body" ]; then
    echo ""
    echo "✗ No response from ${HEALTH_URL} after 180s — nginx (or the backend behind it) never came up."
    echo "  Inspect with:  docker compose ps"
    echo "                 docker compose logs --tail=100 backend nginx pgsql"
    return 1
  fi
  local blockers
  blockers="$(health_blockers "$body" | tr '\n' ' ')"
  if [ -n "${blockers% }" ] || [ -n "$STACK_DOWN" ]; then
    echo ""
    [ -n "${blockers% }" ] && echo "✗ The backend reports trouble with: ${blockers% }"
    [ -n "$STACK_DOWN" ] && echo "✗ Container(s) not running:${STACK_DOWN}"
    echo "  Inspect with:  docker compose ps"
    echo "                 docker compose logs --tail=100 backend nginx pgsql"
    return 1
  fi
  echo ""
  echo "✓ Harvis is up → http://localhost:9000"
  # The endpoint returns {"needs_setup":..,"setup_complete":..} — extract the
  # one field we need without anchoring to the whole body (a second key was
  # added later, and an anchored match silently yields empty → a false
  # "unreachable" claim right after a 200).
  #
  # Both `|| true`s below are load-bearing under `set -euo pipefail`. grep exits 1
  # when it matches nothing, pipefail promotes that to the pipeline, and a failing
  # command substitution in an assignment ends the script — so on a fresh install
  # this printed "✓ Harvis is up" and then died silently with status 1, never
  # reaching the `*)` branch written for exactly this case and never printing the
  # setup code the first signup needs. Measured on a clean VM: backend container
  # started 03:00:34, installer exited 03:00:40.
  #
  # That timing is the other half of it. The poll above breaks out the moment the
  # health blockers clear, which can be seconds after the backend starts — early
  # enough that this endpoint is not serving yet. So retry briefly instead of
  # treating the first empty answer as the final one.
  local setup_body="" needs="" attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    setup_body="$(curl -s -m 8 "$SETUP_URL" 2>/dev/null || true)"
    needs="$(printf '%s' "$setup_body" | grep -o '"needs_setup" *: *\(true\|false\)' | grep -o 'true\|false' | head -1 || true)"
    [ -n "$needs" ] && break
    sleep 2
  done
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
  # Provider status is informational, never pass/fail: with none configured,
  # report_models below says what to do. Configured-but-unreachable gets its own
  # pointer, because chat will fail until that server answers — but the install
  # itself still succeeded.
  if [ -n "$LLM_ENDPOINT" ]; then
    local provider_state
    provider_state="$(printf '%s' "$body" | sed -n "s/.*\"${PROVIDER_HEALTH_KEY}\":{\"status\":\"\([a-z_]*\)\".*/\1/p")"
    if [ -n "$provider_state" ] && [ "$provider_state" != "up" ]; then
      echo ""
      echo "  ⚠ ${LLM_ENDPOINT} is configured but the backend cannot reach it yet (${provider_state})."
      echo "    Chat has nothing to talk to until that server answers."
    fi
  fi
  report_models
  return 0
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
  # Launching IS the point of running this — "one command, no questions asked".
  # So a bare Enter (and a non-interactive stdin, where read fails and leaves
  # $run empty) builds and starts. --no-launch above, or answering n, opts out.
  local run
  if [ "$ASSUME_YES" -eq 1 ]; then run="y"; else read -rp "Build and start the stack now? [Y/n]: " run || true; fi
  if [[ "${run:-Y}" =~ ^[Nn]$ ]]; then
    echo ""
    echo "When ready, run:  docker compose up --build -d"
  else
    # A failed `up` leaves whatever it managed to create running or half-built.
    # Left behind, those containers hold the very names the next attempt needs,
    # so the retry fails with a name conflict instead of the original error and
    # the user chases the wrong problem. Tear this project's own containers down
    # — only ever ours, selected by the compose project label — and say so.
    if ! docker compose up --build -d; then
      echo ""
      echo "✗ Startup failed. Removing the containers this attempt created so a"
      echo "  retry reports the real error instead of a name conflict..."
      docker compose down --remove-orphans >/dev/null 2>&1 || true
      echo "  Cleaned up. Fix the error above, then run ./install.sh again."
      return 1
    fi
    poll_health
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
  detect_docker_gid
  detect_gpu_runtime
  detect_provider
  select_compose_files
  check_compose_merge
  check_ports
  check_container_names
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
