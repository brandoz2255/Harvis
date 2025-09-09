#!/bin/bash

# Jarvis Backend Service Runner
# This script manages the Python backend service

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Jarvis Backend Service Manager${NC}"
echo "================================"

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
  echo -e "${RED}Error: Docker is not running${NC}"
  exit 1
fi

# Check if env file exists
ENV_FILE="$(pwd)/python_back_end/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo -e "${RED}Error: Environment file not found at $ENV_FILE${NC}"
  exit 1
fi

# Function to show usage
show_usage() {
  echo "Usage: $0 [COMMAND]"
  echo ""
  echo "Commands:"
  echo "  start       Start the backend service"
  echo "  stop        Stop the backend service"
  echo "  restart     Restart the backend service"
  echo "  logs        Show backend service logs"
  echo "  status      Show backend service status"
  echo "  shell       Open interactive shell in backend container"
  echo ""
  echo "Examples:"
  echo "  $0 start"
  echo "  $0 restart"
  echo "  $0 logs"
}

# Function to check if container is running
is_running() {
  docker ps | grep -q "backend"
}

# Function to start backend service
start_backend() {
  if is_running; then
    echo -e "${YELLOW}Backend service is already running${NC}"
    return 0
  fi

  echo -e "${BLUE}Starting Jarvis Backend Service...${NC}"

  # Stop and remove existing container if it exists
  docker stop backend 2>/dev/null || true
  docker rm backend 2>/dev/null || true

  # Start the backend service
  docker run --rm -it \
    --name backend \
    --gpus all \
    -p 8000:8000 \
    --env-file "$ENV_FILE" \
    --network ollama-n8n-network \
    -v "$(pwd)/python_back_end:/app" \
    -v "$(pwd)/embedding:/app/embedding" \
    -v /tmp:/tmp \
    -v /var/run/docker.sock:/var/run/docker.sock \
    dulc3/jarvis-backend:latest \
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
}

# Function to start backend service in background
start_backend_detached() {
  if is_running; then
    echo -e "${YELLOW}Backend service is already running${NC}"
    return 0
  fi

  echo -e "${BLUE}Starting Jarvis Backend Service (detached)...${NC}"

  # Stop and remove existing container if it exists
  docker stop backend 2>/dev/null || true
  docker rm backend 2>/dev/null || true

  # Start the backend service in detached mode
  docker run -d \
    --name backend \
    --gpus all \
    -p 8000:8000 \
    --env-file "$ENV_FILE" \
    --network ollama-n8n-network \
    -v "$(pwd)/python_back_end:/app" \
    -v "$(pwd)/embedding:/app/embedding" \
    -v /tmp:/tmp \
    -v /var/run/docker.sock:/var/run/docker.sock \
    dulc3/jarvis-backend:latest \
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

  echo -e "${GREEN}Backend service started successfully!${NC}"
  echo -e "${BLUE}Backend API available at: http://localhost:8000${NC}"
}

# Function to stop backend service
stop_backend() {
  if ! is_running; then
    echo -e "${YELLOW}Backend service is not running${NC}"
    return 0
  fi

  echo -e "${BLUE}Stopping Jarvis Backend Service...${NC}"
  docker stop backend
  docker rm backend 2>/dev/null || true
  echo -e "${GREEN}Backend service stopped successfully!${NC}"
}

# Function to restart backend service
restart_backend() {
  echo -e "${BLUE}Restarting Jarvis Backend Service...${NC}"
  stop_backend
  sleep 2
  start_backend_detached
}

# Function to show logs
show_logs() {
  if ! is_running; then
    echo -e "${RED}Backend service is not running${NC}"
    exit 1
  fi

  echo -e "${BLUE}Showing backend service logs (Ctrl+C to exit):${NC}"
  docker logs -f backend
}

# Function to show status
show_status() {
  if is_running; then
    echo -e "${GREEN}Backend service is running${NC}"
    echo ""
    echo "Container details:"
    docker ps | grep backend
    echo ""
    echo "Service endpoints:"
    echo "- API: http://localhost:8000"
    echo "- Docs: http://localhost:8000/docs"
    echo "- Health: http://localhost:8000/health"
  else
    echo -e "${RED}Backend service is not running${NC}"
  fi
}

# Function to open shell
open_shell() {
  if ! is_running; then
    echo -e "${RED}Backend service is not running${NC}"
    echo "Starting temporary container for shell access..."

    docker run --rm -it \
      --name backend-shell \
      --gpus all \
      --env-file "$ENV_FILE" \
      --network ollama-n8n-network \
      -v "$(pwd)/python_back_end:/app" \
      -v "$(pwd)/embedding:/app/embedding" \
      -v /tmp:/tmp \
      -v /var/run/docker.sock:/var/run/docker.sock \
      dulc3/jarvis-backend:latest \
      /bin/bash
  else
    echo -e "${BLUE}Opening shell in running backend container...${NC}"
    docker exec -it backend /bin/bash
  fi
}

# Main command handling
case "${1:-help}" in
"start")
  start_backend
  ;;
"start-bg" | "start-detached")
  start_backend_detached
  ;;
"stop")
  stop_backend
  ;;
"restart")
  restart_backend
  ;;
"logs")
  show_logs
  ;;
"status")
  show_status
  ;;
"shell")
  open_shell
  ;;
"help" | *)
  show_usage
  ;;
esac
