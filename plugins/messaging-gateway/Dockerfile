FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Default to the stub adapter for the bring-up smoke test. Real deployments
# override ENABLED_PLATFORMS and pass per-platform credentials.
ENV ENABLED_PLATFORMS=stub \
    HARVIS_BACKEND_URL=http://backend:8000 \
    STUB_ENABLED=false \
    STUB_PORT=18800

CMD ["python", "-u", "gateway.py"]
