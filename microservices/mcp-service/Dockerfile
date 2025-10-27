FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl libmagic1 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1001 -s /bin/bash appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt && pip cache purge
COPY . .
RUN chown -R appuser:appuser /app
USER appuser
ENV PYTHONPATH=/app HOME=/home/appuser
EXPOSE 8004
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 CMD curl -f http://localhost:8004/health || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
