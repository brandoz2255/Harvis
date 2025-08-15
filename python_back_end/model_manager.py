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
try:
    import whisper
except ImportError:
    # Try alternative whisper import
    try:
        import openai_whisper as whisper
    except ImportError:
        logger.error("No whisper package found. Please install with: pip install openai-whisper")
        whisper = None
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
        if whisper is None:
            logger.error("❌ Whisper not available - install with: pip install openai-whisper")
            return None
        try:
            logger.info("🔄 Loading Whisper model")
            # Try a larger model for better transcription accuracy
            try:
                whisper_model = whisper.load_model("medium")
                logger.info("✅ Loaded Whisper 'medium' model")
            except Exception as e:
                logger.warning(f"Failed to load 'medium' model, falling back to 'small': {e}")
                try:
                    whisper_model = whisper.load_model("small")
                    logger.info("✅ Loaded Whisper 'small' model")
                except Exception as e2:
                    logger.warning(f"Failed to load 'small' model, falling back to 'base': {e2}")
                    whisper_model = whisper.load_model("base")
            logger.info("✅ Whisper model loaded successfully")
        except AttributeError as e:
            logger.error(f"❌ Whisper module missing load_model: {e}")
            logger.error(f"Available whisper attributes: {dir(whisper)}")
            return None
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            return None
    return whisper_model

# ─── Model Unloading Functions ──────────────────────────────────────────────
def unload_tts_model():
    """Unload only TTS model to free GPU memory for Whisper"""
    global tts_model
    
    if tts_model is not None:
        logger.info("🗑️ Unloading TTS model to free GPU memory for Whisper")
        del tts_model
        tts_model = None
        
        # Aggressive GPU cleanup
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            gc.collect()
            torch.cuda.empty_cache()
        
        log_gpu_memory("after TTS unload")

def unload_whisper_model():
    """Unload only Whisper model to free GPU memory for TTS"""
    global whisper_model
    
    if whisper_model is not None:
        logger.info("🗑️ Unloading Whisper model to free GPU memory for TTS")
        del whisper_model
        whisper_model = None
        
        # Aggressive GPU cleanup
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            gc.collect()
            torch.cuda.empty_cache()
        
        log_gpu_memory("after Whisper unload")

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

# ─── VRAM-Optimized Sequential Model Functions ─────────────────────────────
def use_whisper_model_optimized():
    """Load Whisper model with VRAM optimization (unload TTS first)"""
    global whisper_model, tts_model
    
    logger.info("🔄 Starting VRAM-optimized Whisper loading")
    log_gpu_memory("before Whisper optimization")
    
    # Unload TTS model to free VRAM for Whisper
    unload_tts_model()
    
    # Load Whisper model
    if whisper_model is None:
        load_whisper_model()
    
    log_gpu_memory("after Whisper loaded")
    return whisper_model

def use_tts_model_optimized():
    """Load TTS model with VRAM optimization (unload Whisper first)"""
    global tts_model, whisper_model
    
    logger.info("🔄 Starting VRAM-optimized TTS loading")
    log_gpu_memory("before TTS optimization")
    
    # Unload Whisper model to free VRAM for TTS
    unload_whisper_model()
    
    # Load TTS model
    if tts_model is None:
        load_tts_model()
    
    log_gpu_memory("after TTS loaded")
    return tts_model

def transcribe_with_whisper_optimized(audio_path):
    """Transcribe audio with VRAM optimization"""
    logger.info(f"🎤 Starting VRAM-optimized transcription for: {audio_path}")
    
    # Load Whisper with optimization
    whisper_model = use_whisper_model_optimized()
    
    if whisper_model is None:
        raise RuntimeError("Failed to load Whisper model")
    
    try:
        # Perform transcription
        result = whisper_model.transcribe(
            audio_path,
            fp16=False,
            language='en',
            task='transcribe',
            verbose=True
        )
        
        logger.info(f"✅ Transcription completed: {result.get('text', '')[:100]}...")
        return result
        
    except Exception as e:
        logger.error(f"❌ Transcription failed: {e}")
        raise
    finally:
        # Unload Whisper to free VRAM
        logger.info("🗑️ Unloading Whisper after transcription")
        unload_whisper_model()

def generate_speech_optimized(text, audio_prompt=None, exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    """Generate speech with VRAM optimization"""
    logger.info(f"🔊 Starting VRAM-optimized TTS generation for: {text[:50]}...")
    
    # Load TTS with optimization  
    tts_model = use_tts_model_optimized()
    
    if tts_model is None:
        raise RuntimeError("Failed to load TTS model")
    
    try:
        # Generate speech
        result = generate_speech(text, tts_model, audio_prompt, exaggeration, temperature, cfg_weight)
        
        logger.info("✅ TTS generation completed")
        return result
        
    except Exception as e:
        logger.error(f"❌ TTS generation failed: {e}")
        raise
    finally:
        # Unload TTS to free VRAM
        logger.info("🗑️ Unloading TTS after generation")
        unload_tts_model()

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