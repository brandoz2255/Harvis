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
from model_manager import transcribe_with_whisper_optimized, generate_speech_optimized, reload_models_if_needed

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
        
        # Use VRAM-optimized transcription
        result = transcribe_with_whisper_optimized(tmp_path)
        transcription = result.get("text", "").strip()
        
        # Clean up temp file
        os.remove(tmp_path)
        
        logger.info(f"🎤 Voice transcribed for vibe coding: {transcription}")
        return {"transcription": transcription, "model_used": "whisper-base"}
    except Exception as e:
        logger.error("Voice transcription failed: %s", e)
        raise HTTPException(500, str(e)) from e

@router.post("/api/run-command", tags=["vibe-coding"])
async def run_command(req: RunCommandRequest):
    """
    Execute terminal commands for vibe coding.
    """
    try:
        logger.info(f"🔧 Executing command: {req.command}")
        
        # Security: Enhanced command filtering
        dangerous_commands = ["rm -rf", "sudo", "chmod 777", "mkfs", "dd if=", "format", "fdisk", "sfdisk"]
        dangerous_chars = [";", "&", "|", "`", "$", "$(", ")", ">", "<", ">>"]
        
        # Check for dangerous commands and characters
        command_lower = req.command.lower()
        if any(cmd in command_lower for cmd in dangerous_commands):
            return {"output": "❌ Command blocked for security reasons", "error": True}
        
        if any(char in req.command for char in dangerous_chars):
            return {"output": "❌ Command contains potentially dangerous characters", "error": True}
        
        # Execute command safely without shell=True
        try:
            # Split command into arguments safely
            cmd_args = shlex.split(req.command)
            result = subprocess.run(
                cmd_args,
                shell=False,  # Safer: no shell interpretation
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getcwd()
            )
        except ValueError as e:
            # shlex.split failed - command has invalid syntax
            return {"output": f"❌ Invalid command syntax: {str(e)}", "error": True}
        
        output = result.stdout + result.stderr
        return {"output": output, "error": result.returncode != 0}
        
    except subprocess.TimeoutExpired:
        return {"output": "❌ Command timed out", "error": True}
    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        return {"output": f"❌ Error: {str(e)}", "error": True}

@router.post("/api/save-file", tags=["vibe-coding"])
async def save_file(req: SaveFileRequest):
    """
    Save file content for vibe coding.
    """
    try:
        logger.info(f"💾 Saving file: {req.filename}")
        
        # Security: Basic path validation
        if ".." in req.filename or req.filename.startswith("/"):
            return {"success": False, "error": "Invalid filename"}
        
        # Save file in current working directory
        filepath = os.path.join(os.getcwd(), req.filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(req.content)
        
        return {"success": True, "message": f"File {req.filename} saved successfully"}
        
    except Exception as e:
        logger.error(f"File save failed: {e}")
        return {"success": False, "error": str(e)}