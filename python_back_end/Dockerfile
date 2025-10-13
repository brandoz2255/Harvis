# ---------- Builder: compile any source wheels ----------
FROM docker.io/nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential python3 python3-pip python3-dev curl \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /w
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel
# Pre-reqs for pkuseg build
RUN pip install --no-cache-dir Cython
# Install Torch (CUDA) explicitly so it doesn't reappear later
RUN pip install --no-cache-dir \
  torch==2.6.0+cu124 torchvision==0.21.0+cu124 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124
# Build wheels for the rest (excluding torch and numpy to prevent conflicts)
RUN grep -v "^torch" requirements.txt | grep -v "^numpy" > requirements_no_torch_numpy.txt \
  && pip wheel --no-cache-dir -r requirements_no_torch_numpy.txt -w /wheels
# Also build a wheel for pkuseg if it comes from source
RUN pip wheel --no-cache-dir pkuseg==0.0.25 --no-build-isolation -w /wheels
# Remove any numpy wheels that got built as dependencies (keep only one version)
RUN rm -f /wheels/numpy-*.whl

# ---------- Runtime: no compilers, minimal OS deps ----------
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
  python3 python3-pip libgl1 ffmpeg tesseract-ocr tesseract-ocr-eng curl \
  && rm -rf /var/lib/apt/lists/*

# Install dependencies in controlled order to avoid conflicts
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install numpy first with constraint compatible with chatterbox-tts (<1.26.0)
RUN pip install --no-cache-dir "numpy>=1.24.0,<1.26.0"

# Install torch from PyTorch repo (with CUDA support)
RUN pip install --no-cache-dir \
  torch==2.6.0+cu124 torchvision==0.21.0+cu124 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124

# Install all other prebuilt wheels (numpy already installed, wheels removed from builder)
COPY --from=builder /wheels /wheels
RUN rm -f /wheels/torch-*.whl /wheels/torchvision-*.whl /wheels/torchaudio-*.whl \
  && pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
  && rm -rf /wheels \
  && pip cache purge

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
