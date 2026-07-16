#!/bin/bash
# build-and-run.sh - Build and run Harvis with Docker Compose.
#
# This inherits your backend choice from .env (COMPOSE_FILE=…), which ./install.sh
# writes. If you haven't run the installer yet, this uses the NVIDIA default and
# requires an NVIDIA GPU + nvidia-container-toolkit. For CPU/AMD, run ./install.sh
# first (it picks the backend and writes COMPOSE_FILE + a JWT secret).

set -e

# The stack's shared network is external — create it if missing (compose won't).
docker network inspect ollama-n8n-network >/dev/null 2>&1 || docker network create ollama-n8n-network

echo "🚀 Building Harvis Docker Compose images..."
docker compose build

echo "✅ Build complete!"
echo "🏃 Starting services..."
docker compose up -d

echo "🎉 Harvis is running! → http://localhost:9000"
echo "📊 Check status with: docker compose ps"
echo "📜 View logs with:    docker compose logs -f"
