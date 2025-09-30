############################
# 🐳 Podman-compatible single-stage build
############################
FROM docker.io/nvidia/cuda:12.4.1-runtime-ubuntu22.04

############################
# 🐧 OS packages
############################
RUN apt-get update && apt-get install -y \
  build-essential curl libgl1 ffmpeg tesseract-ocr tesseract-ocr-eng \
  python3 python3-pip python3-dev \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

############################
# 👤 Create non-root user early (Podman compatibility)
############################
RUN useradd -m -u 1001 -s /bin/bash appuser

############################
# 🐍 Python deps (as root, then switch to appuser)
############################
COPY requirements.txt .

# Upgrade pip and install build dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install build dependencies for chatterbox-tts (pkuseg needs numpy pre-installed)
RUN pip install --no-cache-dir numpy Cython

# Install PyTorch first (specific CUDA version) to avoid conflicts
RUN pip install --no-cache-dir \
  torch==2.6.0+cu124 \
  torchvision==0.21.0+cu124 \
  torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124

# Install pkuseg separately with no build isolation (critical for chatterbox-tts)
RUN pip install --no-cache-dir pkuseg==0.0.25 --no-build-isolation

# Create requirements without torch to avoid conflicts
RUN grep -v "^torch" requirements.txt > requirements_no_torch.txt

# Copy the robust installation script
COPY install_deps.py .

# Install remaining requirements using robust Python script with fallback
RUN python3 install_deps.py || \
  (echo "Python script failed, falling back to traditional method..." && \
  pip install --no-cache-dir -r requirements_no_torch.txt)

# Clean up build dependencies and caches to reduce image size
RUN pip cache purge && \
  rm -rf /tmp/* /var/tmp/* && \
  find /usr/local/lib/python3.* -name '*.pyc' -delete && \
  find /usr/local/lib/python3.* -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

############################
# 📦 Copy app code and set permissions
############################
WORKDIR /app
COPY . .

# Set up cache directories (models downloaded at runtime, not build time)
RUN mkdir -p /home/appuser/.cache/whisper /home/appuser/.cache/huggingface && \
  chown -R appuser:appuser /home/appuser/.cache /app

# Switch to non-root user for Podman compatibility
USER appuser

############################
# 🌐 Environment and launch
############################
EXPOSE 8000
ENV PYTHONPATH=/app
ENV TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface
ENV HOME=/home/appuser

# NOTE: Models now download at runtime instead of build time to save space
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

