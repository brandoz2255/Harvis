# SentrySearch MCP sidecar (optional, profile: sentrysearch)
#
# This is a PLACEHOLDER image for local VIDEO search (Tesla Sentry Mode heritage),
# NOT security/CVE/OSINT search. Default product install: OFF.
#
# Do not bake the upstream OpenClaw skill (needs Gemini + egress).
# Wire a real MCP stdio server here only after an explicit "yes, video search" product call.

FROM python:3.12-slim

WORKDIR /app
RUN useradd -m -u 1001 harvis
COPY server.py /app/server.py
USER harvis

ENV SENTRYSEARCH_VIDEO_DIR=/data/videos
VOLUME ["/data/videos"]

# Honest stub: exits with guidance unless HARVIS_SENTRYSEARCH_REAL=1 and a real
# server is later dropped in. Keeps compose `build` working without a 500MB pull.
CMD ["python", "/app/server.py"]
