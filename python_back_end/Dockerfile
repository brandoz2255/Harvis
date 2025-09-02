############################
# 🐳 Base with CUDA libs
############################
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

############################
# 🐧 OS packages
############################
RUN apt-get update && apt-get install -y \
  build-essential curl libgl1 ffmpeg tesseract-ocr tesseract-ocr-eng \
  python3 python3-pip \
  && rm -rf /var/lib/apt/lists/*

############################
# 🐍 Python deps
############################
COPY requirements.txt .

# Multi-stage pip installation with retry mechanism and dependency resolution
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install PyTorch first (specific CUDA version) to avoid conflicts
RUN pip install --no-cache-dir \
  torch==2.6.0+cu124 \
  torchvision==0.21.0+cu124 \
  torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124

# Create requirements without torch to avoid conflicts
RUN grep -v "^torch" requirements.txt > requirements_no_torch.txt

# Copy the robust installation script
COPY install_deps.py .

# Install remaining requirements using robust Python script with fallback
RUN python3 install_deps.py || \
  (echo "Python script failed, falling back to traditional method..." && \
  pip install --no-cache-dir -r requirements_no_torch.txt && \
  pip install --no-cache-dir -r requirements_no_torch.txt)  

# Add this section after your OS packages installation
############################
# 👤 Create non-root user
############################
RUN useradd -m -u 1001 -s /bin/bash appuser
WORKDIR /app
USER appuser

############################
# 📦 Copy app code
############################
WORKDIR /app
COPY . .

############################
# 🎯 Pre-seed Whisper models for offline operation
############################
USER root
RUN mkdir -p /root/.cache/whisper
COPY whisper_models/tiny.pt /root/.cache/whisper/tiny.pt
COPY whisper_models/base.pt /root/.cache/whisper/base.pt
RUN chown -R appuser:appuser /root/.cache
USER appuser

############################
# 🚀 Pre-warm models into Hugging Face cache (BuildKit required!)
############################
RUN --mount=type=cache,id=model-cache,target=/root/.cache \
  set -eux; \
  python3 -c 'import whisper'; \
  python3 -c 'from chatterbox.tts import ChatterboxTTS; ChatterboxTTS.from_pretrained(device="cpu")'

############################
# 🌐 Expose + launch
############################
EXPOSE 8000
ENV PYTHONPATH=/app
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

