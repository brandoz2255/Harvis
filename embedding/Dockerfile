FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including PostgreSQL dev libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the embedding module
COPY . .

# Create volume mount point for workflow data
RUN mkdir -p /data/workflows

# Set Python path
ENV PYTHONPATH=/app

# Default command
CMD ["python", "main.py", "--help"]