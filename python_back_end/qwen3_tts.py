"""
Qwen3-TTS Text-to-Speech Module (Voice Clone)

Uses the official Qwen3-TTS from Alibaba (qwen-tts package).
Model: Qwen/Qwen3-TTS-12Hz-1.7B-Base (for voice cloning)

Clones the harvis_voice.mp3 reference audio, same as Chatterbox TTS.

VRAM Requirements:
- 0.6B model: ~4 GB minimum, 6 GB recommended
- 1.7B model: ~6 GB minimum, 8 GB recommended

Usage:
    from qwen3_tts import load_qwen_tts_model, generate_qwen_speech
    model = load_qwen_tts_model()
    sr, wav = generate_qwen_speech("Hello world!", model, ref_audio="harvis_voice.mp3")
"""

import os
import torch
import logging
import time
import gc
import numpy as np
import threading
import atexit
from typing import Optional, Tuple

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global model variable
qwen_tts_model = None

# Cached voice clone prompt (reused across generations to avoid recomputing)
_voice_clone_prompt = None
_voice_clone_ref_audio = None

# Auto-unload configuration
_last_tts_use_time: float = 0.0
_auto_unload_timeout: float = float(os.getenv("TTS_IDLE_TIMEOUT", "30"))  # seconds
_auto_unload_thread: Optional[threading.Thread] = None
_auto_unload_stop_event = threading.Event()
_auto_unload_lock = threading.Lock()

# Model configuration - Qwen3-TTS Base models (voice clone capable)
QWEN_TTS_MODEL_1_7B = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
QWEN_TTS_MODEL_0_6B = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"

# Default reference audio for voice cloning
DEFAULT_REF_AUDIO = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "harvis_voice.mp3"
)
DEFAULT_LANGUAGE = "English"


def get_vram_threshold():
    """Get VRAM threshold (80% of total GPU memory)"""
    if not torch.cuda.is_available():
        return float("inf")
    total_mem = torch.cuda.get_device_properties(0).total_memory
    return max(int(total_mem * 0.8), 10 * 1024**3)


# ═══════════════════════════════════════════════════════════════════════════════
# Auto-Unload System - Frees RAM after idle timeout
# ═══════════════════════════════════════════════════════════════════════════════

def _touch_tts_usage():
    """Update last TTS usage timestamp"""
    global _last_tts_use_time
    _last_tts_use_time = time.time()


def _auto_unload_worker():
    """Background thread that unloads TTS model after idle timeout"""
    global qwen_tts_model, _last_tts_use_time

    logger.info(f"🕐 TTS auto-unload worker started (timeout: {_auto_unload_timeout}s)")

    while not _auto_unload_stop_event.is_set():
        # Check every 5 seconds
        _auto_unload_stop_event.wait(5)

        if _auto_unload_stop_event.is_set():
            break

        # Check if we should unload (without holding the lock during unload)
        should_unload = False
        idle_time = 0

        with _auto_unload_lock:
            if qwen_tts_model is None:
                continue

            idle_time = time.time() - _last_tts_use_time
            should_unload = idle_time >= _auto_unload_timeout

        # Unload outside the lock check (unload_qwen_tts_model acquires its own lock)
        if should_unload:
            logger.info(f"🗑️ TTS idle for {idle_time:.1f}s, auto-unloading to free RAM...")
            unload_qwen_tts_model()
            logger.info("✅ TTS auto-unloaded successfully")


def _start_auto_unload_thread():
    """Start the auto-unload background thread if not running"""
    global _auto_unload_thread

    if _auto_unload_thread is not None and _auto_unload_thread.is_alive():
        return  # Already running

    _auto_unload_stop_event.clear()
    _auto_unload_thread = threading.Thread(
        target=_auto_unload_worker,
        daemon=True,
        name="tts-auto-unload"
    )
    _auto_unload_thread.start()


def _stop_auto_unload_thread():
    """Stop the auto-unload background thread"""
    global _auto_unload_thread

    if _auto_unload_thread is not None:
        _auto_unload_stop_event.set()
        _auto_unload_thread.join(timeout=2)
        _auto_unload_thread = None


def set_tts_idle_timeout(seconds: float):
    """Set the TTS idle timeout (how long before auto-unload)"""
    global _auto_unload_timeout
    _auto_unload_timeout = max(5.0, seconds)  # Minimum 5 seconds
    logger.info(f"🕐 TTS idle timeout set to {_auto_unload_timeout}s")


def get_tts_idle_timeout() -> float:
    """Get the current TTS idle timeout"""
    return _auto_unload_timeout


# Register cleanup on process exit
atexit.register(_stop_auto_unload_thread)


def check_qwen_tts_available() -> bool:
    """Check if qwen-tts library is available"""
    try:
        from qwen_tts import Qwen3TTSModel

        return True
    except ImportError:
        logger.warning("qwen-tts not installed. Install with: pip install qwen-tts")
        return False


def load_qwen_tts_model(force_cpu: bool = False, use_1_7b: bool = False):
    """
    Load Qwen3-TTS Base model (voice clone capable).

    Args:
        force_cpu: Force CPU inference
        use_1_7b: Use 1.7B model (higher quality) or 0.6B (lower VRAM)
                 NOTE: Default changed to False to use 0.6B only for better VRAM compatibility

    Returns:
        The loaded Qwen3TTSModel instance
    """
    global qwen_tts_model

    # Use lock for thread-safe loading
    with _auto_unload_lock:
        if qwen_tts_model is not None:
            logger.info("Qwen3-TTS model already loaded")
            _touch_tts_usage()  # Reset idle timer
            return qwen_tts_model

        if not check_qwen_tts_available():
            raise ImportError("qwen-tts is not installed")

        # Always use 0.6B model for better VRAM compatibility (~3-4GB instead of ~7GB)
        device = "cuda:0" if torch.cuda.is_available() and not force_cpu else "cpu"
        model_id = QWEN_TTS_MODEL_0_6B  # Always use 0.6B model

        if use_1_7b:
            logger.warning("1.7B model requested but using 0.6B for VRAM compatibility")

        logger.info(f"Loading Qwen3-TTS model '{model_id}' on {device}...")

        try:
            from qwen_tts import Qwen3TTSModel

            # GPU cleanup before loading
            if "cuda" in device and torch.cuda.is_available():
                logger.info("Performing GPU cleanup before loading Qwen3-TTS...")
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                gc.collect()
                time.sleep(0.5)

            # Use sdpa attention (flash_attention_2 requires flash-attn package)
            attn_impl = "sdpa"
            try:
                import flash_attn

                attn_impl = "flash_attention_2"
                logger.info("Using FlashAttention 2 for Qwen3-TTS")
            except ImportError:
                logger.info("Using SDPA attention for Qwen3-TTS (flash-attn not installed)")

            dtype = torch.bfloat16 if "cuda" in device else torch.float32

            qwen_tts_model = Qwen3TTSModel.from_pretrained(
                model_id,
                device_map=device,
                dtype=dtype,
                attn_implementation=attn_impl,
            )

            logger.info(f"Qwen3-TTS model loaded successfully on {device.upper()}")

            # Log memory usage
            if "cuda" in device and torch.cuda.is_available():
                allocated = torch.cuda.memory_allocated() / 1024**3
                logger.info(f"GPU memory allocated: {allocated:.2f} GB")

            # Start auto-unload thread and mark usage
            _touch_tts_usage()
            _start_auto_unload_thread()

            return qwen_tts_model

        except RuntimeError as e:
            error_str = str(e).lower()
            if "out of memory" in error_str or "cuda" in error_str:
                logger.warning(f"CUDA OOM during Qwen3-TTS load: {e}")
                logger.info("Attempting CPU fallback for Qwen3-TTS (0.6B model)...")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    gc.collect()
                # Release lock before recursive call
                # (lock is released when 'with' block exits)

        except Exception as e:
            logger.error(f"Failed to load Qwen3-TTS model: {e}")
            raise

    # CPU fallback (outside lock to avoid deadlock on recursive call)
    return load_qwen_tts_model(force_cpu=True, use_1_7b=False)


def unload_qwen_tts_model():
    """Unload Qwen3-TTS model to free GPU VRAM and CPU RAM"""
    global qwen_tts_model, _voice_clone_prompt, _voice_clone_ref_audio

    with _auto_unload_lock:
        if qwen_tts_model is not None:
            logger.info("Unloading Qwen3-TTS model...")

            try:
                if hasattr(qwen_tts_model, "model") and hasattr(qwen_tts_model.model, "to"):
                    qwen_tts_model.model.to("cpu")
            except Exception as e:
                logger.debug(f"Could not move Qwen3-TTS model to CPU: {e}")

            del qwen_tts_model
            qwen_tts_model = None
            _voice_clone_prompt = None
            _voice_clone_ref_audio = None

            # Aggressive cleanup
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()

            gc.collect()
            gc.collect()
            gc.collect()

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("Qwen3-TTS model unloaded successfully")

            if torch.cuda.is_available():
                allocated = torch.cuda.memory_allocated() / 1024**3
                logger.info(f"GPU memory after unload: {allocated:.2f} GB")


def _get_or_create_voice_clone_prompt(model, ref_audio: str, ref_text: str = None):
    """
    Get or create a reusable voice clone prompt from the reference audio.
    Caches the prompt to avoid recomputing on every generation.
    """
    global _voice_clone_prompt, _voice_clone_ref_audio

    # If we already have a prompt for this ref_audio, reuse it
    if _voice_clone_prompt is not None and _voice_clone_ref_audio == ref_audio:
        logger.info("Using cached voice clone prompt")
        return _voice_clone_prompt

    logger.info(f"Creating voice clone prompt from: {ref_audio}")

    # Use x_vector_only_mode=True since we don't have a transcript of the reference
    # This extracts only the speaker embedding, which is simpler but still effective
    _voice_clone_prompt = model.create_voice_clone_prompt(
        ref_audio=ref_audio,
        ref_text=ref_text,
        x_vector_only_mode=(ref_text is None),
    )
    _voice_clone_ref_audio = ref_audio

    logger.info("Voice clone prompt created and cached")
    return _voice_clone_prompt


def generate_qwen_speech(
    text: str,
    interface=None,
    ref_audio: str = None,
    ref_text: str = None,
    language: str = None,
    temperature: float = 0.3,
    repetition_penalty: float = 1.1,
    max_length: int = 4096,
    _cpu_retry: bool = False,
    timeout: float = 120.0,  # Max 2 minutes per chunk
) -> Tuple[int, np.ndarray]:
    """
    Generate speech using Qwen3-TTS voice cloning.

    Clones the voice from ref_audio (defaults to harvis_voice.mp3).
    Automatically falls back to CPU if GPU runs out of memory.

    Args:
        text: Text to synthesize
        interface: Qwen3TTSModel instance (loads if None)
        ref_audio: Path to reference audio for voice cloning (default: harvis_voice.mp3)
        ref_text: Optional transcript of the reference audio
        language: Language (e.g. "English", "Chinese"). None for auto.
        temperature: Generation temperature (lower = more stable)
        repetition_penalty: Penalty for repeated tokens
        max_length: Maximum generation length
        _cpu_retry: Internal flag, True if this is a CPU fallback retry
        timeout: Max seconds to wait for generation (default: 120)

    Returns:
        Tuple of (sample_rate, audio_numpy_array)
    """
    global qwen_tts_model, _voice_clone_prompt, _voice_clone_ref_audio

    model = interface
    if model is None:
        logger.info("🔄 TTS: Loading model (not provided)...")
        model = load_qwen_tts_model()

    if model is None:
        raise RuntimeError("Failed to load Qwen3-TTS model")

    # Use the same voice file as Chatterbox by default
    if ref_audio is None:
        ref_audio = DEFAULT_REF_AUDIO

    if language is None:
        language = DEFAULT_LANGUAGE

    # Touch usage time for auto-unload tracking
    _touch_tts_usage()

    # Check device
    device_info = "unknown"
    if hasattr(model, 'device'):
        device_info = str(model.device)
    elif hasattr(model, 'model') and hasattr(model.model, 'device'):
        device_info = str(model.model.device)

    # Warn if running on CPU (will be VERY slow)
    if "cpu" in device_info.lower():
        logger.warning(f"⚠️ TTS: Running on CPU! This will be VERY SLOW (~10-60x slower than GPU)")
        logger.warning(f"⚠️ TTS: Consider freeing GPU VRAM or text will take minutes to generate")

    logger.info(f"🎙️ TTS: Generating speech for {len(text)} chars on {device_info}")
    logger.info(f"🎙️ TTS: ref_audio={os.path.basename(ref_audio)}, temp={temperature}")

    # Verify reference audio exists
    if not os.path.exists(ref_audio):
        raise FileNotFoundError(f"Reference audio not found: {ref_audio}")

    try:
        start_time = time.time()

        # Get or create the voice clone prompt (cached for reuse)
        logger.info(f"🎙️ TTS: Creating/getting voice clone prompt...")
        prompt_start = time.time()
        voice_clone_prompt = _get_or_create_voice_clone_prompt(
            model, ref_audio, ref_text
        )
        logger.info(f"🎙️ TTS: Voice clone prompt ready in {time.time() - prompt_start:.2f}s")

        # Generate speech using voice cloning
        logger.info(f"🎙️ TTS: Starting model.generate_voice_clone() for {len(text)} chars...")
        gen_start = time.time()
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=language,
            voice_clone_prompt=voice_clone_prompt,
        )
        gen_elapsed = time.time() - gen_start
        logger.info(f"🎙️ TTS: model.generate_voice_clone() returned in {gen_elapsed:.2f}s")

        elapsed = time.time() - start_time
        logger.info(f"✅ TTS: Speech generated in {elapsed:.2f}s total")

        # wavs is a list of numpy arrays, take the first one
        logger.info(f"🎙️ TTS: Processing output - wavs type: {type(wavs)}, sr: {sr}")

        audio_np = wavs[0] if isinstance(wavs, list) else wavs

        if audio_np is None:
            logger.error("❌ TTS: model.generate_voice_clone() returned None audio!")
            return (None, None)

        if torch.is_tensor(audio_np):
            logger.info(f"🎙️ TTS: Converting tensor to numpy (shape: {audio_np.shape})")
            audio_np = audio_np.squeeze().cpu().numpy()
        elif hasattr(audio_np, "numpy"):
            audio_np = audio_np.numpy().squeeze()
        else:
            audio_np = np.array(audio_np).squeeze()

        if len(audio_np) == 0:
            logger.error("❌ TTS: Generated audio is EMPTY (0 samples)!")
            return (None, None)

        logger.info(f"✅ TTS: Audio ready - {len(audio_np)} samples at {sr}Hz ({len(audio_np)/sr:.2f}s)")

        # Touch usage time again after generation
        _touch_tts_usage()

        return (sr, audio_np)

    except RuntimeError as e:
        error_str = str(e).lower()
        if ("out of memory" in error_str or "cuda" in error_str) and not _cpu_retry:
            logger.warning(f"⚠️ CUDA OOM during Qwen3-TTS generation: {e}")
            logger.info("🔄 Falling back to CPU for Qwen3-TTS generation...")

            # Unload the GPU model completely
            unload_qwen_tts_model()

            # Force cleanup
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            gc.collect()
            time.sleep(0.5)

            # Reload on CPU (use 0.6B to keep RAM usage low ~2.5GB vs ~8GB for 1.7B)
            logger.info("🔄 Reloading Qwen3-TTS 0.6B on CPU...")
            cpu_model = load_qwen_tts_model(force_cpu=True, use_1_7b=False)

            if cpu_model is None:
                raise RuntimeError("Failed to load Qwen3-TTS on CPU for fallback")

            # Retry generation on CPU (with _cpu_retry=True to prevent infinite loop)
            return generate_qwen_speech(
                text=text,
                interface=cpu_model,
                ref_audio=ref_audio,
                ref_text=ref_text,
                language=language,
                temperature=temperature,
                repetition_penalty=repetition_penalty,
                max_length=max_length,
                _cpu_retry=True,
            )
        else:
            logger.error(f"Qwen3-TTS generation error: {e}")
            raise

    except Exception as e:
        logger.error(f"Qwen3-TTS generation error: {e}")
        raise


def chunk_text_for_qwen_tts(text: str, max_chars: int = 500) -> list:
    """
    Split long text into chunks for stable TTS generation.
    Qwen3-TTS handles ~42 seconds of audio well per chunk.
    """
    if len(text) <= max_chars:
        return [text]

    import re

    # Split on sentence endings
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk = (
                current_chunk + " " + sentence if current_chunk else sentence
            )

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    logger.info(f"Split text into {len(chunks)} chunks for Qwen3-TTS")
    return chunks


def generate_qwen_speech_chunked(
    text: str,
    interface=None,
    ref_audio: str = None,
    ref_text: str = None,
    language: str = None,
    temperature: float = 0.3,
    repetition_penalty: float = 1.1,
    max_chunk_chars: int = 500,
) -> Tuple[int, np.ndarray]:
    """
    Generate speech with automatic chunking for long text.
    Uses voice cloning from harvis_voice.mp3 by default.

    Returns:
        Tuple of (sample_rate, concatenated_audio_numpy_array)
    """
    total_start = time.time()
    logger.info(f"🎙️ TTS CHUNKED: Starting for {len(text)} chars...")

    model = interface
    if model is None:
        model = load_qwen_tts_model()

    chunks = chunk_text_for_qwen_tts(text, max_chunk_chars)
    logger.info(f"🎙️ TTS CHUNKED: Split into {len(chunks)} chunks")
    all_wavs = []
    sample_rate = 24000

    for i, chunk in enumerate(chunks):
        chunk_start = time.time()
        logger.info(f"🎙️ TTS CHUNK {i + 1}/{len(chunks)}: Starting ({len(chunk)} chars): '{chunk[:50]}...'")

        sr, wav = generate_qwen_speech(
            text=chunk,
            interface=model,
            ref_audio=ref_audio,
            ref_text=ref_text,
            language=language,
            temperature=temperature,
            repetition_penalty=repetition_penalty,
        )

        chunk_elapsed = time.time() - chunk_start
        wav_size = len(wav) if wav is not None else 0
        logger.info(f"✅ TTS CHUNK {i + 1}/{len(chunks)}: Done in {chunk_elapsed:.2f}s, {wav_size} samples")

        sample_rate = sr
        all_wavs.append(wav)

    # Concatenate all chunks
    if len(all_wavs) > 1:
        final_wav = np.concatenate(all_wavs)
        logger.info(
            f"🎙️ TTS CHUNKED: Concatenated {len(all_wavs)} chunks, total: {len(final_wav)} samples"
        )
    else:
        final_wav = all_wavs[0] if all_wavs else np.array([])

    total_elapsed = time.time() - total_start
    total_duration = len(final_wav) / sample_rate if len(final_wav) > 0 else 0
    logger.info(f"✅ TTS CHUNKED: Complete! {total_duration:.2f}s audio in {total_elapsed:.2f}s")

    if len(final_wav) == 0:
        logger.error("❌ TTS CHUNKED: No audio generated!")
        return (None, None)

    return (sample_rate, final_wav)


# Convenience functions for model manager integration
def is_qwen_tts_loaded() -> bool:
    """Check if Qwen3-TTS model is currently loaded (thread-safe)"""
    with _auto_unload_lock:
        return qwen_tts_model is not None


def get_qwen_tts_model():
    """Get Qwen3-TTS model, loading if necessary (thread-safe)"""
    # load_qwen_tts_model handles locking and returns existing model if loaded
    return load_qwen_tts_model()
