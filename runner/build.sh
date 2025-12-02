#!/bin/bash
# Build the VibeCode runner image with Python 3.11 + Node.js 20

set -e

echo "🔨 Building VibeCode runner image..."
docker build -t harvis-runner:py311-node20 .

echo "✅ Runner image built successfully!"
echo "📝 To use this image, set the environment variable:"
echo "   export VIBECODING_RUNNER_IMAGE=harvis-runner:py311-node20"
echo ""
echo "🚀 Or add to your docker-compose.yaml:"
echo "   environment:"
echo "     - VIBECODING_RUNNER_IMAGE=harvis-runner:py311-node20"

