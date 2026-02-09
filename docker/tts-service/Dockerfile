# TTS Service Dockerfile
# Voice cloning and podcast generation with VibeVoice + RVC character voices

# Using CUDA 12.4 for RTX 50 series (Blackwell) support
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies including FFmpeg development libraries
# Using Python 3.10 for fairseq compatibility (3.11+ has dataclass breaking changes)
RUN apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    python3.10-distutils \
    python3-pip \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswresample-dev \
    libswscale-dev \
    libsndfile1 \
    libsndfile1-dev \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.10 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

# Create app directory
WORKDIR /app

# Create required directories
RUN mkdir -p /app/voices /app/output /app/models /app/rvc_models /app/assets/hubert /app/assets/pretrained_v2

# Copy requirements first for caching (from docker build context root)
COPY docker/tts-service/requirements-tts.txt .

# Install Python dependencies in stages to avoid resolution issues
# First: Upgrade pip (PyTorch will be installed later with nightly for sm_120)
RUN python3.10 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Second: Install core TTS dependencies
RUN python3.10 -m pip install --no-cache-dir \
    fastapi>=0.104.0 \
    "uvicorn[standard]>=0.24.0" \
    python-multipart>=0.0.6 \
    transformers>=4.35.0 \
    accelerate>=0.24.0 \
    bitsandbytes>=0.41.0 \
    librosa>=0.10.0 \
    soundfile>=0.12.0 \
    scipy>=1.11.0 \
    speechbrain>=1.0.2 \
    huggingface-hub>=0.30.2 \
    pydantic>=2.0.0 \
    loguru>=0.7.0 \
    httpx>=0.25.0 \
    numpy==1.23.5 \
    datasets>=2.14.0

# Third: Download and patch omegaconf 2.0.6 (has broken metadata)
COPY docker/tts-service/patch_omegaconf.py /tmp/patch_omegaconf.py
RUN python3.10 /tmp/patch_omegaconf.py \
    && python3.10 -m pip install --no-cache-dir /tmp/omegaconf-2.0.6-py3-none-any.whl

# Fourth: Install fairseq and RVC dependencies
RUN python3.10 -m pip install --no-cache-dir hydra-core==1.0.7 bitarray cython sacrebleu \
    && python3.10 -m pip install --no-cache-dir --no-deps fairseq==0.12.2 \
    && python3.10 -m pip install --no-cache-dir faiss-cpu==1.7.3 av ffmpeg-python torchcrepe praat-parselmouth pyworld

# Fifth: Install rvc-python (with --no-deps since we installed deps manually)
RUN python3.10 -m pip install --no-cache-dir --no-deps rvc-python==0.1.5

# Sixth: CRITICAL - Install PyTorch NIGHTLY for sm_120 (RTX 50 series Blackwell) support
# This must be done AFTER all other packages to ensure sm_120 kernels are available
# Using cu124 index with nightly for Python 3.10
RUN python3.10 -m pip install --no-cache-dir --pre torch --index-url https://download.pytorch.org/whl/nightly/cu124

# Note: Dia (nari-tts) is skipped because it requires torchaudio which is incompatible with PyTorch nightly
# SpeechT5 is used as the primary TTS engine instead

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
# RVC configuration
ENV RVC_MODELS_DIR=/app/rvc_models
ENV RVC_ASSETS_DIR=/app/assets
ENV RVC_MAX_CACHED_MODELS=4

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run the TTS server
CMD ["python3", "-m", "tts_system.server"]
