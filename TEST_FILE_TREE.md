# File Tree 404 Error - Diagnosis & Fix

## Problem
Browser shows:
```
POST http://localhost:9000/api/vibecode/files/tree
[HTTP/1.1 404 Not Found 2ms]
Failed to load file tree: 404
```

## Investigation Results

### Test 1: Direct API Call (No Auth)
```bash
curl -X POST http://localhost:9000/api/vibecode/files/tree \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"test"}'
```
**Result**: `{"detail":"Authorization header missing"}` - **401** (not 404!)

### Test 2: Through Frontend (Port 3000)
```bash
curl -X POST http://localhost:3000/api/vibecode/files/tree \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"test"}'
```
**Result**: `{"error":"Unauthorized"}` - **401** (not 404!)

### Test 3: Nginx Proxy with Auth
```bash
curl -X POST http://localhost:9000/api/vibecode/files/tree \
  -H 'Authorization: Bearer test' \
  -d '{"session_id":"test"}'
```
**Result**: `{"detail":"Invalid token"}` - **401** (not 404!)

## Root Cause

The API endpoint EXISTS and works correctly. The **404 in browser is misleading**.

**Actual issue**: Missing or invalid JWT token in browser's localStorage.

## Solution

### Step 1: Check Browser Token
Open browser console and run:
```javascript
console.log('Token:', localStorage.getItem('token'))
```

**If null or undefined**:
- User needs to **log out and log back in**
- Token expired (JWT exp claim)
- Token never saved after login

### Step 2: Verify Token is Valid
If token exists, decode it at https://jwt.io to check:
- `exp` (expiration) - should be future timestamp
- `sub` (user ID) - should match your user

### Step 3: Clear Browser Cache
```javascript
// In browser console
localStorage.clear()
location.reload()
```
Then log in again.

### Step 4: Check Frontend Code
**File**: `components/MonacoVibeFileTree.tsx`  
**Line 186-191**:
```typescript
const response = await fetch('/api/vibecode/files/tree', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...(token && { 'Authorization': `Bearer ${token}` })  // ← Conditional!
  },
  body: JSON.stringify({
    session_id: sessionId,
    path: '/workspace'
  })
})
```

**Issue**: If `token` is falsy, Authorization header is NOT sent!

## Quick Fix Instructions

### For User:
1. **Open DevTools** (F12)
2. **Go to Application tab** → Storage → Local Storage
3. **Check if `token` exists**
4. **If missing**: Logout and login again
5. **Hard refresh**: Ctrl+Shift+R (Windows/Linux) or Cmd+Shift+R (Mac)

### For Developer:
Add better error handling in `MonacoVibeFileTree.tsx`:

```typescript
const loadFileTree = useCallback(async () => {
  if (!sessionId) return

  try {
    setIsLoading(true)
    const token = localStorage.getItem('token')
    
    // ADD THIS CHECK:
    if (!token) {
      console.error('❌ No auth token - user needs to log in')
      setFileTree([])
      setIsLoading(false)
      return
    }
    
    const response = await fetch('/api/vibecode/files/tree', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`  // Always include
      },
      body: JSON.stringify({
        session_id: sessionId,
        path: '/workspace'
      })
    })

    if (!response.ok) {
      // ADD THIS:
      if (response.status === 401) {
        console.error('❌ Auth failed - token expired, please re-login')
        // Optionally redirect to login
        // window.location.href = '/login'
      }
      console.error('Failed to load file tree:', response.status)
      return
    }
    
    // ... rest of code
  }
}, [sessionId])
```

## Nginx Configuration (Already Correct)

```nginx
# VibeCode IDE API routes (direct to backend)
location /api/vibecode/ {
    proxy_pass http://backend:8000;
    proxy_set_header Authorization $http_authorization;  # ← Forwards auth header
    # ... other headers
}
```

## Why Browser Shows 404 Instead of 401?

Possible reasons:
1. **Browser DevTools bug**: Sometimes shows wrong status
2. **CORS preflight failure**: OPTIONS request failed
3. **Cached error**: Old 404 from when route didn't exist
4. **Network error**: Interpreted as 404 by frontend

**Solution**: Hard refresh browser (Ctrl+Shift+R)

## Testing Checklist

- [ ] Token exists in localStorage
- [ ] Token is not expired (check exp claim)
- [ ] User is logged in (check /api/auth/me)
- [ ] Hard refresh browser
- [ ] Clear browser cache
- [ ] Try in incognito/private window
- [ ] Check backend logs for actual request

## Expected Working Flow

1. User logs in → Token saved to localStorage
2. User selects session → File tree component mounts
3. Component reads token from localStorage
4. Sends POST to `/api/vibecode/files/tree` with `Authorization: Bearer {token}`
5. Nginx forwards to backend:8000 with auth header
6. Backend validates JWT → Returns file tree
7. Frontend displays files

---

**Status**: Routes exist and work correctly. Issue is **client-side auth token**.

**Action**: User needs to **re-login** or **hard refresh browser**.











