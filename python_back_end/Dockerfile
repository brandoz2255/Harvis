# ─────────────────────────────────────────────────────────────
# ✅ Base Image
FROM python:3.11-slim

# ─────────────────────────────────────────────────────────────
# ✅ Set working directory
WORKDIR /app

# ─────────────────────────────────────────────────────────────
# ✅ Declare environment variable for Gemini API Key
# This variable should be set when running the Docker container, e.g.,
# docker run -e GEMINI_API_KEY="your_api_key_here" your_image_name
ENV GEMINI_API_KEY=""

# ─────────────────────────────────────────────────────────────
# ✅ Install system dependencies
RUN apt-get update && apt-get install -y     curl     build-essential     libgl1     ffmpeg     git     tesseract-ocr     tesseract-ocr-eng     && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────────────────────
# ✅ Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────
# ✅ Copy all code (done AFTER deps for better caching)
COPY . .

# ─────────────────────────────────────────────────────────────
# ✅ Warm-up: preload models so cold start is faster
RUN python -c "import whisper" && \
    python -c 'from transformers import pipeline; pipeline("image-to-text", model="Salesforce/blip-image-captioning-base")' && \
    python -c 'from chatterbox.tts import ChatterboxTTS; ChatterboxTTS.from_pretrained(device="cpu")'

# ─────────────────────────────────────────────────────────────
# ✅ Expose API port
EXPOSE 8000

# ─────────────────────────────────────────────────────────────
# ✅ Start server (use Gunicorn for prod; uvicorn for dev)
# Set working directory inside container
WORKDIR /app

# Set the PYTHONPATH to include the app directory for module resolution
ENV PYTHONPATH=/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
