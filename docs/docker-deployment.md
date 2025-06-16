# Docker Deployment Guide

This document provides instructions for deploying the AI Voice Assistant using Docker containers.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Docker Setup](#docker-setup)
3. [Building Images](#building-images)
4. [Running Containers](#running-containers)
5. [Environment Variables](#environment-variables)
6. [Network Configuration](#network-configuration)
7. [Volume Mounting](#volume-mounting)
8. [Security Considerations](#security-considerations)
9. [Advanced Usage](#advanced-usage)

## Prerequisites

### Hardware Requirements
- CPU: Multi-core processor (8+ cores recommended)
- GPU: NVIDIA GPU with CUDA support (optional but recommended)
- RAM: 16GB or more
- Storage: SSD with at least 50GB free space

### Software Requirements
- Docker: Version 20.10 or later
- Docker Compose: Version 1.29 or later
- NVIDIA drivers and CUDA toolkit (if using GPU)

## Docker Setup

### Install Docker
Follow the official Docker installation guide for your operating system:
- [Docker Installation](https://docs.docker.com/get-docker/)

### Install Docker Compose
Install Docker Compose following the official documentation:
- [Docker Compose Installation](https://docs.docker.com/compose/install/)

## Building Images

### Clone Repository
First, clone the project repository:

```bash
git clone https://github.com/yourusername/ai-voice-assistant.git
cd ai-voice-assistant
```

### Build Docker Images
Build the necessary Docker images using the provided Dockerfile:

```bash
docker-compose -f docker-compose.yml build
```

## Running Containers

### Start Services
Start all services defined in the `docker-compose.yml` file:

```bash
docker-compose up -d
```

This will start:
- Ollama LLM server
- Web application
- Any additional services required for the project

### Check Container Status
Verify that all containers are running correctly:

```bash
docker-compose ps
```

## Environment Variables

### Configuration File
Create a `.env` file in the root directory with necessary environment variables. Here's an example configuration:

```ini
# .env

# Ollama LLM server settings
OLLAMA_URL=http://ollama:11434

# Web application settings
WEB_PORT=8000

# GPU settings (if using CUDA)
USE_CUDA=true
```

## Network Configuration

### Docker Network
Docker Compose automatically creates a network for the services. You can inspect it with:

```bash
docker network ls
```

### Service Communication
Services can communicate with each other using their service names as hostnames within the Docker network.

Example: The web application can connect to the Ollama server at `http://ollama:11434`.

## Volume Mounting

### Persistent Storage
Mount volumes for persistent storage of data:

```yaml
services:
  ollama:
    image: ollama/ollama
    volumes:
      - ./data/ollama:/root/.cache/ollama
```

This configuration mounts the `./data/ollama` directory on your host to `/root/.cache/ollama` in the container, allowing data persistence across container restarts.

## Security Considerations

### Best Practices
- Use non-root users inside containers whenever possible
- Limit resources (CPU/memory) for each container
- Regularly update Docker images to include security patches
- Use Docker secrets or environment variables for sensitive information

### Network Security
- Restrict access to the Docker daemon
- Run containers in user-defined networks with proper isolation
- Enable firewalls and use appropriate network policies

## Advanced Usage

### GPU Support with NVIDIA
To enable CUDA support, install the NVIDIA Container Toolkit:

```bash
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

Add the following to your Docker daemon configuration (`/etc/docker/daemon.json`):

```json
{
  "default-runtime": "nvidia",
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime",
      "runtimeArgs": []
    }
  }
}
```

### Scaling Services
Use Docker Swarm or Kubernetes for scaling services across multiple nodes:

```bash
# Initialize Docker Swarm (only on one node)
docker swarm init

# Deploy stack using Docker Compose
docker stack deploy -c docker-compose.yml ai-voice-assistant
```

## Troubleshooting

### Common Issues
- **Service Not Starting**: Check logs with `docker-compose logs <service_name>`
- **Network Connectivity**: Ensure services can resolve each other's hostnames
- **Resource Limits**: Verify Docker daemon has access to sufficient CPU and memory resources

### Debugging Tips
- Use `docker exec` to enter a running container for interactive troubleshooting
- Check Docker events with `docker events`
- Monitor resource usage with `docker stats`

## Resources for Further Learning

### Docker Documentation
- [Docker Docs](https://docs.docker.com/)
- [Docker Compose Docs](https://docs.docker.com/compose/)

### NVIDIA Container Toolkit
- [NVIDIA Container Toolkit Install Guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

### Kubernetes for Scaling
- [Kubernetes Docs](https://kubernetes.io/docs/home/)
