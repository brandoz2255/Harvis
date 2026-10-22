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
#   ./install.sh --expose local|lan|tunnel|lan+tunnel  # who can reach it (new install: local; --k8s: lan)
#   ./install.sh --k8s --preset NAME   # a site's own defaults from config/presets/NAME.env (not in git)
#   ./install.sh --k8s                  # run Harvis on Kubernetes (k3s) instead of plain Docker
#   ./install.sh --k8s-off              # back to plain Docker; all data kept
#   ./install.sh --k8s-status | --k8s-join-command | --k8s-join URL TOKEN | --k8s-uninstall
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# --expose local|lan|tunnel|lan+tunnel: preflight rows, .env keys, tunnel report.
. scripts/exposure.sh

ASSUME_YES=0
CHECK_ONLY=0
NO_LAUNCH=0
# Where inference happens. "auto" probes the host for a running server; "manual"
# means --llm-url settled it and detection is skipped entirely.
LLM_MODE="auto"
LLM_ENDPOINT=""
LLM_BRIDGE_GW=""
LLM_REACH_FIX=""
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
# Kubernetes hosting mode (scripts/k8s/harvis-k8s.sh). Empty = plain Docker.
K8S_ACTION=""
ADMIN_CODE=0
NODE_ACTION=""
POWER_ACTION=""
K8S_JOIN_ARGS=()
# Set when this run just moved Harvis out of Kubernetes (--k8s-off / --k8s-uninstall).
LEFT_K8S=0
HARVIS_LAUNCHED=0  # set by launch once compose up succeeded
K8S_MODE_FILE=/var/lib/harvis/k8s/mode

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

PRESET_NAME=""
# --preset NAME reads config/presets/NAME.env, which git ignores: a site's network
# names and people stay on that site's machines. It fills in only what the command
# line left out, and is read as KEY=VALUE lines, never run.
load_preset() {
  [ -n "$PRESET_NAME" ] || return 0
  if ! [[ "$PRESET_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "✗ --preset takes a name such as mylab (lower-case letters, digits, - and _)"; exit 1
  fi
  local file="config/presets/${PRESET_NAME}.env" line key value expose="" networks="" emails="" public=""
  [ -f "$file" ] || { echo "✗ No preset '${PRESET_NAME}': ${file} does not exist on this machine"; exit 1; }
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; value="${line#*=}"
    value="$(printf '%s' "$value" | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")"
    case "$key" in
      EXPOSE) expose="$value" ;;
      TUNNEL_NETWORKS) networks="$value" ;;
      ALLOW_EMAILS) emails="$value" ;;
      PUBLIC_ACCESS) public="$value" ;;
      *) echo "✗ ${file}: unknown key '${key}' (EXPOSE, TUNNEL_NETWORKS, ALLOW_EMAILS, PUBLIC_ACCESS)"; exit 1 ;;
    esac
  done < "$file"
  EXPOSE_MODE="${EXPOSE_MODE:-$expose}"
  case "$EXPOSE_MODE" in
    tunnel|lan+tunnel)
      TUNNEL_NETWORKS_ARG="${TUNNEL_NETWORKS_ARG:-$networks}"
      ALLOW_EMAILS_ARG="${ALLOW_EMAILS_ARG:-$emails}"
      PUBLIC_ACCESS="${PUBLIC_ACCESS:-$public}" ;;
  esac
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes|-y) ASSUME_YES=1; shift ;;
      --check-only) CHECK_ONLY=1; shift ;;
      --no-launch) NO_LAUNCH=1; shift ;;
      --k8s) K8S_ACTION=up; shift ;;
      --k8s-off) K8S_ACTION=off; shift ;;
      --k8s-status) K8S_ACTION=status; shift ;;
      --stop) POWER_ACTION=stop; shift ;;
      --start) POWER_ACTION=start; shift ;;
      --admin-code) ADMIN_CODE=1; shift ;;
      --inference-node) NODE_ACTION=run; shift ;;
      --inference-node-service) NODE_ACTION=service; shift ;;
      --k8s-uninstall) K8S_ACTION=uninstall; shift ;;
      --k8s-join-command) K8S_ACTION=join-command; shift ;;
      --k8s-join) K8S_ACTION=join; K8S_JOIN_ARGS=("${2:-}" "${3:-}"); shift $(( $# >= 3 ? 3 : $# )) ;;
      --expose) EXPOSE_MODE="${2:-}"; shift $(( $# >= 2 ? 2 : 1 ))
        [ -n "$EXPOSE_MODE" ] || { echo "✗ --expose needs local, lan, tunnel or lan+tunnel"; exit 1; } ;;
      --expose=*) EXPOSE_MODE="${1#*=}"; shift
        [ -n "$EXPOSE_MODE" ] || { echo "✗ --expose needs local, lan, tunnel or lan+tunnel"; exit 1; } ;;
      --tunnel-networks) TUNNEL_NETWORKS_ARG="${2:-}"; shift $(( $# >= 2 ? 2 : 1 )) ;;
      --tunnel-networks=*) TUNNEL_NETWORKS_ARG="${1#*=}"; shift ;;
      --allow-emails) ALLOW_EMAILS_ARG="${2:-}"; shift $(( $# >= 2 ? 2 : 1 )) ;;
      --allow-emails=*) ALLOW_EMAILS_ARG="${1#*=}"; shift ;;
      --public-access) PUBLIC_ACCESS="${2:-}"; shift $(( $# >= 2 ? 2 : 1 ))
        [ -n "$PUBLIC_ACCESS" ] || { echo "✗ --public-access needs access or harvis"; exit 1; } ;;
      --public-access=*) PUBLIC_ACCESS="${1#*=}"; shift
        [ -n "$PUBLIC_ACCESS" ] || { echo "✗ --public-access needs access or harvis"; exit 1; } ;;
      --preset) PRESET_NAME="${2:-}"; shift $(( $# >= 2 ? 2 : 1 ))
        [ -n "$PRESET_NAME" ] || { echo "✗ --preset needs a name"; exit 1; } ;;
      --preset=*) PRESET_NAME="${1#*=}"; shift
        [ -n "$PRESET_NAME" ] || { echo "✗ --preset needs a name"; exit 1; } ;;
      --llm-url|--ollama-url) LLM_ENDPOINT="${2:-}"; LLM_MODE="manual"; shift 2 ;;
      --llm-url=*|--ollama-url=*) LLM_ENDPOINT="${1#*=}"; LLM_MODE="manual"; shift ;;
      # Accepted and ignored: the stack no longer needs a GPU, so there is no
      # backend to pick. Warn rather than exit 1 — scripts and docs from before
      # this change shouldn't hard-fail on an argument that is simply moot now.
      --backend) echo "⚠ --backend is no longer used (the stack needs no GPU) — ignoring '${2:-}'"; shift 2 ;;
      --backend=*) echo "⚠ --backend is no longer used (the stack needs no GPU) — ignoring '${1#*=}'"; shift ;;
      -h|--help)
        echo "Usage: ./install.sh [--llm-url URL] [--expose MODE] [--yes] [--check-only] [--no-launch]"
        echo ""
        echo "  With no arguments, this looks for a model server already running on"
        echo "  this machine (Ollama, LM Studio, llama.cpp, vLLM), uses it, and then"
        echo "  builds and starts the stack. --no-launch stops after writing .env."
        echo ""
        echo "  --llm-url URL   Skip detection and use this OpenAI-compatible server."
        echo "                  From inside a container 'localhost' is the container,"
        echo "                  not your machine — use host.docker.internal or a LAN IP:"
        echo "                    ./install.sh --llm-url http://host.docker.internal:11434"
        echo ""
        echo "  --expose MODE   Who can reach Harvis. Left out: a new install is local, --k8s is"
        echo "                  lan, and an existing install keeps what it had."
        echo "                  local   this computer only"
        echo "                  lan     your network; the first sign-up becomes admin, then"
        echo "                          sign-up is closed until you open it in Settings"
        echo "                  tunnel  experimental: the internet through a Cloudflare"
        echo "                          Tunnel behind Cloudflare Access (asks for the tunnel"
        echo "                          token, team domain and AUD tag; plain Docker only)"
        echo "                  lan+tunnel  experimental: your network, and the internet"
        echo "                          through the tunnel (Docker or --k8s)"
        echo ""
        echo "  With --expose tunnel or lan+tunnel (each takes 'off' to remove it):"
        echo "  --allow-emails LIST     Only these people get in, even if the Cloudflare"
        echo "                          Access policy is wider: a@x.edu,b@x.edu or @x.edu"
        echo "  --tunnel-networks LIST  Run the tunnel only on these networks (Wi-Fi name"
        echo "                          or NetworkManager connection), e.g. lab-wifi,lab-wired;"
        echo "                          anywhere else it is stopped. Linux with NetworkManager"
        echo "  --public-access WHO     Who checks people arriving through the tunnel:"
        echo "                          access  Cloudflare Access signs them in first (default)"
        echo "                          harvis  no Cloudflare login: they sign up in Harvis and"
        echo "                                  wait until you approve them in Settings → People"
        echo "                                  (asks for the tunnel token only)"
        echo ""
        echo "  --preset NAME   Read this site's defaults from config/presets/NAME.env, a"
        echo "                  file you make on the machine (git ignores it). Lines:"
        echo "                    EXPOSE=lan+tunnel"
        echo "                    TUNNEL_NETWORKS=lab-wifi,lab-wired"
        echo "                    ALLOW_EMAILS=a@x.edu,b@x.edu   (or off: no list)"
        echo "                    PUBLIC_ACCESS=harvis           (or access)"
        echo "                  Flags on the command line win over the file."
        echo ""
        echo "  Kubernetes hosting mode (optional; Linux, needs sudo):"
        echo "  --k8s               Install k3s here and run Harvis in it, same address"
        echo "                      and data. Ollama runs in the cluster (on the GPU when"
        echo "                      there is an NVIDIA one) and its models are shared on"
        echo "                      your network for chat only. With --llm-url, your own"
        echo "                      model server is used instead."
        echo "  --k8s-off           Back to plain Docker. Nothing is deleted."
        echo "  --k8s-status        Nodes, pods and addresses."
        echo "  --k8s-join-command  Print the command another machine runs to join."
        echo ""
        echo "  --stop          Stop Harvis (Docker or Kubernetes) and keep it off after"
        echo "                  a reboot. Nothing is deleted."
        echo "  --start         Start it again after --stop."
        echo ""
        echo "  --admin-code    A new 6-digit first-admin code for a shared server that"
        echo "                  has no admin yet (printed to this terminal only)."
        echo ""
        echo "  Lend this computer's models to a Harvis server elsewhere on your network:"
        echo "  --inference-node          Run the node here. It shows a 6-digit PIN; type it"
        echo "                            into that Harvis under Settings > Models."
        echo "  --inference-node-service  After pairing: keep the node running in the"
        echo "                            background (Linux, a systemd user service)."
        echo "  --k8s-join URL TOKEN  Join this machine to another Harvis as a worker."
        echo "  --k8s-uninstall     --k8s-off, then remove k3s from this machine."
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
  load_preset
  validate_expose_arg
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
  # `|| true`: a port held by anything but Docker (k3s, a local service) makes
  # grep exit 1, and pipefail + `set -e` ended the installer silently.
  docker ps --format '{{.Ports}}\t{{.Label "com.docker.compose.project"}}' 2>/dev/null \
    | grep -E ":$1->" | awk -F'\t' 'NF>1 && $2!="" {print $2; exit}' || true
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

# On the plain Linux engine, host.docker.internal is the Docker bridge gateway,
# not this machine's loopback. Stock Linux Ollama listens on 127.0.0.1 only, so
# it answers this shell and never a container: the installer used to say PASS
# and chat then had no model. Docker Desktop (macOS, Windows, Linux Desktop)
# forwards the name to loopback, so the gap is the Linux engine alone. Probing
# the bridge gateway from here is the same connect a container makes, without
# pulling an image to prove it.
containers_reach_port() { # port — succeeds when a container could connect
  case "$(docker info --format '{{.OperatingSystem}}' 2>/dev/null || true)" in
    *"Docker Desktop"*) return 0 ;;
  esac
  [ "$(uname -s)" = "Linux" ] || return 0
  local gw
  gw="$(docker network inspect bridge --format '{{range .IPAM.Config}}{{.Gateway}} {{end}}' 2>/dev/null \
    | tr ' ' '\n' | grep -m1 -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || true)"
  # No bridge to ask about means no way to tell; do not cry wolf.
  [ -n "$gw" ] || return 0
  LLM_BRIDGE_GW="$gw"
  port_listening "$gw" "$1"
}

add_unreachable_hint() { # port name
  local fix
  if [ "$2" = "Ollama" ]; then
    fix="  Ollama on Linux listens on 127.0.0.1 only. Let it listen for containers too,
  then re-run the installer:
      sudo systemctl edit ollama        # add these two lines and save:
          [Service]
          Environment=\"OLLAMA_HOST=0.0.0.0\"
      sudo systemctl restart ollama
      ./install.sh --yes"
  else
    fix="  Restart ${2} so it listens on 0.0.0.0 instead of 127.0.0.1 (LM Studio: turn on
  \"Serve on Local Network\"; llama.cpp and vLLM: --host 0.0.0.0), then re-run
  ./install.sh --yes"
  fi
  # Kept for the closing summary too: the build prints thousands of lines
  # between the check table and the end, and this is the one thing to act on.
  LLM_REACH_FIX="${fix}"
  add_hint "⚠ ${2} answers on this machine but not from inside Docker (${LLM_BRIDGE_GW}:${1} refused).
  Harvis will start, but chat will have no model until this is fixed.
${fix}
  0.0.0.0 also opens port ${1} to your network; firewall it if that matters.
  Or point Harvis at an address containers can reach:
      ./install.sh --yes --llm-url http://<this machine's LAN IP>:${1}"
}

# Probe from THIS shell (127.0.0.1) but record the URL a CONTAINER will use
# (host.docker.internal). Those are the same listener seen from two sides, and
# conflating them is the classic way a working install can't reach its model.
detect_provider() {
  if [ "$LLM_MODE" = "manual" ]; then
    add_row PASS "model server" "using ${LLM_ENDPOINT} (--llm-url)"
    return 0
  fi
  local entry port name path body count host saved
  # A server already saved in .env is the user's earlier choice and outranks the
  # local probe, as --llm-url does. Re-running on a stack whose server lives on
  # another machine used to print "none found" and "chat has nothing to talk to"
  # while chat worked, and a local server that appeared later silently replaced
  # the saved one. host.docker.internal values were auto-detected, so re-probe.
  # `|| true`: on a fresh clone there is no .env yet; sed's failure under
  # pipefail + `set -e` ended the installer silently right after its banner.
  saved="$(sed -n 's/^HARVIS_LLM_BASE_URL=//p' .env 2>/dev/null | tail -n 1)" || true
  case "$saved" in
    ""|*host.docker.internal*) : ;;
    *)
      LLM_ENDPOINT="$saved"
      LLM_PROVIDER="the server saved in .env"
      body=""
      if command -v curl >/dev/null 2>&1; then
        body="$(curl -s -m 4 "${saved%/}/api/tags" 2>/dev/null || true)"
        case "$body" in *'"models"'*) : ;; *) body="$(curl -s -m 4 "${saved%/}/v1/models" 2>/dev/null || true)" ;; esac
      fi
      case "$body" in
        *'"models"'*|*'"data"'*)
          count="$(printf '%s' "$body" | grep -o '"id"\|"name"' | wc -l | tr -d ' ' || true)"
          add_row PASS "model server" "${saved} (saved in .env), ${count:-0} model(s)" ;;
        *)
          add_row WARN "model server" "${saved} is saved in .env but not answering now — kept; --llm-url changes it" ;;
      esac
      return 0 ;;
  esac
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
      containers_reach_port "$port" || add_unreachable_hint "$port" "$name"
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
    if ! containers_reach_port "$port"; then
      add_row WARN "model server" "${name} at ${host}:${port}, but containers cannot reach it — see below"
      add_unreachable_hint "$port" "$name"
    elif [ "${count:-0}" -gt 0 ]; then
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
  if [ -f "$K8S_MODE_FILE" ]; then
    add_row SKIP "host ports" "Kubernetes mode holds them (re-run)"
    return 0
  fi
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
  # It holds the JWT secret, the database password and the tunnel token; with a
  # 022 umask it would be readable by every account on this machine.
  chmod 600 .env
  # A hand-edited .env often lacks a final newline; every append below would
  # then glue its key onto the last value.
  if [ -s .env ] && [ -n "$(tail -c1 .env)" ]; then printf '\n' >> .env; fi
  # Not compose_project_name: the merged config it reads is gone by now.
  local stack="${HARVIS_STACK_NAME:-$(env_value HARVIS_STACK_NAME)}"
  choose_tunnel_subnet "${stack:-harvis}"
  # enable-https.sh copies the listener once; an install that already has one
  # keeps the copy, so bring it up to date with the template on every run.
  if [ -f nginx/tls/harvis-tls.conf ] && ! cmp -s nginx/tls/harvis-tls.conf.template nginx/tls/harvis-tls.conf; then
    cp nginx/tls/harvis-tls.conf.template nginx/tls/harvis-tls.conf
    echo "✓ Updated the HTTPS listener from its template"
  fi
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
  # No HARVIS_SETUP_CODE is written. On a local install the first signup claims
  # admin outright; nobody else can reach it. On a shared one (lan, k8s) the
  # backend makes a 6-digit first-admin code, keeps only its hash, and this
  # installer prints it to the host's terminal (print_first_admin). An operator
  # who wants a fixed code still adds HARVIS_SETUP_CODE to .env by hand.
  # POSTGRES_PASSWORD — the database ships with a well-known default that is
  # published in this repo, so every install used to share one credential.
  # Postgres only reads this variable at initdb, so an existing database keeps
  # whatever it was created with; sync_db_password makes the database follow
  # .env on every launch, which is what lets a fresh .env sit beside old data.
  ensure_env_secret POSTGRES_PASSWORD "$(rand_hex 24)" "a POSTGRES_PASSWORD"

  # OPENCLAW_GATEWAY_TOKEN — SHARED across backend/openclaw/harvis-mcp; a running
  # stack authenticated with the old value breaks if this ever regenerates.
  ensure_env_secret OPENCLAW_GATEWAY_TOKEN "$(rand_hex 32)" "an OPENCLAW_GATEWAY_TOKEN"
  # MESSAGING_GATEWAY_TOKEN — shared by the backend and the messaging
  # gateway (on by default). Without it the gateway cannot reach the backend.
  ensure_env_secret MESSAGING_GATEWAY_TOKEN "$(rand_hex 32)" "a MESSAGING_GATEWAY_TOKEN"
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
# The backend's own CLI makes the code (see plugins/exposure/first_admin.py);
# a fresh one replaces any older code, so the one printed here is the one that works.
first_admin_cli() {
  local cli=(python -m plugins.exposure.first_admin)
  if [ "$K8S_ACTION" = "up" ] || [ -f "$K8S_MODE_FILE" ]; then
    local sudo=""; [ "$(id -u)" -eq 0 ] || sudo="sudo"
    $sudo k3s kubectl -n harvis exec deploy/backend -- "${cli[@]}"
  else
    docker compose exec -T backend "${cli[@]}"
  fi
}

print_first_admin() {
  # A manual HARVIS_SETUP_CODE or a host-made first-admin code must never land
  # in captured output (tee'd logs, CI transcripts), so either one is written to
  # the terminal directly.
  local code="" tty=0 reach out
  # `-w /dev/tty` only checks permission bits; actually opening it is the real
  # "do we have a controlling terminal" probe.
  ( : > /dev/tty ) 2>/dev/null && tty=1
  # `|| true`: no such key in .env means grep exits 1, and under `set -e` that
  # would end the installer on its very last useful line.
  code="$(grep '^HARVIS_SETUP_CODE=' .env | head -1 | cut -d= -f2- || true)"
  if [ -n "$code" ]; then
    echo "  No admin yet. This instance sets HARVIS_SETUP_CODE, so the first"
    if [ "$tty" -eq 1 ]; then
      echo "  signup will ask for it:"
      printf '    setup code: %s\n' "$code" > /dev/tty
      echo "  (printed to your terminal only — it is also in .env)"
    else
      echo "  signup will ask for it — view it with:  grep '^HARVIS_SETUP_CODE=' .env"
    fi
    return 0
  fi
  reach="$(current_exposure)"
  if [ "$reach" = local ] && [ "$K8S_ACTION" != "up" ] && [ ! -f "$K8S_MODE_FILE" ]; then
    echo "  No admin yet — the first account you sign up with becomes the admin."
    return 0
  fi
  if [ "$tty" -eq 0 ]; then
    echo "  No admin yet. The first sign-up needs a 6-digit code; get one on this"
    echo "  machine with:  ./install.sh --admin-code"
    return 0
  fi
  if out="$(first_admin_cli 2>/dev/null)" && code="$(printf '%s' "$out" | grep -o '[0-9]\{6\}' | head -1)" && [ -n "$code" ]; then
    echo "  No admin yet. Anyone on your network can open the sign-up page, so the"
    echo "  first account needs this code:"
    printf '    first-admin code: %s\n' "$code" > /dev/tty
    echo "  (printed to your terminal only; five wrong tries retire it — get a new"
    echo "  one with ./install.sh --admin-code)"
  else
    echo "  No admin yet. The first sign-up needs a 6-digit code, and making one"
    echo "  failed just now. Try again in a minute:  ./install.sh --admin-code"
  fi
}

# --admin-code: a fresh first-admin code, for a shared server with no admin yet.
cmd_admin_code() {
  local out code
  if ! out="$(first_admin_cli 2>&1)"; then
    printf '%s\n' "$out" | tail -3
    echo "✗ No code was made. Is Harvis running? (./install.sh --k8s-status or docker compose ps)"
    return 1
  fi
  code="$(printf '%s' "$out" | grep -o '[0-9]\{6\}' | head -1 || true)"
  if [ -z "$code" ]; then printf '%s\n' "$out"; return 1; fi
  if ( : > /dev/tty ) 2>/dev/null; then
    printf 'First-admin code: %s\n' "$code" > /dev/tty
    echo "(printed to your terminal only; the old code no longer works)"
  else
    echo "✗ No terminal to print the code to; run this from a terminal on the server."
    return 1
  fi
}

# --inference-node: this computer serves its Ollama to a Harvis server elsewhere.
# The node is one stdlib Python file, so it also runs on a machine without Harvis.
NODE_SCRIPT="scripts/inference-node/harvis_node.py"
cmd_inference_node() { # $1 = run | service
  command -v python3 >/dev/null || { echo "✗ python3 is needed for the inference node."; return 1; }
  if ! curl -s -m 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    echo "⚠ Ollama is not answering on this computer (127.0.0.1:11434). Start it first,"
    echo "  or pass the node --ollama URL."
  fi
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [ "$1" = run ]; then
    echo "In Harvis, Settings > Models > Add a computer, enter ${ip:-the address of this computer} and the PIN below."
    echo "Ctrl-C stops the node; ./install.sh --inference-node-service keeps it running after pairing."
    exec python3 "$NODE_SCRIPT"
  fi
  command -v systemctl >/dev/null || { echo "✗ The background service needs systemd. Run ./install.sh --inference-node in a terminal instead."; return 1; }
  if ! python3 "$NODE_SCRIPT" --print-state | grep -q '"paired": *true'; then
    echo "✗ Pair first: run ./install.sh --inference-node, enter the PIN in Harvis, then run this again."
    return 1
  fi
  local unit_dir="$HOME/.config/systemd/user"
  mkdir -p "$unit_dir"
  cat > "$unit_dir/harvis-node.service" <<UNIT
[Unit]
Description=Harvis inference node (lends this computer's Ollama to a paired Harvis)
After=network-online.target

[Service]
ExecStart=$(command -v python3) $PWD/$NODE_SCRIPT
Restart=on-failure

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now harvis-node.service
  echo "✓ The node runs in the background (systemctl --user status harvis-node)."
  echo "  It stops when you log out unless lingering is on:  loginctl enable-linger $USER"
}

report_models() {
  # Kubernetes mode runs its own Ollama in the cluster and has already printed
  # how to pull a model into it.
  if [ "$K8S_ACTION" = "up" ] && [ "${HARVIS_K8S_OLLAMA:-1}" = "1" ]; then return 0; fi
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
  # $1 is the backend's view of that server. Anything but "up" was already
  # explained above; advice about loading models would contradict it.
  if [ -n "${1:-}" ] && [ "$1" != "up" ]; then
    echo "  Fix the connection above first, then pick a model in the setup wizard."
    return 0
  fi
  case "$LLM_PROVIDER" in
    Ollama) echo "  The setup wizard ranks the models this machine can run and pulls the one you pick." ;;
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
# services (artifact-init, hermes-ui-builder) are one-shot jobs that SHOULD exit 0,
# so read states with -a and judge exited containers by their exit code.
# Failed services land in STACK_DOWN for the caller to act on.
STACK_DOWN=""
check_stack_containers() {
  STACK_DOWN=""
  # In Kubernetes mode harvis-k8s.sh already waited on every Deployment and
  # printed the result; docker compose ps would only show nothing running.
  [ "$K8S_ACTION" = "up" ] && return 0
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
  echo "✓ Harvis is up → http://localhost:9000/harvis/"
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
  # first-admin line the operator needs. Measured on a clean VM: backend container
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
    true)  print_first_admin ;;
    false) echo "  Instance already has an admin — sign in as usual." ;;
    *)     if [ -z "$setup_body" ]; then
             echo "  Could not reach ${SETUP_URL} — if this is a fresh install, the first"
             echo "  account you sign up with becomes the admin."
           else
             echo "  ${SETUP_URL} answered but its state was unrecognised — if this is a"
             echo "  fresh install, the first account you sign up with becomes the admin."
           fi ;;
  esac
  # tunnel visitors already arrive over Cloudflare's HTTPS, and enable-https.sh
  # drives the Docker nginx, not Kubernetes. Port 9000 counts as shared when it is
  # bound to every address, recorded mode or not (an upgrade can keep it open).
  local reach
  reach="$(current_exposure)"
  if [ "$reach" != tunnel ] && [ "$reach" != lan+tunnel ] && [ "$(env_value HARVIS_BIND_ADDR_PUBLIC)" = "0.0.0.0" ]; then
    [ "$reach" = lan ] || echo "  ⚠ Port 9000 is open to your network and the first sign-up becomes admin."
    reach=lan
  fi
  [ "$K8S_ACTION" = "up" ] && reach=k8s
  case "$reach" in
    local)
      echo ""
      echo "  Harvis answers on this computer only. To use it from a phone, tablet or"
      echo "  another computer, share it on your network, then turn on HTTPS:"
      echo ""
      echo "      ./install.sh --expose lan"
      echo "      ./scripts/enable-https.sh"
      echo ""
      echo "  Browsers hand out the microphone only over https (or at localhost), so"
      echo "  voice will not work from other devices without the second step." ;;
    lan)
      echo ""
      echo "  Using Harvis from a phone, tablet or another computer? Turn on HTTPS:"
      echo ""
      echo "      ./scripts/enable-https.sh"
      echo ""
      echo "  Browsers hand out the microphone only over https (or on this machine at"
      echo "  localhost), so voice will not work from other devices until you do. The"
      echo "  script makes its own certificate, so the first visit shows a warning you"
      echo "  click past once. Plain http on :9000 keeps working either way."
      echo ""
      echo "  Auth cookie: HARVIS_COOKIE_SECURE defaults to false, which is what lets"
      echo "  the http lane log in. Set it to true in .env only if you have switched to"
      echo "  https for everyone — a Secure cookie is not sent over http at all, so"
      echo "  turning it on while anyone still uses :9000 locks them out." ;;
    lan+tunnel)
      echo ""
      echo "  Your network reaches Harvis on port 9000; sign-up is closed, so add people"
      echo "  in Settings. For the microphone from other devices here, turn on HTTPS:"
      echo ""
      echo "      ./scripts/enable-https.sh"
      echo ""
      echo "  Leave HARVIS_COOKIE_SECURE unset: the tunnel port marks the cookie Secure"
      echo "  itself, and the http lane on :9000 needs it plain." ;;
  esac
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
      if [ -n "$LLM_REACH_FIX" ]; then printf '%s\n' "$LLM_REACH_FIX"; fi
    fi
  fi
  report_models "${provider_state:-}"
  return 0
}

# The database keeps the password it was created with, while every service
# connects with the one in .env. A fresh clone beside an old database (or one a
# --k8s run created) left the backend running with no database: "password
# authentication failed for user pguser". Postgres trusts its own local socket,
# so set the role's password from the container's env before anything else
# starts. Idempotent, and the value never leaves the container.
sync_db_password() {
  local i
  echo "Starting the database ..."
  docker compose up -d pgsql >/dev/null || return 1
  for i in $(seq 1 30); do
    if printf "ALTER ROLE pguser WITH PASSWORD :'pw';\n" | docker compose exec -T pgsql \
        sh -c 'psql -q -v ON_ERROR_STOP=1 -v pw="$POSTGRES_PASSWORD" -U pguser -d postgres' >/dev/null 2>&1; then
      echo "✓ Database password matches .env"
      return 0
    fi
    sleep 2
  done
  echo "⚠ Could not confirm the database password; if sign-in fails with \"Database"
  echo "  unavailable\", run ./install.sh --yes again."
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
    sync_db_password || true
    if docker compose up --build -d; then
      HARVIS_LAUNCHED=1
    else
      echo ""
      echo "✗ Startup failed. Removing the containers this attempt created so a"
      echo "  retry reports the real error instead of a name conflict..."
      docker compose down --remove-orphans >/dev/null 2>&1 || true
      echo "  Cleaned up. Fix the error above, then run ./install.sh again."
      return 1
    fi
    # The backend opens its database pool once at start. One left running from an
    # earlier attempt with the old password keeps failing until it restarts.
    if docker compose logs --tail 200 backend 2>/dev/null | grep -q 'password authentication failed'; then
      echo "Restarting the backend so it signs in with the synced password ..."
      docker compose restart backend >/dev/null || true
    fi
    # nginx bind-mounts its config files and the two UI builds. `git pull` and the
    # builders replace those paths rather than writing into them, and a running
    # container keeps the old ones: a re-run served the previous routes and the
    # previous UI until someone restarted nginx by hand. `up` leaves an unchanged
    # container alone, so restart it here; it takes about a second.
    docker compose restart nginx >/dev/null 2>&1 || true
    poll_health
  fi
}

# ── Main ────────────────────────────────────────────────────────────────────
run_k8s() { # $@ = harvis-k8s.sh arguments
  bash scripts/k8s/harvis-k8s.sh "$@"
}

# The Shut down button's host watcher (scripts/power-button.sh). Only with
# passwordless sudo: a Docker install never stops to ask for a password.
setup_power_button() {
  [ -d /run/systemd/system ] || return 0
  if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
    if ! bash scripts/power-button.sh installed; then
      echo "  The Shut down button in Command Center needs a root watcher. Add it: sudo -v && ./install.sh"
    fi
    return 0
  fi
  # Optional: a watcher that will not install leaves the button hidden, not the install broken.
  if HARVIS_POWER_SUDO="sudo -n" bash scripts/power-button.sh install; then
    set_env_value HARVIS_CONTROL_DIR /var/lib/harvis/control
  fi
}

# One switch for both modes. A joined worker has no mode file, only k3s-agent.
cmd_power() { # stop|start
  if [ -f "$K8S_MODE_FILE" ] || systemctl cat k3s-agent >/dev/null 2>&1; then run_k8s "$1"; return $?; fi
  if [ "$1" = stop ]; then
    # Stopped, not removed: "unless-stopped" containers then stay down across reboots.
    docker compose stop && echo "✓ Harvis is stopped and stays off after a reboot. Nothing was deleted." &&
      echo "  Start it again: ./install.sh --start"
  else
    # A Shut down press that was never picked up would stop it again at once.
    HARVIS_POWER_SUDO="sudo -n" bash scripts/power-button.sh clear 2>/dev/null || true
    docker compose start || { echo "✗ No stopped Harvis to start here — run ./install.sh"; return 1; }
    echo "✓ Harvis is back → http://localhost:9000/harvis/"
  fi
}

# Kubernetes mode after the normal preflight and .env: build the images with
# Docker, then hand the stack to k3s. The generated secrets in .env are the
# same ones either mode uses, so switching back and forth keeps logins working.
launch_k8s() {
  if [ "$(uname -s)" != "Linux" ]; then
    echo "✗ Kubernetes hosting mode needs Linux (k3s). Plain Docker mode works everywhere."
    return 1
  fi
  if [ "$LLM_MODE" = "manual" ]; then export HARVIS_K8S_OLLAMA=0; fi
  echo ""
  echo "Building Harvis images ..."
  docker compose build
  run_k8s up
  poll_health
}

main() {
  parse_args "$@"
  echo "Harvis installer"
  echo "================"
  if [ -n "$PRESET_NAME" ]; then echo "Preset: config/presets/${PRESET_NAME}.env"; fi
  if [ "$ADMIN_CODE" -eq 1 ]; then cmd_admin_code; exit $?; fi
  if [ -n "$NODE_ACTION" ]; then cmd_inference_node "$NODE_ACTION"; exit $?; fi
  if [ -n "$POWER_ACTION" ]; then cmd_power "$POWER_ACTION"; exit $?; fi
  case "$K8S_ACTION" in
    status|join-command) run_k8s "$K8S_ACTION"; exit $? ;;
    join) run_k8s join "${K8S_JOIN_ARGS[@]}"; exit $? ;;
    # Leaving Kubernetes runs the full Docker launch below rather than a bare
    # `compose up`: that skipped the new .env secrets, the database password sync
    # and the image builds, so a switch back could start a backend that cannot sign in.
    # Tunnel values are asked first: after teardown the run is non-interactive.
    # The exposure checks run before Kubernetes stops: failing them afterwards
    # left Harvis running in neither Kubernetes nor Docker.
    off|uninstall) collect_exposure_inputs
      check_exposure
      if [ "$CHECK_FAILED" -eq 1 ]; then
        print_check_table
        echo "✗ Preflight failed — nothing was changed; Harvis still runs in Kubernetes."
        exit 1
      fi
      CHECK_ROWS=(); CHECK_HINTS=()
      HARVIS_K8S_OFF_SKIP_START=1 run_k8s "$K8S_ACTION" || exit $?; K8S_ACTION=""; ASSUME_YES=1; LEFT_K8S=1 ;;
  esac
  if [ -z "$K8S_ACTION" ] && [ -f "$K8S_MODE_FILE" ] && [ "$CHECK_ONLY" -eq 0 ]; then
    echo "✗ Harvis is running in Kubernetes mode on this machine."
    echo "  Update it with:          ./install.sh --k8s"
    echo "  Go back to plain Docker: ./install.sh --k8s-off"
    exit 1
  fi
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
  choose_default_exposure
  check_exposure
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
  collect_exposure_inputs
  write_env
  write_exposure_env
  ensure_network
  if [ "$K8S_ACTION" = "up" ]; then launch_k8s; else
    # Docker mode: the agent browser reaches the internet, not this machine or the LAN.
    # Kubernetes does the same with a NetworkPolicy (scripts/k8s/k8s_harden.py).
    bash scripts/browser-egress-lock.sh apply || true
    setup_power_button
    launch; report_exposure
  fi
}

main "$@"
