#!/bin/bash

# n8n Workflow Embedding Service Runner
# This script helps you run the embedding service in Docker

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}n8n Workflow Embedding Service${NC}"
echo "================================"

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Function to show usage
show_usage() {
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  build       Build the embedding service Docker image"
    echo "  test        Test the embedding system"
    echo "  embed-all   Embed all workflow repositories"
    echo "  embed-n8n   Embed only n8n-workflows repository"
    echo "  search      Search workflows (requires query as second argument)"
    echo "  stats       Show collection statistics"
    echo "  shell       Open interactive shell in container"
    echo "  logs        Show container logs"
    echo "  clean       Remove container and images"
    echo ""
    echo "Examples:"
    echo "  $0 build"
    echo "  $0 test"
    echo "  $0 embed-all"
    echo "  $0 search \"email automation\""
    echo "  $0 stats"
    echo "  $0 shell"
}

# Function to build the Docker image
build_image() {
    echo -e "${YELLOW}Building embedding service Docker image...${NC}"
    docker build -t n8n-embedding-service .
    echo -e "${GREEN}Image built successfully!${NC}"
}

# Function to run a command in the container
run_command() {
    local cmd="$1"
    
    # Ensure the image exists
    if ! docker images | grep -q "n8n-embedding-service"; then
        echo -e "${YELLOW}Image not found. Building...${NC}"
        build_image
    fi
    
    echo -e "${BLUE}Running: $cmd${NC}"
    
    docker run --rm -it \
        --network ollama-n8n-network \
        -v /home/guruai/compose/rag-info:/data/workflows:ro \
        -v $(pwd)/logs:/app/logs \
        -e VECTOR_DATABASE_URL=postgresql://pguser:pgpassword@pgsql:5432/database \
        -e VECTOR_COLLECTION_NAME=n8n_workflows \
        -e N8N_WORKFLOWS_PATH=/data/workflows/n8n-workflows/workflows \
        -e TEST_WORKFLOWS_PATH=/data/workflows/test-workflows \
        -e EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
        -e PYTHONUNBUFFERED=1 \
        n8n-embedding-service \
        python main.py $cmd
}

# Function to open interactive shell
open_shell() {
    echo -e "${BLUE}Opening interactive shell in embedding container...${NC}"
    
    docker run --rm -it \
        --network ollama-n8n-network \
        -v /home/guruai/compose/rag-info:/data/workflows:ro \
        -v $(pwd)/logs:/app/logs \
        -e VECTOR_DATABASE_URL=postgresql://pguser:pgpassword@pgsql:5432/database \
        -e VECTOR_COLLECTION_NAME=n8n_workflows \
        -e N8N_WORKFLOWS_PATH=/data/workflows/n8n-workflows/workflows \
        -e TEST_WORKFLOWS_PATH=/data/workflows/test-workflows \
        -e EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
        -e PYTHONUNBUFFERED=1 \
        n8n-embedding-service \
        /bin/bash
}

# Function to show logs
show_logs() {
    echo -e "${BLUE}Container logs:${NC}"
    if [ -d "logs" ]; then
        ls -la logs/
        echo ""
        echo "Recent log entries:"
        tail -n 50 logs/*.log 2>/dev/null || echo "No log files found"
    else
        echo "No logs directory found"
    fi
}

# Function to clean up
clean_up() {
    echo -e "${YELLOW}Cleaning up Docker resources...${NC}"
    
    # Remove containers
    docker ps -a | grep n8n-embedding-service | awk '{print $1}' | xargs -r docker rm -f
    
    # Remove images
    docker images | grep n8n-embedding-service | awk '{print $3}' | xargs -r docker rmi -f
    
    echo -e "${GREEN}Cleanup completed!${NC}"
}

# Create logs directory if it doesn't exist
mkdir -p logs

# Main command handling
case "${1:-help}" in
    "build")
        build_image
        ;;
    "test")
        run_command "test"
        ;;
    "embed-all")
        run_command "embed --all"
        ;;
    "embed-n8n")
        run_command "embed --repo n8n_workflows"
        ;;
    "search")
        if [ -z "$2" ]; then
            echo -e "${RED}Error: Search query required${NC}"
            echo "Usage: $0 search \"your search query\""
            exit 1
        fi
        run_command "search \"$2\""
        ;;
    "stats")
        run_command "stats"
        ;;
    "shell")
        open_shell
        ;;
    "logs")
        show_logs
        ;;
    "clean")
        clean_up
        ;;
    "help"|*)
        show_usage
        ;;
esac