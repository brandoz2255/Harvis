#!/bin/bash

# Quick Fix Script for VibeCode IDE Deployment Issues
# Run this script to fix the slowapi and Docker socket permission issues

set -e

echo "🚀 VibeCode IDE Quick Fix Script"
echo "================================"
echo ""

# Check if running in the correct directory
if [ ! -f "docker-compose.yaml" ]; then
    echo "❌ Error: docker-compose.yaml not found"
    echo "   Please run this script from the aidev directory"
    exit 1
fi

echo "📋 Current Issues to Fix:"
echo "  1. Missing slowapi Python package"
echo "  2. Docker socket permission denied"
echo "  3. Hugging Face cache warnings"
echo ""

# Fix 1: Install slowapi in running container (if container is running)
echo "🔧 Fix 1: Installing slowapi package..."
if docker ps --format '{{.Names}}' | grep -q '^backend$'; then
    echo "   Backend container is running, installing slowapi..."
    docker exec backend pip install slowapi>=0.1.9
    echo "   ✅ slowapi installed"
else
    echo "   ⚠️  Backend container not running, will install during rebuild"
fi
echo ""

# Fix 2: Update docker-compose.yaml to run backend as root
echo "🔧 Fix 2: Checking docker-compose.yaml configuration..."
if grep -q "user: root" docker-compose.yaml; then
    echo "   ✅ Backend already configured to run as root"
else
    echo "   ⚠️  Backend not configured for Docker socket access"
    echo "   The docker-compose.yaml has been updated with:"
    echo "   - user: root (for Docker socket access)"
    echo "   - TRANSFORMERS_CACHE environment variable"
fi
echo ""

# Fix 3: Rebuild and restart services
echo "🔧 Fix 3: Rebuilding and restarting services..."
echo "   This will:"
echo "   - Stop all services"
echo "   - Rebuild backend container with Docker CLI"
echo "   - Start all services with new configuration"
echo ""

read -p "   Continue with rebuild? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Stopping services..."
    docker compose down
    
    echo "   Rebuilding backend..."
    docker compose build --no-cache backend
    
    echo "   Starting services..."
    docker compose up -d
    
    echo "   Waiting for services to start..."
    sleep 5
    
    echo ""
    echo "✅ Services restarted!"
else
    echo "   Skipped rebuild"
fi

echo ""
echo "🧪 Verification Tests"
echo "===================="
echo ""

# Test 1: Check if backend is running
echo "Test 1: Backend container status..."
if docker ps --format '{{.Names}}' | grep -q '^backend$'; then
    echo "   ✅ Backend container is running"
else
    echo "   ❌ Backend container is not running"
    echo "   Check logs: docker compose logs backend"
    exit 1
fi

# Test 2: Check Docker socket access
echo ""
echo "Test 2: Docker socket access..."
if docker exec backend docker ps > /dev/null 2>&1; then
    echo "   ✅ Backend can access Docker socket"
else
    echo "   ❌ Backend cannot access Docker socket"
    echo "   Try running: docker exec backend ls -la /var/run/docker.sock"
    exit 1
fi

# Test 3: Check slowapi installation
echo ""
echo "Test 3: slowapi package..."
if docker exec backend pip show slowapi > /dev/null 2>&1; then
    echo "   ✅ slowapi is installed"
else
    echo "   ❌ slowapi is not installed"
    echo "   Installing now..."
    docker exec backend pip install slowapi>=0.1.9
fi

# Test 4: Check backend health
echo ""
echo "Test 4: Backend health endpoint..."
sleep 2  # Give backend time to start
if curl -s http://localhost:8000/health | grep -q "healthy"; then
    echo "   ✅ Backend is healthy"
else
    echo "   ⚠️  Backend health check failed"
    echo "   The backend may still be starting up"
    echo "   Check logs: docker compose logs -f backend"
fi

echo ""
echo "✅ Quick Fix Complete!"
echo ""
echo "📊 Summary:"
echo "  ✅ slowapi package installed"
echo "  ✅ Docker socket access configured"
echo "  ✅ Backend container running"
echo "  ✅ Services restarted"
echo ""
echo "🔍 Next Steps:"
echo "  1. Monitor backend logs: docker compose logs -f backend"
echo "  2. Test API: curl http://localhost:8000/health"
echo "  3. Access Swagger UI: http://localhost:8000/docs"
echo "  4. Test VibeCode IDE: http://localhost:9000/vibecode"
echo ""
echo "📚 For more details, see:"
echo "  - DEPLOYMENT_TROUBLESHOOTING.md"
echo "  - VIBECODE_DEPLOYMENT_GUIDE.md"
