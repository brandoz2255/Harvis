# Reuse the models of an Ollama already running on this machine. Sourced by
# harvis-k8s.sh, which provides say, kc, NS and env_get_raw.
#
# Security: this adds no exposure. The host Ollama is only named to the backend
# so its pods can call it at the node IP. If it listens beyond loopback, that
# was the machine's own setting; nothing here opens or forwards a port.
HOST_OLLAMA_PORT=11434
HOST_OLLAMA_NAME=this-computer
HOST_OLLAMA_ENTRY=""

tcp_open() { (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null; }

host_ollama_answers() {
  command -v curl >/dev/null 2>&1 || return 1
  local body
  body="$(curl -fsS -m 3 "http://127.0.0.1:$HOST_OLLAMA_PORT/api/tags" 2>/dev/null)" || return 1
  case "$body" in *'"models"'*) return 0 ;; esac
  return 1
}

# Our own lan-models Service is published on this port by ServiceLB and answers
# /api/tags too; that is the cluster's Ollama, not a host one.
lan_models_serves() { # port
  [ "$(kc -n "$NS" get svc lan-models -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || true)" = "$1" ]
}

existing_hosts() { printf '%s' "${HARVIS_OLLAMA_HOSTS-$(env_get_raw HARVIS_OLLAMA_HOSTS)}"; }

hosts_with_entry() { # existing value, entry — appended, never overwritten
  case "$1" in
    *"$HOST_OLLAMA_NAME="*) printf '%s' "$1" ;;
    "["*) printf '%s' "$1" ;;
    "") printf '%s' "$2" ;;
    *) printf '%s,%s' "${1%,}" "$2" ;;
  esac
}

detect_host_ollama() { # node IP — sets HOST_OLLAMA_ENTRY when pods can reuse it
  HOST_OLLAMA_ENTRY=""
  [ "${HARVIS_K8S_REUSE_HOST_OLLAMA:-1}" = "0" ] && return 0
  [ "${HARVIS_K8S_OLLAMA:-1}" = "1" ] || return 0
  host_ollama_answers || return 0
  lan_models_serves "$HOST_OLLAMA_PORT" && return 0
  case "$(existing_hosts)" in
    "["*) say "• HARVIS_OLLAMA_HOSTS is a JSON list, so the Ollama on this machine was not added; add $HOST_OLLAMA_NAME=http://$1:$HOST_OLLAMA_PORT to it to reuse its models"; return 0 ;;
  esac
  if tcp_open "$1" "$HOST_OLLAMA_PORT"; then
    HOST_OLLAMA_ENTRY="$HOST_OLLAMA_NAME=http://$1:$HOST_OLLAMA_PORT|label=This computer"
    say "✓ Ollama on this machine found — its models are available in Harvis as \"This computer\""
  else
    say "⚠ Ollama on this machine listens on 127.0.0.1 only, so Kubernetes mode cannot reuse its models. To allow it: sudo systemctl edit ollama,"
    say "  add [Service] Environment=\"OLLAMA_HOST=0.0.0.0\", sudo systemctl restart ollama, re-run ./install.sh --k8s (0.0.0.0 also opens port $HOST_OLLAMA_PORT to your network)"
  fi
  return 0
}
