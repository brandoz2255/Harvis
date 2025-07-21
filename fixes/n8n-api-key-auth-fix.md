# n8n API Key Authentication Fix

**Issue Date:** 2025-01-21  
**Status:** ✅ RESOLVED  
**Issue Type:** Authentication Error  

## Problem Summary

n8n automation service was failing with `401 Unauthorized` errors when trying to create workflows via REST API calls.

### Error Messages
- `{"status":"error","message":"Unauthorized"}` from `/rest/workflows` endpoint
- `{"message":"'X-N8N-API-KEY' header required"}` from `/api/v1/workflows` endpoint

### Initial Symptoms
```
ERROR:n8n.client:n8n API error 401: {"status":"error","message":"Unauthorized"}
ERROR:n8n.automation_service:Automation request failed: n8n API error 401: {"status":"error","message":"Unauthorized"}  
WARNING:main:❌ n8n automation failed: n8n API error 401: {"status":"error","message":"Unauthorized"}
```

## Root Cause Analysis

1. **n8n REST API Requirements**: The n8n instance was configured to require API key authentication via `X-N8N-API-KEY` header for all REST API endpoints
2. **Overcomplex Authentication Logic**: The client was attempting multiple fallback authentication methods (Basic Auth, UI session login) which don't work with n8n REST API
3. **Persistent API Key Issue**: API keys created programmatically get deleted when n8n container restarts, breaking automation

## Solutions Attempted

### ❌ Failed Approach 1: Basic Authentication
- Updated docker-compose.yaml with `N8N_BASIC_AUTH_ACTIVE: "true"`
- Implemented HTTPBasicAuth in client.py
- **Result**: Still returned 401 - n8n REST API doesn't accept Basic Auth

### ❌ Failed Approach 2: Session Login + API Key Generation  
- Implemented UI login via `/rest/login`
- Added automatic API key creation/retrieval
- **Result**: Overly complex, unreliable, and API keys get deleted on container restart

### ✅ Successful Approach: Manual API Key + Simplified Client

## Final Solution

### Step 1: Create Persistent API Key
1. Access n8n UI at `http://localhost:5678`
2. Login with credentials: `admin` / `adminpass`
3. Navigate to: **Settings → n8n API → Create API key**
4. Copy the generated API key (e.g., `n8n_api_1234567890abcdef...`)

### Step 2: Configure Environment Variables
Add to `/home/guruai/auth/aidev/python_back_end/.env`:
```bash
N8N_API_KEY=n8n_api_1234567890abcdef...
```

### Step 3: Simplified Client Implementation
Updated `python_back_end/n8n/client.py` with minimal authentication logic:

```python
def _login(self) -> bool:
    if self.authenticated:
        return True

    if not self.api_key:
        raise N8nClientError("API key not provided. Set N8N_API_KEY environment variable.")

    # Test the API key
    try:
        headers = {'X-N8N-API-KEY': self.api_key}
        response = self.session.get(f"{self.base_url}/api/v1/workflows", headers=headers)
        
        if response.status_code == 200:
            self.authenticated = True
            return True
        else:
            raise N8nClientError(f"API key authentication failed: {response.status_code}")
    except Exception as e:
        raise N8nClientError(f"API key authentication error: {e}")
```

### Step 4: Request Headers
All API requests now include:
```python
headers['X-N8N-API-KEY'] = self.api_key
```

## Files Modified

- `python_back_end/n8n/client.py` - Simplified authentication to API key only
- `python_back_end/.env` - Added N8N_API_KEY environment variable  
- `nginx.conf` - Added CORS support for n8n (still useful)
- `python_back_end/n8n/helper.py` - Created helper module (still useful)

## Verification Steps

### Test API Key Works:
```bash
# From backend container:
curl -H "X-N8N-API-KEY: your_api_key" http://n8n:5678/api/v1/workflows
# Should return: {"data": []} or list of workflows
```

### Test Client Connection:
```python
from n8n.client import N8nClient
client = N8nClient(api_key="your_api_key")
success = client.test_connection()
print(f"Connection successful: {success}")
```

## Key Learnings

1. **Keep It Simple**: n8n REST API only needs `X-N8N-API-KEY` header - no complex auth flows needed
2. **Manual API Key Creation**: Programmatically created API keys don't persist across container restarts
3. **Read the Error Messages**: `"'X-N8N-API-KEY' header required"` was the clear indicator of what was needed
4. **Environment Variables**: Properly configure `.env` files and ensure container loading

## Prevention for Future

- Always check n8n documentation for current authentication requirements
- Test authentication with simple curl commands before implementing complex logic
- Store API keys securely in environment variables, never hardcode
- Create API keys manually through UI for persistence across container restarts

## Related Issues

This fix resolves the same core issue described in:
- `research/n8nIssue/solution1.md`
- `research/n8nIssue/solution2.md`  
- `research/n8nIssue/solution3.md`
- `research/n8nIssue/solution4.md`

The research correctly identified the problem but the final working solution required the simplified approach documented here.