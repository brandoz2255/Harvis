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

| # | Change | Saving | Risk | Blocked by |
|---|---|---:|---|---|
| 5 | Give up GPU: CPU-only torch | ~4.6 GB | **high — breaks Whisper/TTS speed** | not recommended; see below |
| 6 | Stop shipping `owui-builder` as a persistent image | ~5.25 GB | low–medium | needs a build-stage or prebuilt-artifact design |
| 7 | Swap the conda PyTorch base for `python:3.11-slim` + pip torch, **and** drop `triton` in the same layer | **1.6 GB (measured)** | low — fully verified | an adoption decision only |

**Item 7 is built and verified, not estimated.** Image `harvis-backend:exp-floor2`, built from the
same `python_back_end/` context:

| Image | Disk | Pull |
|---|---:|---:|
| `latest` (before any of this work) | 16.9 GB | 5.63 GB |
| `slim-cli` (items 3+4, committed `06845118`) | 15.4 GB | 5.05 GB |
| slim base only | 14.6 GB | 4.87 GB |
| **slim base + triton dropped in-layer** | **13.8 GB** | **4.71 GB** |

Verification: `import main` → `STATUS OK` (6,777 modules, 320 top-level packages); 14/14 CUDA ops
pass on the RTX 5070 including `stft`, `fft`, `linalg.svd`, `cholesky` and `sdpa`; 26/26 runtime
imports; and the `pip list` diff against `slim-cli` shows **55 packages removed, 0 added** — 54 of
them conda's own tooling and dev extras (`conda*`, `ipython`, `jedi`, `hypothesis`, `ninja`,
`cmake`, `lintrunner`, `torchelastic`), plus `triton`.

One honest caveat: `pip check` now reports `torch` and `openai-whisper` require `triton, which is
not installed`. Nothing imports it and every op passes, but the declared-dependency graph is
knowingly inconsistent. If that trade isn't wanted, keep triton and take 14.6 GB instead of 13.8.

**A note on the two size numbers.** This box runs the containerd snapshotter, so `docker images`
and `docker system df` report **uncompressed on-disk** size while `docker image inspect -f
'{{.Size}}'` reports **compressed pull** size. They differ by ~3×. This document tracks the disk
column throughout; quote the pull column only when talking about download time.

**Item 5 is no longer attractive.** Dropping the CUDA stack means CPU-only torch, and the CUDA
libraries turned out to be load-bearing rather than optional (see the per-package table below).
Whisper and TTS both run real GPU inference here — TTS was ~15 s/sentence on CPU before the CUDA
12.8 base fixed it. Listed for completeness, not as a recommendation.

**On the "torch is barely used" argument — it does not survive contact with the runtime.** `main.py`
itself touches torch in only nine lines, all GPU housekeeping:

```
1629: device = 0 if torch.cuda.is_available() else -1
4165: if torch.cuda.is_available(): torch.cuda.empty_cache()
5840: ... empty_cache() / synchronize()
5886: ... empty_cache()
6006: ... empty_cache()
```

No tensors, no models — housekeeping that `pynvml` would answer in a few hundred kilobytes. It is
tempting to conclude torch is nearly free to remove. **It isn't, and the reasoning above is a trap:
`main.py` is not the whole program.** Actually importing it pulls in 6,777 modules across 320
top-level packages, and `torch`, `transformers`, `librosa`, `sentence_transformers`, `torchvision`,
`sklearn` and `numba` all load — several through dynamic router imports that no static scan of
`main.py` can see. The real tensor work lives in `model_manager.py`, the TTS engines and the vision
models, not in `main.py`.

**Item 6** — `owui-builder` is `restart: no`. It copies `/app/build` into a host bind mount, exits,
and skips entirely if `index.html` already exists. A 5.25 GB image for a job that runs once per
install, and the thing it delivers is **263 MB of static files**. Its layers are `npm ci --force`
(2.77 GB of `node_modules`) and `npm run build` (651 MB) — both build-time only. The Dockerfile
stops at the `build` target and has no final stage that keeps just `/app/build`.

**Why item 7 needs a `FROM` change rather than a cleanup.** On the conda base, `site-packages`
totals 8.5 GB and **6.3 GB of it ships inside the base layer**: `torch` 1.7 GB, `nvidia/*` 4.1 GB,
`triton` 542 MB. Layers are additive, so `pip uninstall` in any later `RUN` writes a whiteout and
reclaims **zero bytes** — the same trap item 2 fixed. Confirmed by listing the base image's own
packages: `torch`, `triton`, `cmake`, every `nvidia-*`, `torchvision`, `torchaudio` and the whole
conda distribution are inherited, not installed by us. Moving to `python:3.11-slim` puts all of it
in *our* layers, which is what makes the triton removal below possible at all.

Inside that 4.1 GB of `nvidia/*`: `cudnn` 1005 MB, `cublas` 830 MB, `cusparselt` 431 MB, `nccl`
410 MB, `cusolver` 387 MB, `cusparse` 371 MB, `cufft` 268 MB, `cuda_nvrtc` 212 MB, `curand` 133 MB,
`nvjitlink` 90 MB, `cupti` 41 MB, `cuda_runtime` 5 MB, `cufile` 3 MB, `nvtx` 1 MB.

**None of it is removable — tested one package at a time, each in a fresh container.** An earlier
version of this document called `cusparselt` and `nccl` "840 MB of pure waste on a single-GPU box."
That was wrong. This torch build links `libcusparseLt.so.0` and `libnccl.so.2` at import; drop either
and `import torch` dies with `ImportError: cannot open shared object file`. Eleven of the fourteen
fail that way immediately. **The remaining three fail a deeper test, and that is the part worth
remembering:**

| Package | Size | `import torch` + matmul + conv2d | Full 14-op suite |
|---|---:|---|---|
| `nvidia-cuda-nvrtc-cu12` | 212 MB | survives | **breaks `fft` and `stft`** |
| `nvidia-cusolver-cu12` | 387 MB | survives | **breaks `solve`, `svd`, `cholesky`, `inv`** |
| `nvidia-nvtx-cu12` | 1 MB | survives | survives (not worth a layer) |

`stft` is how Whisper builds its log-mel spectrogram, so `nvrtc` is load-bearing for GPU speech even
though a matmul-only smoke test says otherwise. **A shallow CUDA check will greenlight a removal that
breaks the actual workload** — exercise `fft`/`stft`/`linalg`/`sdpa`, not just `a @ b`.

**`triton` (541 MB) is the one real win, and getting it requires collapsing three steps into one
layer.** It survives all 14 ops, `import main` reaches `STATUS OK` without it, and the backend
contains no `torch.compile`, no `torch._inductor`, no `word_timestamps` and no `import triton`
across 381 files.

The layer placement is the whole difficulty, and it is worth spelling out because the obvious
version silently does nothing:

- `pip install torch` pulls `triton==3.4.0` as a dependency, so **triton's 542 MB is created in the
  torch layer**, not the wheels layer.
- Uninstalling it in the wheels `RUN` — a later layer — writes a whiteout. `site-packages` drops
  541 MB and `ls` shows no triton, but the image is **1.4 kB smaller**. Measured, after doing
  exactly this and expecting a win.
- It cannot be uninstalled *before* the wheels install either: `openai-whisper` declares triton, so
  the `--no-index` install fails its dependency check.

So the torch install, the wheels install, and `pip uninstall -y triton` must be a **single `RUN`**.
The cost is cache granularity — any `requirements.txt` edit now re-downloads torch too.

The swap itself is `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` → `python:3.11-slim` +
`pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128`. It drops the Anaconda
distribution, its 559 MB package cache, and `cmake` (a build-only extra of triton and piper-tts). It
does not touch the 4.1 GB of CUDA libraries, because Whisper genuinely runs CUDA inference here.

Two corrections to earlier drafts of this section, both found by building it:

- **The estimate of 1.5–2.5 GB was too high.** Conda's total overhead beyond `site-packages` is
  **620 MB** — `/opt/conda/pkgs` 559 MB, `bin` 51 MB, `share` 39 MB, `include` 30 MB. Everything
  else under `/opt/conda` *is* `site-packages`, which moves to `/usr/local` rather than disappearing.
- **The "101 MB of `/usr/lib/firmware/nvidia` blobs" do not exist.** `du /usr/lib/firmware` returns
  nothing in either image; the directory isn't there. That line was never measured.

**`torchvision` and `torchaudio` must be installed explicitly on a non-conda base, and this is easy
to get wrong.** A static import scan says `torchvision` has no importer and `torchaudio` has one, in
`tts_system/`, which runs in the separate `tts-service` container — both look droppable. They are
not. Importing `main` actually loads `torchvision` (a dynamic router import the AST scan cannot
see), and `qwen-tts` declares `torchaudio` as a hard requirement, so the wheels install dies with
`No matching distribution found for torchaudio` without it. The conda base shipped both for free,
which is why nothing ever surfaced the dependency. Install the pairing the base used:
`torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0`.

**Method note, learned the hard way:** static AST tracing of `main.py` under-reports badly — it
found 95 reachable modules and declared `librosa`, `sentence_transformers` and `torchvision`
unreachable. Actually importing `main` in a throwaway container loads **7,324 modules across 339
top-level packages**, all three of those included. Trust the import, not the scan:

```bash
docker run --rm --network none --user 0:0 --tmpfs /data:rw --entrypoint python <image> \
  -c "import sys; sys.path.insert(0,'/app'); import main; print(len(sys.modules))"
```

## What blocks item 5 (the CPU-only floor, if it is ever wanted)

Ten top-level `import torch` statements exist in the backend. Only the ones reachable from `main.py`'s
import graph matter, because a single one keeps CUDA torch mandatory:

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
