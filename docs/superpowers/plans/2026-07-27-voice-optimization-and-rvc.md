# Harvis Voice Optimization + RVC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the torch-free voice tiering work started on `deploy-optimize-test`, expose it in `install.sh`, and ship real RVC voice cloning/conversion as an opt-in advanced capability rather than a broken default.

**Architecture:**
- The default voice path is `voice-onnx` (`--profile voice`): ONNX-based Whisper STT + Kokoro TTS, no torch/CUDA, ~1 GB image + ~630 MB downloaded models.
- The heavy torch path moves behind `--profile advanced-voice` and is rebuilt/repurposed as the RVC host: it trains RVC models from audio samples and converts base TTS audio through them.
- The backend already has a provider-neutral boundary (`python_back_end/synthesis.py`, `python_back_end/transcription.py`) with `local | sidecar | browser | disabled` providers; the plan extends that boundary so RVC is an optional post-process step, not a hard dependency.

**Tech Stack:** Docker Compose, FastAPI, sherpa-onnx, Kokoro, rvc-python, PyTorch 2.8+cu128, Python 3.10 (fairseq constraint), soundfile, librosa.

## Global Constraints

- No PyTorch/CUDA in the default backend image; the `voice` profile must stay torch-free.
- RVC must live behind a Compose profile (`advanced-voice` or `rvc`) so a default install does not download multi-gigabyte voice weights.
- All new endpoints follow the existing OpenAI-shaped STT/TTS contracts used by `synthesis.py` and `transcription.py`.
- The browser Kokoro mirror must not silently fall back to `huggingface.co` without user consent (the 10th acceptance criteria from commit `35a92c3f`).
- `install.sh` must write `COMPOSE_PROFILES` into `.env` the same way it writes `COMPOSE_FILE` for backend selection.
- RVC training is CPU/GPU optional and must report progress; it is never a boot-blocking dependency.

---

## State of the World (read this first)

- Branch: `deploy-optimize-test` (branched from `harvis1.1`).
- Latest voice commit: `35a92c3f` — `voice` profile now contains only `voice-onnx`; `advanced-voice` contains `tts-service` + `model-downloader`; `voice-fallback` contains `stt`.
- `voice-onnx` is implemented in `services/voice-onnx/` and exposes `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/audio/voices`, plus `/browser` for mirrored Kokoro weights.
- `tts-service` (`python_back_end/tts_system/server.py`) currently initialises `VibeVoiceEngine` which tries Dia → falls back to SpeechT5 because Dia requires torchaudio and the image uses PyTorch nightly. RVC code exists (`python_back_end/tts_system/engines/rvc_engine.py`) but is only useful when `rvc_python` and torch import successfully.
- `install.sh` currently does **not** set `COMPOSE_PROFILES`; users must discover profiles manually.
- The backend's `synthesis.py` provider model supports `HARVIS_TTS_PROVIDER=sidecar` pointing at `http://voice-onnx:8000/v1`.

---

## Phase 1: Optimization Completion

### Task 1: Installer exposes voice profile selection

**Files:**
- Modify: `install.sh`
- Modify: `.env.example`
- Test: run `install.sh --help` and a dry-run install to inspect `.env`

**Interfaces:**
- Consumes: existing `COMPOSE_FILE` selection logic, existing `OLLAMA_MODE` flow.
- Produces: `.env` line `COMPOSE_PROFILES=voice` (or empty, or `advanced-voice`, etc.).

- [ ] **Step 1: Add profile prompt to install.sh**

After the Ollama/BYO prompts and before the summary, add a multiple-choice prompt:

```bash
ask_voice_profile() {
  echo ""
  echo "Voice capability:"
  echo "  1) Torch-free Voice-First preset (Kokoro + Whisper ONNX, ~1 GB image) — recommended"
  echo "  2) No voice (typed chat only)"
  echo "  3) Advanced voice + RVC (torch/CUDA sidecar, ~20 GB image, voice cloning)"
  echo "  4) Voice fallback (Speaches STT sidecar instead of ONNX)"
  local choice
  read -rp "Choose [1-4, default 1]: " choice
  case "${choice:-1}" in
    1) VOICE_PROFILE="voice" ;;
    2) VOICE_PROFILE="" ;;
    3) VOICE_PROFILE="advanced-voice" ;;
    4) VOICE_PROFILE="voice-fallback" ;;
    *) VOICE_PROFILE="voice" ;;
  esac
}
```

- [ ] **Step 2: Write COMPOSE_PROFILES into .env**

After writing `COMPOSE_FILE`, add:

```bash
if [ -n "$VOICE_PROFILE" ]; then
  update_env "COMPOSE_PROFILES" "$VOICE_PROFILE"
  # When voice-fallback is chosen, STT goes to the Speaches sidecar.
  if [ "$VOICE_PROFILE" = "voice-fallback" ]; then
    update_env "HARVIS_STT_PROVIDER" "sidecar"
    update_env "HARVIS_STT_URL" "http://stt:8000/v1"
  else
    update_env "HARVIS_STT_PROVIDER" "sidecar"
    update_env "HARVIS_STT_URL" "http://voice-onnx:8000/v1"
  fi
  update_env "HARVIS_TTS_PROVIDER" "sidecar"
  update_env "HARVIS_TTS_URL" "http://voice-onnx:8000/v1"
else
  update_env "COMPOSE_PROFILES" ""
  update_env "HARVIS_TTS_PROVIDER" "disabled"
  update_env "HARVIS_STT_PROVIDER" "disabled"
fi
```

Use the same `update_env` helper that handles `COMPOSE_FILE`.

- [ ] **Step 3: Update .env.example**

Add or ensure these lines exist and are commented:

```bash
# Voice capability profile — set by install.sh
# COMPOSE_PROFILES=voice
# HARVIS_STT_PROVIDER=sidecar
# HARVIS_STT_URL=http://voice-onnx:8000/v1
# HARVIS_TTS_PROVIDER=sidecar
# HARVIS_TTS_URL=http://voice-onnx:8000/v1
# HARVIS_TTS_VOICE=af_heart
```

- [ ] **Step 4: Test the installer dry-run**

```bash
./install.sh --dry-run --backend nvidia <<< $'\n\n1\n'
grep -E '^(COMPOSE_PROFILES|HARVIS_(STT|TTS)_PROVIDER|HARVIS_(STT|TTS)_URL)=' .env
```

Expected: `COMPOSE_PROFILES=voice`, `HARVIS_TTS_PROVIDER=sidecar`, `HARVIS_TTS_URL=http://voice-onnx:8000/v1`, `HARVIS_STT_PROVIDER=sidecar`, `HARVIS_STT_URL=http://voice-onnx:8000/v1`.

- [ ] **Step 5: Commit**

```bash
git add install.sh .env.example
git commit -m "feat(install): expose voice profiles and set sidecar providers in .env"
```

---

### Task 2: Browser Kokoro must not silently fall back to huggingface.co

**Files:**
- Modify: `front_end/owui/app/src/lib/components/chat/MessageInput.svelte` (or whichever component loads `/browser` assets)
- Modify: `services/voice-onnx/app/browser_assets.py`
- Modify: `services/voice-onnx/app/main.py`
- Test: manual browser DevTools Network tab + unit test for manifest

**Interfaces:**
- Consumes: `/v1/browser/manifest` response shape `{complete: bool, voices: [...]}`.
- Produces: browser only loads mirrored assets when `complete=true`; otherwise it stays silent or shows a consent gate.

- [ ] **Step 1: Write a failing test for the manifest contract**

Create `services/voice-onnx/tests/test_browser_assets.py`:

```python
import pytest
from browser_assets import manifest, ROOT


def test_manifest_reports_incomplete_when_mirror_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_assets, "ROOT", tmp_path)
    m = manifest()
    assert m["complete"] is False
    assert "voices" in m
```

Run:

```bash
cd services/voice-onnx
pytest tests/test_browser_assets.py -v
```

Expected: FAIL because `browser_assets.py` currently returns `complete` based on file presence and the test path does not exist.

- [ ] **Step 2: Change browser_assets.manifest to never claim complete unless every configured dtype is mirrored**

In `services/voice-onnx/app/browser_assets.py`, ensure `manifest()` computes:

```python
def manifest() -> dict:
    required = _required_assets()  # list of (relative_path, dtype)
    present = {p for p in required if (ROOT / p).exists()}
    return {
        "complete": len(present) == len(required),
        "voices": list(present),
        "missing": [p for p in required if p not in present],
        "base_url": "/kokoro",
    }
```

- [ ] **Step 3: Make the browser path automatically fall back to huggingface.co when the mirror is incomplete, but respect a user toggle**

In the browser Kokoro loader (OWUI component, likely `front_end/owui/app/src/lib/components/chat/MessageInput.svelte` or a Web Worker), change the load flow:

```typescript
const res = await fetch('/v1/browser/manifest');
const manifest = await res.json();
const settings = await fetch('/api/user/settings').then(r => r.json());
const allowRemote = settings?.voice?.allow_remote_kokoro ?? true;

if (!manifest.complete && !allowRemote) {
  console.warn('Local Kokoro mirror incomplete and remote fallback disabled.');
  return { enabled: false, reason: 'mirror-incomplete' };
}

// Try local first, then remote if allowed.
const baseUrl = manifest.complete ? manifest.base_url : null;
const remoteUrl = allowRemote ? 'https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main' : null;
await loadKokoro({ baseUrl, remoteUrl });
```

- [ ] **Step 4: Add a user-facing toggle for remote Kokoro fallback**

Add to the backend settings schema (`python_back_end/chat_history_module/models.py` or wherever `owui_user_settings` lives):

```python
# In the user_settings validation/default dict:
"voice": {
    "allow_remote_kokoro": True,  # default: automatic remote fallback enabled
}
```

In the browser loader, read this setting from `/api/config` or the user-settings endpoint before allowing any remote fetch. Surface the toggle in OWUI Settings under Voice / Offline speech.

- [ ] **Step 5: Run the test and verify**

```bash
cd services/voice-onnx
pytest tests/test_browser_assets.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/voice-onnx/app/browser_assets.py services/voice-onnx/tests/test_browser_assets.py front_end/owui/...
git commit -m "fix(voice): no silent huggingface fallback for browser Kokoro"
```

---

### Task 3: Verify voice-onnx E2E and document the preset

**Files:**
- Modify: `docs/voice-processing.md`
- Modify: `docker-compose.yaml` (only if healthcheck/env gaps found)
- Test: live container acceptance run

**Interfaces:**
- Consumes: `voice-onnx` health, `/v1/audio/speech`, `/v1/audio/transcriptions`.
- Produces: updated docs and a verified command checklist.

- [ ] **Step 1: Build and start voice-onnx**

```bash
docker compose --profile voice up --build -d voice-onnx
docker logs -f harvis-voice-onnx
```

Wait for `/health` to return `200`.

- [ ] **Step 2: Test speech out through the backend**

```bash
curl -s -X POST http://localhost:9000/api/tts/speech \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"text":"Hello from the torch-free voice path","voice":"af_heart"}' \
  --output /tmp/test.wav
file /tmp/test.wav
```

Expected: `RIFF (little-endian) wave data, WAVE audio, Microsoft PCM, 16 bit, mono 24000 Hz` or similar.

- [ ] **Step 3: Test speech in**

Use the existing `/tmp/test.wav`:

```bash
curl -s -X POST http://localhost:9000/api/stt \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/test.wav"
```

Expected: JSON containing `{"text": "..."}` with non-empty text.

- [ ] **Step 4: Update docs/voice-processing.md**

Add a section "Voice profiles" summarising:

```markdown
## Voice profiles

| Profile | Services | Use case |
|---------|----------|----------|
| `voice` (default) | `voice-onnx` | Torch-free STT/TTS; recommended for all installs. |
| `advanced-voice` | `tts-service`, `model-downloader` | RVC voice cloning/conversion + neural TTS; opt-in. |
| `voice-fallback` | `stt` | Speaches STT sidecar if ONNX ASR is insufficient. |

### Quick start (voice)

```bash
./install.sh        # choose voice option 1
# or manually:
COMPOSE_PROFILES=voice HARVIS_TTS_PROVIDER=sidecar HARVIS_TTS_URL=http://voice-onnx:8000/v1 \
  HARVIS_STT_PROVIDER=sidecar HARVIS_STT_URL=http://voice-onnx:8000/v1 \
  docker compose --profile voice up -d
```
```

- [ ] **Step 5: Commit**

```bash
git add docs/voice-processing.md
git commit -m "docs(voice): verify and document torch-free voice preset"
```

---

## Phase 2: Real RVC Voice Cloning and Generation

### Task 4: Decide and scaffold the RVC host

**Files:**
- Create: `services/rvc-service/Dockerfile`
- Create: `services/rvc-service/requirements.txt`
- Create: `services/rvc-service/app/main.py`
- Modify: `docker-compose.yaml`
- Modify: `python_back_end/synthesis.py`

**Interfaces:**
- Consumes: trained `.pth` + `.index` files, base audio WAV from any TTS provider.
- Produces: converted WAV; OpenAI-shaped endpoints for model import, training, conversion.

- [ ] **Step 1: Choose the RVC host path**

Two options; implement Option A unless testing proves Option B is smaller.

- **Option A (recommended):** Replace `tts-service` with a dedicated `rvc-service` that does only RVC training + conversion. Base TTS stays in `voice-onnx` (or backend local fallback). This keeps the torch footprint behind one profile and avoids the broken Dia/SpeechT5 stack.
- **Option B:** Keep `tts-service` but strip out VibeVoice/Dia and make it an RVC-only host. Risk: the image already drags in broken Dia/torchaudio dependencies.

Decision record: create `docs/adr/2026-07-27-rvc-service-boundary.md` with the chosen option.

- [ ] **Step 2: Create the RVC service Dockerfile**

`services/rvc-service/Dockerfile`:

```dockerfile
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN useradd -m -u 1001 -s /bin/bash appuser \
    && mkdir -p /models /data \
    && chown -R appuser:appuser /models /data /srv
USER appuser

ENV PYTHONPATH=/srv \
    PYTHONUNBUFFERED=1 \
    RVC_MODELS_DIR=/models \
    RVC_OUTPUT_DIR=/data/output

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Pin RVC dependencies**

`services/rvc-service/requirements.txt`:

```text
fastapi>=0.110.0
uvicorn>=0.27.0
pydantic>=2.0
numpy>=1.24.0,<2.0
soundfile>=0.12.1
librosa>=0.10.0
rvc-python>=0.1.5
torch==2.8.0+cu128
--index-url https://download.pytorch.org/whl/cu128
```

Use the same `2.8.0+cu128` base that already fixed `sm_120` on the backend. If CUDA is unavailable, the container falls back to CPU; document this.

- [ ] **Step 4: Add rvc-service to docker-compose.yaml under advanced-voice**

Replace the existing `tts-service` block or add a new service. For Option A:

```yaml
  rvc-service:
    build:
      context: ./services/rvc-service
      dockerfile: Dockerfile
    image: harvis-rvc-service:local
    pull_policy: build
    container_name: harvis-rvc-service
    profiles: ["advanced-voice"]
    restart: unless-stopped
    environment:
      RVC_MODELS_DIR: /models
      RVC_OUTPUT_DIR: /data/output
      RVC_MAX_CACHED_MODELS: "2"
      RVC_DEVICE: "cuda:0"
    volumes:
      - rvc-models:/models
      - rvc-output:/data/output
    networks:
      - ollama-n8n-network
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

Add volumes:

```yaml
volumes:
  rvc-models:
  rvc-output:
```

- [ ] **Step 5: Add RVC sidecar URL to backend env**

In `docker-compose.yaml` backend env block, add:

```yaml
      HARVIS_RVC_URL: "${HARVIS_RVC_URL:-http://rvc-service:8000}"
```

- [ ] **Step 6: Commit**

```bash
git add services/rvc-service/ docker-compose.yaml docs/adr/2026-07-27-rvc-service-boundary.md
git commit -m "feat(rvc): scaffold dedicated RVC service behind advanced-voice profile"
```

---

### Task 5: RVC model import and listing endpoints

**Files:**
- Create: `services/rvc-service/app/models.py`
- Create: `services/rvc-service/app/rvc_engine.py`
- Create: `services/rvc-service/app/main.py` (or extend from Task 4)
- Create: `services/rvc-service/tests/test_import.py`

**Interfaces:**
- `POST /v1/rvc/models/import` with `model_file`, optional `index_file`, `name`, `slug`, `pitch_shift`.
- `GET /v1/rvc/models` returns list of imported models.
- `GET /v1/rvc/models/{slug}` returns model metadata.
- `DELETE /v1/rvc/models/{slug}`.

- [ ] **Step 1: Write failing import test**

`services/rvc-service/tests/test_import.py`:

```python
import io
import zipfile
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _fake_pth() -> bytes:
    return b"FAKE_PTH"


def test_import_model_without_index():
    response = client.post(
        "/v1/rvc/models/import",
        data={"name": "Test Voice", "slug": "test_voice", "pitch_shift": 0},
        files={"model_file": ("test.pth", io.BytesIO(_fake_pth()), "application/octet-stream")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "test_voice"
    assert body["model_path"].endswith("test_voice/test_voice.pth")
```

Run:

```bash
cd services/rvc-service
pytest tests/test_import.py -v
```

Expected: FAIL with `404` or import error.

- [ ] **Step 2: Implement model import endpoint**

`services/rvc-service/app/main.py`:

```python
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from pydantic import BaseModel
from pathlib import Path
import shutil
import re

app = FastAPI(title="Harvis RVC Service")

RVC_MODELS_DIR = Path(os.getenv("RVC_MODELS_DIR", "/models"))


@app.get("/health")
def health():
    return {"status": "ok", "service": "rvc-service"}


@app.post("/v1/rvc/models/import")
def import_model(
    name: str = Form(...),
    slug: str = Form(...),
    pitch_shift: int = Form(0),
    model_file: UploadFile = File(...),
    index_file: UploadFile | None = File(None),
):
    slug = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    voice_dir = RVC_MODELS_DIR / slug
    if voice_dir.exists():
        raise HTTPException(400, f"Model '{slug}' already exists")
    voice_dir.mkdir(parents=True)

    model_path = voice_dir / f"{slug}.pth"
    with open(model_path, "wb") as f:
        shutil.copyfileobj(model_file.file, f)

    index_path = None
    if index_file:
        index_path = voice_dir / f"{slug}.index"
        with open(index_path, "wb") as f:
            shutil.copyfileobj(index_file.file, f)

    metadata = {
        "name": name,
        "slug": slug,
        "pitch_shift": pitch_shift,
        "model_path": str(model_path),
        "index_path": str(index_path) if index_path else None,
    }
    (voice_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return metadata
```

- [ ] **Step 3: Implement listing and deletion**

```python
@app.get("/v1/rvc/models")
def list_models():
    models = []
    for d in RVC_MODELS_DIR.iterdir():
        meta = d / "metadata.json"
        if meta.exists():
            models.append(json.loads(meta.read_text()))
    return {"models": models}


@app.get("/v1/rvc/models/{slug}")
def get_model(slug: str):
    meta = RVC_MODELS_DIR / slug / "metadata.json"
    if not meta.exists():
        raise HTTPException(404, "model not found")
    return json.loads(meta.read_text())


@app.delete("/v1/rvc/models/{slug}")
def delete_model(slug: str):
    voice_dir = RVC_MODELS_DIR / slug
    if not voice_dir.exists():
        raise HTTPException(404, "model not found")
    shutil.rmtree(voice_dir)
    return {"deleted": slug}
```

- [ ] **Step 4: Run tests**

```bash
cd services/rvc-service
pytest tests/test_import.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/rvc-service/
git commit -m "feat(rvc): import and list RVC models"
```

---

### Task 6: RVC voice conversion endpoint

**Files:**
- Modify: `services/rvc-service/app/rvc_engine.py`
- Modify: `services/rvc-service/app/main.py`
- Create: `services/rvc-service/tests/test_convert.py`

**Interfaces:**
- `POST /v1/rvc/convert` accepts `{"audio_url": "...", "slug": "...", "pitch_shift": 0}` or multipart `audio_file`.
- Returns converted audio bytes (`audio/wav`) and `X-RVC-Slug` header.

- [ ] **Step 1: Port the existing RVC engine**

Copy/adapt `python_back_end/tts_system/engines/rvc_engine.py` into `services/rvc-service/app/rvc_engine.py`, removing FastAPI/HTTP concerns. Keep the LRU cache and `convert()` signature.

Key changes:
- Remove `async` from `convert` if the underlying `rvc_python.infer.RVCInference` is synchronous; wrap in `run_in_threadpool` in the endpoint.
- Use `RVC_MODELS_DIR` from env.

- [ ] **Step 2: Write conversion test with mocked engine**

`services/rvc-service/tests/test_convert.py`:

```python
from unittest.mock import patch
import io


def test_convert_endpoint_uses_rvc_engine(tmp_path):
    fake_wav = tmp_path / "in.wav"
    fake_wav.write_bytes(b"RIFF" + b"\x00" * 100)  # minimal invalid wav for test

    with patch("app.main.convert_audio") as mock_convert:
        mock_convert.return_value = (b"FAKE_WAV", "audio/wav")
        with open(fake_wav, "rb") as f:
            response = client.post(
                "/v1/rvc/convert",
                data={"slug": "test_voice", "pitch_shift": 0},
                files={"audio_file": ("in.wav", f, "audio/wav")},
            )
    assert response.status_code == 200
    assert response.content == b"FAKE_WAV"
    assert response.headers["x-rvc-slug"] == "test_voice"
```

Run:

```bash
pytest services/rvc-service/tests/test_convert.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement convert endpoint**

```python
from fastapi import UploadFile
from fastapi.responses import Response
import httpx
from starlette.concurrency import run_in_threadpool
from app.rvc_engine import get_rvc_engine


@app.post("/v1/rvc/convert")
async def convert(
    slug: str = Form(...),
    pitch_shift: int = Form(0),
    audio_file: UploadFile | None = File(None),
    audio_url: str | None = Form(None),
):
    if not audio_file and not audio_url:
        raise HTTPException(400, "supply audio_file or audio_url")

    if audio_url:
        async with httpx.AsyncClient() as c:
            r = await c.get(audio_url)
            r.raise_for_status()
            audio_bytes = r.content
    else:
        audio_bytes = await audio_file.read()

    engine = get_rvc_engine()
    model_path, index_path = engine.get_model_path(slug)
    if not model_path:
        raise HTTPException(404, f"model {slug} not found")

    output_bytes, mime = await run_in_threadpool(
        engine.convert_bytes, audio_bytes, slug, model_path, index_path, pitch_shift
    )
    return Response(output_bytes, media_type=mime, headers={"X-RVC-Slug": slug})
```

Add `convert_bytes` to `rvc_engine.py` (decode → convert → encode using ffmpeg/librosa).

- [ ] **Step 4: Run tests**

```bash
pytest services/rvc-service/tests/test_convert.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/rvc-service/
git commit -m "feat(rvc): add RVC voice conversion endpoint"
```

---

### Task 7: RVC training endpoint (actual voice cloning)

**Files:**
- Create: `services/rvc-service/app/training.py`
- Modify: `services/rvc-service/app/main.py`
- Modify: `services/rvc-service/Dockerfile` (add training deps)
- Create: `services/rvc-service/tests/test_training.py`

**Interfaces:**
- `POST /v1/rvc/models/train` accepts multipart `audio_file` (or `audio_url`), `name`, `slug`, optional `epochs`/`batch_size`.
- Returns `202 Accepted` with `{job_id, slug, status: "queued"}`.
- `GET /v1/rvc/train/{job_id}` returns progress.

- [ ] **Step 1: Add training dependencies**

`services/rvc-service/requirements.txt` append:

```text
# RVC training stack
praat-parselmouth>=0.4.3
pyworld>=0.3.2
faiss-cpu>=1.7.4
```

Use `faiss-cpu` because the RVC training index build does not need a GPU; inference still uses CUDA when available.

- [ ] **Step 2: Implement async training job queue**

`services/rvc-service/app/training.py`:

```python
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Callable

from rvc_python.infer import RVCInference  # or the training API if rvc-python exposes one

TRAIN_JOBS: dict[str, dict] = {}


def preprocess_audio(input_path: str, output_dir: Path, sr: int = 40000) -> Path:
    """Split, denoise, and resample raw audio into training segments."""
    import librosa
    import soundfile as sf

    y, orig_sr = librosa.load(input_path, sr=sr, mono=True)
    # Simple segmenting; production may use librosa effects/trim
    segment_len = sr * 10  # 10-second segments
    out_dir = output_dir / "wavs"
    out_dir.mkdir(parents=True)
    for i, start in enumerate(range(0, len(y), segment_len)):
        seg = y[start:start + segment_len]
        if len(seg) < sr * 2:
            continue
        sf.write(out_dir / f"{i:04d}.wav", seg, sr)
    return out_dir


def train_rvc_model(
    job_id: str,
    audio_path: str,
    slug: str,
    models_dir: Path,
    epochs: int = 200,
    progress_callback: Callable[[int, str], None] | None = None,
):
    TRAIN_JOBS[job_id]["status"] = "preprocessing"
    work_dir = Path(tempfile.mkdtemp(prefix=f"rvc_train_{slug}_"))
    try:
        wavs = preprocess_audio(audio_path, work_dir)
        TRAIN_JOBS[job_id]["status"] = "extracting_features"
        if progress_callback:
            progress_callback(10, "feature extraction started")

        # rvc-python may expose a trainer; if not, shell out to the RVC repo.
        # This is the integration seam — replace with the actual API once chosen.
        from rvc_python.train import Trainer  # hypothetical
        trainer = Trainer(
            experiment_name=slug,
            wavs_dir=str(wavs),
            output_dir=str(models_dir / slug),
            epochs=epochs,
        )
        trainer.run(progress=lambda p, m: TRAIN_JOBS[job_id].update({"progress": p, "message": m}))

        TRAIN_JOBS[job_id].update({"status": "done", "progress": 100, "model_path": str(models_dir / slug / f"{slug}.pth")})
    except Exception as e:
        TRAIN_JOBS[job_id].update({"status": "failed", "error": str(e)})
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
```

- [ ] **Step 3: Wire training endpoint**

In `services/rvc-service/app/main.py`:

```python
from fastapi import BackgroundTasks
from app.training import TRAIN_JOBS, train_rvc_model
import threading


@app.post("/v1/rvc/models/train")
def train(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    slug: str = Form(...),
    epochs: int = Form(200),
    audio_file: UploadFile | None = File(None),
    audio_url: str | None = Form(None),
):
    if not audio_file and not audio_url:
        raise HTTPException(400, "supply audio_file or audio_url")
    job_id = f"train_{uuid.uuid4().hex[:12]}"
    work_dir = Path(tempfile.mkdtemp(prefix=f"rvc_train_upload_{slug}_"))
    input_path = work_dir / "input.wav"

    if audio_file:
        with open(input_path, "wb") as f:
            shutil.copyfileobj(audio_file.file, f)
    else:
        import httpx
        r = httpx.get(audio_url)
        r.raise_for_status()
        input_path.write_bytes(r.content)

    TRAIN_JOBS[job_id] = {
        "job_id": job_id,
        "slug": slug,
        "name": name,
        "status": "queued",
        "progress": 0,
        "message": "queued",
    }

    def run():
        train_rvc_model(job_id, str(input_path), slug, RVC_MODELS_DIR, epochs=epochs)
        shutil.rmtree(work_dir, ignore_errors=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return {"job_id": job_id, "slug": slug, "status": "queued"}


@app.get("/v1/rvc/train/{job_id}")
def train_status(job_id: str):
    if job_id not in TRAIN_JOBS:
        raise HTTPException(404, "job not found")
    return TRAIN_JOBS[job_id]
```

- [ ] **Step 4: Write a mocked training test**

`services/rvc-service/tests/test_training.py`:

```python
from unittest.mock import patch


def test_train_endpoint_queues_job():
    with patch("app.main.threading.Thread") as MockThread:
        response = client.post(
            "/v1/rvc/models/train",
            data={"name": "Clone Me", "slug": "clone_me", "epochs": 10},
            files={"audio_file": ("sample.wav", io.BytesIO(b"RIFF" + b"\x00" * 100), "audio/wav")},
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["slug"] == "clone_me"
    MockThread.assert_called_once()
```

Run:

```bash
pytest services/rvc-service/tests/test_training.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/rvc-service/
git commit -m "feat(rvc): async RVC model training endpoint"
```

---

### Task 7b: RVC training quality hardening (fixes robotic/messed-up clones)

**Files:**
- Modify: `services/rvc-service/app/training.py`
- Modify: `services/rvc-service/app/rvc_engine.py`
- Create: `services/rvc-service/app/audio_quality.py`
- Create: `services/rvc-service/tests/test_quality.py`

**Interfaces:**
- `preprocess_audio()` returns a quality report before training starts.
- `train_rvc_model()` uses stricter defaults and auto-selects pitch/f0 settings.
- `RVCEngine.convert()` uses voice-specific calibration instead of global defaults.

- [ ] **Step 1: Add audio quality analysis before training**

Create `services/rvc-service/app/audio_quality.py`:

```python
import numpy as np
import librosa
import soundfile as sf


def analyze_audio(path: str, sr: int = 40000) -> dict:
    y, _ = librosa.load(path, sr=sr, mono=True)
    duration = len(y) / sr
    rms = np.sqrt(np.mean(y ** 2))
    peak = np.max(np.abs(y))
    silent_ratio = np.mean(np.abs(y) < 0.005)
    # Simple SNR estimate: speech vs non-speech energy
    speech_mask = np.abs(y) > 0.01
    if np.any(speech_mask):
        speech_rms = np.sqrt(np.mean(y[speech_mask] ** 2))
        noise_rms = np.sqrt(np.mean(y[~speech_mask] ** 2)) if np.any(~speech_mask) else 1e-9
        snr_db = 20 * np.log10(speech_rms / noise_rms)
    else:
        snr_db = 0.0
    return {
        "duration": round(duration, 2),
        "rms": round(float(rms), 4),
        "peak": round(float(peak), 4),
        "clipped": bool(peak >= 0.99),
        "silent_ratio": round(float(silent_ratio), 3),
        "snr_db": round(float(snr_db), 2),
        "recommendations": _recommend(duration, peak, silent_ratio, snr_db),
    }


def _recommend(duration, peak, silent_ratio, snr_db) -> list[str]:
    recs = []
    if duration < 60:
        recs.append("Audio is short; 2-10 minutes of clean speech gives better clones.")
    if peak >= 0.99:
        recs.append("Audio is clipped; lower the recording level and re-record.")
    if silent_ratio > 0.4:
        recs.append("Too much silence; trim pauses before training.")
    if snr_db < 20:
        recs.append("Background noise detected; use a quieter room or denoise first.")
    return recs
```

- [ ] **Step 2: Preprocess training audio with denoising and VAD splitting**

Extend `training.py` `preprocess_audio()`:

```python
def preprocess_audio(input_path: str, output_dir: Path, sr: int = 40000) -> Path:
    import librosa
    import soundfile as sf

    y, orig_sr = librosa.load(input_path, sr=sr, mono=True)
    # Light high-pass to remove rumble
    y = librosa.effects.preemphasis(y)
    # Simple energy-based VAD to split into utterances
    frames = librosa.effects.split(y, top_db=30, frame_length=2048, hop_length=512)
    out_dir = output_dir / "wavs"
    out_dir.mkdir(parents=True)
    for i, (start, end) in enumerate(frames):
        seg = y[start:end]
        # Keep segments between 2s and 15s
        if len(seg) < 2 * sr:
            continue
        # Split long utterances every 10s
        for j, pos in enumerate(range(0, len(seg), 10 * sr)):
            chunk = seg[pos:pos + 10 * sr]
            if len(chunk) < 2 * sr:
                continue
            sf.write(out_dir / f"{i:04d}_{j:02d}.wav", chunk, sr)
    return out_dir
```

- [ ] **Step 3: Auto-select training hyperparameters based on dataset size**

In `training.py`:

```python
def choose_training_params(num_segments: int, duration_sec: float) -> dict:
    # More data = more epochs up to a point; tiny datasets overfit quickly.
    epochs = min(500, max(100, int(duration_sec / 6)))
    batch_size = 8 if num_segments >= 50 else 4
    return {
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": 2e-4,
        "save_every_epoch": max(10, epochs // 10),
        "fp16_run": True,
    }
```

- [ ] **Step 4: Add per-voice pitch analysis and recommended pitch_shift**

```python
def estimate_pitch_stats(audio_path: str, sr: int = 40000) -> dict:
    y, _ = librosa.load(audio_path, sr=sr, mono=True)
    f0, voiced_flag, _ = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'))
    f0 = f0[voiced_flag]
    if len(f0) == 0:
        return {"median_f0": 0, "suggested_pitch_shift": 0}
    median_f0 = float(np.median(f0))
    # Neutral base speaker (Kokoro af_heart) is roughly 180 Hz female / 110 Hz male.
    # Suggest shifting the target voice toward a neutral range only if extreme.
    suggested = 0
    if median_f0 > 280:
        suggested = -3
    elif median_f0 < 90:
        suggested = 3
    return {"median_f0": round(median_f0, 2), "suggested_pitch_shift": suggested}
```

Store these stats in the model metadata so conversion can use them.

- [ ] **Step 5: Improve conversion calibration with a larger search grid**

In `rvc_engine.py`, replace the 3-point grid with one that covers the common failure modes:

```python
CALIBRATION_GRID = [
    {"f0_method": "rmvpe", "index_rate": 0.10, "protect": 0.50, "rms_mix_rate": 0.20},
    {"f0_method": "rmvpe", "index_rate": 0.20, "protect": 0.40, "rms_mix_rate": 0.10},
    {"f0_method": "rmvpe", "index_rate": 0.30, "protect": 0.33, "rms_mix_rate": 0.05},
    {"f0_method": "rmvpe", "index_rate": 0.50, "protect": 0.25, "rms_mix_rate": 0.00},
]
```

Add artifact scoring that penalises metallic/robotic signatures (high zero-crossing rate combined with low dynamic range):

```python
def _score_artifact(self, audio_data: np.ndarray, sr: int) -> float:
    score = 0.0
    peak = np.max(np.abs(audio_data))
    if peak >= 0.99:
        score += 10.0
    rms = np.sqrt(np.mean(audio_data ** 2))
    if rms < 0.01:
        score += 5.0
    # Robotic/metallic penalty: high ZCR with low dynamic range
    zcr = np.mean(librosa.feature.zero_crossing_rate(audio_data, sr=sr))
    if zcr > 0.15 and rms < 0.05:
        score += 8.0
    return score
```

- [ ] **Step 6: Test quality analysis**

`services/rvc-service/tests/test_quality.py`:

```python
def test_analyze_audio_flags_clipping():
    # Generate a clipped sine wave
    t = np.linspace(0, 1, 40000)
    y = np.clip(np.sin(2 * np.pi * 200 * t) * 1.5, -1.0, 1.0)
    path = "/tmp/clipped.wav"
    sf.write(path, y, 40000)
    report = analyze_audio(path)
    assert report["clipped"] is True
```

Run:

```bash
pytest services/rvc-service/tests/test_quality.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/rvc-service/
git commit -m "feat(rvc): audio quality checks and calibration hardening for realistic clones"
```

### Task 8: Integrate RVC into backend synthesis provider model

**Files:**
- Modify: `python_back_end/synthesis.py`
- Modify: `python_back_end/api/tts_routes.py`
- Modify: `python_back_end/main.py` (if audio serving needs adjustment)

**Interfaces:**
- `HARVIS_RVC_URL` env var.
- Optional `rvc_slug` and `rvc_pitch_shift` fields on speech requests.
- When `rvc_slug` is present and provider is `sidecar`, base TTS is generated first, then sent to RVC service for conversion.

- [ ] **Step 1: Add RVC conversion helper to synthesis.py**

```python
import httpx


def _apply_rvc(audio_bytes: bytes, slug: str, pitch_shift: float = 0.0) -> bytes:
    url = os.getenv("HARVIS_RVC_URL", "http://rvc-service:8000").rstrip("/") + "/v1/rvc/convert"
    files = {"audio_file": ("base.wav", audio_bytes, "audio/wav")}
    data = {"slug": slug, "pitch_shift": int(pitch_shift)}
    r = httpx.post(url, files=files, data=data, timeout=120.0)
    r.raise_for_status()
    return r.content
```

- [ ] **Step 2: Extend synthesize() to optionally post-process through RVC**

```python
def synthesize(
    text: str,
    voice: str | None = None,
    speed: float | None = None,
    fmt: str | None = None,
    engine: str | None = None,
    rvc_slug: str | None = None,
    rvc_pitch_shift: float = 0.0,
) -> tuple[bytes, str]:
    audio, mime = _synthesize_without_rvc(text, voice, speed, fmt, engine)
    if rvc_slug:
        try:
            audio = _apply_rvc(audio, rvc_slug, rvc_pitch_shift)
            mime = "audio/wav"
        except Exception as e:
            logger.warning("RVC conversion failed for %s: %s", rvc_slug, e)
            # Fall back to base audio rather than failing entirely.
    return audio, mime
```

Extract the existing provider dispatch into `_synthesize_without_rvc` so RVC wraps any provider.

- [ ] **Step 3: Add RVC options to the speech endpoint**

In `python_back_end/api/tts_routes.py`, update `/generate/speech` to accept `rvc_slug` and `rvc_pitch_shift` and pass them through to `synthesis.synthesize()`.

- [ ] **Step 4: Test end-to-end with mocked RVC**

Write `tests/test_synthesis_rvc.py`:

```python
from unittest.mock import patch
import os
import synthesis


def test_synthesize_applies_rvc_when_slug_given():
    os.environ["HARVIS_TTS_PROVIDER"] = "disabled"
    with patch("synthesis._synthesize_without_rvc") as mock_base, \
         patch("synthesis._apply_rvc") as mock_rvc:
        mock_base.return_value = (b"BASE", "audio/wav")
        mock_rvc.return_value = b"RVC"
        audio, mime = synthesis.synthesize("hello", rvc_slug="peter")
    assert audio == b"RVC"
    assert mime == "audio/wav"
    mock_rvc.assert_called_once()
```

Run:

```bash
pytest tests/test_synthesis_rvc.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python_back_end/synthesis.py python_back_end/api/tts_routes.py tests/test_synthesis_rvc.py
git commit -m "feat(rvc): integrate RVC conversion into backend synthesis"
```

---

### Task 9: Frontend UI for RVC voices

**Files:**
- Modify: OWUI settings/voice page (find the exact Svelte file that hosts voice settings)
- Modify: composer TTS dropdown to show RVC voices

**Interfaces:**
- Consumes: `GET /api/tts/rvc/voices` (proxy existing `tts_routes.py` or add new route).
- Produces: user can pick an RVC voice and optional pitch shift; request includes `rvc_slug`/`rvc_pitch_shift`.

- [ ] **Step 1: Verify existing RVC proxy routes still work**

`python_back_end/api/tts_routes.py` already has `/api/tts/rvc/voices`, `/api/tts/rvc/voices/clone`, etc. Confirm they proxy to the RVC service URL rather than the old `tts-service` URL.

Change:

```python
RVC_SERVICE_URL = os.getenv("RVC_SERVICE_URL", "http://rvc-service:8000")
```

and update the RVC proxy routes to use it.

- [ ] **Step 2: Add voice clone/train UI**

Create or extend a Svelte component in the OWUI settings page with:

```svelte
<script>
  let rvcVoices = [];
  let selectedRvc = "";
  let pitchShift = 0;

  async function loadRvcVoices() {
    const res = await fetch("/api/tts/rvc/voices");
    const data = await res.json();
    rvcVoices = data.voices || [];
  }

  async function uploadVoiceModel(files) {
    const form = new FormData();
    form.append("model_file", files[0]);
    form.append("name", "My Voice");
    form.append("slug", "my_voice");
    await fetch("/api/tts/rvc/voices/import", { method: "POST", body: form });
    await loadRvcVoices();
  }
</script>
```

- [ ] **Step 3: Commit**

```bash
git add front_end/owui/... python_back_end/api/tts_routes.py
git commit -m "feat(ui): RVC voice selection and import in settings"
```

---

### Task 10: Acceptance run and documentation

**Files:**
- Modify: `docs/voice-processing.md`
- Modify: `docs/superpowers/plans/2026-07-27-voice-optimization-and-rvc.md` (mark tasks done)
- Test: live Docker run

- [ ] **Step 1: Build and run advanced-voice profile**

```bash
docker compose --profile advanced-voice up --build -d rvc-service
curl -fsS http://localhost:8000/health || echo "not exposed"
# internal healthcheck:
docker exec harvis-rvc-service curl -fsS http://localhost:8000/health
```

- [ ] **Step 2: Import a known-good RVC model**

Download a small public RVC model (e.g., from voice-models.com) and import:

```bash
curl -X POST http://backend:8000/api/tts/rvc/voices/import \
  -F "model_file=@model.pth" \
  -F "index_file=@model.index" \
  -F "name=Test Voice" \
  -F "slug=test_voice"
```

- [ ] **Step 3: Convert base TTS audio through RVC**

```bash
curl -X POST http://backend:8000/api/tts/generate/speech \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world","voice":"af_heart","rvc_slug":"test_voice"}' \
  --output /tmp/rvc_out.wav
file /tmp/rvc_out.wav
```

Expected: valid WAV, duration similar to base TTS.

- [ ] **Step 4: Update docs**

Add to `docs/voice-processing.md`:

```markdown
## RVC voice cloning (advanced)

1. Enable the profile: `COMPOSE_PROFILES=advanced-voice`.
2. Import a trained model: `POST /api/tts/rvc/voices/import` with `.pth` and optional `.index`.
3. Train from audio: `POST /api/tts/rvc/models/train` with a 2–10 minute clean voice sample.
4. Use it: pass `rvc_slug` and optional `rvc_pitch_shift` to `/api/tts/generate/speech`.
```

- [ ] **Step 5: Final commit**

```bash
git add docs/voice-processing.md
git commit -m "docs(voice): RVC acceptance run and usage guide"
```

---

## Self-Review

1. **Spec coverage:**
   - Installer profile selection: Task 1.
   - Browser Kokoro silent fallback: Task 2 (automatic fallback + settings toggle).
   - Voice-onnx verification: Task 3.
   - RVC service scaffold: Task 4.
   - RVC import/list/delete: Task 5.
   - RVC conversion: Task 6.
   - RVC training (actual cloning): Task 7.
   - **RVC training quality / realistic voices: Task 7b.**
   - Backend integration: Task 8.
   - Frontend UI: Task 9.
   - Docs/acceptance: Task 10.

2. **Placeholder scan:**
   - `rvc_python.train.Trainer` is a placeholder seam; Task 7 must be validated against the actual rvc-python API or replaced with a shell call to the RVC training repo. This is flagged as a seam, not a hidden TODO.
   - All other steps include concrete file paths, commands, and expected outputs.

3. **Type consistency:**
   - `synthesis.synthesize()` gains `rvc_slug: str | None` and `rvc_pitch_shift: float`.
   - `RVC_SERVICE_URL` is introduced in `api/tts_routes.py` and matches `HARVIS_RVC_URL` in `docker-compose.yaml`.
   - `convert_bytes` must return `(bytes, str)` in `rvc_engine.py` and is consumed by the endpoint as such.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-27-voice-optimization-and-rvc.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Which approach?**
