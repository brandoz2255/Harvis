#!/bin/bash
# Run E2E tests for VibeCode using Playwright

echo "Running VibeCode E2E Tests..."
echo "=============================="
echo ""
echo "⚠️  NOTE: These tests require:"
echo "   - Full stack running (docker-compose up)"
echo "   - Frontend at http://localhost:3000"
echo "   - Backend at http://localhost:8000"
echo "   - Nginx at http://localhost:9000"
echo ""

# Check if Playwright is installed
if ! npm list @playwright/test > /dev/null 2>&1; then
    echo "Installing Playwright..."
    npm install --save-dev @playwright/test
    npx playwright install chromium
fi

# Check if services are running
echo "Checking services..."
if curl -s http://localhost:9000 > /dev/null 2>&1; then
    echo "✓ Frontend accessible at http://localhost:9000"
else
    echo "⚠️  Frontend not accessible at http://localhost:9000"
    echo "   Start with: docker-compose up -d"
fi

if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ Backend accessible at http://localhost:8000"
else
    echo "⚠️  Backend not accessible at http://localhost:8000"
fi

echo ""
echo "Running E2E tests..."
echo "===================="

# Run Playwright tests
npx playwright test --reporter=list

echo ""
echo "E2E test run complete!"
echo ""
echo "View detailed report: npx playwright show-report"
