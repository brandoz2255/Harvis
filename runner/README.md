# VibeCode Runner Container

Multi-runtime container for executing code in VibeCode IDE sessions.

## Features

- **Python 3.11** - Full Python environment with pip
- **Node.js 20** - Latest LTS Node.js with npm
- **Bash/Shell** - Standard shell scripting support
- **Common Tools** - git, curl, and essential utilities

## Building the Image

```bash
cd runner
./build.sh
```

This creates the `harvis-runner:py311-node20` image.

## Using the Runner

### Option 1: Environment Variable

Set the environment variable before starting the backend:

```bash
export VIBECODING_RUNNER_IMAGE=harvis-runner:py311-node20
cd python_back_end
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Option 2: Docker Compose

Add to your `docker-compose.yaml`:

```yaml
services:
  backend:
    environment:
      - VIBECODING_RUNNER_IMAGE=harvis-runner:py311-node20
```

### Option 3: Update Default in Code

Edit `python_back_end/vibecoding/containers.py`:

```python
runner_image = os.getenv("VIBECODING_RUNNER_IMAGE", "harvis-runner:py311-node20")
```

## Supported Languages

### ✅ Fully Supported

- **Python** (`.py`) - Uses `python` or `python3` command
- **JavaScript** (`.js`, `.mjs`) - Uses `node` command
- **TypeScript** (`.ts`) - Requires `ts-node` to be installed
- **Bash** (`.sh`, `.bash`) - Uses `bash` command

### 🔧 Add More Runtimes

To add additional language support:

1. Update the Dockerfile:
```dockerfile
RUN apt-get update && apt-get install -y \
    ruby \
    golang-go \
    && rm -rf /var/lib/apt/lists/*
```

2. Rebuild the image:
```bash
./build.sh
```

## Capabilities Detection

The backend automatically detects available runtimes:

```python
capabilities = {
    "python": _probe("command -v python || command -v python3"),
    "bash": _probe("command -v bash"),
    "node": _probe("command -v node"),
    "ruby": _probe("command -v ruby"),
    "go": _probe("command -v go"),
}
```

## Troubleshooting

### Node.js not found

If you see `exec: "node": executable file not found`:

1. Ensure you're using the custom runner image:
```bash
docker images | grep harvis-runner
```

2. Check the environment variable:
```bash
echo $VIBECODING_RUNNER_IMAGE
```

3. Restart the backend after setting the variable.

### Python not found

The custom image includes Python 3.11. If Python is missing:

1. Rebuild the image:
```bash
cd runner && ./build.sh
```

2. Verify Python is in the image:
```bash
docker run --rm harvis-runner:py311-node20 python --version
```

## Image Size

The runner image is approximately **500MB** compressed, which includes:
- Node.js 20 runtime (~200MB)
- Python 3.11 + pip (~150MB)
- System libraries (~150MB)

## Security

The runner container:
- Runs as non-root user (automatically in Node.js image)
- Has no network access restrictions (add if needed)
- Shares `/workspace` volume with IDE container (read/write)
- Has resource limits enforced by Docker (2GB RAM, 1.5 CPU cores)

## Customization

### Add Custom Packages

Edit `Dockerfile` to add more packages:

```dockerfile
# Python packages
RUN pip3 install --no-cache-dir \
    fastapi \
    sqlalchemy \
    redis

# Node.js packages (global)
RUN npm install -g \
    typescript \
    ts-node \
    eslint

# System packages
RUN apt-get update && apt-get install -y \
    vim \
    htop \
    && rm -rf /var/lib/apt/lists/*
```

### Use Different Base Image

For more runtimes, start from Ubuntu:

```dockerfile
FROM ubuntu:22.04

# Install everything
RUN apt-get update && apt-get install -y \
    python3.11 \
    nodejs \
    ruby \
    golang-go \
    && rm -rf /var/lib/apt/lists/*
```

## Production Recommendations

1. **Pin versions** - Use specific versions for reproducibility
2. **Multi-stage build** - Reduce image size by removing build tools
3. **Security scanning** - Run `docker scan harvis-runner:py311-node20`
4. **Registry** - Push to private registry for production use
5. **Updates** - Regularly rebuild with security patches

## Testing

Test the runner manually:

```bash
# Test Python
docker run --rm harvis-runner:py311-node20 python -c "print('Hello from Python')"

# Test Node.js
docker run --rm harvis-runner:py311-node20 node -e "console.log('Hello from Node')"

# Test Bash
docker run --rm harvis-runner:py311-node20 bash -c "echo 'Hello from Bash'"
```

