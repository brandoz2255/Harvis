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
| `backend` | `harvis-backend` | **15.40 GB** | 12.10 GB of it is the `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` base |
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

**Total ≈ 32.4 GB**, minus ~0.19 GB counted twice for the shared `python:3.11-slim` base → **≈ 32.2 GB**.

Not included, because they depend on what the user does:

- **Ollama model weights** — a single 8B model is ~5 GB; `nomic-embed-text` ~0.3 GB
- **Postgres data volume** — grows with chat history and artifacts
- **The owui build output** — a host bind mount, tens of MB

### Where it actually goes

Three images are 91% of the install:

```
backend        15.40 GB  ██████████████████████████████████████████████    48%
ollama          9.70 GB  █████████████████████████████                     30%
owui-builder    5.25 GB  ████████████████                                  16%
everything else 1.88 GB  █████                                              6%
```

`ollama` is upstream's image and effectively fixed: its Ubuntu base is 88 MB, the `ollama` binary
43 MB and apt libs 340 MB — everything else is `/usr/lib/ollama`, GPU compute libraries for CUDA,
ROCm **and** Vulkan so that one image runs on any vendor's card. Model weights are not in it.

## Reduction ledger

### Banked

| # | Change | Saved | Status |
|---|---|---:|---|
| 1 | Profile-gate the optional stack (24 → 11 default services) | **~35 GB** | landed `fa494b41` |
| 2 | Bind-mount the builder wheels instead of `COPY` | **0.90 GB** | landed `81fd6ba8`, rebuild-verified |
| 3 | Stop building the orphaned `pkuseg` wheel | **190 MB** | landed, rebuild-verified |
| 4 | Ship the Docker **client** instead of `docker.io` | **240 MB** | landed, rebuild-verified |

**Item 2, measured:** `COPY --from=builder /wheels /wheels` created its own ~455 MB layer, and the
`rm -rf /wheels` that followed ran in a *later* layer, so it never reclaimed a byte — layers are
additive. A BuildKit bind mount lets pip read the wheels without them entering the image. Rebuilt
to a throwaway tag and measured: **16.9 GB → 16.0 GB**, roughly double the 455 MB the layer history
attributed to the `COPY` alone. Smoke-tested with all 16 runtime imports plus
`torch 2.8.0+cu128` — clean.

**Item 3, measured:** the Dockerfile explicitly built `pkuseg==0.0.25` as a prerequisite of
`chatterbox-tts` — which has been commented out of `requirements.txt` since the
`transformers>=0.27.0` conflict. That left 180 MB of Chinese word-segmentation data in the runtime
image with **zero importers across 381 backend files** and no installed package declaring it as a
dependency. Deleting the one `pip wheel` line took the wheels-install layer from 1.97 GB to 1.78 GB.
A full `pip list` diff of the old and new images shows exactly one package removed — `pkuseg` —
and nothing added. Note that `jieba` (29 MB) **survives the diff**: it is a real transitive
dependency, not pkuseg baggage, so don't chase it.

**Item 4, measured:** `apt-get install docker.io` installs the entire Docker package — `dockerd`
(84 MB), `containerd` (48 MB), `containerd-stress` (22 MB), `runc` ×2, `containerd-shim` and
`docker-proxy` — roughly 190 MB of daemon binaries the backend never executes. It only ever talks
to the **host** daemon through the bind-mounted `/var/run/docker.sock`, and socket permission comes
from Compose (`group_add: "984"`), not from any group the package creates. Ubuntu 22.04 ships no
CLI-only package, so the fix pulls the official static release and keeps one file. The apt layer
fell from 365 MB to 81.9 MB and the new client layer costs 42.6 MB — net **240 MB**. Verified by
running the image with the real socket mounted as `1001:1001 --group-add 984`: both `docker ps` and
`docker-py` see the host's containers, and `torch.cuda.is_available()` is still `True` under
`--gpus all` on the RTX 5070.

Only one reference to a daemon binary exists anywhere in the backend, and it is a docstring in
`workspace/harvis_readiness.py:69`. Ten files shell out to the `docker` client, which is why the
client stays.

### Available, measured

| # | Change | Est. saving | Risk | Blocked by |
|---|---|---:|---|---|
| 5 | Drop the CUDA/torch base from the backend image | **~12–14 GB** | medium | the torch decoupling below |
| 6 | Stop shipping `owui-builder` as a persistent image | **~5.25 GB** | low–medium | needs a build-stage or prebuilt-artifact design |
| 7 | Swap the conda PyTorch base for `python:3.11-slim` + pip torch | **~1.5–2.5 GB** | medium | full rebuild + import sweep |

**Item 5 is the big one, and the evidence says it's more tractable than it looks.** `main.py` imports
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

**Item 6** — `owui-builder` is `restart: no`. It copies `/app/build` into a host bind mount, exits,
and skips entirely if `index.html` already exists. A 5.25 GB image for a job that runs once per
install, and the thing it delivers is **263 MB of static files**. Its layers are `npm ci --force`
(2.77 GB of `node_modules`) and `npm run build` (651 MB) — both build-time only. The Dockerfile
stops at the `build` target and has no final stage that keeps just `/app/build`.

**Item 7 — the base image is the wall, and it can only be moved by changing `FROM`.**
`site-packages` totals 8.5 GB, but 6.3 GB of that ships inside the base layer: `torch` 1.7 GB,
`nvidia/*` 4.1 GB, `triton` 542 MB. Layers are additive, so `pip uninstall triton` in a later `RUN`
writes a whiteout and reclaims **zero bytes** — the same trap item 2 fixed. Confirmed by listing the
base image's own packages: `torch`, `triton`, `cmake`, every `nvidia-*`, `torchvision`, `torchaudio`
and the whole conda distribution are all inherited, not installed by us.

Inside that 4.1 GB of `nvidia/*`: `cudnn` 1005 MB, `cublas` 830 MB, `cusparselt` 432 MB, `nccl`
410 MB, `cusolver` 387 MB, `cusparse` 371 MB, `cufft` 269 MB, `cuda_nvrtc` 212 MB, `curand` 133 MB.
`cusparselt` (structured sparsity) and `nccl` (multi-GPU collectives) are dead on a single-GPU box —
840 MB of pure waste — but base-layer, so they cost a rebuild, not a delete. Note that
`torch/__init__.py` eagerly preloads `libnccl.so`, so removing it is not a free deletion even then.

The realistic middle move is replacing `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` with
`python:3.11-slim` + `pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128`.
That drops the Anaconda distribution, its 559 MB package cache, 101 MB of `/usr/lib/firmware/nvidia`
blobs, `cmake` (a build-only extra of triton and piper-tts), and `torchvision`/`torchaudio` — the
latter has exactly one importer, `tts_system/engines/vibevoice_engine.py`, which runs in the
**separate `tts-service` container**, not here. It does not touch the 4.1 GB of CUDA libraries,
because Whisper genuinely runs CUDA inference in this process.

## What blocks item 5

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
