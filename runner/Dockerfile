# Multi-runtime runner container for VibeCode
# Supports Python 3.11 + Node.js 20 + common tools

FROM node:20-bullseye-slim

# Install Python 3.9 (available in Bullseye) and essential tools
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    bash \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create symlink for python command
RUN ln -sf /usr/bin/python3 /usr/local/bin/python

# Install common Python packages
RUN pip3 install --no-cache-dir \
    requests \
    numpy \
    pandas

# Set working directory
WORKDIR /workspace

# Keep container running
CMD ["sleep", "infinity"]

