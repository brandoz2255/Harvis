# Harvis voice-onnx — the DEFAULT speech service.
#
# Local speech recognition, voice activity detection and Kokoro synthesis on
# ONNX Runtime. The contract of this image is that it contains no PyTorch, no
# CUDA and no GPU runtime of any kind; that contract is asserted at build time
# below, so a dependency that drags torch back in fails the build instead of
# quietly turning the "light" voice service into a multi-gigabyte one.
#
# Models are NOT baked in. They download once into /models, which is a
# persistent volume, so they survive image rebuilds and the image stays small.
#
# Build:
#   docker build -t harvis-voice-onnx:local services/voice-onnx
# Run:
#   docker run --rm -p 8020:8000 -v harvis_voice_models:/models harvis-voice-onnx:local

FROM python:3.12-slim

# ffmpeg          decode whatever the browser records (webm/ogg/mp4) and encode
#                 mp3/opus/flac responses
# curl            the compose healthcheck
# ca-certificates the one-time model download from github
RUN apt-get update && apt-get install -y --no-install-recommends \
  ffmpeg curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt \
  && pip cache purge

# The contract, asserted rather than trusted.
RUN python -c "\
import importlib.util, sys; \
bad = [m for m in ('torch', 'torchaudio', 'nvidia', 'triton') if importlib.util.find_spec(m)]; \
sys.exit('VOICE IMAGE CONTRACT VIOLATED — found: %s' % bad) if bad else print('voice-onnx image is torch-free')"

COPY app ./app
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# uid 1001 matches the Harvis backend, so a shared model volume stays writable
# by both. /models is pre-created and owned here because Docker copies
# ownership into a fresh named volume ONLY from a directory that already exists
# in the image — without this line a first-run volume is root-owned and every
# model download fails with EACCES.
RUN useradd -m -u 1001 -s /bin/bash appuser \
  && mkdir -p /models \
  && chown -R appuser:appuser /models /srv

USER appuser

ENV PYTHONPATH=/srv \
  PYTHONUNBUFFERED=1 \
  HOME=/home/appuser \
  VOICE_MODELS_DIR=/models \
  VOICE_ASR_MODEL=whisper-tiny.en \
  VOICE_TTS_MODEL=kokoro-v1.0 \
  VOICE_NUM_THREADS=2

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/srv/entrypoint.sh"]
CMD ["app"]
