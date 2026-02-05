# Frontend Docker Build Guide

## The Problem

Docker's build cache often doesn't detect changes to source files properly, especially with `COPY . .` commands. This causes the frontend to not include your latest changes even after rebuilding.

## The Solution

I've optimized the build process with several improvements:

### 1. Granular COPY Commands
Instead of `COPY . .`, the Dockerfile now copies files individually:
```dockerfile
COPY app ./app
COPY components ./components
COPY hooks ./hooks
COPY lib ./lib
COPY stores ./stores
COPY types ./types
COPY public ./public
COPY *.json *.ts *.js *.mjs ./
```

This ensures Docker properly detects file changes.

### 2. Cache-Busting Build Args
The Dockerfile includes cache-busting arguments:
```dockerfile
ARG BUILD_TIMESTAMP=unknown
ARG GIT_COMMIT=unknown
```

Changing these values forces Docker to invalidate the cache.

### 3. Comprehensive .dockerignore
Created a `.dockerignore` file to prevent unnecessary files from triggering rebuilds or being included in the image.

### 4. Rebuild Helper Script
Created `scripts/rebuild-frontend.sh` for easy rebuilding.

---

## How to Rebuild the Frontend

### Option 1: Smart Rebuild (Recommended)
```bash
./scripts/rebuild-frontend.sh
```
This automatically generates a timestamp to bust the cache and ensures your changes are included.

### Option 2: Full Rebuild (Guaranteed Fresh)
```bash
./scripts/rebuild-frontend.sh --no-cache
```
This completely bypasses Docker's cache. Slowest but most reliable.

### Option 3: Quick Rebuild (Fastest)
```bash
./scripts/rebuild-frontend.sh --quick
```
Or simply:
```bash
docker-compose build frontend
docker-compose up -d frontend
```
This uses Docker's cache. Fastest but may miss some changes.

### Option 4: Manual Build with Timestamp
```bash
# Set timestamp to bust cache
export BUILD_TIMESTAMP=$(date -u +"%Y-%m-%d-%H%M%S")

# Build and restart
docker-compose build --build-arg BUILD_TIMESTAMP="$BUILD_TIMESTAMP" frontend
docker-compose up -d frontend
```

---

## Troubleshooting

### Changes Still Not Showing?

1. **Force a complete rebuild:**
   ```bash
   ./scripts/rebuild-frontend.sh --no-cache
   ```

2. **Check if files are in the container:**
   ```bash
   # Check if component exists
   docker exec harvis-frontend find .next -name "*video*" 2>/dev/null
   
   # Check the built output
   docker exec harvis-frontend ls -la .next/server/
   ```

3. **Clear Docker's build cache:**
   ```bash
   docker builder prune -f
   ./scripts/rebuild-frontend.sh --no-cache
   ```

4. **Check browser cache:**
   - Hard refresh: `Ctrl+Shift+R` (or `Cmd+Shift+R` on Mac)
   - Clear browser cache completely
   - Try incognito/private mode

### Verify YouTube Components Exist

```bash
# Check source files exist locally
ls -la front_end/newjfrontend/components/video-carousel.tsx
ls -la front_end/newjfrontend/components/youtube-embed.tsx

# Rebuild with the helper
./scripts/rebuild-frontend.sh

# Verify in container
docker exec harvis-frontend find .next -type f -name "*" | grep -i "video\|youtube" | head -20
```

---

## Why This Happens

1. **Docker Layer Caching**: Docker caches each layer. If it thinks a layer hasn't changed, it reuses the cached version.

2. **Multi-Stage Builds**: The frontend uses a multi-stage build (deps → deps-dev → builder → runner). The `COPY . .` in the builder stage often doesn't detect changes.

3. **Standalone Output**: Next.js outputs to `.next/standalone` which only includes compiled files, not source.

4. **Build Context**: Docker's build context might not include the latest files if not properly configured.

---

## Quick Reference

| Command | Speed | Reliability | Use When |
|---------|-------|-------------|----------|
| `./rebuild-frontend.sh` | Medium | High | Normal development |
| `./rebuild-frontend.sh --no-cache` | Slow | Guaranteed | Critical changes not showing |
| `./rebuild-frontend.sh --quick` | Fast | Medium | Minor tweaks, testing |
| `docker-compose build frontend` | Fast | Low | Fast iterations (risky) |

---

## For Development (Hot Reload)

If you're doing active frontend development, consider using the development compose file which mounts source code as volumes:

```bash
# Uses volume mounts for hot-reload
docker-compose -f docker-compose.dev.yml up frontend
```

Note: The dev compose file has been fixed to use the correct path (`newjfrontend` instead of `jfrontend`).
