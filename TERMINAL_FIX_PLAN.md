# Terminal WebSocket Connection - Root Cause Analysis & Fix Plan

## 🔍 Root Cause Analysis

### Issue
Browser error: `Firefox can't establish a connection to ws://localhost:9000/ws/vibecoding/terminal`

### Diagnosis Steps Performed

1. ✅ **Nginx Configuration**: CORRECT
   - `/ws/` location exists and proxies to `backend:8000/ws/`
   - WebSocket headers are set correctly
   
2. ✅ **Frontend Code**: CORRECT
   - Constructs URL as `ws://localhost:9000/ws/vibecoding/terminal?session_id=...&token=...`
   - This is the correct format

3. ❌ **Backend Registration**: **PROBLEM FOUND**
   - Testing `curl http://localhost:8000/ws/vibecoding/terminal` returns **404 Not Found**
   - This means the FastAPI route is NOT registered
   - The `terminal_router` IS imported and included in `main.py:458`
   - BUT the backend container needs to restart to register the route

### Root Cause
**The backend container hasn't restarted since the terminal router was added/modified.**

The backend is using `--reload` mode, but sometimes WebSocket routes don't hot-reload properly, or the terminal.py file hasn't been changed recently enough to trigger a reload.

---

## ✅ Fix Plan

### Step 1: Verify Current State

```bash
# Check what routes the backend currently has
docker exec backend python -c "
import sys
sys.path.insert(0, '/app')
from main import app
print('Routes registered:')
for route in app.routes:
    if hasattr(route, 'path'):
        print(f'  {route.path}')
"
```

### Step 2: Trigger Backend Reload

**Option A: Touch the terminal.py file** (forces reload):
```bash
docker exec backend touch /app/vibecoding/terminal.py
```

**Option B: Restart the backend container**:
```bash
docker restart backend
# Wait 10 seconds for it to start
sleep 10
```

**Option C: Stop and start** (cleanest):
```bash
docker stop backend
docker start backend
sleep 10
```

### Step 3: Verify the Route is Registered

```bash
# This should NOT return 404
curl -i "http://localhost:8000/ws/vibecoding/terminal?session_id=test&token=test" 2>&1 | grep "HTTP/"
```

**Expected Result**: 
- Should get `426 Upgrade Required` or `400 Bad Request` or similar
- Should NOT get `404 Not Found`

### Step 4: Test WebSocket Upgrade

```bash
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "http://localhost:8000/ws/vibecoding/terminal?session_id=test&token=test"
```

**Expected Result**:
- Should get `101 Switching Protocols` (even with invalid token, it should attempt the upgrade)
- Or `401 Unauthorized` (if authentication happens before upgrade)

### Step 5: Test Through Nginx

```bash
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "http://localhost:9000/ws/vibecoding/terminal?session_id=test&token=test"
```

**Expected Result**: Same as Step 4, but through Nginx

### Step 6: Test in Browser

1. Refresh the browser (F5)
2. Go to `/ide`
3. Open a session
4. Click Terminal tab
5. Check browser console - should now connect

---

## 📋 Quick Command Sequence

```bash
# 1. Restart backend to ensure routes are registered
docker restart backend && sleep 10

# 2. Verify route exists
echo "Testing if route is registered..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/ws/vibecoding/terminal?session_id=test&token=test")
if [ "$RESPONSE" == "404" ]; then
    echo "❌ Still getting 404 - route not registered"
    echo "Check if terminal_router is properly imported in main.py"
else
    echo "✅ Route is registered (HTTP $RESPONSE)"
fi

# 3. Test through Nginx
echo "Testing through Nginx..."
curl -s -o /dev/null -w "Nginx response: %{http_code}\n" "http://localhost:9000/ws/vibecoding/terminal?session_id=test&token=test"

# 4. Check backend logs for WebSocket
echo "Recent backend logs:"
docker logs backend 2>&1 | tail -20
```

---

## 🎯 Expected Outcome

After restarting the backend:
1. ✅ `curl http://localhost:8000/ws/vibecoding/terminal` returns something OTHER than 404
2. ✅ Browser can connect to WebSocket
3. ✅ Terminal tab shows bash prompt
4. ✅ Can type commands and see output

---

## 🔧 If It Still Doesn't Work

### Check #1: Is terminal.py actually defining the route?
```bash
docker exec backend grep -n "@router.websocket" /app/vibecoding/terminal.py
```

**Expected**: Should show line number with `@router.websocket("/ws/vibecoding/terminal")`

### Check #2: Is the router being exported?
```bash
docker exec backend grep "terminal_router" /app/vibecoding/__init__.py
```

**Expected**: Should see `from .terminal import router as terminal_router`

### Check #3: Are there any import errors?
```bash
docker logs backend 2>&1 | grep -i "error\|exception\|terminal"
```

---

## Summary

**The issue is NOT with Nginx or the frontend.**  
**The issue is that the backend route `/ws/vibecoding/terminal` is not registered.**  
**Solution: Restart the backend container.**

After restart, everything should work.

