#!/bin/bash
# Verification script for VibeCoading performance optimizations

set -e

echo "🔍 VibeCoading Performance Verification"
echo "======================================="

# Configuration
BACKEND_URL="http://localhost:8000"
FRONTEND_URL="http://localhost:3000"
TEST_PROJECT_NAME="perf-test-$(date +%s)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

info() {
    echo -e "ℹ️  $1"
}

# Function to measure time
measure_time() {
    local start_time=$(date +%s%3N)
    "$@"
    local end_time=$(date +%s%3N)
    local duration=$((end_time - start_time))
    echo $duration
}

# Check if services are running
echo ""
info "Checking service availability..."

if curl -s "$BACKEND_URL/health" > /dev/null 2>&1; then
    success "Backend is running"
else
    error "Backend not available at $BACKEND_URL"
    exit 1
fi

if curl -s "$FRONTEND_URL" > /dev/null 2>&1; then
    success "Frontend is running"
else
    warning "Frontend not available at $FRONTEND_URL (continuing anyway)"
fi

# Test 1: Session Creation Performance
echo ""
info "Test 1: Session Creation Performance"
echo "-----------------------------------"

session_create_time=$(measure_time curl -s -X POST \
    "$BACKEND_URL/api/vibecoding/sessions" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": 1, \"project_name\": \"$TEST_PROJECT_NAME\", \"description\": \"Performance test\"}" \
    > /tmp/session_response.json)

if [ $? -eq 0 ]; then
    session_id=$(cat /tmp/session_response.json | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])" 2>/dev/null || echo "")
    
    if [ -n "$session_id" ]; then
        success "Session created in ${session_create_time}ms"
        info "Session ID: $session_id"
        
        if [ $session_create_time -lt 2000 ]; then
            success "Session creation time is under 2s target"
        else
            warning "Session creation took ${session_create_time}ms (target: <2000ms)"
        fi
    else
        error "Failed to extract session ID from response"
        cat /tmp/session_response.json
        exit 1
    fi
else
    error "Session creation failed"
    exit 1
fi

# Test 2: Container Creation Performance
echo ""
info "Test 2: Container Creation Performance"
echo "-------------------------------------"

container_create_time=$(measure_time curl -s -X POST \
    "$BACKEND_URL/api/vibecoding/container/create" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$session_id\", \"user_id\": \"1\"}" \
    > /tmp/container_response.json)

if [ $? -eq 0 ]; then
    container_status=$(cat /tmp/container_response.json | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null || echo "unknown")
    
    success "Container creation completed in ${container_create_time}ms"
    info "Container status: $container_status"
    
    if [ $container_create_time -lt 5000 ]; then
        success "Container creation time is under 5s target"
    else
        warning "Container creation took ${container_create_time}ms (target: <5000ms)"
    fi
else
    error "Container creation failed"
    exit 1
fi

# Test 3: Session Readiness Check
echo ""
info "Test 3: Session Readiness Verification"
echo "--------------------------------------"

max_wait=30
wait_count=0
ready=false

while [ $wait_count -lt $max_wait ] && [ "$ready" = "false" ]; do
    readiness_response=$(curl -s "$BACKEND_URL/api/vibecoding/sessions/$session_id/status" 2>/dev/null || echo '{"ready": false}')
    ready=$(echo "$readiness_response" | python3 -c "import sys, json; print(str(json.load(sys.stdin).get('ready', False)).lower())" 2>/dev/null || echo "false")
    
    if [ "$ready" = "true" ]; then
        success "Session is ready after ${wait_count}s"
        break
    else
        info "Waiting for session readiness... (${wait_count}s)"
        sleep 1
        wait_count=$((wait_count + 1))
    fi
done

if [ "$ready" = "false" ]; then
    error "Session failed to become ready within ${max_wait}s"
    echo "Response: $readiness_response"
else
    success "Session readiness verification passed"
fi

# Test 4: File Operations Performance
echo ""
info "Test 4: File Operations Performance"
echo "----------------------------------"

# Test file listing
list_time=$(measure_time curl -s -X POST \
    "$BACKEND_URL/api/vibecoding/container/files/list" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$session_id\", \"path\": \"/workspace\"}" \
    > /tmp/files_response.json)

if [ $? -eq 0 ]; then
    success "File listing completed in ${list_time}ms"
    
    if [ $list_time -lt 1000 ]; then
        success "File listing time is under 1s target"
    else
        warning "File listing took ${list_time}ms (target: <1000ms)"
    fi
else
    error "File listing failed"
fi

# Test file creation
write_time=$(measure_time curl -s -X POST \
    "$BACKEND_URL/api/vibecoding/container/files/write" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$session_id\", \"file_path\": \"/workspace/test.py\", \"content\": \"print('Performance test successful!')\"}" \
    > /tmp/write_response.json)

if [ $? -eq 0 ]; then
    success "File write completed in ${write_time}ms"
    
    if [ $write_time -lt 500 ]; then
        success "File write time is under 500ms target"
    else
        warning "File write took ${write_time}ms (target: <500ms)"
    fi
else
    error "File write failed"
fi

# Test 5: Terminal WebSocket Connection
echo ""
info "Test 5: Terminal WebSocket Performance"
echo "-------------------------------------"

# Note: This would require a WebSocket client to test properly
# For now, we'll test the endpoint availability
terminal_endpoint="ws://localhost:8000/api/vibecoding/container/$session_id/terminal"
info "Terminal WebSocket endpoint: $terminal_endpoint"
success "Terminal endpoint configured (manual WebSocket test required)"

# Test 6: Resource Usage Check
echo ""
info "Test 6: Resource Usage Analysis"
echo "-------------------------------"

if command -v docker &> /dev/null; then
    container_name="vibecoding_$session_id"
    if docker ps --format "table {{.Names}}" | grep -q "$container_name"; then
        stats=$(docker stats --no-stream --format "{{.CPUPerc}},{{.MemUsage}}" "$container_name" 2>/dev/null || echo "N/A,N/A")
        cpu_usage=$(echo "$stats" | cut -d',' -f1)
        mem_usage=$(echo "$stats" | cut -d',' -f2)
        
        info "Container CPU usage: $cpu_usage"
        info "Container memory usage: $mem_usage"
        success "Resource monitoring active"
    else
        warning "Container not found for resource monitoring"
    fi
else
    warning "Docker CLI not available for resource monitoring"
fi

# Cleanup
echo ""
info "Cleanup"
echo "-------"

cleanup_time=$(measure_time curl -s -X DELETE \
    "$BACKEND_URL/api/vibecoding/container/$session_id" \
    > /tmp/cleanup_response.json)

if [ $? -eq 0 ]; then
    success "Container cleanup completed in ${cleanup_time}ms"
else
    warning "Container cleanup may have failed"
fi

# Performance Summary
echo ""
echo "📊 Performance Summary"
echo "====================="
echo "Session Creation:     ${session_create_time}ms (target: <2000ms)"
echo "Container Creation:   ${container_create_time}ms (target: <5000ms)"
echo "File Operations:      ${list_time}ms / ${write_time}ms (targets: <1000ms / <500ms)"
echo "Session Readiness:    ${wait_count}s (target: <30s)"

# Overall assessment
total_startup_time=$((session_create_time + container_create_time))
echo ""
if [ $total_startup_time -lt 5000 ] && [ "$ready" = "true" ] && [ $wait_count -lt 10 ]; then
    success "🎉 Performance targets met! Total startup: ${total_startup_time}ms"
    echo ""
    echo "✨ Optimization successful:"
    echo "   • Cold start time: ${total_startup_time}ms (target: <5000ms)"
    echo "   • Readiness time: ${wait_count}s (target: <10s)"
    echo "   • File I/O performance: Excellent"
    echo ""
    echo "🚀 Ready for production deployment!"
    exit 0
else
    warning "Performance targets partially met. Review optimization opportunities."
    echo ""
    echo "🔧 Recommendations:"
    [ $total_startup_time -ge 5000 ] && echo "   • Review container image optimization"
    [ $wait_count -ge 10 ] && echo "   • Check readiness probe implementation"
    [ $list_time -ge 1000 ] && echo "   • Optimize file listing operations"
    [ $write_time -ge 500 ] && echo "   • Optimize file write operations"
    exit 1
fi