"""
Model Management System for GPU Memory Optimization
Handles loading/unloading of TTS, Whisper, and Qwen2VL models
"""

import os
import torch
import logging
import time
import gc
from typing import Optional

# Import model classes
import whisper
from chatterbox.tts import ChatterboxTTS

logger = logging.getLogger(__name__)

# ─── Global Model Variables ─────────────────────────────────────────────────
tts_model = None
whisper_model = None

# ─── VRAM Management ────────────────────────────────────────────────────────
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

# ─── Memory Monitoring ──────────────────────────────────────────────────────
def log_gpu_memory(stage: str):
    """Log current GPU memory usage"""
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        free = total - allocated
        logger.info(f"🔍 GPU Memory {stage}: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved, {free:.2f}GB free")

# ─── Model Loading Functions ────────────────────────────────────────────────
def load_tts_model(force_cpu=False):
    """Load TTS model with memory management"""
    global tts_model
    tts_device = "cuda" if torch.cuda.is_available() and not force_cpu else "cpu"

    if tts_model is None:
        try:
            logger.info(f"🔊 Loading TTS model on device: {tts_device}")
            tts_model = ChatterboxTTS.from_pretrained(device=tts_device)
        except Exception as e:
            if "cuda" in str(e).lower():
                logger.warning(f"⚠️ CUDA load failed: {e}. Falling back to CPU...")
                try:
                    tts_model = ChatterboxTTS.from_pretrained(device="cpu")
                    logger.info("✅ Successfully loaded TTS model on CPU")
                except Exception as e2:
                    logger.error(f"❌ Failed to load TTS model on CPU: {e2}")
                    raise RuntimeError("TTS model loading failed on both CUDA and CPU.") from e2
            else:
                logger.error(f"❌ TTS model loading error: {e}")
                raise
    return tts_model

def load_whisper_model():
    """Load Whisper model with memory management"""
    global whisper_model
    if whisper_model is None:
        logger.info("🔄 Loading Whisper model")
        whisper_model = whisper.load_model("base")
        logger.info("✅ Whisper model loaded successfully")
    return whisper_model

# ─── Model Unloading Functions ──────────────────────────────────────────────
def unload_models():
    """Unload TTS and Whisper models to free GPU memory"""
    global tts_model, whisper_model
    
    log_gpu_memory("before unload")
    
    if tts_model is not None:
        logger.info("🗑️ Unloading TTS model to free GPU memory")
        del tts_model
        tts_model = None
    
    if whisper_model is not None:
        logger.info("🗑️ Unloading Whisper model to free GPU memory")
        del whisper_model
        whisper_model = None
    
    # Aggressive GPU cleanup
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        # Force garbage collection
        gc.collect()
        # Clear cache again after GC
        torch.cuda.empty_cache()
        
    log_gpu_memory("after unload")

def unload_all_models():
    """Unload all models including Qwen2VL to free maximum GPU memory"""
    logger.info("🗑️ Unloading ALL models to free GPU memory for vision processing")
    
    log_gpu_memory("before full unload")
    
    # Unload TTS and Whisper
    unload_models()
    
    # Unload Qwen2VL
    from vison_models.llm_connector import unload_qwen_model
    unload_qwen_model()
    
    # Additional aggressive cleanup
    if torch.cuda.is_available():
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        # Wait a moment for cleanup to complete
        time.sleep(0.5)
        torch.cuda.empty_cache()
    
    log_gpu_memory("after full unload")
    logger.info("🧹 All models unloaded - maximum GPU memory available")

def reload_models_if_needed():
    """Reload models if they were unloaded"""
    global tts_model, whisper_model
    
    if tts_model is None:
        logger.info("🔄 Reloading TTS model")
        load_tts_model()
    
    if whisper_model is None:
        logger.info("🔄 Reloading Whisper model")
        load_whisper_model()

# ─── TTS Generation Function ────────────────────────────────────────────────
def generate_speech(text, model=None, audio_prompt=None, exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    """Generate speech using TTS model"""
    from chatterbox.tts import punc_norm
    
    if model is None:
        model = load_tts_model()
    
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

# ─── Model Access Functions ─────────────────────────────────────────────────
def get_tts_model():
    """Get TTS model, loading if necessary"""
    global tts_model
    if tts_model is None:
        load_tts_model()
    return tts_model

def get_whisper_model():
    """Get Whisper model, loading if necessary"""
    global whisper_model
    if whisper_model is None:
        load_whisper_model()
    return whisper_model