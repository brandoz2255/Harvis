# ---------- Builder: compile any source wheels ----------
# PyTorch base with CUDA 12.8 — required for RTX 50-series (sm_120 / Blackwell).
# The prior 2.6.0+cu124 base only had kernels up to sm_90, so every torch model
# (TTS, Whisper, embeddings) silently fell back to CPU on this GPU. 2.8.0+cu128
# ships sm_120 kernels → GPU-accelerated TTS (was ~15s/sentence on CPU).
FROM docker.io/pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime AS builder

# Install build tools for compiling source wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential curl \
  && rm -rf /var/lib/apt/lists/*

############################
# Create non-root user early (Podman compatibility)
############################
RUN useradd -m -u 1001 -s /bin/bash appuser

############################
# Docker socket access setup
############################
# Install Docker CLI for container management
RUN apt-get update && apt-get install -y \
  docker.io \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Add appuser to docker group (GID will be set at runtime)
# Note: The actual docker group GID from host will be mapped via volume mount
RUN groupadd -g 999 docker || true && \
  usermod -aG docker appuser || true

############################
# Python deps (as root, then switch to appuser)
############################
COPY requirements.txt requirements-core.txt requirements-voice.txt ./

# Build tooling for any requirement that has no prebuilt wheel for this
# platform. Cython stays: several source dists in requirements.txt need it.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel Cython

# Build wheels for the rest (excluding torch/torchvision/torchaudio and numpy to prevent conflicts)
# PyTorch is already installed in base image, so skip it.
# The two halves are concatenated rather than read through requirements.txt's
# `-r` lines: the greps below have to see the real package names to strip them,
# and an `-r` include would hide torch from them.
RUN cat requirements-core.txt requirements-voice.txt \
  | grep -v "^torch" | grep -v "^numpy" > requirements_no_torch_numpy.txt \
  && pip wheel --no-cache-dir -r requirements_no_torch_numpy.txt -w /wheels

# NOTE: pkuseg is deliberately NOT built here. It was a prerequisite of
# chatterbox-tts, which has been commented out of requirements.txt since the
# transformers>=0.27.0 conflict. Building it left 180 MB of Chinese word
# segmentation data in the runtime image that nothing imports and no installed
# package depends on. If chatterbox-tts ever comes back, restore:
#   RUN pip wheel --no-cache-dir pkuseg==0.0.25 --no-build-isolation -w /wheels

# Remove any numpy wheels that got built as dependencies (keep only one version)
RUN rm -f /wheels/numpy-*.whl

# Remove any PyTorch / CUDA wheels that may have been pulled transitively.
# PyTorch is already present in the base image; installing a different torch
# wheel here can downgrade/replace the preinstalled CUDA build.
# Also strip torch's FLOOR-PINNED transitive deps (sympy>=1.13.3,
# typing-extensions>=4.10.0 + mpmath) — the builder resolves them without torch's
# constraints visible and bakes older wheels that then conflict with the base's
# torch 2.8.0 at install time. The base image already ships compatible versions.
RUN rm -f /wheels/torch-*.whl /wheels/torchaudio-*.whl /wheels/torchvision-*.whl \
  /wheels/nvidia_*.whl /wheels/cuda_*.whl /wheels/triton-*.whl \
  /wheels/sympy-*.whl /wheels/typing_extensions-*.whl /wheels/mpmath-*.whl || true

# ---------- Runtime: PyTorch pre-installed, minimal OS deps ----------
# Same base as builder: PyTorch 2.8.0 + CUDA 12.8 + cuDNN 9 (sm_120 / Blackwell).
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime

# Install system dependencies for AI services (including sox for TTS)
RUN apt-get update && apt-get install -y --no-install-recommends \
  libgl1 ffmpeg tesseract-ocr tesseract-ocr-eng curl sox libsox-dev \
  && rm -rf /var/lib/apt/lists/*

# Install dependencies in controlled order to avoid conflicts
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install numpy first (pandas/transitive deps require >=1.26.0)
RUN pip install --no-cache-dir "numpy>=1.26.0,<2.0.0"

# NOTE: PyTorch (torch, torchvision, torchaudio) already installed in base image
# No need to install PyTorch separately - saves ~8GB and eliminates CI/CD layer size issues

# Install all other prebuilt wheels (numpy already installed, wheels removed from builder).
# Bind-mounted from the builder rather than COPYed: a COPY lands the wheels in their own
# ~455 MB layer, and the `rm -rf /wheels` that used to follow ran in a LATER layer, so it
# never reclaimed a byte — layers are additive. The bind mount lets pip read them without
# them ever becoming part of the image.
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
  pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
  && pip cache purge

# git for clone-local repo isolation + openssh-client (ssh / ssh-keyscan /
# ssh-keygen) for the Phase 4 SSH target registry — the governed probe/exec
# path shells out to the system ssh binary (argv list,
# StrictHostKeyChecking=yes, pinned per-user known_hosts).
# (kept in this late layer so the expensive pip-wheel layers above stay cached on rebuild)
RUN apt-get update && apt-get install -y --no-install-recommends \
  git openssh-client \
  && rm -rf /var/lib/apt/lists/*

# Docker CLI for vibecoding container management — the client binary ONLY.
# `apt-get install docker.io` used to be on the line above, and it installs the
# entire Docker package: dockerd (84 MB), containerd (48 MB), containerd-stress
# (22 MB), runc x2, containerd-shim and docker-proxy — ~190 MB of daemon
# binaries this container never executes. It only ever talks to the HOST
# daemon through the bind-mounted /var/run/docker.sock, and that needs the
# client and nothing else. Socket permission comes from compose
# (`group_add: "984"`), not from any group the package used to create.
# Ubuntu 22.04 has no CLI-only package, so this pulls the official static
# release and keeps one file. Pinned to the host daemon's version.
ARG DOCKER_CLI_VERSION=29.5.2
RUN curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
  | tar -xzC /tmp docker/docker \
  && mv /tmp/docker/docker /usr/bin/docker \
  && rm -rf /tmp/docker \
  && docker --version

# Reinstall Python docker package to override any system docker-py conflict
RUN pip install --no-cache-dir --force-reinstall "docker>=7.0.0"

# Note: Chatterbox TTS has been removed due to dependency conflicts with transformers>=0.27.0
# Qwen3 TTS is now the primary and recommended TTS engine

# App user with docker group access
RUN useradd -m -u 1001 -s /bin/bash appuser \
  && groupadd -g 999 dockerhost || true \
  && usermod -aG 999 appuser || true

# Copy application code and scripts
WORKDIR /app
COPY . .

# Copy and set permissions for entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create cache directories
RUN mkdir -p /home/appuser/.cache/whisper /home/appuser/.cache/huggingface \
  && chown -R appuser:appuser /home/appuser/.cache /app

# Phase 4 SSH state dir (per-user known_hosts + temp keys, 0700). Pre-created
# owned by appuser(1001) so a fresh `ssh_state` named volume mounted here
# inherits that ownership (Docker copies the image dir's perms into an empty
# volume) — otherwise the root-owned volume would be unwritable by uid 1001.
RUN mkdir -p /data/ssh_state \
  && chown -R appuser:appuser /data/ssh_state \
  && chmod 700 /data/ssh_state

# Same treatment for the artifact store. main.py constructs ArtifactStorage() at
# module scope (main.py:113 → artifacts/storage.py:39 os.makedirs), so a fresh
# root-owned /data/artifacts kills the process on import. This box's volume is
# already appuser-owned from an earlier run, which is why the gap has stayed
# invisible here; a genuinely fresh install hits it.
RUN mkdir -p /data/artifacts \
  && chown -R appuser:appuser /data/artifacts

# Switch to non-root user
USER appuser

# Environment variables
# HF_HOME, not TRANSFORMERS_CACHE. compose/k8s now override only HF_HOME, so
# leaving the deprecated variable baked in here would quietly survive as a
# SECOND cache root pointing somewhere else entirely — exactly the duplication
# the env cleanup removed.
ENV PYTHONPATH=/app \
  HF_HOME=/home/appuser/.cache/huggingface \
  HOME=/home/appuser

EXPOSE 8000

# OCI metadata, last so the per-commit VCS_REF does not invalidate the very
# expensive CUDA and wheel layers above it.
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/brandoz2255/Harvis" \
  org.opencontainers.image.licenses="MIT" \
  org.opencontainers.image.revision="${VCS_REF}" \
  org.opencontainers.image.title="harvis-backend-gpu" \
  org.opencontainers.image.description="Harvis backend with the PyTorch CUDA stack — model-downloader and the tts profile, not the default backend"

# Set entrypoint to our script
ENTRYPOINT ["/app/entrypoint.sh"]

# Default to running the app
CMD ["app"]
