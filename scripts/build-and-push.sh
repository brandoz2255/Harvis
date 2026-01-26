#!/bin/bash
set -e

VERSION=${1:-latest}
REGISTRY="localhost:5000"

echo "======================================"
echo "Building Harvis AI Images"
echo "Version: $VERSION"
echo "Registry: $REGISTRY"
echo "======================================"

# Build backend
echo ""
echo "📦 Building backend..."
cd /home/dulc3/Documents/github/harvis/aidev/python_back_end
docker build -t ${REGISTRY}/jarvis-backend:${VERSION} .
echo "✅ Backend image built"

# Push backend
echo ""
echo "🚀 Pushing backend to registry..."
docker push ${REGISTRY}/jarvis-backend:${VERSION}
echo "✅ Backend pushed"

# Build frontend (new UI)
echo ""
echo "📦 Building frontend (new UI)..."
cd /home/dulc3/Documents/github/harvis/aidev/front_end/newjfrontend
docker build -t ${REGISTRY}/jarvis-frontend:${VERSION} .
echo "✅ Frontend image built"

# Push frontend
echo ""
echo "🚀 Pushing frontend to registry..."
docker push ${REGISTRY}/jarvis-frontend:${VERSION}
echo "✅ Frontend pushed"

# Tag as latest if version provided
if [ "$VERSION" != "latest" ]; then
    echo ""
    echo "🏷️  Tagging as latest..."
    docker tag ${REGISTRY}/jarvis-backend:${VERSION} ${REGISTRY}/jarvis-backend:latest
    docker tag ${REGISTRY}/jarvis-frontend:${VERSION} ${REGISTRY}/jarvis-frontend:latest
    docker push ${REGISTRY}/jarvis-backend:latest
    docker push ${REGISTRY}/jarvis-frontend:latest
    echo "✅ Latest tags pushed"
fi

echo ""
echo "======================================"
echo "✅ Build and push complete!"
echo "======================================"
echo "Backend:  ${REGISTRY}/jarvis-backend:${VERSION}"
echo "Frontend: ${REGISTRY}/jarvis-frontend:${VERSION}"
echo ""
echo "To deploy:"
echo "  Docker Compose: docker-compose up -d"
echo "  Kubernetes:     kubectl apply -k k8s-manifests/mini/"
echo "======================================"
