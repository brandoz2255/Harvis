#!/bin/bash

# Jarvis All Services Manager
# This script manages all Jarvis services together

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

echo -e "${PURPLE}Jarvis AI System - All Services Manager${NC}"
echo "======================================="

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Function to show usage
show_usage() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  start       Start all services (ollama, backend, frontend)"
    echo "  stop        Stop all services"
    echo "  restart     Restart all services"
    echo "  status      Show status of all services"
    echo "  logs        Show logs for all services"
    echo "  build       Build all Docker images"
    echo "  clean       Clean up all containers and images"
    echo ""
    echo "Individual service commands:"
    echo "  start-ollama    Start only Ollama service"
    echo "  start-backend   Start only Backend service"
    echo "  start-frontend  Start only Frontend service"
    echo "  start-embedding Start only Embedding service"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 status"
    echo "  $0 restart"
    echo "  $0 start-backend"
}

# Function to check if script exists and is executable
check_script() {
    local script="$1"
    if [ ! -f "$script" ]; then
        echo -e "${RED}Error: Script not found: $script${NC}"
        return 1
    fi
    if [ ! -x "$script" ]; then
        echo -e "${YELLOW}Making script executable: $script${NC}"
        chmod +x "$script"
    fi
    return 0
}

# Function to run a service script safely
run_service_script() {
    local script="$1"
    local command="$2"
    
    if check_script "$script"; then
        echo -e "${BLUE}Running: $script $command${NC}"
        ./"$script" "$command"
        return $?
    else
        echo -e "${RED}Failed to run $script${NC}"
        return 1
    fi
}

# Function to check service status
check_service_status() {
    local service_name="$1"
    local container_name="$2"
    
    if docker ps | grep -q "$container_name"; then
        echo -e "${GREEN}✓ $service_name is running${NC}"
        return 0
    else
        echo -e "${RED}✗ $service_name is not running${NC}"
        return 1
    fi
}

# Function to wait for service to be ready
wait_for_service() {
    local service_name="$1"
    local health_url="$2"
    local max_attempts=30
    local attempt=1
    
    echo -e "${BLUE}Waiting for $service_name to be ready...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s "$health_url" >/dev/null 2>&1; then
            echo -e "${GREEN}$service_name is ready!${NC}"
            return 0
        fi
        
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo -e "${YELLOW}Warning: $service_name may not be fully ready${NC}"
    return 1
}

# Function to start all services
start_all() {
    echo -e "${PURPLE}Starting all Jarvis services...${NC}"
    echo ""
    
    # Start services in order
    echo -e "${BLUE}1. Starting Ollama service...${NC}"
    run_service_script "run-ollama.sh" "start"
    wait_for_service "Ollama" "http://localhost:11434/api/tags"
    echo ""
    
    echo -e "${BLUE}2. Starting Backend service...${NC}"
    run_service_script "run-backend.sh" "start-bg"
    wait_for_service "Backend" "http://localhost:8000/docs"
    echo ""
    
    echo -e "${BLUE}3. Starting Frontend service...${NC}"
    run_service_script "run-frontend.sh" "start"
    wait_for_service "Frontend" "http://localhost:3000"
    echo ""
    
    echo -e "${GREEN}All services started successfully!${NC}"
    show_all_status
}

# Function to stop all services
stop_all() {
    echo -e "${PURPLE}Stopping all Jarvis services...${NC}"
    echo ""
    
    # Stop in reverse order
    echo -e "${BLUE}1. Stopping Frontend service...${NC}"
    run_service_script "run-frontend.sh" "stop" || true
    echo ""
    
    echo -e "${BLUE}2. Stopping Backend service...${NC}"
    run_service_script "run-backend.sh" "stop" || true
    echo ""
    
    echo -e "${BLUE}3. Stopping Ollama service...${NC}"
    run_service_script "run-ollama.sh" "stop" || true
    echo ""
    
    echo -e "${GREEN}All services stopped successfully!${NC}"
}

# Function to restart all services
restart_all() {
    echo -e "${PURPLE}Restarting all Jarvis services...${NC}"
    stop_all
    sleep 3
    start_all
}

# Function to show status of all services
show_all_status() {
    echo -e "${PURPLE}Jarvis Services Status:${NC}"
    echo "======================"
    
    check_service_status "Ollama" "ollama"
    check_service_status "Backend" "backend"
    check_service_status "Frontend" "frontend"
    
    echo ""
    echo -e "${BLUE}Service Endpoints:${NC}"
    echo "- Frontend: http://localhost:3000"
    echo "- Backend API: http://localhost:8000"
    echo "- Backend Docs: http://localhost:8000/docs"
    echo "- Ollama API: http://localhost:11434"
    echo ""
    
    echo -e "${BLUE}Docker Containers:${NC}"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(ollama|backend|frontend)" || echo "No services running"
}

# Function to show logs for all services
show_all_logs() {
    echo -e "${PURPLE}Showing logs for all services...${NC}"
    echo "Use Ctrl+C to stop log streaming"
    echo ""
    
    # Show logs for all containers
    docker logs -f ollama &
    docker logs -f backend &
    docker logs -f frontend &
    
    wait
}

# Function to build all images
build_all() {
    echo -e "${PURPLE}Building all Docker images...${NC}"
    echo ""
    
    echo -e "${BLUE}1. Building Frontend image...${NC}"
    run_service_script "run-frontend.sh" "build"
    echo ""
    
    echo -e "${BLUE}2. Building Embedding service image...${NC}"
    if [ -f "embedding/run-embedding.sh" ]; then
        cd embedding
        ./run-embedding.sh build
        cd ..
    else
        echo -e "${YELLOW}Embedding service not found, skipping...${NC}"
    fi
    echo ""
    
    echo -e "${GREEN}All images built successfully!${NC}"
}

# Function to clean all resources
clean_all() {
    echo -e "${YELLOW}Warning: This will remove all containers and images!${NC}"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
    
    echo -e "${PURPLE}Cleaning up all resources...${NC}"
    
    # Stop all services first
    stop_all
    
    # Clean individual services
    run_service_script "run-frontend.sh" "clean" || true
    run_service_script "run-ollama.sh" "stop" || true
    
    # Clean embedding service
    if [ -f "embedding/run-embedding.sh" ]; then
        cd embedding
        ./run-embedding.sh clean || true
        cd ..
    fi
    
    echo -e "${GREEN}Cleanup completed!${NC}"
}

# Make all scripts executable
echo -e "${BLUE}Ensuring all scripts are executable...${NC}"
chmod +x run-*.sh 2>/dev/null || true
if [ -f "embedding/run-embedding.sh" ]; then
    chmod +x embedding/run-embedding.sh
fi

# Main command handling
case "${1:-help}" in
    "start")
        start_all
        ;;
    "stop")
        stop_all
        ;;
    "restart")
        restart_all
        ;;
    "status")
        show_all_status
        ;;
    "logs")
        show_all_logs
        ;;
    "build")
        build_all
        ;;
    "clean")
        clean_all
        ;;
    "start-ollama")
        run_service_script "run-ollama.sh" "start"
        ;;
    "start-backend")
        run_service_script "run-backend.sh" "start-bg"
        ;;
    "start-frontend")
        run_service_script "run-frontend.sh" "start"
        ;;
    "start-embedding")
        if [ -f "embedding/run-embedding.sh" ]; then
            cd embedding && ./run-embedding.sh shell
        else
            echo -e "${RED}Embedding service not found${NC}"
        fi
        ;;
    "help"|*)
        show_usage
        ;;
esac