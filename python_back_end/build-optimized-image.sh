#!/bin/bash
# Build script for optimized VibeCoading container image

set -e

echo "🔨 Building optimized VibeCoading container image..."

# Change to the directory containing the Dockerfile
cd "$(dirname "$0")/vibecoding"

# Build the optimized image
docker build \
  -f Dockerfile.optimized \
  -t vibecoading-optimized:latest \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  --progress=plain \
  .

echo "✅ Optimized image built successfully!"

# Test the image
echo "🧪 Testing the optimized image..."

# Quick test to ensure image works
docker run --rm vibecoading-optimized:latest ready-check

echo "✅ Image test passed!"

# Show image size
echo "📊 Image information:"
docker images vibecoading-optimized:latest

echo ""
echo "🚀 To use this image, update your container configuration to use:"
echo "   DEV_CONTAINER_IMAGE = 'vibecoading-optimized:latest'"
echo ""
echo "💡 For production deployment:"
echo "   1. Push to your container registry"
echo "   2. Update configuration with registry URL"
echo "   3. Pre-pull on all nodes with: docker pull vibecoading-optimized:latest"