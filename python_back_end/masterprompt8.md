# HARVIS Lightweight Podcast Pipeline Integration Guide

## Overview

This guide integrates a lightweight, consumer-friendly TTS pipeline for podcast generation while keeping Chatterbox for interactive voice chat.

### Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          HARVIS TTS SYSTEM                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    INTERACTIVE MODE (existing)                       │   │
│  │                                                                      │   │
│  │    User Chat → Chatterbox (GPU, 6-8GB) → Voice Response             │   │
│  │                                                                      │   │
│  │    Use case: Real-time voice assistant, voice cloning               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    PODCAST MODE (new, lightweight)                   │   │
│  │                                                                      │   │
│  │    Script → Piper (CPU, 0GB VRAM) → RVC (GPU, 2-4GB) → Character    │   │
│  │                                                                      │   │
│  │    Use case: Multi-character podcasts with voice-models.com voices  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  VRAM COMPARISON:                                                           │
│  ├─ Chatterbox alone: ~6-8GB                                               │
│  ├─ Chatterbox + RVC: ~8-12GB (too heavy for consumers)                    │
│  └─ Piper + RVC: ~2-4GB ✅ (works on most gaming GPUs)                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Installation

### 1. Install Dependencies

```bash
# Piper TTS (CPU-based, lightweight)
pip install piper-tts --break-system-packages

# RVC dependencies
pip install fairseq faiss-cpu pyworld torchcrepe praat-parselmouth --break-system-packages

# Optional: For better RVC inference
pip install rvc-python --break-system-packages
```

### 2. Copy New Files

Place these files in your `python_back_end/` directory:

```
python_back_end/
├── tts_engine_manager.py    # Unified TTS manager
├── voice_model_manager.py   # Voice model downloader
├── model_manager.py         # (existing, minor updates)
└── main.py                  # (existing, add new endpoints)
```

### 3. Update model_manager.py

Add these imports and functions to your existing `model_manager.py`:

```python
# Add at top of file
from tts_engine_manager import (
    TTSMode,
    set_mode,
    get_mode,
    generate_speech,
    generate_podcast_segment,
    get_engine_status,
    unload_all_engines,
    load_chatterbox,
    unload_chatterbox,
)

# Add new function for mode-aware speech generation
def generate_speech_smart(
    text: str,
    mode: str = "auto",
    voice_model: Optional[str] = None,
    audio_prompt: Optional[str] = None,
    **kwargs
) -> Tuple[int, Any]:
    """
    Smart speech generation that picks the right engine
    
    Args:
        text: Text to speak
        mode: "interactive", "podcast", "lightweight", or "auto"
        voice_model: RVC model name (for podcast mode)
        audio_prompt: Audio file for cloning (for interactive mode)
    
    Returns:
        (sample_rate, audio_array)
    """
    if mode == "auto":
        # Auto-detect based on context
        if voice_model:
            mode = "podcast"
        elif audio_prompt:
            mode = "interactive"
        else:
            mode = "interactive"  # Default to Chatterbox
    
    mode_map = {
        "interactive": TTSMode.INTERACTIVE,
        "podcast": TTSMode.PODCAST,
        "lightweight": TTSMode.LIGHTWEIGHT
    }
    
    return generate_speech(
        text,
        mode=mode_map.get(mode, TTSMode.INTERACTIVE),
        voice_model=voice_model,
        audio_prompt=audio_prompt,
        **kwargs
    )
```

### 4. Add API Endpoints to main.py

```python
# Add these imports at top
from tts_engine_manager import (
    TTSMode, set_mode, get_mode, generate_speech as tts_generate,
    generate_podcast_segment, get_engine_status, unload_all_engines
)
from voice_model_manager import (
    VoiceModelManager, download_popular_model, POPULAR_MODELS
)

# Initialize voice model manager
voice_manager = VoiceModelManager()

# ─── New API Endpoints ──────────────────────────────────────────────────────

class PodcastSegmentRequest(BaseModel):
    text: str
    character_voice: str
    
class VoiceModelDownloadRequest(BaseModel):
    url: str
    name: Optional[str] = None
    tags: Optional[List[str]] = None

class TTSModeRequest(BaseModel):
    mode: str  # "interactive", "podcast", "lightweight"

@app.post("/api/tts/set-mode", tags=["tts-engine"])
async def api_set_tts_mode(req: TTSModeRequest):
    """Set the TTS generation mode"""
    mode_map = {
        "interactive": TTSMode.INTERACTIVE,
        "podcast": TTSMode.PODCAST,
        "lightweight": TTSMode.LIGHTWEIGHT
    }
    
    if req.mode not in mode_map:
        raise HTTPException(400, f"Invalid mode. Use: {list(mode_map.keys())}")
    
    set_mode(mode_map[req.mode])
    return {"status": "ok", "mode": req.mode}

@app.get("/api/tts/status", tags=["tts-engine"])
async def api_get_tts_status():
    """Get status of all TTS engines"""
    return get_engine_status()

@app.post("/api/podcast/generate-segment", tags=["podcast"])
async def api_generate_podcast_segment(req: PodcastSegmentRequest):
    """Generate a podcast segment with character voice"""
    try:
        sr, audio = generate_podcast_segment(
            req.text,
            req.character_voice,
            voice_models_dir=str(voice_manager.models_dir)
        )
        
        # Save to temp file
        import soundfile as sf
        import uuid
        
        output_path = f"/tmp/podcast_segment_{uuid.uuid4()}.wav"
        sf.write(output_path, audio, sr)
        
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename=f"segment_{req.character_voice}.wav"
        )
        
    except FileNotFoundError as e:
        raise HTTPException(404, f"Voice model not found: {req.character_voice}")
    except Exception as e:
        logger.error(f"Podcast generation failed: {e}")
        raise HTTPException(500, str(e))

@app.get("/api/voice-models/list", tags=["voice-models"])
async def api_list_voice_models(tag: Optional[str] = None):
    """List available voice models"""
    models = voice_manager.list_models(tag=tag)
    return {
        "count": len(models),
        "models": [
            {
                "name": m.name,
                "epochs": m.epochs,
                "size_mb": m.file_size_mb,
                "tags": m.tags,
                "has_index": m.index_path is not None
            }
            for m in models
        ]
    }

@app.get("/api/voice-models/popular", tags=["voice-models"])
async def api_list_popular_models():
    """List pre-configured popular voice models"""
    return {
        "models": list(POPULAR_MODELS.keys()),
        "note": "Use POST /api/voice-models/download-popular/{name} to download"
    }

@app.post("/api/voice-models/download", tags=["voice-models"])
async def api_download_voice_model(req: VoiceModelDownloadRequest):
    """Download a voice model from HuggingFace URL"""
    info = voice_manager.download_model(
        req.url,
        name=req.name,
        tags=req.tags
    )
    
    if info is None:
        raise HTTPException(500, "Download failed")
    
    return {
        "status": "ok",
        "name": info.name,
        "size_mb": info.file_size_mb,
        "epochs": info.epochs
    }

@app.post("/api/voice-models/download-popular/{name}", tags=["voice-models"])
async def api_download_popular_model(name: str):
    """Download a pre-configured popular voice model"""
    if name not in POPULAR_MODELS:
        raise HTTPException(404, f"Unknown model. Available: {list(POPULAR_MODELS.keys())}")
    
    info = download_popular_model(name, voice_manager)
    
    if info is None:
        raise HTTPException(500, "Download failed")
    
    return {
        "status": "ok",
        "name": info.name,
        "size_mb": info.file_size_mb
    }

@app.delete("/api/voice-models/{name}", tags=["voice-models"])
async def api_delete_voice_model(name: str):
    """Delete a voice model"""
    if voice_manager.delete_model(name):
        return {"status": "ok", "deleted": name}
    raise HTTPException(404, f"Model not found: {name}")
```

## Usage Examples

### CLI Usage

```bash
# Download a popular voice model
python voice_model_manager.py popular spongebob

# Download from custom URL
python voice_model_manager.py download "https://huggingface.co/..." --name my_voice

# List all models
python voice_model_manager.py list

# Generate speech in different modes
python tts_engine_manager.py --mode interactive --text "Hello world"
python tts_engine_manager.py --mode podcast --text "Hello world" --voice spongebob
python tts_engine_manager.py --mode lightweight --text "Hello world"
```

### API Usage

```bash
# Set TTS mode to podcast (lighter weight)
curl -X POST http://localhost:8000/api/tts/set-mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "podcast"}'

# Download a voice model
curl -X POST http://localhost:8000/api/voice-models/download-popular/spongebob

# Generate podcast segment
curl -X POST http://localhost:8000/api/podcast/generate-segment \
  -H "Content-Type: application/json" \
  -d '{"text": "Are you ready kids?", "character_voice": "spongebob"}' \
  --output segment.wav

# Check TTS engine status
curl http://localhost:8000/api/tts/status
```

### Python Usage

```python
from tts_engine_manager import TTSMode, set_mode, generate_speech, generate_podcast_segment
from voice_model_manager import VoiceModelManager, download_popular_model

# Initialize
manager = VoiceModelManager()

# Download character voices
download_popular_model("spongebob", manager)
download_popular_model("plankton", manager)

# Generate podcast with character voices
segments = [
    ("Are you ready kids?", "spongebob"),
    ("I went to college!", "plankton"),
]

for text, character in segments:
    sr, audio = generate_podcast_segment(text, character)
    # ... save or concatenate audio
```

## Hardware Requirements

| Mode | Min VRAM | Recommended | CPU |
|------|----------|-------------|-----|
| Interactive (Chatterbox) | 6GB | 8GB+ | Any |
| Podcast (Piper + RVC) | 2GB | 4GB | Modern multi-core |
| Lightweight (Piper only) | 0GB | 0GB | Any |

## Troubleshooting

### "CUDA out of memory" during podcast generation

```python
# Force lightweight mode (CPU only)
from tts_engine_manager import TTSMode, set_mode
set_mode(TTSMode.LIGHTWEIGHT)
```

### RVC conversion quality is poor

1. Ensure you downloaded the .index file with the model
2. Adjust RVC parameters:
   ```python
   from tts_engine_manager import _config
   _config.rvc_index_rate = 0.85  # Higher = more like target voice
   _config.rvc_protect = 0.5     # Higher = preserve more consonants
   ```

### Piper sounds robotic

Try a different Piper voice model:
```python
from tts_engine_manager import _config
_config.piper_model = "en_US-amy-medium"  # More natural
```

## Open Source Licenses

All components are open source:

- **Piper TTS**: MIT License
- **RVC**: MIT License  
- **fairseq**: MIT License
- **HARVIS TTS Engine Manager**: MIT License

## Contributing

PRs welcome! Areas for improvement:

1. Direct RVC inference (eliminate CLI dependency)
2. Streaming audio generation
3. Better voice model search/discovery
4. Audio quality preprocessing
5. Batch podcast generation optimization