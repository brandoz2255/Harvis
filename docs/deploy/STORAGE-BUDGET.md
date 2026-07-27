# Harvis storage budget

**Living document.** Update the measured table whenever an image changes size, and move items
between "banked" and "available" as they land. Last measured: **2026-07-26** on the dev box
(`docker system df -v`, branch `deploy-optimize-test`).

## How to measure (do this, don't estimate)

```bash
docker system df -v | sed -n '/^Images space usage/,/^Containers/p'
```

Read the **UNIQUE SIZE** column, not SIZE. Adding the SIZE column triple-counts shared bases — the
backend/harvis-mcp/model-downloader family shares one multi-gigabyte layer stack that exists on disk
exactly once. For a *fresh install* footprint, count each distinct base once and add each image's
unique layers.

## What a bare-bones install costs today

The default profile set is 11 services (see `docker-compose.yaml`; everything else sits behind
`engines` / `notebooks` / `voice` / `cad` / `legacy`).

| Service | Image | Fresh-install cost | Note |
|---|---|---:|---|
| `backend` | `harvis-backend` | **16.90 GB** | 12.10 GB of it is the `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` base |
| `ollama` | `ollama/ollama` | **9.70 GB** | upstream image; excludes model weights |
| `owui-builder` | `harvis-owui-builder:local` | **5.25 GB** | runs once, exits, then sits on disk forever |
| `browser-runner` | `harvis-browser-runner` | 0.86 GB | 0.19 GB shared with messaging-gateway |
| `pgsql` | `pgvector/pgvector:pg15` | 0.61 GB | |
| `harvis-messaging-gateway` | `harvis-messaging-gateway:local` | 0.29 GB | |
| `llmfit` | `ghcr.io/alexsjones/llmfit` | 0.18 GB | |
| `nginx` | `nginx:alpine` | 0.09 GB | |
| `ollama-model-check` | `curlimages/curl` | 0.04 GB | |
| `artifact-init` | `busybox` | 0.01 GB | |
| `harvis-mcp` | *(same image as `backend`)* | **0.00 GB** | same Dockerfile, different entrypoint — fully shared |

**Total ≈ 33.9 GB**, minus ~0.19 GB counted twice for the shared `python:3.11-slim` base → **≈ 33.7 GB**.

Not included, because they depend on what the user does:

- **Ollama model weights** — a single 8B model is ~5 GB; `nomic-embed-text` ~0.3 GB
- **Postgres data volume** — grows with chat history and artifacts
- **The owui build output** — a host bind mount, tens of MB

### Where it actually goes

Three images are 91% of the install:

```
backend        16.90 GB  ████████████████████████████████████████████████  50%
ollama          9.70 GB  ███████████████████████████                       29%
owui-builder    5.25 GB  ███████████████                                   16%
everything else 1.88 GB  █████                                              6%
```

## Reduction ledger

### Banked

| # | Change | Saved | Status |
|---|---|---:|---|
| 1 | Profile-gate the optional stack (24 → 11 default services) | **~35 GB** | landed `fa494b41` |
| 2 | Bind-mount the builder wheels instead of `COPY` | **0.90 GB** | landed, rebuild-verified |

**Item 2, measured:** `COPY --from=builder /wheels /wheels` created its own ~455 MB layer, and the
`rm -rf /wheels` that followed ran in a *later* layer, so it never reclaimed a byte — layers are
additive. A BuildKit bind mount lets pip read the wheels without them entering the image. Rebuilt
to a throwaway tag and measured: **16.9 GB → 16.0 GB**, roughly double the 455 MB the layer history
attributed to the `COPY` alone. Smoke-tested with all 16 runtime imports plus
`torch 2.8.0+cu128` — clean.

### Available, measured

| # | Change | Est. saving | Risk | Blocked by |
|---|---|---:|---|---|
| 3 | Drop the CUDA/torch base from the backend image | **~12–14 GB** | medium | the torch decoupling below |
| 4 | Stop shipping `owui-builder` as a persistent image | **~5.25 GB** | low–medium | needs a build-stage or prebuilt-artifact design |

**Item 3 is the big one, and the evidence says it's more tractable than it looks.** `main.py` imports
the entire 12.1 GB CUDA runtime and uses it for exactly nine lines:

```
1629: device = 0 if torch.cuda.is_available() else -1
4165: if torch.cuda.is_available(): torch.cuda.empty_cache()
5840: ... empty_cache() / synchronize()
5886: ... empty_cache()
6006: ... empty_cache()
```

No tensors. No models. GPU housekeeping that `pynvml` or `nvidia-smi` answers in a few hundred
kilobytes. And `import whisper` on `main.py:120` is **never used at all** — the only other "whisper"
strings in the file are literals and route paths.

**Item 4** — `owui-builder` is `restart: no`. It copies `/app/build` into a host bind mount, exits,
and skips entirely if `index.html` already exists. A 5.25 GB image for a job that runs once per
install.

## What blocks item 3

Ten top-level `import torch` statements exist in the backend. Only the ones reachable from `main.py`'s
import graph matter, because a single one keeps the CUDA base mandatory:

| File | Line | Reachable from main? |
|---|---:|---|
| `main.py` | 119 | yes — direct |
| `model_manager.py` | 10 | yes — `main.py:356` imports from it |
| `tts_engine_manager.py` | 5 | yes |
| `chatbot.py` | 3 | yes |
| `qwen3_tts.py` | 20 | voice |
| `chatterbox_tts.py` | 2 | voice |
| `vison_models/qwen.py` | 3 | vision |
| `vison_models/llm_connector.py` | 3 | vision |
| `tts_system/engines/rvc_engine.py` | 18 | no — `tts-service` container |
| `tts_system/engines/vibevoice_engine.py` | 17 | no — `tts-service` container |

`model_manager.py` is the structural blocker: it is two modules in one file. Removing the Whisper
half doesn't remove `import torch`, because the GPU-governance half (`get_gpu_memory_stats`,
`check_memory_pressure`, `auto_cleanup_if_needed`) has live non-voice callers in `main.py:7210+`.
Split it first.

Note that `harvis-mcp` builds from the same Dockerfile, so this one change slims two services.

## Not part of the install, but worth knowing

Measured on the dev box, these are local accumulation rather than what a user downloads:

| Item | Size | Reclaimable |
|---|---:|---:|
| Build cache | 237.5 GB | **149.2 GB** (`docker builder prune`) |
| Local volumes | 102.3 GB | 0.9 GB |
| Images (all 51, incl. every profile) | 295.8 GB | 24.9 GB |

`harvis-comfyui` is 18.73 GB and belongs to **no compose file** — it was started by hand and appears
in none of the seven compose files. Largest single image on the box, entirely off the books.
