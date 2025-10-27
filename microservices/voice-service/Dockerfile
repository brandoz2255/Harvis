# Voice Service - Whisper STT + Chatterbox TTS
# Largest service due to PyTorch and audio models

# Use PyTorch base image with CUDA
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -u 1001 -s /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt \
    && pip cache purge

# Copy application code
COPY . .

# Create cache directories for models
RUN mkdir -p /home/appuser/.cache/whisper /home/appuser/.cache/huggingface \
    && chown -R appuser:appuser /home/appuser/.cache /app

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONPATH=/app \
    TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface \
    HOME=/home/appuser

EXPOSE 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
