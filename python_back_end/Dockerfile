# ---------- Builder: compile any source wheels ----------
# Use PyTorch base image with CUDA 12.4 pre-installed (eliminates ~8GB PyTorch installation)
FROM docker.io/pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime AS builder

# Install build tools for compiling source wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /w
COPY requirements.txt .

# Pre-reqs for pkuseg build
RUN pip install --no-cache-dir --upgrade pip setuptools wheel Cython

# Build wheels for the rest (excluding torch/torchvision/torchaudio and numpy to prevent conflicts)
# PyTorch is already installed in base image, so skip it
RUN grep -v "^torch" requirements.txt | grep -v "^numpy" > requirements_no_torch_numpy.txt \
  && pip wheel --no-cache-dir -r requirements_no_torch_numpy.txt -w /wheels

# Also build a wheel for pkuseg if it comes from source
RUN pip wheel --no-cache-dir pkuseg==0.0.25 --no-build-isolation -w /wheels

# Remove any numpy wheels that got built as dependencies (keep only one version)
RUN rm -f /wheels/numpy-*.whl

# ---------- Runtime: PyTorch pre-installed, minimal OS deps ----------
# Use same PyTorch base image for runtime (PyTorch 2.6.0 + CUDA 12.4 + cuDNN 9)
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

# Install system dependencies for AI services
RUN apt-get update && apt-get install -y --no-install-recommends \
  libgl1 ffmpeg tesseract-ocr tesseract-ocr-eng curl \
  && rm -rf /var/lib/apt/lists/*

# Install dependencies in controlled order to avoid conflicts
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install numpy first with constraint compatible with chatterbox-tts (<1.26.0)
RUN pip install --no-cache-dir "numpy>=1.24.0,<1.26.0"

# NOTE: PyTorch (torch, torchvision, torchaudio) already installed in base image
# No need to install PyTorch separately - saves ~8GB and eliminates CI/CD layer size issues

# Install all other prebuilt wheels (numpy already installed, wheels removed from builder)
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
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
