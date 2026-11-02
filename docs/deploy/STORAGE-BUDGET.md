# Harvis storage budget

**Living document.** Update the measured table whenever an image changes size, and move items
between "banked" and "available" as they land. Last estimated: **2026-10-28** on the dev box
(`scripts/install-size.py`, branch `integration/october`). The sections from "What a bare-bones
install cost" down date from **2026-07-26** (`docker system df -v`, branch `deploy-optimize-test`) and predate the
Python 3.12 slim backend; they are history, not the current install.

## How to measure (do this, don't estimate)

```bash
docker system df -v | sed -n '/^Images space usage/,/^Containers/p'
```

Read the **UNIQUE SIZE** column, not SIZE. Adding the SIZE column triple-counts shared bases — the
backend/harvis-mcp/model-downloader family shares one multi-gigabyte layer stack that exists on disk
exactly once. For a *fresh install* footprint, count each distinct base once and add each image's
unique layers.

## Current estimate: 2026-10-28 (dev box, not a new device)

**Every number in this section is an estimate from the images already on the dev box.** It says
what those images cost, not what a fresh clone produces: the local images can predate the
Dockerfiles (the script flags each one), and images missing from the local store are left out and
named, so the totals are lower bounds. The real figure is a measurement on a new device; see
"Recording a new-device measurement" below.

```bash
python3 scripts/install-size.py                 # default profile set
python3 scripts/install-size.py --each-profile  # + what each opt-in profile adds alone
python3 scripts/install-size.py --json          # same, machine-readable
python3 scripts/install-size.py --self-check    # prove the method against docker system df
```

It reads the compose files, lists the images a fresh `./install.sh` pulls or builds plus the base
images each build pulls and leaves on disk, and counts every layer once by diff-ID. It only reads
(`compose config`, `image inspect`, `history`); no build, pull, prune or container start. Needs
the images to be in the local store; run it before the install, on a box that has built them.

Default profile set: 13 services, 12 distinct images, plus the base images their builds pull. Sizes are decimal GB.
"Alone" is the image's own size; "adds" is what it costs after the images above it have been
counted, which is what the install actually pays.

| Image | Alone | Adds | Note |
|---|---:|---:|---|
| `harvis-backend` | 2.38 | **2.21** | `python:3.12-slim` base, so no 12 GB PyTorch base any more |
| `harvis-harvis-mcp` | 2.38 | 0.00 | same Dockerfile as `backend`; every layer shared |
| `node:20-bookworm` | 1.58 | **1.58** | base of `repo-sandbox-image` |
| `harvis-repo-sandbox` | 1.74 | 0.16 | almost all of it is the `node:20-bookworm` base |
| `harvis-sandbox` | 1.26 | 1.08 | |
| `harvis-browser-runner` | 1.19 | 1.00 | `preview-runner` is the same image |
| `harvis-voice-onnx` | 1.04 | 0.86 | |
| `pgvector/pgvector:pg15` | 0.61 | 0.61 | |
| `python:3.11-slim` / `python:3.12-slim` | 0.19 / 0.18 | 0.19 / 0.18 | build bases, kept in the image store |
| `ghcr.io/alexsjones/llmfit` | 0.18 | 0.18 | |
| `harvis-messaging-gateway` | 0.30 | 0.12 | |
| `nginx:1.29.6-alpine` | 0.09 | 0.09 | |
| `harvis-hermes-ui-builder` | 0.06 | 0.05 | busybox + the built UI; the Node build stage is not an image |
| `busybox:1.37.0` | 0.01 | 0.01 | `artifact-init` and the UI builder's final stage |
| `node:22-bookworm-slim`, `ghcr.io/astral-sh/uv:latest` | not in local store | | build bases, **not counted** |

**Images, shared layers once: 8.31 GB** (6.25 GB unpacked layers + 2.06 GB compressed blobs).
The same images added up naively are 13.18 GB; sharing saves 4.87 GB. Plus the tracked repo
files, 0.11 GB: **≈ 8.42 GB estimated, against the 7.0 GB budget, with two build bases still
uncounted.** Volumes and the BuildKit cache are not estimated; a device that builds its own images
also holds the build cache (the dev box holds 104 GB of it).

Opt-in profiles, each added alone on top of the default set:

| Profile | Adds (GB) | Not in local store, not counted |
|---|---:|---|
| `advanced-voice` | 37.61 | `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` |
| `engines` | 9.79 | |
| `notebooks-upstream` | 2.56 | |
| `cad` | 1.73 | |
| `laya` | 1.55 | |
| `notebooks` | 1.50 | |
| `legacy` | 1.24 | |
| `sentrysearch` | 0.00 | |
| `agent-reach` | 0.00 | `curlimages/curl:8.5.0` |
| `tunnel` | 0.00 | `cloudflare/cloudflared:2026.9.3` |
| `voice-fallback` | 0.00 | `ghcr.io/speaches-ai/speaches:latest-cpu` |

All profiles on: **64.09 GB** of images with six images uncounted (shared layers save 35.9 GB of
the 100.0 GB naive sum).

**What the four merged October branches change in a fresh install.** Nothing in the default set.
The only Docker-relevant files in the merge are `opencode/Dockerfile` (deleted) and
`docker-compose.yaml` (the `opencode` service removed, `HARVIS_OPENCODE_*` settings replaced by
`HARVIS_ENGINE_IDLE_TIMEOUT_S`), so `harvis-opencode` leaves the opt-in `engines` profile; that
image is not in the local store, so its size is not measured here. `docker-compose.prebuilt.yml`
changed environment variables only. No `requirements*.txt`, `package.json` or lockfile changed.
The in-app island adds `front_end/hermes-desktop-ui/public/island/` (`index.html` and `island.js`,
119,695 bytes on 2026-10-28, still changing) to the UI build output, which is negligible next to
the 0.05 GB UI builder image.

**How close the estimate is.** `--self-check` runs the same method over all 63 images on the box
(419 distinct layers, all aligned) and compares with Docker: the whole-store total comes to
103.23 GB against `docker system df` at 103.30 GB (-0.07%). Against `docker system df -v` UNIQUE
SIZE, images over 100 MB are off by a median 0.11%; the worst is `harvis-model-downloader`
(5.12 GB estimated, 4.76 GB reported, 7.7%), where the compressed-blob share is the soft part.

**Method, and why not the obvious numbers.** On Docker 29 with the containerd image store,
`docker image ls` DISK USAGE is the unpacked layers plus the compressed blobs kept beside them, and
`docker image inspect` `.Size` is the same total for one image, with no sharing information.
Per-layer unpacked sizes come from `docker history --human=false`, taken from the non-empty history
rows and matched to `RootFS.Layers` in order. The compressed part is `.Size` minus the unpacked
sum, spread over the image's layers in proportion to their unpacked size. On the classic overlay2
store there are no blobs and that part is zero. The script refuses to guess: an image whose layer
count does not match its history is counted whole and flagged.

## Recording a new-device measurement

The estimate is made on a dev box. The number that counts comes from a device that has never run
Harvis (no Harvis images, no warm build cache, no model server), after the one command under test:

```bash
git clone <repo> harvis && cd harvis
./install.sh
INSTALL_SIZE_DEVICE=pi5-8gb INSTALL_SIZE_NOTE="first boot, wifi" ./scripts/verify-fresh-install.sh
```

Every run of `verify-fresh-install.sh` appends one JSON line to
`~/.local/share/harvis/install-size-history.jsonl`, outside the repo: date, git commit and branch,
OS, kernel and architecture, Docker and Compose versions, image, volume, repo and total GB, the
budget, whether it was within budget, the BuildKit cache and container sizes (recorded, not in
the total), and every image's `SIZE` and `UNIQUE SIZE`. It never changes the script's exit status.
`INSTALL_SIZE_HISTORY` points it at another file (set it empty to record nothing). Compare runs:

```bash
python3 -c "
import json, os
for l in open(os.path.expanduser('~/.local/share/harvis/install-size-history.jsonl')):
    r = json.loads(l)
    print(r['date'][:10], r.get('device'), r['git']['commit'], r['kind'], r.get('total_gb', ''), r.get('build_cache_gb', ''))"
```

`python3 scripts/install-size.py --record` appends the dev-box estimate to the same file as
`kind: estimate`, so estimate and measurement sit side by side.

| Date | Where | Commit | Kind | Images GB | Total GB | Note |
|---|---|---|---|---:|---:|---|
| 2026-10-28 | dev box | `ae5fd20d` (uncommitted merge) | estimate | 8.31 | 8.42 | two build bases uncounted |
| | *no new-device measurement yet* | | | | | |

## What a bare-bones install cost on 2026-07-26 (superseded)

Kept for the reduction history below. `ollama` and `owui-builder` are no longer in the default set,
and the backend is no longer on the PyTorch base; use the current estimate above.

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

## Why Odysseus is 3 GB and we are 27

Measured 2026-07-26 against the Odysseus stack running on this same box
(`/home/ommblitz/Projects/Odysseus/odysseus`). Same method — UNIQUE SIZE, fresh clone, zero
models pulled. Our `ollama-model-check` is detect-only and pulls nothing, so this is a clean
image-only comparison.

| | services | images |
|---|---|---:|
| Harvis default | 11 | **27.4 GB** |
| Harvis `--ollama-url` (BYO) | 9 | **17.7 GB** |
| Odysseus | 4 | **3.03 GB** |

The repo is noise on both sides: Harvis 80 MB checkout + 98 MB pack, Odysseus 34 MB + 23 MB.

**Quote the BYO-adjusted ratio, not the raw one.** Odysseus ships no model server — its compose
points at `host.docker.internal:11434`, which is the same BYO posture `--ollama-url` gives us.
Counting the Ollama a local-inference user needs either way, Harvis is **2.15×** Odysseus, not 9×.

### The gap is one thing, not a hundred

Comparing like with like (both assuming an external Ollama), the delta is 14.66 GB:

| | Harvis BYO | Odysseus | delta |
|---|---:|---:|---:|
| app image | 15.40 GB | 1.71 GB | **13.69 GB** |
| everything else | 2.29 GB | 1.32 GB | 0.97 GB |

The supporting cast is already within a gigabyte. And **12.10 GB of our backend is the
`pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` base — 83% of the entire gap.** No amount of
service trimming, package pruning or repo hygiene touches it.

### The mechanism: inference runtime vs training framework

Odysseus's whole `site-packages` is **371 MB**, and the largest entry in it is **`onnxruntime`
at 55 MB**. Checked by name inside the image, all of these are **absent**: `torch`,
`transformers`, `sentence_transformers`, `whisper`, `faster_whisper`, `librosa`, `soundfile`,
`torchaudio`, `torchvision`, `nvidia/*`, `triton`, `TTS`, `piper`.

Ours is **8,486 MB**, and three entries are 76% of it:

```
nvidia/*   4,184 MB
torch      1,692 MB
triton       542 MB
           ─────────
           6,418 MB   = 76% of site-packages
```

ONNX Runtime executes a pre-compiled model graph and nothing else. PyTorch ships a tensor
library, autograd, a compiler (`triton`) and the CUDA toolchain, because it exists to *train*.
Harvis never trains anything — it pays the training-framework tax because the libraries it
depends on are written against torch.

### What actually keeps torch alive here — four consumers

**`onnxruntime` (57 MB) and `piper` (25 MB) are already installed in our image.** The ONNX path
is not foreign to Harvis; `piper` is a real, used ONNX TTS engine (6 importers, incl.
`tts_engine_manager.py:12`). `onnxruntime` has **zero direct importers** in our code — it arrived
as a transitive dependency.

| Consumer | Call sites | Torch-free path |
|---|---|---|
| `openai-whisper` (STT) | `main.py:120`, `cody.py:19`, +2 | `faster-whisper` (CTranslate2) — keeps GPU, no torch |
| `sentence_transformers` | `enhanced_vector_optimizer.py:8`, `research/rank/rerank.py:139` | fastembed / ONNX MiniLM — literally Odysseus's choice |
| `chatterbox` / `qwen3_tts` | `tts_engine_manager.py:45`, `qwen3_tts.py:14`, +10 | `piper`, already present — quality/voice-clone regression |
| `transformers` (vision) | `model_manager.py:463`, `chatbot.py:9`, `vison_models/qwen.py:1` | ONNX export or a sidecar — **the hard one** |

Only two call sites use `sentence_transformers`. `faster_whisper` has zero — it is not installed.

### The ceiling, and why it is ~10 GB rather than 3

**Estimated, not measured — flagged deliberately.** GPU speech still needs cuDNN (1,005 MB) and
cuBLAS (830 MB); CTranslate2 links them too. The *torch-only* CUDA libraries are roughly
cusolver 387 + cusparselt 431 + nccl 410 + nvrtc 212 + cufft 268 + cusparse 371 + curand 133 ≈
**2.2 GB**. The one-package-at-a-time removal tests recorded above were run against **torch**;
CTranslate2's requirement set needs its own pass before anyone relies on this split.

On that estimate: torch 1.7 + triton 0.5 + transformers 0.12 + torch-only CUDA 2.2 ≈ **4.6 GB
off**, taking the backend from 15.4 GB to about **10.8 GB**, or ~10.2 with item 7's slim base.
A real win — and still **6× Odysseus**.

**All-or-nothing:** one surviving torch consumer keeps the entire 6.4 GB stack. Migrating three
of the four buys nothing in image size.

### The architectural floor

Odysseus is small because of what it does not do. It is a router: no speech, no vision, no
in-process inference beyond an ONNX embedding model, and no model server of its own. Harvis is a
runtime — Whisper STT, TTS, vision and embeddings run in-process on the GPU, which *is* the
optimization-plus-customization premise. Those two shapes have different floors.

Exactly one change bridges them: move torch out of the backend into a GPU worker behind a
profile, leaving the core as a router. That is the `harvis-core` / `harvis-gpu-worker` split,
which was **deliberately closed** — speech stays first-class in core. That decision sets the
floor. It is a legitimate decision; it just means the target is ~10 GB, not 3 GB.

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
