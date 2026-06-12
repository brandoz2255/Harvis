# GPU sm_120 / PyTorch CUDA 12.8 upgrade — ✅ DONE (executed 2026-06-09)

**Status:** SHIPPED 2026-06-09. Backend rebuilt on `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime`
(`torch 2.8.0+cu128`). Verified: `get_device_capability()==(12,0)` (sm_120), GPU matmul runs with
NO "no kernel image" error, Whisper STT + embeddings on GPU, **GPU TTS = 1.43s/sentence warm vs
15.7s CPU (~11×)**. No regressions (embeddings shape 384 OK, chat unaffected — Ollama is separate).

## ⚠️ Result caveat (8 GB laptop): VRAM coexistence, not architecture
The sm_120 wall is gone, but the **8 GB laptop GPU can't hold the LLM + TTS at once**: with
qwen3.5-9b resident (4.4 GB) + desktop (~1.5 GB), only ~0.8 GB is free, and qwen-TTS needs ~1.2 GB
→ it OOMs and falls back to CPU (graceful) when the LLM is loaded. So on the laptop, GPU TTS is fast
**only when VRAM is free** (smaller model / LLM unloaded). **Stance (user): model stays
user-adjustable** — each user picks their model; freeing VRAM for fast voice is their choice, not a
hardcoded voice-model. The backend is correct (tries GPU, falls back cleanly). On the **rig** (ample
VRAM) voice TTS is fast with zero further changes — this was always the real target.

## Build gotcha hit + fixed (for the rig rebuild)
The runtime `pip install /wheels/*` failed first time: torch 2.8.0 needs `sympy>=1.13.3` but the
builder baked `sympy 1.13.1` (resolved without torch's constraint visible). Fix already in the
Dockerfile: the wheel-strip step (after `pip wheel`) now also removes
`sympy-* typing_extensions-* mpmath-*` so the base image's torch-compatible versions win. Rollback
image preserved as `harvis-backend:cu124-rollback`.

---

## Original plan (for reference / the rig)
**Goal:** make all PyTorch models (TTS, Whisper, embeddings, BLIP) run on the
**RTX 5070 Laptop GPU** instead of falling back to CPU.

## Why
The dev box GPU is an **RTX 5070 Laptop = `sm_120` (Blackwell)**. The backend image
ships `torch 2.6.0+cu124`, whose CUDA kernels stop at `sm_90`. So every torch model
silently runs on **CPU**:
```
NVIDIA GeForce RTX 5070 Laptop GPU with CUDA capability sm_120 is not compatible
with the current PyTorch installation (supports sm_50 … sm_90).
```
Ollama (own CUDA build) runs the LLM on GPU fine — but TTS (qwen/chatterbox) use
torch directly → CPU → unusably slow voice playback. (Verified: qwen TTS ≈ 28.6s
cold / 15.7s warm for one short sentence on CPU.)

**First PyTorch with Blackwell `sm_120` kernels: 2.7.0, built on CUDA 12.8.**

## Current state (cite-verified 2026-06-09)
- `python_back_end/Dockerfile` — 2-stage; **both** `FROM` lines use
  `pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime` (builder L3, runtime L55).
  Builder strips torch/numpy from the wheel set (L38) and deletes any torch wheels
  (L50–51) so the base image's torch is authoritative; runtime installs the rest.
- `requirements.txt` — `torch==2.6.0`, `torchaudio==2.6.0` (L23–24). torchvision not pinned.
- In-container: `torch 2.6.0+cu124`, `cuda build 12.4`, `cuda avail True` (but wrong arch).

## The change
1. **Base image → CUDA 12.8 / torch ≥2.7.** Update BOTH `FROM` lines in
   `python_back_end/Dockerfile`. Preferred (mirrors current pattern):
   `FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` (or the newest 2.7.x/2.8.x
   `cuda12.8` runtime tag that exists on Docker Hub — **VERIFY the exact tag first**:
   `docker manifest inspect pytorch/pytorch:<tag>` or browse hub.docker.com/r/pytorch/pytorch/tags).
   **Fallback if no suitable pytorch/pytorch tag:** base on `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04`
   + `pip install torch==2.8.* torchaudio==2.8.* --index-url https://download.pytorch.org/whl/cu128`.
2. **requirements.txt** — bump `torch==`/`torchaudio==` to the matching 2.7/2.8 version
   (keep torch out of the built wheels, same as today — the base image provides it).
3. Keep the builder's torch-wheel strip (L50–51) so we never double-install a cu124 torch.

## Regression surface (retest ALL after rebuild — torch bump can ripple)
| Component | Dep | Check |
|---|---|---|
| **qwen TTS** | `qwen-tts` + transformers | the WIN: `/api/v1/audio/speech` synth < 1s; voice playback real-time |
| **Whisper STT** | `openai-whisper` | `/api/v1/audio/transcriptions` + `/api/mic-chat` still transcribe |
| **Embeddings / RAG** | `sentence-transformers` | notebook/RAG search + memory still embed |
| **Screen analysis** | BLIP (transformers) | `/api/analyze-screen*` if torch-based |
| **numpy** | pinned `>=1.26,<2.0` | torch 2.8 may want numpy 2.x — check the constraint |
| **transformers** | qwen3 needs a min version | confirm no version conflict with torch 2.8 |
| **llama-cpp-python** | separate CUDA build | GGUF TTS path — may need its own cu128 rebuild/flags |

## Validation (definition of done)
```bash
docker exec harvis-backend python3 -c "import torch; print(torch.__version__, torch.cuda.get_device_capability())"
# expect: 2.8.x+cu128  (12, 0)   — and NO sm_120 warning
# then: TTS synth drops ~15s → <1s; Whisper STT OK; embeddings OK
```
After the GPU fix, revert the OWUI voice config to the **neural qwen voice on GPU**
(today it's `auto_unload=False` warm CPU as a stopgap) — `python_back_end/main.py`
`owui_audio_speech._synth()`.

## Risk / rollback
- **Risk: medium-high.** A torch major bump can break pinned transformers / torchaudio
  / chatterbox / llama-cpp. Do it in a **dedicated session with a clean rebuild**, not
  mid-feature.
- **Rollback:** `git revert` the Dockerfile + requirements changes → rebuild → back to
  2.6.0+cu124 (CPU TTS). The whole change is image-level + 4 lines, fully reversible.
- This is also the fix you'll want for the **rig/prod** anyway, so the work transfers.

## Interim (already shipped today, keep until this lands)
- Voice STT + LLM + the *pipeline* all work; only TTS speed is GPU-blocked.
- `owui_audio_speech` uses `auto_unload=False` (model stays warm → 28.6s→15.7s). Keep it.
- The code path is correct — on any `sm_90`-or-compatible GPU (or after this fix) voice
  TTS is fast with **zero further changes**.
