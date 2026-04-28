FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# ACP is stdio-driven — the editor launches this as a subprocess. The
# container build is here mostly for ops who want to ship the adapter
# pre-baked; locally, editors will typically launch `python -m harvis_acp`
# directly from a venv.
ENTRYPOINT ["python", "-m", "harvis_acp"]
