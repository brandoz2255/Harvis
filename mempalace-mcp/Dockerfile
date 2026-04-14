FROM python:3.12-slim

LABEL maintainer="Harvis AI <harvis@dulc3.dev>"
LABEL description="MemPalace HTTP+SSE MCP Server — shared AI memory for Harvis"

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy HTTP+SSE bridge
COPY http_server.py .

# Palace data lives on a persistent volume
RUN mkdir -p /data/palace
VOLUME ["/data/palace"]

ENV MEMPALACE_PALACE_PATH=/data/palace
ENV PYTHONUNBUFFERED=1

EXPOSE 8095

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8095/health')"

CMD ["uvicorn", "http_server:app", "--host", "0.0.0.0", "--port", "8095", "--log-level", "info"]
