#!/bin/bash

# Jarvis Frontend Service Runner
# This script builds and manages the Next.js frontend service

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Jarvis Frontend Service Manager${NC}"
echo "================================"

# Configuration
FRONTEND_DIR="front_end/jfrontend"
IMAGE_NAME="frontend"
CONTAINER_NAME="frontend"

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Check if frontend directory exists
if [ ! -d "$FRONTEND_DIR" ]; then
    echo -e "${RED}Error: Frontend directory not found at $FRONTEND_DIR${NC}"
    exit 1
fi

# Function to show usage
show_usage() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  build       Build the frontend Docker image"
    echo "  start       Build and start the frontend service"
    echo "  stop        Stop the frontend service"
    echo "  restart     Rebuild and restart the frontend service"
    echo "  logs        Show frontend service logs"
    echo "  status      Show frontend service status"
    echo "  shell       Open interactive shell in frontend container"
    echo "  clean       Remove frontend container and image"
    echo "  dev         Start frontend in development mode (with hot reload)"
    echo ""
    echo "Examples:"
    echo "  $0 build"
    echo "  $0 start"
    echo "  $0 restart"
    echo "  $0 logs"
}

# Function to check if container is running
is_running() {
    docker ps | grep -q "$CONTAINER_NAME"
}

# Function to build frontend image
build_frontend() {
    echo -e "${BLUE}Building frontend Docker image...${NC}"
    
    cd "$FRONTEND_DIR"
    
    # Check if Dockerfile exists
    if [ ! -f "Dockerfile" ]; then
        echo -e "${RED}Error: Dockerfile not found in $FRONTEND_DIR${NC}"
        exit 1
    fi
    
    # Build the image
    docker build -t "$IMAGE_NAME" .
    
    cd - > /dev/null
    
    echo -e "${GREEN}Frontend image built successfully!${NC}"
}

# Function to start frontend service
start_frontend() {
    echo -e "${BLUE}Starting Jarvis Frontend Service...${NC}"
    
    # Stop and remove existing container if it exists
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    
    # Build the image first
    build_frontend
    
    # Start the frontend service with environment variables
    docker run -d \
        --name "$CONTAINER_NAME" \
        --network ollama-n8n-network \
        --env-file "$FRONTEND_DIR/.env.local" \
        -p 3000:3000 \
        "$IMAGE_NAME"
    
    echo -e "${GREEN}Frontend service started successfully!${NC}"
    echo -e "${BLUE}Frontend available at: http://localhost:3000${NC}"
    
    # Wait a moment for service to be ready
    echo -e "${BLUE}Waiting for frontend service to be ready...${NC}"
    sleep 3
    
    # Check if service is responding
    if curl -s http://localhost:3000 >/dev/null 2>&1; then
        echo -e "${GREEN}Frontend service is ready and responding!${NC}"
    else
        echo -e "${YELLOW}Frontend service started but may still be initializing...${NC}"
    fi
}

# Function to start frontend in development mode
start_dev() {
    echo -e "${BLUE}Starting Frontend in Development Mode...${NC}"
    
    # Stop existing container if running
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    
    # Run in development mode with volume mount for hot reload
    docker run -it \
        --name "$CONTAINER_NAME" \
        --network ollama-n8n-network \
        -p 3000:3000 \
        -v "$(pwd)/$FRONTEND_DIR:/app" \
        -v /app/node_modules \
        -v /app/.next \
        node:18-alpine \
        sh -c "cd /app && npm install && npm run dev"
}

# Function to stop frontend service
stop_frontend() {
    if ! is_running; then
        echo -e "${YELLOW}Frontend service is not running${NC}"
        return 0
    fi
    
    echo -e "${BLUE}Stopping Jarvis Frontend Service...${NC}"
    docker stop "$CONTAINER_NAME"
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    echo -e "${GREEN}Frontend service stopped successfully!${NC}"
}

# Function to restart frontend service
restart_frontend() {
    echo -e "${BLUE}Restarting Jarvis Frontend Service...${NC}"
    stop_frontend
    sleep 2
    start_frontend
}

# Function to show logs
show_logs() {
    if ! is_running; then
        echo -e "${RED}Frontend service is not running${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}Showing frontend service logs (Ctrl+C to exit):${NC}"
    docker logs -f "$CONTAINER_NAME"
}

# Function to show status
show_status() {
    if is_running; then
        echo -e "${GREEN}Frontend service is running${NC}"
        echo ""
        echo "Container details:"
        docker ps | grep "$CONTAINER_NAME"
        echo ""
        echo "Service endpoints:"
        echo "- Frontend: http://localhost:3000"
        echo "- Next.js API routes: http://localhost:3000/api/"
        echo ""
        
        # Show container resource usage
        echo "Resource usage:"
        docker stats "$CONTAINER_NAME" --no-stream --format "table {{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"
    else
        echo -e "${RED}Frontend service is not running${NC}"
    fi
}

# Function to open shell
open_shell() {
    if ! is_running; then
        echo -e "${RED}Frontend service is not running${NC}"
        echo "Starting temporary container for shell access..."
        
        docker run --rm -it \
            --name "$CONTAINER_NAME-shell" \
            --network ollama-n8n-network \
            -v "$(pwd)/$FRONTEND_DIR:/app" \
            "$IMAGE_NAME" \
            /bin/sh
    else
        echo -e "${BLUE}Opening shell in running frontend container...${NC}"
        docker exec -it "$CONTAINER_NAME" /bin/sh
    fi
}

# Function to clean up
clean_frontend() {
    echo -e "${BLUE}Cleaning up frontend resources...${NC}"
    
    # Stop and remove container
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    
    # Remove image
    docker rmi "$IMAGE_NAME" 2>/dev/null || true
    
    echo -e "${GREEN}Frontend cleanup completed!${NC}"
}

# Function to check frontend dependencies
check_dependencies() {
    echo -e "${BLUE}Checking frontend dependencies...${NC}"
    
    cd "$FRONTEND_DIR"
    
    if [ ! -f "package.json" ]; then
        echo -e "${RED}Error: package.json not found${NC}"
        exit 1
    fi
    
    echo "Frontend dependencies:"
    cat package.json | grep -A 20 '"dependencies"' || echo "Unable to read dependencies"
    
    if [ -f "package-lock.json" ]; then
        echo -e "${GREEN}package-lock.json found${NC}"
    else
        echo -e "${YELLOW}Warning: package-lock.json not found${NC}"
    fi
    
    cd - > /dev/null
}

# Main command handling
case "${1:-help}" in
    "build")
        build_frontend
        ;;
    "start")
        start_frontend
        ;;
    "stop")
        stop_frontend
        ;;
    "restart")
        restart_frontend
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
    "clean")
        clean_frontend
        ;;
    "dev")
        start_dev
        ;;
    "check-deps")
        check_dependencies
        ;;
    "help"|*)
        show_usage
        ;;
esac