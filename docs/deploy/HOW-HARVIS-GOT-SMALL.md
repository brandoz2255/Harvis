# How Harvis got small — 27.5 GB → 6.28 GB

**Companion to `STORAGE-BUDGET.md`.** That document is the living ledger: what each image costs
today and what is still available to trim. This one is the record of how the reduction actually
happened, what the measured numbers were at each step, and which plausible-sounding trims turned out
to be worth nothing.

Everything here was measured with `docker system df` on real machines, not estimated. Dates and
commits are from branch `deploy-optimize-test`.

---

## The finish line

> Fresh clone → working Harvis in one command, no questions asked, under 7 GB.

Not "smaller" — a number, reachable from a clean machine, with no install-time decisions. A CI guard
(`ce29c284`, fails above 7.5 GB) makes it a property of the project instead of a cleanup that decays.

**Result, measured on VM 102 (`harvis-fresh`, 192.168.20.98) after `./install.sh` plus one frontend
rebuild, 2026-07-29:**

| | |
|---|---:|
| Images (9, deduped) | **5.218 GB** |
| Volumes (7) | 0.590 GB |
| Repo checkout (`.git` 119 MB + owui `build/` 264 MB) | 0.472 GB |
| **On-disk total** | **6.28 GB** |

Under the line with about 0.7 GB of margin. One thing the total does **not** include, and no
measurement in this project ever has: the Docker **build cache**, which sits at 10.88 GB on that same
box (8.70 GB reclaimable). It is real disk. Whether a successful install should
`docker builder prune -f` is an open decision, not an oversight.

---

## Where it started

A default `docker compose up -d` used to start **24 services**. The first move was to stop counting
that as the baseline at all: `fa494b41` put everything optional behind `engines` / `notebooks` /
`voice` / `cad` / `legacy` / `messaging` profiles, leaving 11 in the default set. After that and the
owui-builder fix below, a fresh install measured **27.5 GB** (27.3 GB images + ~180 MB repo, zero
model weights). That is the number the rest of this document reduces.

Three images were 91% of it:

```
backend        15.40 GB  ██████████████████████████████████████████████    56%
ollama          9.70 GB  █████████████████████████████                     35%
everything else 2.40 GB  ███████                                            9%
```

Two `COPY` lines explained 25 of the 27.5: `python_back_end/Dockerfile:72` inherited the 12.1 GB
`pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` base, and `ollama/ollama:latest` shipped 5.58 GB of
precompiled GPU kernels for CUDA, ROCm **and** Vulkan so one image runs on any vendor's card.
Neither was load-bearing for Harvis's own code.

---

## The four moves that did the work

### 1. Ship the frontend build artifact, not the build stage — 5.25 GB → 392 MB

`878927eb`

`owui-builder` is `restart: no`. It copies `/app/build` into a host bind mount, exits, and skips
entirely if `index.html` already exists. It was a 5.25 GB image for a job that runs once per install,
and the thing it delivers is **263 MB of static files**. Its two big layers — `npm ci --force`
(2.77 GB of `node_modules`) and `npm run build` (651 MB) — are build-time only, but the Dockerfile
stopped at the `build` target with no final stage that keeps just the output. Adding one cost nothing
functionally.

**−4.86 GB.**

### 2. One backend image, on a slim base — 15.40 GB → 2.32 GB

`b9fa5868` (the switch), on top of `e713cece` · `3dbdf213` · `39af7ed3` · `90830864` · `6ebbf0f7` ·
`4a980fa5` · `50163779` · `f8a16c55` · `37f5040d` (the torch-free path)

This is the whole size story in one line. `python_back_end/Dockerfile.core` builds on
`python:3.12-slim` and is torch-free; the API path was made to survive without torch by wrapping
`import torch` in a null-object shim (`model_manager.py`) and routing every `torch.cuda.*` call
through it (`main.py`). Speech moved to the ONNX `voice-onnx` sidecar; vision resolves whatever model
is installed rather than importing Qwen2VL in-process; `sentence_transformers` became optional.

Then `backend` **and** `harvis-mcp` were both pointed at that Dockerfile. Same context, same args →
one image on disk, two services. `harvis-mcp` costs 18 kB.

**−13.08 GB.** This move also superseded three earlier trims to the GPU image (build wheels
`81fd6ba8`, orphaned pkuseg and the Docker daemon binaries `06845118`, worth ~1.3 GB together) —
they are in the ledger and were rebuild-verified, but the base they applied to no longer ships.

### 3. The model server is yours — drop the bundled Ollama

`2530e090` (BYO as an opt-in axis) then `1fcc2912` (delete it from the default set)

`ollama/ollama:latest` is 9.70 GB of GPU compute libraries. Model weights are not in it. Harvis now
ships no model server: `HARVIS_LLM_BASE_URL` (`ebf36c6d`) points at whatever OpenAI-compatible
endpoint the user already runs, `install.sh` probes the common local ports and writes what it found,
and `extra_hosts: host.docker.internal:host-gateway` is on every service that calls an LLM.

The same commit deleted `docker-compose.cpu.yml`, `docker-compose.amd.yml` and
`docker-compose.byo-ollama.yml`. Three compose files collapsed to one, and `install.sh` lost its
nvidia/amd/cpu prompt — which is what turned "one command" into "one command, **no questions
asked**."

**−9.70 GB**, plus `ollama-model-check` (`curlimages/curl`, 0.04 GB) which existed only to talk to it.

### 4. Voice back in the default set — on purpose

`df8d713e`

A clean `up -d` had been starting no voice service at all, which silently contradicted the shipped
"Voice-First Default" work. `voice-onnx` (local STT, VAD, Kokoro TTS — all ONNX, no torch) came out
from behind the `voice` profile.

**+1.04 GB, deliberately.** This is the one line in the ledger that goes the wrong way, and it is the
one that makes the install honest.

---

## The arithmetic, closed

Starting from the 27.58 GB per-image sum of the 11-service default set:

| Move | Δ | Running total |
|---|---:|---:|
| baseline (11 default services, after `878927eb`) | | **27.58 GB** |
| backend + harvis-mcp on `Dockerfile.core` | −13.08 | 14.50 GB |
| drop bundled Ollama | −9.70 | 4.80 GB |
| drop `ollama-model-check` | −0.04 | 4.76 GB |
| `harvis-messaging-gateway` behind a profile (`7deffb1f`) | −0.29 | 4.47 GB |
| `voice-onnx` into the default set | +1.04 | 5.51 GB |
| **layer sharing the slim base created** | **−0.29** | **5.22 GB** |
| measured on VM 102 | | **5.218 GB** ✓ |

That last row is not a fudge factor. Once the backend sat on `python:3.12-slim`, `browser-runner`
(117.2 MB shared) and `voice-onnx` (176.9 MB shared) started sharing base layers with it — 294 MB
that previously existed twice on disk. Moving off the pytorch base paid a second time, in a place
nobody planned for.

---

## The default set today

Measured on VM 102. Read **UNIQUE SIZE**, never the SIZE column — adding SIZE triple-counts the
2.32 GB base that `backend` and `harvis-mcp` share, which exists on disk exactly once.

| Service | Image | Fresh-install cost |
|---|---|---:|
| `backend` | `harvis-backend` | **2.32 GB** |
| `harvis-mcp` | *(same image, different entrypoint)* | 0.00 GB |
| `voice-onnx` | `harvis-voice-onnx:local` | 0.87 GB |
| `browser-runner` | `harvis-browser-runner` | 0.75 GB |
| `pgsql` | `pgvector/pgvector:pg15` | 0.61 GB |
| `owui-builder` | `harvis-owui-builder:local` | 0.39 GB |
| `llmfit` | `ghcr.io/alexsjones/llmfit:0.9.30` | 0.18 GB |
| `nginx` | `nginx:1.29.6-alpine` | 0.09 GB |
| `artifact-init` | `busybox:1.37.0` | 0.01 GB |
| **Total** | | **5.218 GB** |

Four of these show as `<none>` in `docker images` — `d2cb36b6` pinned every floating tag by digest, so
the daemon holds them by content address rather than by name. Working as intended, confusing the
first time you see it.

Not included, because they depend on what the user does: model weights (a single 8B model is ~5 GB),
the Postgres data volume, and the owui build output (a bind mount, 264 MB).

---

## Changes that were not about size, but shipped in the same pass

- **`db587596` — one HF cache root.** `HF_HOME` and `TRANSFORMERS_CACHE` were both set, at 12 env
  sites and 3 code sites. The premise on record was that they aliased each other harmlessly; measuring
  showed they were duplicating downloads. Now there is one variable. This is volume growth, not
  install size, so it appears in no table above — but it was worth ~13 GB of avoided re-download.
- **`a15bb4c5` — PyMuPDF out, pypdfium2 in.** `requirements-core.txt` carried both `pypdf` and
  AGPL-3.0 `PyMuPDF`. Primarily a licensing fix. `pypdf` alone could not replace it — it cannot
  rasterize — so this needed a real substitute, not a deletion.
- **`829e266f` — the Docker socket stays, but its group did not.** `group_add: "984"` was one
  developer's machine's `docker` GID. Now `HARVIS_DOCKER_GID`. The socket itself is load-bearing (ten
  files shell out to the `docker` client) and removing it was rejected.
- **`3d28c8f4` — `embedding/` out of the build context**, which matters because `openclaw` and
  `tts-service` build with `context: .`.
- **`f4ad0da4` — `.dockerignore`**, which took the build context from 24 GB to under 1 GB.
- **`6da1f659` — OCI labels** on every locally built image (`source`, `revision`, `licenses`).

---

## What was rejected, and why that matters

Recording the failures is the point of this document. Every one of these looked like an obvious win
and cost real time to disprove.

**The two trims in queue C were rejected on measurement** (`6da1f659` carries the note). C1 proposed
swapping `firefox-esr` for `chromium` in `browser-runner`; C2 proposed gating `tesseract-ocr` out of
the core image behind a build arg. Neither returned enough to justify losing browser automation or
OCR out of the box.

**"Torch is barely used" does not survive contact with the runtime.** `main.py` touches torch in nine
lines, all GPU housekeeping — no tensors, no models. It is tempting to conclude torch is nearly free
to remove. Importing `main` actually pulls in **6,777 modules across 320 top-level packages**, and
`torch`, `transformers`, `librosa`, `sentence_transformers`, `torchvision`, `sklearn` and `numba` all
load, several through dynamic router imports that no static scan of `main.py` can see. The torch-free
core image worked because the *consumers* were migrated (STT to an ONNX sidecar, embeddings to
optional, vision to a resolver), not because torch was unused.

**None of the 4.1 GB of `nvidia/*` packages is removable — tested one at a time, in fresh
containers.** Eleven of fourteen fail `import torch` outright. Three survive a matmul smoke test and
fail a real one: dropping `cuda-nvrtc` (212 MB) breaks `fft` and `stft`, and `stft` is how Whisper
builds its log-mel spectrogram. Dropping `cusolver` (387 MB) breaks `solve`, `svd`, `cholesky` and
`inv`. **A shallow CUDA check will greenlight a removal that breaks the actual workload** — exercise
`fft`/`stft`/`linalg`/`sdpa`, not just `a @ b`.

**`pip uninstall` in a later layer reclaims zero bytes.** Hit twice. `COPY --from=builder /wheels`
followed by `rm -rf /wheels` in a later `RUN` left the full ~455 MB layer in place (fixed in
`81fd6ba8` with a BuildKit bind mount). And removing `triton` — 542 MB, created inside the *torch*
layer as a dependency — in the wheels `RUN` made the image **1.4 kB smaller**. `site-packages` drops
541 MB, `ls` shows nothing, the image doesn't move. Layers are additive; a whiteout costs space, it
doesn't free it.

**The `harvis-core` / `harvis-gpu-worker` split was closed deliberately.** Speech stays first-class in
core. That decision sets the floor at roughly 10 GB for a *GPU* build rather than 3 GB, and it is a
legitimate product call — the plug-and-play default sidesteps it by shipping the ONNX path instead.

**Two numbers in earlier drafts of the budget were never measured and were wrong**: the estimate that
the conda-base swap would save 1.5–2.5 GB (real overhead beyond `site-packages`: 620 MB), and "101 MB
of `/usr/lib/firmware/nvidia` blobs" — that directory does not exist in either image.

---

## How to measure this yourself

```bash
docker system df                    # the authoritative deduped total
docker system df -v | sed -n '/^Images space usage/,/^Containers/p'   # per-image, read UNIQUE SIZE
```

**Never `docker image inspect --format '{{.Size}}'`.** This daemon runs the containerd snapshotter,
where that field reports *compressed pull* bytes, not on-disk bytes — they differ by roughly 3×. It
reported 5.07 GB for the 15.4 GB backend and produced a wrong number once already.

Two build-side facts that will bite anyone reproducing the measurement:

- **The owui build needs swap on an 8 GB box.** `npm run build` sets `--max-old-space-size=8192`; on
  VM 102 (7941 MB, no swap) with the stack already up, the kernel SIGKILLs it during "rendering
  chunks" after `✓ 6285 modules transformed`. 6 GB of temporary swap fixes it. A *fresh* `install.sh`
  survives only because nothing else is running yet.
- **Clearing the bind-mounted build dir must happen in place.** `owui-builder` populates it with
  `cp -a`, preserving container ownership, and its command is skip-if-`/out/index.html`-exists. Use
  `sudo find front_end/owui/build -mindepth 1 -delete` — replacing the directory inode breaks the
  bind mount.

---

## What is still open

1. **The build cache.** 10.88 GB on VM 102, 8.70 GB reclaimable, counted by nothing. `docker builder
   prune -f` after a successful install trades it for slower rebuilds.
2. **The GPU build.** `Dockerfile` (the pytorch one) still exists for users who want in-process GPU
   speech and vision. Its floor is ~10.2 GB and the measured path to it is documented in
   `STORAGE-BUDGET.md` item 7 (slim base + triton dropped in a single layer).
3. **ARM.** Groundwork is favorable — `python:3.12-slim` is multi-arch, onnxruntime ships aarch64
   wheels, fastembed is pure Python — but it needs hardware to verify.
4. **`tts-service` + `model-downloader`** (37 GB together) are profile-gated, so they cost nothing in
   the default set. Relocating them to their own repo is hygiene, not size.
