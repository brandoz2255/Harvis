# Handoff — plug-and-play core + the Ollama question (2026-07-28)

**Status:** direction set by the user, nothing implemented. This is a research brief.
**Branch:** `deploy-optimize-test` (30 commits ahead of origin, unpushed — separate blocker, see bottom).
**Target the user set:** *a working Harvis install should be no more than **12 GB** on disk.*
**Guiding question the user wants applied to every decision:**
> "What can users just plug and play on their own and put into Harvis — like Odysseus? And can we
> improve on that, giving Harvis better structural support without copying completely? If copying is
> better, that's fine. If we have to sacrifice some space, that's also fine."

---

## 1. Measured baseline (all numbers verified 2026-07-27/28 on this box)

Fresh install today, default path (`COMPOSE_FILE=docker-compose.yaml:docker-compose.override.yml`):

| Component | Size | Notes |
|---|---|---|
| `backend` + `harvis-mcp` | **15.4 GB** | same Dockerfile, no differing build args → one image on disk |
| `ollama/ollama:latest` | **9.7 GB** | engine only, **zero models** |
| `browser-runner` | 864 MB | in the default set |
| `pgvector/pgvector:pg15` | 612 MB | |
| `owui-builder` | 392 MB | |
| `llmfit` | 178 MB | |
| `nginx:alpine` | 93.5 MB | |
| `curl` + `busybox` | 43 MB | init/health helpers |
| repo clone | ~180 MB | 98 MB pack + 80 MB checkout |
| **Total** | **≈27.5 GB** | |

Measurement note: this daemon uses the **containerd snapshotter**, where
`docker image inspect --format '{{.Size}}'` reports *unique-layer* bytes, not the image total. Use
`docker images` / `docker system df -v`. An earlier pass in this session reported 13.87 GB from
`inspect` — that number was wrong, ignore it if it appears in older notes.

### Why the backend is 15.4 GB

From `docker history harvis-backend:latest`:

| Layer | Size |
|---|---|
| `COPY /opt/conda` (from the PyTorch base — torch + CUDA + cuDNN kernels) | **7.74 GB** |
| `pip install /wheels/*` (core + voice requirements) | 1.80 GB |
| `apt: libgl1 ffmpeg tesseract-ocr …` | 440 MB |
| everything else | < 100 MB each |

The single cause is `python_back_end/Dockerfile:72` → `FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime`
(that base is 12.1 GB standalone). Roughly **8 of the 15 GB is torch/CUDA; about 2 GB is Harvis.**

### Why Ollama is 9.7 GB

From `docker history ollama/ollama:latest`:

| Layer | Size |
|---|---|
| `COPY /lib/ollama → /usr/lib/ollama` | **5.58 GB** |
| `apt: ca-certificates libvulkan1 libopenblas0` | 340 MB |
| Debian base | 87 MB |
| `COPY /bin` | 40 MB |

That 5.58 GB is Ollama's **precompiled inference kernels for every GPU backend they ship** — CUDA
across several compute capabilities, ROCm, Vulkan — bundled whether or not the host can use them.
**No model weights.**

---

## 2. What is already true (do NOT re-do these)

- **`Dockerfile.core` already exists and works.** `python:3.12-slim`, builds to **2.42 GB**, tagged
  `harvis-backend:core`. It proves the user's central claim: Harvis itself does not need PyTorch.
- **The requirements split is already done.**
  - `requirements-core.txt` — 66 lines, **zero torch/whisper/sentence-transformers**.
  - `requirements-voice.txt` — 9 lines, and it is where the weight lives: `torch==2.8.0`,
    `torchaudio==2.8.0`, `accelerate`, `openai-whisper`, `sentence-transformers`, `piper-tts`,
    `onnxruntime`.
  - `requirements.txt` — 2 lines, just includes the other two.
  So "replace the default Torch consumers" is scoped to **one 9-line file**.
- **Ollama never auto-pulls models.** `ollama-model-check` is detect-only — it waits for the API,
  counts existing tags, prints, exits. Item 10 on the user's list is effectively already satisfied
  for models. Models live in their own volume and start empty.
- **`voice-onnx` already exists** as its own 1.04 GB image with a 1.1 GB `voice-models` volume, and
  the ONNX STT/TTS work landed and was verified E2E.

## 3. What is broken or missing (verified)

1. **The CPU path is *bigger* than the GPU path.** `docker-compose.cpu.yml` correctly points
   `backend` at `Dockerfile.core`, but leaves **`harvis-mcp` on the full torch `Dockerfile`**. So a
   CPU install builds *both*: 2.42 GB + 15.4 GB = 17.8 GB of backend images vs 15.4 GB shared on the
   GPU path. Choosing "cpu" in `install.sh` currently costs **~2.4 GB extra** and still drags the
   whole CUDA stack onto a machine with no GPU. One-line fix.
2. **`voice-onnx` is not in the default set** — it sits behind `profiles: ["voice"]`. A clean
   `docker compose up -d` starts **no voice service at all**, which contradicts the "Voice-First
   Default" framing of the last batch.
3. **`Dockerfile.core` is not the default for anything on the GPU path**, and is not used by
   `harvis-mcp` on any path.
4. **No provider-discovery step exists.** Nothing checks for a host Ollama / LM Studio / llama.cpp /
   vLLM before starting our own Ollama container.

---

## 4. The arithmetic that decides everything

If `Dockerfile.core` becomes the default for **both** `backend` and `harvis-mcp` (one shared 2.42 GB
image), and voice-onnx moves into the default set, the non-Ollama stack is:

| | GB |
|---|---|
| backend + mcp (core) | 2.42 |
| voice-onnx image | 1.04 |
| voice-models volume | 1.10 |
| browser-runner | 0.86 |
| pgsql | 0.61 |
| owui-builder | 0.39 |
| llmfit | 0.18 |
| nginx + curl + busybox | 0.13 |
| repo | 0.18 |
| **subtotal** | **≈6.9 GB** |

**That leaves ~5.1 GB of headroom for Ollama under the 12 GB cap.** The official image is 9.7 GB, so
it does not fit. Three ways to land inside 12 GB:

- **External Ollama** (user already has one) → **≈6.9 GB total.** Comfortably inside.
- **A single-architecture Ollama image ≤5.1 GB** → fits, *if such a thing can be built or pulled.*
  This is the main open question.
- **Portable/official Ollama** → ~16.6 GB. Over budget, but a legitimate opt-in choice.

Secondary levers if 5.1 GB proves too tight: `browser-runner` (864 MB) is in the default set and is
probably profile-able; the core image's **535 MB `ffmpeg + tesseract-ocr` apt layer** is its single
largest, ahead of the 978 MB of Python wheels.

Where `Dockerfile.core`'s 2.42 GB actually goes (`docker history`): 978 MB pip wheels · **535 MB
ffmpeg/tesseract** · 99 MB git+openssh · 87 MB Debian base · 43 MB Docker CLI. Biggest single
site-packages entries: `googleapiclient` 100 MB, `sympy` 73 MB, `pymupdf` 64 MB, `numpy` 43+27 MB,
`babel` 33 MB, `jieba` 29 MB, `fontTools` 27 MB, `yt_dlp` 24 MB.

---

## 5. Research brief — answer these next session

The user's ask: **"research what other things we can do for the backend and Ollama, or if we should
settle."** These are the questions worth answering *before* writing code.

### Ollama (highest leverage — it is 35% of the install)

- **R1. Does a smaller official Ollama variant exist?** `ollama/ollama:rocm` is already used by
  `docker-compose.amd.yml`, so at least one arch-split tag exists. Are there CUDA-12-only /
  CUDA-13-only / CPU-only tags, and what do they weigh? *Do not assume — check the registry.*
- **R2. If not, can we build one?** Ollama is open source; the 5.58 GB is `/usr/lib/ollama` runners.
  How hard is it to build an image with one runner? What's the maintenance cost of carrying our own
  Ollama build forever?
- **R3. Can we prune the official image instead?** Deleting unused runners from `/usr/lib/ollama` in
  a derived layer does **not** shrink the image (layers are additive) — it would need a
  `--squash`/multi-stage `COPY` of just the wanted runner. Feasible? Legal per their license?
- **R4. Is bundling Ollama at all the right default,** or should the default be *external/BYO* with
  a container as the fallback? (Note: `--ollama-url` BYO already shipped, `2530e090`.)
- **R5. What does hardware detection actually need?** `install.sh` already picks nvidia|amd|cpu. Can
  it also read the CUDA compute capability to pick a runner variant, and how does it behave when it
  guesses wrong?

### Backend

- **R6. Is `faster-whisper` + CTranslate2 actually a win over what voice-onnx already does?** We
  already ship ONNX STT. Measure before swapping — the last benchmark returned an identical 4.58% WER
  across all five engines on 12 synthetic clips, which was a **measurement failure, not a tie**. Any
  STT comparison needs real recorded audio first.
- **R7. FastEmbed/ONNX vs sentence-transformers** — which models do we actually use for embeddings
  today, are ONNX equivalents available for them, and does swapping change retrieval quality? This
  removes `sentence-transformers` → removes a torch dependency.
- **R8. What in the core image is genuinely core?** 535 MB of ffmpeg+tesseract in a "lightweight"
  backend deserves scrutiny — could OCR move to a document/vision pack?
- **R9. Vision routing** — enumerate every place the backend runs a torch vision model locally
  (`screen_analyzer.py`, BLIP, etc.) and confirm each has a provider-routed replacement path.
- **R10. Engine-pack mechanics** — how does "Settings → Voice Engines → Install Qwen3-TTS" actually
  work at runtime? Pulling an image from inside a container needs the Docker socket (already
  mounted — and already flagged as a host-root security concern in the Build Space plan). This is
  the one item on the user's list with a real architectural unknown, and it likely deserves its own
  design doc rather than being bundled into a size-reduction pass.
- **R11. Health-check semantics** — the `connected` / `disabled` / `not installed` tri-state the user
  asked for: how many surfaces report optional engines as failures today?

### The "or should we settle" question

Worth answering honestly. **Just fixing the CPU overlay and making `Dockerfile.core` the default for
`backend` + `harvis-mcp` — with external Ollama — reaches roughly 6.9 GB with no new architecture at
all.** That is already under the 12 GB target. Everything past that (engine packs, provider
discovery UI, custom Ollama builds) buys polish and user experience, not headroom. The research
should say plainly which items are needed to *hit the number* versus which are needed to *make it
feel like a product* — and the second group can be sequenced later without blocking the first.

---

## 6. The user's 10 concrete changes, annotated with what's measured

| # | Change | Grounded status |
|---|---|---|
| 1 | Make `Dockerfile.core` the default backend **and MCP** image | Image exists (2.42 GB). Blocker: verify nothing in the API path imports torch. Biggest single win. |
| 2 | Provider discovery screen (host + remote engines) | Not built. `--ollama-url` BYO plumbing exists to build on. |
| 3 | Stop starting Ollama automatically | Compose change; needs a graceful "no engine configured" state in the UI. |
| 4 | Optional Ollama variants (portable / CUDA 13 / CUDA 12 / CPU) | **Gated on R1–R3.** Only `:rocm` is confirmed to exist. |
| 5 | Replace OpenAI Whisper with Faster-Whisper | Scoped to `requirements-voice.txt`. **Gated on R6** — measure first. |
| 6 | Replace Sentence Transformers with FastEmbed | Scoped to `requirements-voice.txt`. **Gated on R7.** |
| 7 | Keep Piper / Kokoro as built-in voice baseline | Already true — `piper-tts` is in requirements, `voice-onnx` ships Kokoro, browser Kokoro verified offline (`16fb3a24`). Mostly a *profile* change: move `voice-onnx` into the default set. |
| 8 | Route vision through connected providers | **Gated on R9.** |
| 9 | Package Qwen3-TTS / Chatterbox / RVC as optional voice engines | Partly exists — `advanced-voice` profile already holds `tts-service` (20.3 GB) and `model-downloader` (16.9 GB). The gap is the *install-from-Settings* UX. **Gated on R10.** |
| 10 | Health checks understand connected / disabled / not installed | **Gated on R11.** Model auto-pull half is already done. |

---

## 7. Also still open (unrelated to this, do not lose)

- **30 unpushed commits on `deploy-optimize-test`**, blocked on the decision about the 51 MB
  `embedding/database_backup.dump` in the history of all three pushed branches of a **public** repo.
  That account's password should be treated as compromised regardless.
- **huggingface.co fallback policy** (voice acceptance criterion 8): fail loudly vs. keep-and-announce.
  Currently keep-and-announce.
- **Item 12 benchmark accuracy** — needs real recorded audio, per R6.
- **Split HF model cache** — `HF_HOME` + `TRANSFORMERS_CACHE` both set → ~13 GB downloaded twice.
  Fix is destructive, needs the user's call. Directly relevant to the size target.
