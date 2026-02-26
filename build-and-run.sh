#!/bin/bash
# build-and-run.sh - Build and run Harvis with Docker Compose

set -e

echo "🚀 Building Harvis Docker Compose images..."
docker-compose build

echo "✅ Build complete!"
echo "🏃 Starting services..."
docker-compose up -d

echo "🎉 Harvis is running!"
echo "📊 Check status with: docker-compose ps"
echo "📜 View logs with: docker-compose logs -f"