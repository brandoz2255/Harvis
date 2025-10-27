#!/bin/bash
echo "🧪 Testing Terminal WebSocket Connection"
echo ""

# Test 1: Check if backend route exists
echo "1️⃣ Testing backend route..."
BACKEND_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/ws/vibecoding/terminal?session_id=test&token=test")
if [ "$BACKEND_RESPONSE" == "404" ]; then
    echo "   ❌ Backend route not found (404)"
    echo "   → You need to restart the backend: docker restart backend"
else
    echo "   ✅ Backend route exists (HTTP $BACKEND_RESPONSE)"
fi
echo ""

# Test 2: Test through Nginx
echo "2️⃣ Testing through Nginx..."
NGINX_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:9000/ws/vibecoding/terminal?session_id=test&token=test")
if [ "$NGINX_RESPONSE" == "404" ]; then
    echo "   ❌ Nginx routing failed (404)"
    echo "   → Check nginx configuration"
else
    echo "   ✅ Nginx routing works (HTTP $NGINX_RESPONSE)"
fi
echo ""

# Test 3: Check if runner container exists
echo "3️⃣ Checking runner containers..."
RUNNER_COUNT=$(docker ps -a | grep "vibecode-runner" | wc -l)
echo "   Found $RUNNER_COUNT runner container(s)"
echo ""

echo "📋 Summary:"
echo "  - Backend route: HTTP $BACKEND_RESPONSE"
echo "  - Nginx route: HTTP $NGINX_RESPONSE"
echo ""
echo "🎯 If terminal still doesn't work:"
echo "  1. Restart backend: docker restart backend"
echo "  2. Hard refresh browser: Ctrl+Shift+R"
echo "  3. Open /ide page and try terminal again"

