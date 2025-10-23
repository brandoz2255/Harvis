#!/bin/bash

# Fix Deployment Issues Script
# This script fixes common deployment issues for VibeCode IDE

echo "🔧 Fixing VibeCode IDE Deployment Issues..."
echo ""

# Issue 1: Install missing slowapi dependency
echo "📦 Installing missing Python dependencies..."
pip install slowapi>=0.1.9
if [ $? -eq 0 ]; then
    echo "✅ slowapi installed successfully"
else
    echo "❌ Failed to install slowapi"
    exit 1
fi

# Issue 2: Fix Docker socket permissions
echo ""
echo "🔐 Checking Docker socket permissions..."

# Check if Docker socket exists
if [ ! -S /var/run/docker.sock ]; then
    echo "❌ Docker socket not found at /var/run/docker.sock"
    echo "   Make sure docker-compose.yaml has the volume mount:"
    echo "   volumes:"
    echo "     - /var/run/docker.sock:/var/run/docker.sock"
    exit 1
fi

# Get Docker socket group
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
echo "   Docker socket group ID: $DOCKER_GID"

# Check if current user can access Docker socket
if docker ps > /dev/null 2>&1; then
    echo "✅ Docker socket is accessible"
else
    echo "⚠️  Docker socket permission denied"
    echo "   Adding current user to docker group..."
    
    # Add user to docker group
    if getent group docker > /dev/null 2>&1; then
        usermod -aG docker $(whoami) || true
    else
        # Create docker group if it doesn't exist
        groupadd -g $DOCKER_GID docker || true
        usermod -aG docker $(whoami) || true
    fi
    
    echo "   Note: You may need to restart the container for group changes to take effect"
    echo "   Run: docker compose restart backend"
fi

# Issue 3: Fix Hugging Face cache permissions
echo ""
echo "📁 Fixing Hugging Face cache permissions..."
export TRANSFORMERS_CACHE=/tmp/huggingface_cache
mkdir -p $TRANSFORMERS_CACHE
chmod 777 $TRANSFORMERS_CACHE
echo "✅ Set TRANSFORMERS_CACHE to $TRANSFORMERS_CACHE"

# Issue 4: Verify all dependencies
echo ""
echo "🔍 Verifying critical dependencies..."

python3 << 'EOF'
import sys

dependencies = [
    'fastapi',
    'uvicorn',
    'docker',
    'slowapi',
    'asyncpg',
    'websockets',
]

missing = []
for dep in dependencies:
    try:
        __import__(dep)
        print(f"✅ {dep}")
    except ImportError:
        print(f"❌ {dep} - MISSING")
        missing.append(dep)

if missing:
    print(f"\n❌ Missing dependencies: {', '.join(missing)}")
    print("   Run: pip install " + " ".join(missing))
    sys.exit(1)
else:
    print("\n✅ All critical dependencies installed")
EOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Some dependencies are missing. Installing..."
    pip install -r requirements.txt
fi

echo ""
echo "✅ All fixes applied!"
echo ""
echo "Next steps:"
echo "1. If Docker socket permission was fixed, restart the backend:"
echo "   docker compose restart backend"
echo ""
echo "2. Verify the backend starts successfully:"
echo "   docker compose logs -f backend"
echo ""
echo "3. Test Docker access from within the container:"
echo "   docker exec backend docker ps"
