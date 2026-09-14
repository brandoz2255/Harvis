#!/usr/bin/env bash
# Start FreeToken as a Harvis inference node. Everything comes from the environment
# (systemd reads ~/.config/freetoken.env — see freetoken.env.example) so one script
# serves the laptop, a desktop, or a rented box without editing.
#
#   FT_HOME         directory holding ./venv and ./models        (required)
#   FT_MODEL        model dir relative to FT_HOME                 (required)
#   FT_HOST         bind address. 172.17.0.1 = Docker bridge only, reachable from the
#                   Harvis container as host.docker.internal and from nothing on the
#                   LAN. 0.0.0.0 = every interface — FreeToken has no auth, so only do
#                   that behind a token proxy or on a private network.  (default 127.0.0.1)
#   FT_PORT         default 1919
#   FT_MAX_RUNNING  concurrent requests (default 2 on an 8 GB card)
#   FT_KV_RESERVE   --kv-reserve-tokens (default 4096; needed on 8 GB, see docs)
#   FT_MEMORY_RATIO --memory-ratio (default 0.95)
#   FT_MOE_THREADS  --moe-cpu-threads (default 6; leave cores for the rest of the box)
#   FT_MAX_PREFILL  --max-prefill-length (default 8192). Prefill of one chunk needs
#                   scratch VRAM on top of the memory-ratio budget; on 8 GB a 4k-token
#                   prompt OOM-killed the scheduler at 8192, so set 2048 there.
set -euo pipefail

: "${FT_HOME:?FT_HOME is required (directory with venv/ and models/)}"
: "${FT_MODEL:?FT_MODEL is required (model directory relative to FT_HOME)}"
cd "$FT_HOME"
exec ./venv/bin/ft serve \
  --model "$FT_MODEL" \
  --host "${FT_HOST:-127.0.0.1}" \
  --port "${FT_PORT:-1919}" \
  --max-running-requests "${FT_MAX_RUNNING:-2}" \
  --kv-reserve-tokens "${FT_KV_RESERVE:-4096}" \
  --memory-ratio "${FT_MEMORY_RATIO:-0.95}" \
  --moe-cpu-threads "${FT_MOE_THREADS:-6}" \
  --max-prefill-length "${FT_MAX_PREFILL:-8192}" \
  "$@"
