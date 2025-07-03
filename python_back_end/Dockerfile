############################
# 🐳 Base with CUDA libs
############################
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

############################
# 🐧 OS packages
############################
RUN apt-get update && apt-get install -y \
      git build-essential curl libgl1 ffmpeg tesseract-ocr tesseract-ocr-eng \
      python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

############################
# 🐍 Python deps
############################
COPY requirements.txt .

# 1️⃣ install your pinned deps
# 2️⃣ add Perth for Chatterbox watermarking
# 3️⃣ pull CUDA wheels for torch + friends
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir \
      torch==2.6.0+cu124 \
      torchvision==0.21.0+cu124 \
      torchaudio==2.6.0 \
      --index-url https://download.pytorch.org/whl/cu124  

############################
# 📦 Copy code
############################
WORKDIR /app
COPY . .

############################
# 🚀 Model warm-up (parallel & cached)
############################
# ✅ Model warm-up (parallel + cache)
############################
# 🚀 Model warm-up (parallel + cache)
############################
# 🚀 Model warm-up (parallel & cached) — BuildKit required!
#  • caches /root/.cache across builds
RUN --mount=type=cache,id=model-cache,target=/root/.cache \
    set -eux; \
    python3 -c 'import whisper'; \
    python3 -c 'from transformers import pipeline; pipeline("image-to-text", model="Salesforce/blip-image-captioning-base")'; \
    python3 -c 'from chatterbox.tts import ChatterboxTTS; ChatterboxTTS.from_pretrained(device="cuda")'  # Model name is implicit

############################
# 🌐 Expose + launch
############################
EXPOSE 8000
ENV PYTHONPATH=/app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
