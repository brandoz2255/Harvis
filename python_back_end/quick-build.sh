#!/bin/bash
# Quick build script for vibecoding-optimized image

echo "🔨 Building vibecoding-optimized image..."
echo "======================================="

cd "$(dirname "$0")"

# Build the image
docker build -f vibecoding/Dockerfile.optimized -t vibecoding-optimized:latest vibecoding/

echo ""
echo "✅ Image built successfully!"
echo ""
echo "📋 Usage:"
echo "   • Set environment: export VIBECODING_IMAGE=vibecoding-optimized:latest"
echo "   • Or pull from registry: docker pull <registry>/vibecoding-optimized:latest"
echo ""
echo "🧪 Test the fixes:"
echo "   • Run: ./test-loadfix.sh"