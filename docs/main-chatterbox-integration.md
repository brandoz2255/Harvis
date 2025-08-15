# Main and Chatterbox TTS Integration

This document provides an overview of the `main.py` and `chatterbox_tts.py` modules, which form the core of our AI Voice Assistant system. It explains their functionality, integration, and key features.

## Table of Contents
1. [Introduction](#introduction)
2. [Main Module (`main.py`)](#main-module-mainpy)
   - [Overview](#overview)
   - [Key Features](#key-features)
   - [Code Structure](#code-structure)
3. [Chatterbox TTS Module (`chatterbox_tts.py`)](#chatterbox-tts-module-chatterbox_ttspy)
   - [Overview](#overview-1)
   - [Key Features](#key-features-1)
   - [Code Structure](#code-structure-1)
4. [Integration with Other Components](#integration-with-other-components)
5. [Why This Design?](#why-this-design)

## Introduction

The AI Voice Assistant is a comprehensive system that integrates voice recognition, natural language processing, and text-to-speech capabilities to provide an intelligent assistant interface. The core of this system is implemented in two main modules: `main.py` and `chatterbox_tts.py`.

These modules work together to:
- Process user commands via speech
- Generate appropriate responses using a large language model (LLM)
- Convert text responses back to speech
- Integrate with browser automation for web-related tasks

## Main Module (`main.py`)

### Overview

The `main.py` file is the central component of our system. It serves as the entry point and orchestrates all interactions between the different modules. This module:
1. Sets up the FastAPI server
2. Handles HTTP requests and responses
3. Integrates with TTS, STT, LLM, and browser automation components
4. Manages device selection (CPU/GPU)
5. Implements error handling and logging

### Key Features

- **FastAPI Backend**: Provides a RESTful API for interacting with the assistant
- **Device Management**: Automatically selects between CPU and GPU based on availability
- **Model Integration**: Loads and integrates image captioning, TTS, STT, and LLM models
- **Browser Automation**: Handles web navigation and search commands
- **Comprehensive Error Handling**: Catches and logs errors at various levels
- **Configurable Parameters**: Allows customization of response generation through query parameters

### Code Structure

```python
# Import necessary modules and dependencies
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
import uvicorn, os, tempfile, uuid, base64, io, logging, re, requests
import torch, soundfile as sf
from transformers import pipeline
import whisper

# Import local helper functions and classes
from chatterbox_tts import load_tts_model, generate_speech  # TTS functionality

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define paths and constants
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "front_end")
JARVIS_VOICE_PATH = os.path.abspath("jarvis_voice.mp3")

# Initialize FastAPI app
app = FastAPI(title="Jarves-TTS API")

# Set up device and models (CPU/GPU selection)
device = 0 if torch.cuda.is_available() else -1

try:
    image_to_text = pipeline(
        "image-to-text",
        model="Salesforce/blip-image-captioning-base",
        device=device
    )
except Exception as e:
    logger.error("BLIP model failed: %s", e)
    image_to_text = None

# Define configuration constants
OLLAMA_URL = "http://ollama:11434"
DEFAULT_MODEL = "mistral"

# Define Pydantic schemas for request validation
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = DEFAULT_MODEL
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

class ScreenAnalysisRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)

# Define helper functions for command pattern matching
BROWSER_PATTERNS = [...]
is_browser_command = lambda txt: any(re.match(p, txt.lower().strip()) for p in BROWSER_PATTERNS)

# Define API routes/endpoints
@app.get("/", tags=["frontend"])
async def root() -> FileResponse:
    # Serve the frontend

@app.post("/api/chat", tags=["chat"])
async def chat(req: ChatRequest, request: Request):
    # Main conversational endpoint

@app.get("/api/audio/{filename}", tags=["audio"])
async def serve_audio(filename: str):
    # Serve audio files

@app.post("/api/analyze-screen", tags=["vision"])
async def analyze_screen(req: ScreenAnalysisRequest):
    # Analyze screen content from image

@app.post("/api/mic-chat", tags=["voice"])
async def mic_chat(file: UploadFile = File(...)):
    # Process voice input from microphone

# Load models once at startup
whisper_model = whisper.load_model("base")

# Warmup and preload models
try:
    _ = load_tts_model()
    _ = whisper.load_model("base")
    _ = pipeline("image-to-text", model="Salesforce/blip-image-captioning-base", device=device)
except Exception as e:
    logger.error("Preload failed: %s", e)

# Start the server
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
```

## Chatterbox TTS Module (`chatterbox_tts.py`)

### Overview

The `chatterbox_tts.py` file is responsible for implementing the text-to-speech (TTS) functionality of our system. It:
1. Manages VRAM usage to optimize GPU performance
2. Loads and configures the Chatterbox TTS model
3. Generates speech from text with various customization options

### Key Features

- **VRAM Management**: Monitors and optimizes GPU memory usage
- **Model Loading**: Handles both CPU and GPU model loading with fallbacks
- **Speech Generation**: Converts text to speech with configurable parameters
- **Error Handling**: Manages CUDA errors and provides fallback mechanisms

### Code Structure

```python
from chatterbox.tts import ChatterboxTTS, punc_norm
import torch
import logging
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# VRAM Management functions
def get_vram_threshold():
    if not torch.cuda.is_available():
        return float('inf')
    total_mem = torch.cuda.get_device_properties(0).total_memory
    return max(int(total_mem * 0.8), 10 * 1024**3)

THRESHOLD_BYTES = get_vram_threshold()
logger.info(f"VRAM threshold set to {THRESHOLD_BYTES/1024**3:.1f} GiB")

def wait_for_vram(threshold=THRESHOLD_BYTES, interval=0.5):
    if not torch.cuda.is_available():
        return
    used = torch.cuda.memory_allocated()
    while used > threshold:
        logger.info(f"VRAM {used/1024**3:.1f} GiB > {threshold/1024**3:.1f} GiB. Waiting…")
        time.sleep(interval)
        used = torch.cuda.memory_allocated()
    torch.cuda.empty_cache()
    logger.info("VRAM is now below threshold. Proceeding with TTS.")

# Global model variable
tts_model = None

def load_tts_model(force_cpu=False):
    global tts_model
    tts_device = "cuda" if torch.cuda.is_available() and not force_cpu else "cpu"

    if tts_model is None:
        try:
            logger.info(f"Loading TTS model on {tts_device}")
            tts_model = ChatterboxTTS.from_pretrained(device=tts_device)
        except Exception as e:
            if "cuda" in str(e).lower():
                logger.warning(f"CUDA loading failed: {e}. Trying CPU...")
                try:
                    tts_model = ChatterboxTTS.from_pretrained(device="cpu")
                    logger.info("Successfully loaded TTS model on CPU")
                except Exception as e2:
                    logger.error(f"FATAL: Could not load TTS model on CPU either: {e2}")
                    raise
            else:
                logger.error(f"FATAL: Could not load TTS model: {e}")
                raise
    return tts_model

def generate_speech(text, model, audio_prompt=None, exaggeration=0.5,
                   temperature=0.8, cfg_weight=0.5):
    try:
        normalized = punc_norm(text)
        if torch.cuda.is_available():
            try:
                wav = model.generate(
                    normalized,
                    audio_prompt_path=audio_prompt,
                    exaggeration=exaggeration,
                    temperature=temperature,
                    cfg_weight=cfg_weight
                )
            except RuntimeError as e:
                if "CUDA" in str(e):
                    logger.error(f"CUDA Error: {e}")
                    torch.cuda.empty_cache()
                    try:
                        wav = model.generate(
                            normalized,
                            audio_prompt_path=audio_prompt,
                            exaggeration=exaggeration,
                            temperature=temperature,
                            cfg_weight=cfg_weight
                        )
                    except RuntimeError as e2:
                        logger.error(f"CUDA Retry Failed: {e2}")
                        raise ValueError("CUDA error persisted after cache clear") from e2
                else:
                    raise
        else:
            wav = model.generate(
                normalized,
                audio_prompt_path=audio_prompt,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfg_weight,
                device="cpu"
            )
        return (model.sr, wav.squeeze(0).numpy())
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        raise
```

## Integration with Other Components

The `main.py` and `chatterbox_tts.py` modules integrate with other components of the system as follows:

1. **LLM Integration**: The main module communicates with an LLM server (Ollama) to generate responses based on user input.
2. **Browser Automation**: Commands related to browser actions are processed and executed using the browser automation module.
3. **Voice Processing**: Speech-to-text is handled by Whisper, while text-to-speech is managed by Chatterbox TTS.
4. **Frontend Integration**: The FastAPI server serves a frontend interface for user interaction.

## Why This Design?

This design was chosen for several reasons:

1. **Modularity**: By separating concerns into different modules, the code becomes more maintainable and easier to understand.
2. **Scalability**: Each module can be independently scaled or optimized without affecting others.
3. **Flexibility**: Different components can be easily swapped out or upgraded (e.g., using a different TTS model).
4. **Error Handling**: Comprehensive error handling ensures the system remains robust even when individual components fail.
5. **Performance**: Device management and VRAM optimization ensure efficient use of resources, particularly for GPU-intensive tasks.

This architecture allows us to build a powerful AI Voice Assistant that can handle complex interactions while remaining maintainable and scalable.
