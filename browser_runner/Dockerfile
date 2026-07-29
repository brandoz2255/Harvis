FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
  firefox-esr \
  ca-certificates \
  curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Non-root. This image had no USER at all, so it ran as root — and of every
# service in the default set this is the one that renders hostile input by
# design. Nothing here wants root: uvicorn binds 8765 (unprivileged) and
# Firefox actively prefers not to be root.
#
# The -m matters. app.py:70 calls GeckoDriverManager().install(), which writes
# the driver under ~/.wdm at first use; without a real home that fails at the
# first browse rather than at boot.
RUN useradd -m -u 1001 -s /bin/bash runner \
  && chown -R runner:runner /app
USER runner
ENV HOME=/home/runner

EXPOSE 8765
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765"]

