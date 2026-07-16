#!/usr/bin/env bash
# Harvis installer — pick your inference backend (NVIDIA / AMD / CPU), write the
# right compose selection + a JWT secret into .env, create the docker network, and
# optionally bring the stack up. Re-run any time to switch backends.
#
#   ./install.sh              # interactive
#   ./install.sh --backend cpu --yes   # non-interactive (nvidia|amd|cpu)
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKEND=""
ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="${2:-}"; shift 2 ;;
    --backend=*) BACKEND="${1#*=}"; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) echo "Usage: ./install.sh [--backend nvidia|amd|cpu] [--yes]"; exit 0 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

echo "Harvis installer"
echo "================"

# ── 1. Prerequisites ────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || { echo "✗ Docker not found — install Docker first."; exit 1; }
if ! docker compose version >/dev/null 2>&1; then
  echo "✗ Docker Compose v2 ('docker compose') not found — install the compose plugin."; exit 1
fi
echo "✓ docker + docker compose present"

# ── 2. Detect a likely backend ──────────────────────────────────────────────
detected="cpu"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  detected="nvidia"
elif [ -e /dev/kfd ] || command -v rocminfo >/dev/null 2>&1; then
  detected="amd"
fi
echo "• Detected backend: ${detected}"
case "$(uname -s)" in
  Darwin) echo "  Note: on macOS, Docker can't use the Mac GPU — this picks CPU. For Metal speed,"
          echo "        run Ollama NATIVELY and set OLLAMA_URL=http://host.docker.internal:11434." ;;
esac

# ── 3. Choose backend ───────────────────────────────────────────────────────
if [ -z "$BACKEND" ]; then
  echo ""
  echo "Choose your inference backend:"
  echo "  1) nvidia   NVIDIA GPU + nvidia-container-toolkit (fastest)"
  echo "  2) amd      AMD GPU via ROCm — accelerates Ollama; TTS/STT stay CPU"
  echo "  3) cpu      No GPU — runs anywhere, much slower"
  read -rp "Backend [${detected}]: " choice || true
  choice="${choice:-$detected}"
  case "$choice" in
    1|nvidia) BACKEND=nvidia ;;
    2|amd)    BACKEND=amd ;;
    3|cpu)    BACKEND=cpu ;;
    *) echo "✗ Unknown choice '$choice'"; exit 1 ;;
  esac
fi
case "$BACKEND" in
  nvidia|amd|cpu) : ;;
  *) echo "✗ --backend must be nvidia|amd|cpu (got '$BACKEND')"; exit 1 ;;
esac

# ── 4. Map backend → COMPOSE_FILE ───────────────────────────────────────────
case "$BACKEND" in
  nvidia) COMPOSE_FILE="docker-compose.yaml" ;;
  amd)    COMPOSE_FILE="docker-compose.yaml:docker-compose.amd.yml" ;;
  cpu)    COMPOSE_FILE="docker-compose.yaml:docker-compose.cpu.yml" ;;
esac

# ── 5. Write .env (preserve existing values) ────────────────────────────────
touch .env
# COMPOSE_FILE — docker compose auto-reads this, so `docker compose up` uses the right files.
if grep -q '^COMPOSE_FILE=' .env; then
  tmp="$(mktemp)"; grep -v '^COMPOSE_FILE=' .env > "$tmp"; mv "$tmp" .env
fi
printf 'COMPOSE_FILE=%s\n' "$COMPOSE_FILE" >> .env
# JWT_SECRET — required by the stack; generate one if absent.
if ! grep -q '^JWT_SECRET=' .env; then
  secret="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  printf 'JWT_SECRET=%s\n' "$secret" >> .env
  echo "✓ Generated a JWT_SECRET"
fi
echo "✓ Wrote .env  (COMPOSE_FILE=${COMPOSE_FILE})"

# ── 6. Network + optional launch ────────────────────────────────────────────
docker network inspect ollama-n8n-network >/dev/null 2>&1 || docker network create ollama-n8n-network >/dev/null
echo "✓ docker network 'ollama-n8n-network' ready"

echo ""
echo "Backend selected: ${BACKEND}"
case "$BACKEND" in
  amd) echo "  Note: AMD accelerates Ollama (chat/agents); voice (TTS + Whisper STT) runs on CPU." ;;
  cpu) echo "  Note: everything runs on CPU — inference is slower and voice (TTS/STT) may lag." ;;
esac
if [ "$ASSUME_YES" -eq 1 ]; then run="y"; else read -rp "Build and start the stack now? [y/N]: " run || true; fi
if [[ "${run:-N}" =~ ^[Yy]$ ]]; then
  docker compose up --build -d
  echo ""
  echo "✓ Harvis is starting → http://localhost:9000"
else
  echo ""
  echo "When ready, run:  docker compose up --build -d   (.env selects the ${BACKEND} backend)"
fi
