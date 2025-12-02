#!/bin/bash
# Run performance tests for VibeCode backend

echo "Running VibeCode Performance Tests..."
echo "======================================"
echo ""
echo "⚠️  NOTE: These tests require:"
echo "   - Backend server running (docker-compose up)"
echo "   - Database initialized"
echo "   - Docker daemon accessible"
echo ""
echo "Performance Requirements:"
echo "  - Container start: < 3 seconds"
echo "  - File save: < 500ms"
echo "  - File tree load: < 1 second"
echo "  - Terminal connect: < 1 second"
echo ""

# Check if running in Docker
if [ -f /.dockerenv ]; then
    echo "✓ Running in Docker environment"
    PYTHON_CMD="python"
else
    echo "✓ Running in host environment"
    PYTHON_CMD="python3"
fi

# Check if backend is running
echo "Checking if backend is available..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ Backend is running"
else
    echo "⚠️  Backend not detected at http://localhost:8000"
    echo "   Start with: docker-compose up -d"
    echo ""
fi

# Run performance tests
echo ""
echo "Running performance tests..."
echo "=============================="
$PYTHON_CMD -m pytest tests/test_performance.py \
    -v \
    -s \
    --tb=short

echo ""
echo "Performance test run complete!"
