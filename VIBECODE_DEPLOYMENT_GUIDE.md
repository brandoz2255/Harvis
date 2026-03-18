# VibeCode IDE Deployment Guide

## Overview

This guide provides step-by-step instructions for deploying the VibeCode IDE feature in the Harvis AI platform. VibeCode is a browser-based development environment that provides VSCode-like functionality with Docker container isolation, file management, terminal access, code execution, and AI assistance.

## Prerequisites

### System Requirements

- **Operating System**: Linux (Ubuntu 20.04+ recommended)
- **Docker**: Version 20.10 or higher
- **Docker Compose**: Version 2.0 or higher
- **RAM**: Minimum 8GB (16GB+ recommended for multiple concurrent sessions)
- **CPU**: 4+ cores recommended
- **Disk Space**: 50GB+ for Docker images and volumes

### Required Software

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt-get update
sudo apt-get install docker-compose-plugin

# Verify installations
docker --version
docker compose version
```

### Docker Socket Access

The backend service requires access to the Docker socket to manage user containers. This is configured in `docker-compose.yaml`:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

**Security Note**: The Docker socket provides root-level access to the host system. Ensure the backend container is properly secured and only trusted code runs within it.

## Environment Configuration

### Backend Environment Variables

Create or update `aidev/python_back_end/.env`:

```bash
# Database Configuration
DATABASE_URL=postgresql://pguser:pgpassword@pgsql:5432/database

# JWT Authentication
JWT_SECRET=your-secret-key-here-change-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# N8N Integration (optional)
N8N_URL=http://n8n:5678
N8N_USER=your-n8n-user
N8N_PASSWORD=your-n8n-password
N8N_API_KEY=your-n8n-api-key

# Ollama Configuration (optional - for local AI)
OLLAMA_URL=http://ollama:11434

# OpenAI Configuration (optional - for cloud AI)
# OPENAI_API_KEY=your-openai-api-key

# Anthropic Configuration (optional - for cloud AI)
# ANTHROPIC_API_KEY=your-anthropic-api-key
```

**Important**: Change the `JWT_SECRET` to a secure random value in production:

```bash
# Generate a secure JWT secret
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Frontend Environment Variables

Create or update `aidev/front_end/jfrontend/.env.local`:

```bash
# API Configuration
NEXT_PUBLIC_API_URL=http://localhost:9000

# Authentication
NEXT_PUBLIC_JWT_SECRET=same-as-backend-jwt-secret
```

### Database Configuration

The PostgreSQL database is configured in `docker-compose.yaml`:

```yaml
environment:
  POSTGRES_USER: pguser
  POSTGRES_PASSWORD: pgpassword
  POSTGRES_DB: database
```

**Production Note**: Change these credentials in production and update the `DATABASE_URL` accordingly.

## Database Setup

### 1. Initialize Database

The database is automatically initialized when the PostgreSQL container starts. The `init-db.sh` script creates the required extensions and base schema.

### 2. Run Migrations

After the containers are running, execute the migrations:

```bash
# Enter the backend container
docker exec -it backend bash

# Run migrations
cd /app
python run_migrations.py

# Verify migrations
python check_schema.py
```

### 3. Create Test User (Development Only)

For development/testing, create a test user:

```bash
# Inside backend container
python create_test_user.py
```

This creates a user with:
- Username: `testuser`
- Password: `testpass123`
- Email: `test@example.com`

## Deployment Steps

### 1. Clone Repository

```bash
git clone <repository-url>
cd aidev
```

### 2. Configure Environment

```bash
# Copy example environment files
cp python_back_end/.env.example python_back_end/.env
cp front_end/jfrontend/.env.local.example front_end/jfrontend/.env.local

# Edit environment files with your configuration
nano python_back_end/.env
nano front_end/jfrontend/.env.local
```

### 3. Create Docker Network

```bash
# Create the external network for service communication
docker network create ollama-n8n-network
```

### 4. Build and Start Services

```bash
# Build and start all services
docker compose up -d --build

# View logs
docker compose logs -f

# Check service status
docker compose ps
```

### 5. Verify Services

```bash
# Check backend health
curl http://localhost:8000/health

# Check frontend
curl http://localhost:3000

# Check Nginx proxy
curl http://localhost:9000
```

### 6. Run Database Migrations

```bash
# Execute migrations
docker exec -it backend python run_migrations.py

# Verify schema
docker exec -it backend python check_schema.py
```

### 7. Access the Application

Open your browser and navigate to:
- **Main Application**: http://localhost:9000
- **Backend API**: http://localhost:9000/api/docs (Swagger UI)
- **Frontend Direct**: http://localhost:3000 (development only)

## Nginx Configuration

The Nginx reverse proxy is configured in `aidev/nginx.conf`. Key configurations:

### WebSocket Support

```nginx
location ~ ^/api/vibecode/ws/terminal$ {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;  # 24 hours
}
```

### API Routes

- `/api/vibecode/*` - VibeCode IDE API endpoints (backend)
- `/api/auth/*` - Authentication endpoints (backend)
- `/api/me` - User profile endpoint (backend)
- `/` - Frontend application (frontend)

### CORS Configuration

CORS is configured to allow requests from:
- `http://localhost:9000` (main access point)
- `http://localhost:3000` (frontend dev server)
- `http://localhost:8000` (backend dev server)

Update the `map $http_origin $cors_origin` section in `nginx.conf` for production domains.

## Container Management

### VibeCode Session Containers

Each user session creates a Docker container with:

**Naming Convention**: `vibecode-{user_id}-{session_id}`

**Volume**: `vibecode-{user_id}-{session_id}-ws` mounted at `/workspace`

**Resource Limits**:
- Memory: 2GB
- CPU: 1.5 cores
- PIDs: 512 (prevents fork bombs)

**Security Options**:
- `no-new-privileges:true`
- Network: bridge (isolated)

### Container Lifecycle

1. **Create**: User creates a new session
2. **Start**: Container starts with `tail -f /dev/null` (idle)
3. **Active**: User interacts via terminal, file operations, code execution
4. **Suspend**: Container stops, volume persists
5. **Resume**: Container restarts from existing volume
6. **Delete**: Container and volume removed (optional force delete)

### Cleanup

Inactive containers are automatically cleaned up after 2 hours of inactivity. Manual cleanup:

```bash
# List VibeCode containers
docker ps -a --filter "label=app=vibecode"

# Remove stopped VibeCode containers
docker container prune --filter "label=app=vibecode"

# Remove unused volumes
docker volume prune
```

## Monitoring and Logs

### View Service Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f nginx

# VibeCode session containers
docker logs vibecode-{user_id}-{session_id}
```

### Health Checks

```bash
# Backend health
curl http://localhost:9000/api/health

# Database connection
docker exec -it pgsql-db psql -U pguser -d database -c "SELECT 1;"

# Check running sessions
docker exec -it backend python -c "
from vibecoding.sessions import SessionManager
import asyncio
sm = SessionManager()
sessions = asyncio.run(sm.list_sessions(user_id=1))
print(f'Active sessions: {len(sessions)}')
"
```

### Performance Monitoring

```bash
# Container resource usage
docker stats

# Disk usage
docker system df

# Network usage
docker network inspect ollama-n8n-network
```

## Troubleshooting

### Common Issues

#### 1. Backend Cannot Access Docker Socket

**Symptom**: Error creating containers: "Cannot connect to Docker daemon"

**Solution**:
```bash
# Verify socket mount in docker-compose.yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock

# Check socket permissions
ls -la /var/run/docker.sock

# Restart backend
docker compose restart backend
```

#### 2. Database Connection Failed

**Symptom**: Backend logs show "could not connect to server"

**Solution**:
```bash
# Check database is running
docker compose ps pgsql

# Verify DATABASE_URL in .env
# Check database logs
docker compose logs pgsql

# Restart database
docker compose restart pgsql
```

#### 3. WebSocket Connection Failed

**Symptom**: Terminal shows "Disconnected" or fails to connect

**Solution**:
```bash
# Check Nginx WebSocket configuration
docker compose logs nginx

# Verify backend is running
curl http://localhost:8000/health

# Check WebSocket endpoint
wscat -c "ws://localhost:9000/api/vibecode/ws/terminal?session_id=test&token=your-jwt"
```

#### 4. Container Creation Timeout

**Symptom**: Session creation takes > 3 seconds or times out

**Solution**:
```bash
# Check Docker daemon performance
docker info

# Pull base image manually
docker pull python:3.10-slim

# Check disk space
df -h

# Clean up unused images
docker image prune -a
```

#### 5. File Operations Fail

**Symptom**: Cannot read/write files in workspace

**Solution**:
```bash
# Check volume exists
docker volume ls | grep vibecode

# Inspect volume
docker volume inspect vibecode-{user_id}-{session_id}-ws

# Check container is running
docker ps --filter "name=vibecode-{user_id}-{session_id}"

# Verify permissions inside container
docker exec vibecode-{user_id}-{session_id} ls -la /workspace
```

## Security Considerations

### 1. Docker Socket Access

The backend has access to the Docker socket, which provides root-level access. Mitigations:

- Run backend in a restricted container
- Implement strict input validation
- Use resource limits on user containers
- Apply security options (`no-new-privileges`)
- Monitor container creation/deletion

### 2. Path Traversal Prevention

All file operations use path sanitization:

```python
def sanitize_path(path: str, base: str = "/workspace") -> str:
    # Blocks .., absolute paths, symlinks outside workspace
    ...
```

### 3. Command Injection Prevention

Code execution uses safe command construction:

```python
def execute_safe_command(cmd: str) -> str:
    # Blocks dangerous patterns: ;, &&, ||, |, `, $()
    ...
```

### 4. Rate Limiting

API endpoints are rate-limited:

- Execution: 10 requests/minute
- File save: 60 requests/minute
- General API: 100 requests/minute

### 5. JWT Authentication

All API requests require valid JWT tokens:

```python
@router.post("/api/vibecode/sessions/create")
async def create_session(
    user: Dict = Depends(get_current_user)
):
    ...
```

### 6. Resource Limits

User containers have strict resource limits:

- Memory: 2GB
- CPU: 1.5 cores
- PIDs: 512
- Network: isolated bridge

## Backup and Recovery

### Database Backup

```bash
# Backup database
docker exec pgsql-db pg_dump -U pguser database > backup_$(date +%Y%m%d).sql

# Restore database
docker exec -i pgsql-db psql -U pguser database < backup_20250107.sql
```

### Volume Backup

```bash
# Backup a session volume
docker run --rm \
  -v vibecode-1-abc123-ws:/source:ro \
  -v $(pwd):/backup \
  alpine tar czf /backup/session-backup.tar.gz -C /source .

# Restore a session volume
docker run --rm \
  -v vibecode-1-abc123-ws:/target \
  -v $(pwd):/backup \
  alpine tar xzf /backup/session-backup.tar.gz -C /target
```

## Scaling Considerations

### Horizontal Scaling

To scale the backend:

```yaml
backend:
  deploy:
    replicas: 3
```

**Note**: Session affinity is required for WebSocket connections. Use a load balancer with sticky sessions.

### Vertical Scaling

Increase container resources:

```yaml
backend:
  deploy:
    resources:
      limits:
        cpus: '4'
        memory: 8G
```

### Database Scaling

For high load:

1. Use connection pooling (already configured in asyncpg)
2. Add read replicas for session queries
3. Consider Redis for session caching

## Production Checklist

- [ ] Change all default passwords
- [ ] Generate secure JWT_SECRET
- [ ] Configure HTTPS/TLS (use Let's Encrypt)
- [ ] Set up firewall rules
- [ ] Configure backup automation
- [ ] Set up monitoring (Prometheus/Grafana)
- [ ] Configure log aggregation (ELK stack)
- [ ] Review and restrict CORS origins
- [ ] Set up container resource monitoring
- [ ] Configure automatic container cleanup
- [ ] Test disaster recovery procedures
- [ ] Document incident response procedures
- [ ] Set up alerting for critical errors
- [ ] Review security audit logs
- [ ] Configure rate limiting for production load

## Support and Maintenance

### Regular Maintenance Tasks

**Daily**:
- Monitor container count and resource usage
- Check error logs for anomalies
- Verify backup completion

**Weekly**:
- Clean up unused Docker images and volumes
- Review security logs
- Update dependencies if needed

**Monthly**:
- Test backup restoration
- Review and optimize database queries
- Update Docker images to latest versions
- Security audit and vulnerability scan

### Getting Help

For issues or questions:

1. Check logs: `docker compose logs -f`
2. Review this deployment guide
3. Check the troubleshooting section
4. Consult the API documentation: http://localhost:9000/api/docs
5. Review the design document: `.kiro/specs/vibecode-ide/design.md`

## Additional Resources

- **Requirements Document**: `.kiro/specs/vibecode-ide/requirements.md`
- **Design Document**: `.kiro/specs/vibecode-ide/design.md`
- **Implementation Tasks**: `.kiro/specs/vibecode-ide/tasks.md`
- **API Documentation**: http://localhost:9000/api/docs
- **Docker Documentation**: https://docs.docker.com/
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Next.js Documentation**: https://nextjs.org/docs
