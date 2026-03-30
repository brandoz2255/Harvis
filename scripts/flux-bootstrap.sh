#!/bin/bash

# FluxCD Bootstrap Script for Harvis AI Project
# Repository: brandoz2255/aidev

echo "🚀 Bootstrapping FluxCD for automated GitOps deployment..."

# Check if GITHUB_TOKEN is set
if [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ GITHUB_TOKEN environment variable is not set"
    echo "Please set it with: export GITHUB_TOKEN=your_token_here"
    exit 1
fi

echo "✅ GitHub token found"

# Bootstrap FluxCD
echo "🔧 Bootstrapping FluxCD on cluster..."
flux bootstrap github \
  --owner=brandoz2255 \
  --repository=aidev \
  --branch=main \
  --path=clusters/production \
  --personal \
  --components-extra=image-reflector-controller,image-automation-controller

echo "✅ FluxCD bootstrap completed!"

# Check FluxCD status
echo "📊 Checking FluxCD status..."
kubectl get pods -n flux-system

echo "🎉 FluxCD is now watching your repository for changes!"
echo "📁 Configuration will be stored in: clusters/production/"