# Harvis CAD engine sidecar — isolated build123d / OCP kernel (Stage 2).
# Kept out of the torch backend image so the pinned build123d==0.9.1 + cadquery-ocp
# stack (numpy 2.x) can't conflict with the backend's numpy<2 / torch 2.8 pins.
FROM python:3.11-slim

# OCP/OCCT runtime needs GL + X11 shared libs even for headless meshing.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libxi6 curl \
    && rm -rf /var/lib/apt/lists/*

# Pinned combo verified working: build123d 0.9.1 matches the OCP wheel whose
# TopoDS API still has HashCode (the 7.9 wheel removed it and breaks 0.11.x).
RUN pip install --no-cache-dir \
    "build123d==0.9.1" \
    "fastapi>=0.110,<1" \
    "uvicorn>=0.29,<1" \
    "pydantic>=2,<3" \
    "httpx>=0.27,<1" \
    "pytest>=8,<9"

# httpx + pytest add ~10 MB to a 418 MB profile-gated image, and they buy the
# ability to run the input-hardening suite against the EXACT pinned OCP build that
# serves traffic. A separate test image would exercise a different geometry kernel,
# which is the one thing those tests exist to pin down.

# The container runs with a read-only root filesystem (see docker-compose.yaml), so
# never attempt to write bytecode next to the source. Scratch goes to the tmpfs /tmp.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY recipes.py server.py validation.py runner.py worker_main.py admission.py \
     exporters.py pool.py /app/
COPY tests /app/tests

# Non-root
RUN useradd -m -u 1001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
