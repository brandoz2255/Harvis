#!/bin/bash
#
# rebuild-frontend.sh - Helper script to rebuild the frontend with proper cache invalidation
#
# Usage:
#   ./rebuild-frontend.sh              # Rebuild with automatic cache busting
#   ./rebuild-frontend.sh --no-cache   # Full rebuild without any cache
#   ./rebuild-frontend.sh --quick      # Quick rebuild (may use cache)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

NO_CACHE=false
QUICK=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --quick)
            QUICK=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --no-cache    Force complete rebuild without any Docker cache"
            echo "  --quick       Quick rebuild (may use cache) - fastest but might miss changes"
            echo "  --help, -h    Show this help message"
            echo ""
            echo "Default behavior: Smart rebuild with timestamp-based cache busting"
            exit 0
            ;;
    esac
done

echo "🔄 Rebuilding Harvis Frontend..."
echo ""

# Stop the current frontend container
echo "📦 Stopping current frontend container..."
docker-compose stop frontend 2>/dev/null || true
docker-compose rm -f frontend 2>/dev/null || true

if [ "$NO_CACHE" = true ]; then
    echo "🔨 Building with NO CACHE (full rebuild)..."
    echo "   This will take longer but ensures all changes are included."
    echo ""
    docker-compose build --no-cache frontend
elif [ "$QUICK" = true ]; then
    echo "⚡ Quick build (using cache where possible)..."
    echo "   WARNING: May not pick up all file changes!"
    echo ""
    docker-compose build frontend
else
    # Smart rebuild with timestamp-based cache busting
    echo "🧠 Smart rebuild with cache busting..."
    echo "   Using timestamp to ensure source code changes are detected."
    echo ""
    
    # Generate build timestamp
    BUILD_TIMESTAMP=$(date -u +"%Y-%m-%d-%H%M%S")
    GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    
    echo "   Build timestamp: $BUILD_TIMESTAMP"
    echo "   Git commit: $GIT_COMMIT"
    echo ""
    
    # Build with cache-busting args
    docker-compose build \
        --build-arg BUILD_TIMESTAMP="$BUILD_TIMESTAMP" \
        --build-arg GIT_COMMIT="$GIT_COMMIT" \
        frontend
fi

echo ""
echo "✅ Frontend build complete!"
echo ""
echo "🚀 Starting services..."
docker-compose up -d frontend

echo ""
echo "✨ Done! Frontend is starting up..."
echo "   Check logs with: docker-compose logs -f frontend"
