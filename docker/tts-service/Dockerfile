# TTS Service Dockerfile
# Voice cloning and podcast generation with VibeVoice

FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies including FFmpeg development libraries
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3.11-venv \
    python3-pip \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswresample-dev \
    libswscale-dev \
    libsndfile1 \
    libsndfile1-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Create app directory
WORKDIR /app

# Create required directories
RUN mkdir -p /app/voices /app/output /app/models

# Copy requirements first for caching (from docker build context root)
COPY docker/tts-service/requirements-tts.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir -r requirements-tts.txt

# Copy TTS system code (from project root context)
COPY python_back_end/tts_system /app/tts_system

# Environment variables
ENV PYTHONPATH=/app
ENV VOICES_DIR=/app/voices
ENV OUTPUT_DIR=/app/output
ENV MODEL_CACHE_DIR=/app/models
ENV TTS_HOST=0.0.0.0
ENV TTS_PORT=8001
ENV QUANTIZE_4BIT=true

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run the TTS server
CMD ["python3", "-m", "tts_system.server"]
