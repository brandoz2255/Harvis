#!/bin/bash

# JARVIS DAST Security Scanner Launcher Script
# This script sets up and runs the DAST security testing tool

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Banner
echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════════════════════════════════╗"
echo "║                             🛡️  JARVIS DAST SECURITY TOOL 🛡️                         ║"
echo "║                                   Launcher Script                                    ║"
echo "╚══════════════════════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if Python package is installed
python_package_exists() {
    python3 -c "import $1" >/dev/null 2>&1
}

echo -e "${YELLOW}🔍 Checking prerequisites...${NC}"

# Check Python
if command_exists python3; then
    echo -e "${GREEN}✅ Python 3 is installed${NC}"
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    echo "   Version: $PYTHON_VERSION"
else
    echo -e "${RED}❌ Python 3 is not installed${NC}"
    echo "   Please install Python 3.7+ to continue"
    exit 1
fi

# Check Docker
if command_exists docker; then
    echo -e "${GREEN}✅ Docker is installed${NC}"
    if docker info >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Docker daemon is running${NC}"
    else
        echo -e "${YELLOW}⚠️  Docker daemon is not running${NC}"
        echo "   Please start Docker to use ZAP container management"
    fi
else
    echo -e "${YELLOW}⚠️  Docker is not installed${NC}"
    echo "   ZAP container management will not be available"
fi

# Check if we're in the right directory
if [ ! -f "jarvis_dast.py" ]; then
    echo -e "${RED}❌ jarvis_dast.py not found${NC}"
    echo "   Please run this script from the dast directory"
    exit 1
fi

# Check Python dependencies
echo -e "${YELLOW}📦 Checking Python dependencies...${NC}"

MISSING_DEPS=()

if ! python_package_exists "rich"; then
    MISSING_DEPS+=("rich")
fi

if ! python_package_exists "requests"; then
    MISSING_DEPS+=("requests")
fi

if ! python_package_exists "yaml"; then
    MISSING_DEPS+=("PyYAML")
fi

# ZAP API is optional but recommended
if ! python_package_exists "zapv2"; then
    echo -e "${YELLOW}⚠️  ZAP Python API not found (optional but recommended)${NC}"
    echo "   Install with: pip install python-owasp-zap-v2.4"
fi

# Install missing dependencies
if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
    echo -e "${YELLOW}📦 Installing missing dependencies...${NC}"
    if [ -f "requirements.txt" ]; then
        echo "   Using requirements.txt..."
        pip3 install -r requirements.txt
    else
        echo "   Installing individual packages..."
        for dep in "${MISSING_DEPS[@]}"; do
            echo "   Installing $dep..."
            pip3 install "$dep"
        done
    fi
    echo -e "${GREEN}✅ Dependencies installed${NC}"
else
    echo -e "${GREEN}✅ All dependencies are satisfied${NC}"
fi

# Check target application
echo -e "${YELLOW}🎯 Checking target application...${NC}"
if curl -s --connect-timeout 5 http://localhost:9000 >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Target application is accessible at http://localhost:9000${NC}"
else
    echo -e "${YELLOW}⚠️  Target application not accessible at http://localhost:9000${NC}"
    echo "   Make sure your Jarvis application is running"
    echo "   You can specify a different target URL in the tool"
fi

# Check ZAP availability
echo -e "${YELLOW}🕷️ Checking OWASP ZAP...${NC}"
if curl -s --connect-timeout 3 http://127.0.0.1:8080 >/dev/null 2>&1; then
    echo -e "${GREEN}✅ ZAP proxy is running at http://127.0.0.1:8080${NC}"
else
    echo -e "${YELLOW}⚠️  ZAP proxy not running${NC}"
    echo "   The tool can start ZAP automatically using Docker"
fi

# Make script executable
chmod +x jarvis_dast.py

# Create reports directory
if [ ! -d "reports" ]; then
    mkdir reports
    echo -e "${GREEN}✅ Created reports directory${NC}"
fi

echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════════════════════════════════╗"
echo "║                                 🚀 Ready to Launch!                                  ║"
echo "╚══════════════════════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${BLUE}Available launch options:${NC}"
echo "1. 🖥️  Interactive TUI Mode    - python3 jarvis_dast.py"
echo "2. ⚡ Quick Scan Mode        - python3 jarvis_dast.py --quick"
echo "3. 📋 With Custom Config     - python3 jarvis_dast.py --config config.yaml"
echo ""

# Parse command line arguments
case "${1:-interactive}" in
    "quick"|"-q"|"--quick")
        echo -e "${GREEN}🚀 Starting Quick Scan Mode...${NC}"
        python3 jarvis_dast.py --quick --target "${2:-http://localhost:9000}"
        ;;
    "config"|"-c"|"--config")
        if [ -z "$2" ]; then
            echo -e "${RED}❌ Config file path required${NC}"
            echo "Usage: ./run_dast.sh config /path/to/config.yaml"
            exit 1
        fi
        echo -e "${GREEN}🚀 Starting with custom config: $2${NC}"
        python3 jarvis_dast.py --config "$2"
        ;;
    "help"|"-h"|"--help")
        echo -e "${BLUE}JARVIS DAST Launcher Help${NC}"
        echo ""
        echo "Usage: ./run_dast.sh [mode] [options]"
        echo ""
        echo "Modes:"
        echo "  interactive     Launch interactive TUI (default)"
        echo "  quick [url]     Run quick scan on target URL"  
        echo "  config <file>   Use custom configuration file"
        echo "  help            Show this help message"
        echo ""
        echo "Examples:"
        echo "  ./run_dast.sh                                    # Interactive TUI"
        echo "  ./run_dast.sh quick                              # Quick scan on localhost:9000"
        echo "  ./run_dast.sh quick http://example.com           # Quick scan on custom URL"
        echo "  ./run_dast.sh config my_config.yaml              # Use custom config"
        echo ""
        ;;
    *)
        echo -e "${GREEN}🚀 Starting Interactive TUI Mode...${NC}"
        python3 jarvis_dast.py
        ;;
esac

echo -e "${GREEN}✨ JARVIS DAST session completed${NC}"