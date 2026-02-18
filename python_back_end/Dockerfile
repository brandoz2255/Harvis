# ---------- Runtime: PyTorch pre-installed, install deps directly ----------
# Use PyTorch base image with CUDA 12.4 pre-installed
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

# Install system dependencies for AI services (including build tools and sox for TTS)
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential libgl1 ffmpeg tesseract-ocr tesseract-ocr-eng curl sox libsox-dev \
  && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy and install Python dependencies
WORKDIR /app
COPY requirements.txt .

# Install all Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
  && pip cache purge

# Note: Chatterbox TTS has been removed due to dependency conflicts with transformers>=0.27.0
# Qwen3 TTS is now the primary and recommended TTS engine

# App user
RUN useradd -m -u 1001 -s /bin/bash appuser

# Copy application code and scripts
WORKDIR /app
COPY . .

# Copy and set permissions for entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create cache directories
RUN mkdir -p /home/appuser/.cache/whisper /home/appuser/.cache/huggingface \
  && chown -R appuser:appuser /home/appuser/.cache /app

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONPATH=/app \
  TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface \
  HOME=/home/appuser

EXPOSE 8000

# Set entrypoint to our script
ENTRYPOINT ["/app/entrypoint.sh"]

# Default to running the app
CMD ["app"]
