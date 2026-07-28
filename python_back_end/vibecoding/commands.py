"""Vibe Commands Router Module

This module contains the FastAPI routes for vibe command processing,
extracted from main.py to keep the vibe coding logic organized.
"""

import os
import uuid
import tempfile
import soundfile as sf
import shlex
import subprocess
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging

from .core import get_vibe_agent, execute_vibe_coding_with_model_management
from model_manager import generate_speech_optimized, reload_models_if_needed
from transcription import TranscriptionUnavailable, transcribe as transcribe_audio

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vibe-commands"])

# Constants
HARVIS_VOICE_PATH = os.path.join(os.path.dirname(__file__), "..", "harvis_voice.mp3")
DEFAULT_MODEL = "mistral"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
API_KEY = os.getenv("API_KEY", "key")

# Request models
class VibeCommandRequest(BaseModel):
    command: str
    mode: str = "assistant"

class VibeCodingRequest(BaseModel):
    message: str
    files: List[Dict[str, Any]] = []
    terminalHistory: List[str] = []
    model: str = DEFAULT_MODEL
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

class RunCommandRequest(BaseModel):
    command: str

class SaveFileRequest(BaseModel):
    filename: str
    content: str

# Command endpoints
@router.post("/api/vibe/command")
async def vibe_command(req: VibeCommandRequest):
    """Process a vibe command with the specified mode."""
    try:
        vibe_agent = get_vibe_agent()
        if vibe_agent is None:
            raise HTTPException(status_code=503, detail="Vibe agent not initialized")
        
        vibe_agent.mode = req.mode
        response_text, _ = vibe_agent.process_command(req.command)
        return {"response": response_text}
    except Exception as e:
        logger.error(f"Vibe command failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/api/ws/vibe")
async def websocket_vibe_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time vibe command processing."""
    await websocket.accept()
    try:
        vibe_agent = get_vibe_agent()
        if vibe_agent is None:
            await websocket.send_json({"type": "error", "content": "Vibe agent not initialized"})
            return
        
        while True:
            data = await websocket.receive_json()
            command = data.get("command")
            mode = data.get("mode", "assistant")
            
            if command:
                vibe_agent.mode = mode
                await vibe_agent.process_command(command, websocket)
            else:
                await websocket.send_json({"type": "error", "content": "No command received"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.send_json({"type": "error", "content": str(e)})

@router.post("/api/vibe-coding", tags=["vibe-coding"])
async def vibe_coding(req: VibeCodingRequest):
    """
    Voice-enabled vibe coding with intelligent model management.
    Unloads models → Executes vibe agent → Generates TTS response → Reloads models.
    """
    try:
        # Execute vibe coding with model management
        vibe_response, steps = await execute_vibe_coding_with_model_management(
            message=req.message,
            files=req.files,
            terminal_history=req.terminalHistory,
            model=req.model,
            ollama_url=OLLAMA_URL,
            api_key=API_KEY
        )
        
        # Generate TTS response
        audio_prompt_path = req.audio_prompt or HARVIS_VOICE_PATH
        if not os.path.isfile(audio_prompt_path):
            audio_prompt_path = None
        
        # Create speech-friendly version of response
        tts_text = vibe_response
        if len(tts_text) > 200:
            tts_text = tts_text[:200] + "... I'm ready to help you code this!"
        
        sr, wav = generate_speech_optimized(
            text=tts_text,
            audio_prompt=audio_prompt_path,
            exaggeration=req.exaggeration,
            temperature=req.temperature,
            cfg_weight=req.cfg_weight,
        )
        
        # Save audio file
        filename = f"vibe_coding_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)
        
        logger.info("✅ Vibe coding complete - all models restored")
        return {
            "response": vibe_response,
            "steps": steps,
            "audio_path": f"/api/audio/{filename}",
            "model_used": req.model,
            "processing_stages": {
                "vibe_agent": "✅ Completed",
                "tts_generation": "✅ Completed"
            }
        }
    except Exception as e:
        logger.error("Vibe coding failed: %s", e)
        # Ensure models are reloaded even on error
        logger.info("🔄 Reloading models after vibe coding error")
        reload_models_if_needed()
        raise HTTPException(500, str(e)) from e

@router.post("/api/voice-transcribe", tags=["vibe-coding"])
async def voice_transcribe(file: UploadFile = File(...), model: str = DEFAULT_MODEL):
    """
    Transcribe voice input for vibe coding with model management.
    """
    try:
        # Save uploaded file to temp
        contents = await file.read()
        tmp_path = os.path.join(tempfile.gettempdir(), f"vibe_{uuid.uuid4()}.wav")
        with open(tmp_path, "wb") as f:
            f.write(contents)
        
        # Whichever provider HARVIS_STT_PROVIDER selects; `local` is the
        # VRAM-optimized in-process Whisper this used to call directly.
        result = transcribe_audio(tmp_path)
        transcription = (result or {}).get("text", "").strip()

        # Clean up temp file
        os.remove(tmp_path)

        logger.info(f"🎤 Voice transcribed for vibe coding: {transcription}")
        return {"transcription": transcription, "model_used": "whisper-base"}
    except TranscriptionUnavailable as e:
        logger.warning("🎤 Voice transcription unavailable: %s", e)
        raise HTTPException(503, str(e)) from e
    except Exception as e:
        logger.error("Voice transcription failed: %s", e)
        raise HTTPException(500, str(e)) from e

@router.post("/api/run-command", tags=["vibe-coding"])
async def run_command(req: RunCommandRequest):
    """DISABLED — superseded by the governed Execution Core.

    This endpoint used to run ``subprocess.run`` on the backend HOST (cwd=os.getcwd())
    with NO authentication, behind a trivially-bypassable string denylist — an
    unauthenticated RCE. It never executes now. Use the governed sandbox shell
    (``/api/harvis/exec``, lane 3) or SSH targets (lane 5). Local host shell (lane 4)
    is parked behind ``HARVIS_EXEC_HOST_SHELL`` and is unimplemented in Execution Core v0.
    """
    host_shell = (os.getenv("HARVIS_EXEC_HOST_SHELL") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not host_shell:
        raise HTTPException(
            status_code=410,
            detail="Host command execution is disabled. Use the governed sandbox shell "
                   "(/api/harvis/exec). Local host shell (lane 4) is parked pending review.",
        )
    raise HTTPException(
        status_code=501,
        detail="Host shell (lane 4) is not implemented in Execution Core v0.",
    )

@router.post("/api/save-file", tags=["vibe-coding"])
async def save_file(req: SaveFileRequest):
    """DISABLED — this wrote arbitrary files to the backend CWD with NO authentication.
    Superseded by the governed workspace file tools (Execution Core lane 2)."""
    raise HTTPException(
        status_code=410,
        detail="Direct file save is disabled. Use the governed workspace file tools.",
    )