# .devcontainer/Dockerfile

FROM python:3.11-slim

# Avoid prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /workspace

# Install OS-level dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    ffmpeg \
    libsndfile1 \
    libgl1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ----- Optional: Node.js (for frontend support) -----
# Install Node.js 20 and npm
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g npm

# Copy Python requirements
COPY requirements.txt .

# ---- TEMP FIX: Resolve dependency conflicts ----
# Patch fsspec version to resolve with datasets 3.6.0
RUN sed -i 's/^fsspec==.*$/fsspec<=2025.3.0/' requirements.txt

# Install Python packages with pip
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Expose ports if needed (FastAPI/React/etc)
EXPOSE 7860 8501 3000 8000

# Default shell and command
SHELL ["/bin/bash", "-c"]
CMD ["bash"]

