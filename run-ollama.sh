#!/bin/bash

# Ollama Service Runner
# This script manages the Ollama GPU service

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Ollama Service Manager${NC}"
echo "====================="

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Check if GPU is available
check_gpu() {
    if ! command -v nvidia-smi &> /dev/null; then
        echo -e "${YELLOW}Warning: nvidia-smi not found. GPU support may not be available.${NC}"
        return 1
    fi
    
    if ! nvidia-smi &> /dev/null; then
        echo -e "${YELLOW}Warning: NVIDIA GPU not detected or driver issue.${NC}"
        return 1
    fi
    
    return 0
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  start       Start the Ollama service"
    echo "  stop        Stop the Ollama service"
    echo "  restart     Restart the Ollama service"
    echo "  logs        Show Ollama service logs"
    echo "  status      Show Ollama service status"
    echo "  shell       Open interactive shell in Ollama container"
    echo "  models      List available models"
    echo "  pull        Pull a model (requires model name as second argument)"
    echo "  gpu-check   Check GPU availability"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 models"
    echo "  $0 pull mistral"
    echo "  $0 logs"
}

# Function to check if container is running
is_running() {
    docker ps | grep -q "ollama"
}

# Function to start Ollama service
start_ollama() {
    if is_running; then
        echo -e "${YELLOW}Ollama service is already running${NC}"
        return 0
    fi
    
    echo -e "${BLUE}Starting Ollama Service...${NC}"
    
    # Check GPU availability
    GPU_FLAG=""
    if check_gpu; then
        echo -e "${GREEN}GPU detected - enabling GPU support${NC}"
        GPU_FLAG="--gpus all"
    else
        echo -e "${YELLOW}Running in CPU-only mode${NC}"
    fi
    
    # Stop and remove existing container if it exists
    docker stop ollama 2>/dev/null || true
    docker rm ollama 2>/dev/null || true
    
    # Start the Ollama service
    docker run -d $GPU_FLAG \
        --name ollama \
        --network ollama-n8n-network \
        -v ollama:/root/.ollama \
        -p 11434:11434 \
        ollama/ollama
    
    echo -e "${GREEN}Ollama service started successfully!${NC}"
    echo -e "${BLUE}Ollama API available at: http://localhost:11434${NC}"
    
    # Wait a moment for service to be ready
    echo -e "${BLUE}Waiting for Ollama service to be ready...${NC}"
    sleep 3
    
    # Check if service is responding
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo -e "${GREEN}Ollama service is ready and responding!${NC}"
    else
        echo -e "${YELLOW}Ollama service started but may still be initializing...${NC}"
    fi
}

# Function to stop Ollama service
stop_ollama() {
    if ! is_running; then
        echo -e "${YELLOW}Ollama service is not running${NC}"
        return 0
    fi
    
    echo -e "${BLUE}Stopping Ollama Service...${NC}"
    docker stop ollama
    docker rm ollama 2>/dev/null || true
    echo -e "${GREEN}Ollama service stopped successfully!${NC}"
}

# Function to restart Ollama service
restart_ollama() {
    echo -e "${BLUE}Restarting Ollama Service...${NC}"
    stop_ollama
    sleep 2
    start_ollama
}

# Function to show logs
show_logs() {
    if ! is_running; then
        echo -e "${RED}Ollama service is not running${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}Showing Ollama service logs (Ctrl+C to exit):${NC}"
    docker logs -f ollama
}

# Function to show status
show_status() {
    if is_running; then
        echo -e "${GREEN}Ollama service is running${NC}"
        echo ""
        echo "Container details:"
        docker ps | grep ollama
        echo ""
        echo "Service endpoints:"
        echo "- API: http://localhost:11434"
        echo "- Models: http://localhost:11434/api/tags"
        echo ""
        
        # Try to show available models
        echo "Available models:"
        if curl -s http://localhost:11434/api/tags 2>/dev/null | grep -q "models"; then
            curl -s http://localhost:11434/api/tags | jq -r '.models[].name' 2>/dev/null || echo "Unable to parse models list"
        else
            echo "Unable to fetch models list (service may be starting)"
        fi
    else
        echo -e "${RED}Ollama service is not running${NC}"
    fi
}

# Function to open shell
open_shell() {
    if ! is_running; then
        echo -e "${RED}Ollama service is not running${NC}"
        echo "Start the service first with: $0 start"
        exit 1
    fi
    
    echo -e "${BLUE}Opening shell in Ollama container...${NC}"
    docker exec -it ollama /bin/bash
}

# Function to list models
list_models() {
    if ! is_running; then
        echo -e "${RED}Ollama service is not running${NC}"
        echo "Start the service first with: $0 start"
        exit 1
    fi
    
    echo -e "${BLUE}Available Ollama models:${NC}"
    if command -v jq &> /dev/null; then
        curl -s http://localhost:11434/api/tags | jq -r '.models[] | "\(.name) - \(.size/1024/1024/1024 | floor)GB"'
    else
        curl -s http://localhost:11434/api/tags
    fi
}

# Function to pull a model
pull_model() {
    local model_name="$1"
    
    if [ -z "$model_name" ]; then
        echo -e "${RED}Error: Model name required${NC}"
        echo "Usage: $0 pull <model_name>"
        echo "Example: $0 pull mistral"
        exit 1
    fi
    
    if ! is_running; then
        echo -e "${RED}Ollama service is not running${NC}"
        echo "Start the service first with: $0 start"
        exit 1
    fi
    
    echo -e "${BLUE}Pulling model: $model_name${NC}"
    docker exec -it ollama ollama pull "$model_name"
}

# Function to check GPU
check_gpu_info() {
    echo -e "${BLUE}GPU Information:${NC}"
    
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi
        echo ""
        echo -e "${BLUE}Docker GPU Runtime:${NC}"
        docker run --rm --gpus all nvidia/cuda:11.0-base-ubuntu20.04 nvidia-smi 2>/dev/null || echo "GPU runtime not available in Docker"
    else
        echo -e "${RED}nvidia-smi not found. GPU support not available.${NC}"
    fi
}

# Main command handling
case "${1:-help}" in
    "start")
        start_ollama
        ;;
    "stop")
        stop_ollama
        ;;
    "restart")
        restart_ollama
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
    "models")
        list_models
        ;;
    "pull")
        pull_model "$2"
        ;;
    "gpu-check")
        check_gpu_info
        ;;
    "help"|*)
        show_usage
        ;;
esac