# Harvis laya — the voice router's decision model, on CPU.
#
# Laya (Apache-2.0, convaiinnovations/laya) is a 421M ModernBERT classifier that
# answers typed questions ("choice" / "score" / "noul") in one forward pass. The
# backend asks it one question per spoken turn — answer fast, escalate, run a
# tool, or ask back — and picks the model from the answer
# (python_back_end/plugins/hermes_ui/voice_route.py).
#
# CPU only, on purpose: the laptop GPU is already held by Ollama, and a CPU call
# measured 193-464 ms. Weights are NOT baked in; the English checkpoint
# downloads once into /models (a named volume) on first start.
#
# Opt-in: the compose service sits behind the `laya` profile.

FROM python:3.12-slim

WORKDIR /srv

# The CPU torch wheel first, from PyTorch's own index, so pip never resolves the
# multi-gigabyte CUDA build from PyPI when laya asks for torch.
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
  && pip install --no-cache-dir "laya[serve]==0.3.20" \
  && pip cache purge

RUN python -c "\
import sys, torch; \
sys.exit('LAYA IMAGE CONTRACT VIOLATED — CUDA torch %s' % torch.__version__) if torch.version.cuda else print('laya image is CPU-only torch', torch.__version__)"

# uid 1001 matches the rest of the stack. /models is pre-created and owned here
# so a fresh named volume inherits that ownership instead of coming up root-owned.
RUN useradd -m -u 1001 -s /bin/bash appuser \
  && mkdir -p /models \
  && chown -R appuser:appuser /models /srv

USER appuser

ENV PYTHONUNBUFFERED=1 \
  HOME=/home/appuser \
  HF_HOME=/models/huggingface \
  LAYA_HOST=0.0.0.0 \
  LAYA_PORT=8000 \
  LAYA_DEVICE=cpu \
  LAYA_MODELS=english \
  LAYA_THREADS=2

EXPOSE 8000

# Long start period: the first start downloads the checkpoint before it listens.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1

ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/brandoz2255/Harvis" \
  org.opencontainers.image.licenses="MIT" \
  org.opencontainers.image.revision="${VCS_REF}" \
  org.opencontainers.image.title="harvis-laya" \
  org.opencontainers.image.description="Laya decision model on CPU — routes spoken turns to a small or big model"

CMD ["laya-serve"]
