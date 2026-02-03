# HARVIS Optimization & Fixes Plan

## 1. Optimized Nginx Configuration
Replace your current `nginx.conf` with this version. It includes:
- **Upstream with Keep-Alive:** Reuses connections to the backend to prevent handshake overhead.
- **HTTP/1.1 for Backend:** Critical for Keep-Alive and stable streaming.
- **Disabled Buffering:** Ensures audio and text streams flow to the browser immediately without waiting for the full response.
- **Generic API Block:** Handles memory stats and other misc API calls directly.

```nginx
events {}

http {
    # Upstream definition with keepalive to recycle connections efficiently
    upstream backend_api {
        server backend:8000;
        keepalive 32; # Keep 32 idle connections to the backend open
    }

    # Global proxy timeout settings
    proxy_connect_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_read_timeout 3600s;
    send_timeout 3600s;
    client_body_timeout 3600s;

    # Allow larger body size for image uploads
    client_max_body_size 50m;

    # Keep-alive settings
    keepalive_timeout 3600s;
    keepalive_requests 1000;

    # Map allowed origins dynamically
    map $http_origin $cors_origin {
        default "";
        "http://localhost:9000" "$http_origin";
        "http://127.0.0.1:9000" "$http_origin";
        "http://localhost:8000" "$http_origin";
        "http://localhost:3000" "$http_origin";
        "http://localhost:3001" "$http_origin";
        "http://127.0.0.1:8080" "$http_origin";
        "http://127.0.0.1:3000" "$http_origin";
        "http://127.0.0.1:3001" "$http_origin";
        "http://localhost:5173" "$http_origin";
        "http://localhost:5678" "$http_origin";
        "http://127.0.0.1:5678" "$http_origin";
    }

    server {
        listen 80;

        # Direct API calls to backend with Keep-Alive
        location /api/ {
            proxy_pass http://backend_api;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            
            proxy_connect_timeout 300s;
            proxy_send_timeout 300s;
            proxy_read_timeout 300s;
        }

        # Auth & History (Specific direct blocks)
        location ~ ^/api/(me|auth/|chat-history/) {
            if ($request_method = 'OPTIONS') {
                add_header 'Access-Control-Allow-Origin' $cors_origin always;
                add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS, PUT, DELETE' always;
                add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
                add_header 'Access-Control-Allow-Credentials' 'true' always;
                return 204;
            }
            
            proxy_hide_header 'Access-Control-Allow-Origin';
            proxy_hide_header 'Access-Control-Allow-Methods';
            proxy_hide_header 'Access-Control-Allow-Headers';
            proxy_hide_header 'Access-Control-Allow-Credentials';
            
            add_header 'Access-Control-Allow-Origin' $cors_origin always;
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS, PUT, DELETE' always;
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
            add_header 'Access-Control-Allow-Credentials' 'true' always;

            proxy_pass http://backend_api;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Authorization $http_authorization;
            proxy_set_header Cookie $http_cookie;
        }

        # Chat & Mic-Chat (Streaming + Keep-Alive)
        location ~ ^/api/(chat|mic-chat) {
            if ($request_method = 'OPTIONS') {
                add_header 'Access-Control-Allow-Origin' $cors_origin always;
                add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS, PUT, DELETE' always;
                add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
                add_header 'Access-Control-Allow-Credentials' 'true' always;
                return 204;
            }

            proxy_hide_header 'Access-Control-Allow-Origin';
            proxy_hide_header 'Access-Control-Allow-Methods';
            add_header 'Access-Control-Allow-Origin' $cors_origin always;
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS, PUT, DELETE' always;
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
            add_header 'Access-Control-Allow-Credentials' 'true' always;

            proxy_pass http://backend_api;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_buffering off;
            proxy_cache off;
            
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header Authorization $http_authorization;
            proxy_set_header Cookie $http_cookie;

            proxy_read_timeout 3600s;
        }

        # Research Endpoints
        location ~ ^/api/(research|research-chat|fact-check|web-search) {
             # ... Same as Chat but with 600s timeout ...
             proxy_pass http://backend_api;
             proxy_http_version 1.1;
             proxy_set_header Connection "";
             proxy_read_timeout 600s;
        }

        # AI SDK (Next.js Side)
        location /api/ai-chat {
            proxy_pass http://frontend:3000;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_buffering off;
            proxy_read_timeout 3600s;
        }

        # Frontend
        location / {
            proxy_pass http://frontend:3000;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
        }
    }
}
```

## 2. Backend Concurrency Advice
If you use a single worker, TTS generation will block the memory stats endpoint. Use at least 4 workers:

```bash
# Example for Uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

## 3. Frontend Fixes Applied
- **AbortController:** Added to `fetchMemoryStats` in `components/chat-sidebar.tsx` with a 5s timeout.
- **Request Tracking:** Used `useRef` to prevent multiple simultaneous polling requests.
- **Diagnostic Logging:** Added detailed `console.log` for debugging timeouts vs. network errors.

## 4. Troubleshooting Steps
1. Apply the `nginx.conf` changes.
2. Restart the backend with multiple workers.
3. Reload the frontend and check the console for `[MemoryStats]` logs.
