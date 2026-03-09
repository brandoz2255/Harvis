"""Qwen3-TTS voice-clone module used by Harvis voice chat."""

import gc
import logging
import os
import re
import threading
import time
from typing import Any, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
DEFAULT_SR = 24000

_model_interface: Optional[Any] = None
_model_lock = threading.Lock()

# Cached voice-clone prompt values (architecture contract)
_voice_clone_prompt = None
_voice_clone_ref_key = None

# Runtime guards/state
_cuda_kernel_available = None
_auto_unload_timeout = max(0, int(os.environ.get("TTS_IDLE_TIMEOUT", "30")))
_last_used_ts = 0.0
_unload_timer: Optional[threading.Timer] = None


def _check_cuda_kernel_available() -> bool:
    """One-time CUDA compatibility probe to avoid crash loops on unsupported GPUs."""
    global _cuda_kernel_available
    if _cuda_kernel_available is not None:
        return _cuda_kernel_available

    try:
        import torch

        if not torch.cuda.is_available():
            _cuda_kernel_available = False
            return False

        cap = torch.cuda.get_device_capability(0)
        # Guard for environments where installed torch lacks support for newer cards.
        if cap[0] >= 12:
            _cuda_kernel_available = False
            logger.warning(
                "CUDA device capability sm_%s not supported by current torch build. "
                "Using CPU for Qwen3-TTS.",
                f"{cap[0]}{cap[1]}",
            )
            return False

        _cuda_kernel_available = True
        return True
    except Exception as e:
        logger.warning("CUDA compatibility probe failed (%s). Using CPU.", e)
        _cuda_kernel_available = False
        return False


def _cancel_unload_timer() -> None:
    global _unload_timer
    if _unload_timer is not None:
        _unload_timer.cancel()
        _unload_timer = None


def _schedule_auto_unload() -> None:
    global _unload_timer
    _cancel_unload_timer()
    if _auto_unload_timeout <= 0:
        return
    _unload_timer = threading.Timer(_auto_unload_timeout, _auto_unload_if_idle)
    _unload_timer.daemon = True
    _unload_timer.start()


def _auto_unload_if_idle() -> None:
    if _model_interface is None:
        return
    elapsed = time.time() - _last_used_ts
    if elapsed >= _auto_unload_timeout:
        logger.info("Qwen3-TTS idle for %.0fs, auto-unloading", elapsed)
        unload_qwen_tts_model()


def _chunk_text(text: str, max_chars: int = 500) -> List[str]:
    """Split text into <= max_chars chunks on sentence boundaries where possible."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence

    if current.strip():
        chunks.append(current.strip())
    return chunks


def _ref_audio_key(path: str):
    abs_path = os.path.abspath(path)
    st = os.stat(abs_path)
    return (abs_path, st.st_mtime_ns, st.st_size)


def _get_or_create_voice_clone_prompt(model, ref_audio: str, ref_text: Optional[str] = None):
    """Return cached prompt if same reference audio; otherwise build and cache it."""
    global _voice_clone_prompt, _voice_clone_ref_key
    cache_key = _ref_audio_key(ref_audio)
    if _voice_clone_prompt is not None and _voice_clone_ref_key == cache_key:
        return _voice_clone_prompt

    _voice_clone_prompt = model.create_voice_clone_prompt(
        ref_audio=ref_audio,
        ref_text=ref_text,
        x_vector_only_mode=(ref_text is None),
    )
    _voice_clone_ref_key = cache_key
    return _voice_clone_prompt


def load_qwen_tts_model(model_name: str = MODEL_NAME):
    """Load and cache Qwen3-TTS model interface."""
    global _model_interface, _last_used_ts
    if _model_interface is not None:
        _last_used_ts = time.time()
        _cancel_unload_timer()
        return _model_interface

    with _model_lock:
        if _model_interface is not None:
            _last_used_ts = time.time()
            _cancel_unload_timer()
            return _model_interface

        from qwen_tts import Qwen3TTSModel
        import torch

        device = "cuda:0" if _check_cuda_kernel_available() else "cpu"
        logger.info("Loading Qwen3-TTS model on %s: %s", device, model_name)

        kwargs = {"dtype": torch.float16} if device.startswith("cuda") else {"dtype": torch.float32}
        if device.startswith("cuda"):
            kwargs["device_map"] = device

        t0 = time.time()
        _model_interface = Qwen3TTSModel.from_pretrained(model_name, **kwargs)
        if device == "cpu" and hasattr(_model_interface, "model") and hasattr(_model_interface.model, "to"):
            _model_interface.model = _model_interface.model.to("cpu")
        logger.info("Qwen3-TTS loaded in %.1fs", time.time() - t0)

        _last_used_ts = time.time()
        _cancel_unload_timer()
        return _model_interface


def unload_qwen_tts_model() -> None:
    """Unload Qwen3-TTS and clear cached prompt state."""
    global _model_interface, _voice_clone_prompt, _voice_clone_ref_key
    if _model_interface is None:
        return
    logger.info("Unloading Qwen3-TTS")
    with _model_lock:
        _cancel_unload_timer()
        _model_interface = None
        _voice_clone_prompt = None
        _voice_clone_ref_key = None
    gc.collect()


def generate_qwen_speech_chunked(
    text: str,
    interface=None,
    ref_audio: Optional[str] = None,
    ref_text: Optional[str] = None,
    temperature: float = 0.3,
    repetition_penalty: float = 1.1,
) -> Tuple[int, np.ndarray]:
    """Generate speech with sentence chunking and optional voice cloning prompt cache."""
    global _last_used_ts

    model = interface or load_qwen_tts_model()
    _last_used_ts = time.time()
    _cancel_unload_timer()

    chunks = _chunk_text(text, max_chars=500)
    if not chunks:
        raise RuntimeError("No text provided for Qwen3-TTS generation")

    prompt = None
    if ref_audio and os.path.isfile(ref_audio):
        prompt = _get_or_create_voice_clone_prompt(model, ref_audio=ref_audio, ref_text=ref_text)

    all_wavs: List[np.ndarray] = []
    sample_rate = DEFAULT_SR

    for idx, chunk in enumerate(chunks, start=1):
        logger.info("Qwen3-TTS chunk %d/%d (%d chars)", idx, len(chunks), len(chunk))
        kwargs = {
            "text": chunk,
            "temperature": temperature,
            "repetition_penalty": repetition_penalty,
            "non_streaming_mode": True,
        }
        if prompt is not None:
            kwargs["voice_clone_prompt"] = prompt
        elif ref_audio:
            kwargs["ref_audio"] = ref_audio

        audio_list, sr = model.generate_voice_clone(**kwargs)
        sample_rate = sr if isinstance(sr, (int, float)) and sr > 0 else DEFAULT_SR

        if not audio_list:
            logger.warning(
                "Qwen3-TTS chunk %d/%d produced no audio",
                idx,
                len(chunks),
            )
            continue
        wav = audio_list[0]
        if isinstance(wav, np.ndarray):
            all_wavs.append(wav)
        elif hasattr(wav, "cpu"):
            all_wavs.append(wav.cpu().numpy())
        else:
            all_wavs.append(np.array(wav))

    _last_used_ts = time.time()
    _schedule_auto_unload()

    if not all_wavs:
        raise RuntimeError("No audio segments generated")

    result = np.concatenate(all_wavs) if len(all_wavs) > 1 else all_wavs[0]
    return sample_rate, result


class Qwen3TTS:
    """Compatibility wrapper used by existing model_manager integration."""

    @property
    def is_loaded(self) -> bool:
        return _model_interface is not None

    def load(self, device: str = "cpu") -> None:
        _ = device
        load_qwen_tts_model()

    def unload(self) -> None:
        unload_qwen_tts_model()

    def generate(self, text: str, ref_audio_path: Optional[str] = None) -> Tuple[int, np.ndarray]:
        return generate_qwen_speech_chunked(text=text, ref_audio=ref_audio_path)


_instance: Optional["Qwen3TTS"] = None


def get_instance() -> "Qwen3TTS":
    global _instance
    if _instance is None:
        with _model_lock:
            if _instance is None:
                _instance = Qwen3TTS()
    return _instance
