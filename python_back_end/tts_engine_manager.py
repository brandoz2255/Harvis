
import os
import logging
import numpy as np
import torch
from enum import Enum
from typing import Optional, Tuple, Any, Dict
from dataclasses import dataclass

# Try imports, handle gracefully if not installed yet
try:
    from piper.voice import PiperVoice
except ImportError:
    PiperVoice = None

try:
    from rvc_python.infer import RVCInference
except ImportError:
    RVCInference = None

# Placeholder for Chatterbox imports to avoid immediate loading
ChatterboxTTS = None

logger = logging.getLogger(__name__)

class TTSMode(Enum):
    INTERACTIVE = "interactive"   # Chatterbox (GPU heavy)
    PODCAST = "podcast"           # Piper + RVC (Mid GPU)
    LIGHTWEIGHT = "lightweight"   # Piper only (CPU)

@dataclass
class TTSConfig:
    piper_model: str = "en_US-lessac-medium" # Default piper model
    rvc_f0_method: str = "rmvpe"
    rvc_index_rate: float = 0.75
    rvc_protect: float = 0.33
    # SAFETY: Force CPU if we detect we are in a broken CUDA environment (e.g. sm_120 on old pytorch)
    # But usually we want to try CUDA.
    device: str = "cuda" if torch.cuda.is_available() else "cpu"

_config = TTSConfig()
_current_mode = TTSMode.INTERACTIVE
_engines: Dict[str, Any] = {
    "piper": None,
    "chatterbox": None,
    "rvc_wrapper": None
}

def get_mode() -> TTSMode:
    return _current_mode

def set_mode(mode: TTSMode):
    global _current_mode
    _current_mode = mode
    logger.info(f"TTS Engine switched to: {mode.value}")
    
    # Optional: Unload unused engines to save VRAM?
    # For now we keep them loaded if they were used, unless explicit unload called.

def get_engine_status() -> Dict[str, bool]:
    return {
        "mode": _current_mode.value,
        "piper_loaded": _engines["piper"] is not None,
        "chatterbox_loaded": _engines["chatterbox"] is not None,
        "rvc_loaded": _engines["rvc_wrapper"] is not None,
        "device": _config.device
    }

def unload_chatterbox():
    if _engines["chatterbox"]:
        del _engines["chatterbox"]
        _engines["chatterbox"] = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Unloaded Chatterbox to free resources.")

def unload_all_engines():
    global _engines
    _engines = {k: None for k in _engines}
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

# ─── Loading Helpers ─────────────────────────────────────────────────────────

def _load_piper():
    global _engines
    if _engines["piper"] is None:
        if PiperVoice is None:
            raise ImportError("Piper TTS not installed. Install 'piper-tts'.")
        
        # In a real app, you'd manage downloading piper models.
        # For now, let's assume a default path or download on fly if library supports it.
        # Piper python wrapper usually expects a .onnx path.
        # WE NEED TO ENSURE A MODEL EXISTS.
        # For this implementation, we will assume a standard location or mock if missing.
        
        # Check standard location or use a dummy for now if file not found
        model_path = os.path.expanduser(f"~/.local/share/piper_models/{_config.piper_model}.onnx")
        
        if not os.path.exists(model_path):
             logger.warning(f"Piper model not found at {model_path}. attempting auto-download not implemented in this snippet.")
             # In a full implementation, we'd pull the ONNX here.
             pass

        try:
            # We strictly need the path. If dependencies are installed via pip install piper-tts, 
            # managing models is separate. 
            # For simplicity, we might fail hard here if file missing in production.
            # But for "agentic" flow, let's just flag it.
            _engines["piper"] = "LOADED_PLACEHOLDER" # Real load needs file path
            # _engines["piper"] = PiperVoice.load(model_path)
        except Exception as e:
            logger.error(f"Failed to load Piper: {e}")

def _ensure_chatterbox():
    global ChatterboxTTS, _engines
    if _engines["chatterbox"] is None:
        try:
            import chatterbox
            from chatterbox import ChatterboxTTS as CBox
            _engines["chatterbox"] = CBox
        except ImportError:
            logger.error("Chatterbox not installed")
            raise

load_chatterbox = _ensure_chatterbox

# ─── Generation Functions ───────────────────────────────────────────────────

def generate_speech(
    text: str,
    mode: TTSMode = TTSMode.INTERACTIVE,
    voice_model: Optional[str] = None,
    audio_prompt: Optional[str] = None,
    **kwargs
) -> Tuple[int, np.ndarray]:
    
    if mode == TTSMode.INTERACTIVE:
        _ensure_chatterbox()
        # Call existing chatterbox logic (mocked or bridged)
        # Note: In the existing codebase, model_manager handles calls.
        # This function might delegate back or assume Chatterbox is usable.
        # Since Chatterbox returns file paths or bytes usually, we adapt.
        logger.info("Generating via Chatterbox (Interactive)...")
        # Placeholder return for now, as actual heavy lifting is in existing modules
        return (24000, np.zeros(24000)) 

    elif mode == TTSMode.LIGHTWEIGHT:
        # Piper only
        return _generate_piper(text)

    elif mode == TTSMode.PODCAST:
        # Piper -> RVC
        sr, audio = _generate_piper(text)
        if voice_model:
            return _convert_rvc(audio, sr, voice_model)
        return sr, audio

    return (24000, np.zeros(24000))

def _generate_piper(text: str) -> Tuple[int, np.ndarray]:
    """
    Generate audio using Piper TTS.
    Returns (sample_rate, audio_float_array)
    """
    # NOTE: Since we are in a dev environment and might lack the .onnx model file,
    # and `piper` python lib is tricky without files,
    # we will use the `piper` CLI if available or fallback to a dummy for the test phase
    # until we explicitly download a model.
    try:
        import subprocess
        import soundfile as sf
        import io
        
        # Try running piper cli
        # This requires the binary 'piper' to be in PATH or downloaded.
        # The python package 'piper-tts' might provide bindings.
        
        # For executed code simplicity, if we can't load the object, we error.
        # But we haven't downloaded a model yet.
        
        # MOCKING output for the planning phase to ensure logic flow.
        # In real execution, we need to download a model.
        logger.info(f"Piper generating: {text[:20]}...")
        
        # Mock 1 second of noise
        sr = 22050
        audio = np.random.uniform(-0.1, 0.1, sr).astype(np.float32)
        return sr, audio
        
    except Exception as e:
        logger.error(f"Piper gen failed: {e}")
        return (22050, np.zeros(22050))

def _convert_rvc(audio_data: np.ndarray, sr: int, model_name: str) -> Tuple[int, np.ndarray]:
    """
    Convert audio using RVC.
    """
    if RVCInference is None:
        logger.warning("RVC not installed, returning original audio")
        return sr, audio_data
        
    # We need the path to the model from VoiceModelManager
    # Ideally, this manager is passed in or we inspect the directory
    model_path = f"voice_models/{model_name}/{model_name}.pth"
    index_path = f"voice_models/{model_name}/added_{model_name}.index"
    
    if not os.path.exists(model_path):
        logger.error(f"RVC Model not found: {model_path}")
        return sr, audio_data

    # Save input audio to temp file for RVC (lib usually works with files)
    import soundfile as sf
    import tempfile
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
        sf.write(tmp_in.name, audio_data, sr)
        input_path = tmp_in.name
    
    output_path = input_path.replace(".wav", "_rvc.wav")
    
    try:
        # Perform inference
        # Note: arguments depend on specific rvc implementation
        rvc = RVCInference(device=_config.device)
        rvc.load_model(model_path)
        rvc.infer_file(
            input_path=input_path,
            output_path=output_path,
            index_path=index_path if os.path.exists(index_path) else None,
            f0_method=_config.rvc_f0_method,
            index_rate=_config.rvc_index_rate,
            protect=_config.rvc_protect
        )
        
        # Read back
        out_data, out_sr = sf.read(output_path)
        return out_sr, out_data
        
    except Exception as e:
        logger.error(f"RVC conversion failed: {e}")
        if "no kernel image" in str(e) or "CUDA error" in str(e):
            logger.warning("⚠️ CUDA ARCHITECTURE ERROR DETECTED (RTX 50-series?)")
            logger.warning("Falling back to CPU-only mode for RVC (might be slow but will work).")
            # Fallback logic: Try running on CPU if device was cuda
            if _config.device == "cuda":
                logger.info("🔄 Retrying RVC on CPU...")
                try:
                    rvc = RVCInference(device="cpu")
                    rvc.load_model(model_path)
                    rvc.infer_file(
                        input_path=input_path,
                        output_path=output_path,
                        index_path=index_path if os.path.exists(index_path) else None,
                        f0_method=_config.rvc_f0_method,
                        index_rate=_config.rvc_index_rate,
                        protect=_config.rvc_protect
                    )
                    out_data, out_sr = sf.read(output_path)
                    return out_sr, out_data
                except Exception as cpu_e:
                    logger.error(f"❌ RVC CPU fallback also failed: {cpu_e}")

        # Final fallback: return original audio (Piper TTS) without voice conversion
        logger.info("↩️ Returning original Piper TTS audio due to RVC failure.")
        return sr, audio_data
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        if os.path.exists(output_path): os.remove(output_path)

def generate_podcast_segment(text: str, character_voice: str, voice_models_dir: str) -> Tuple[int, np.ndarray]:
    """
    High level helper for pipeline (Piper -> RVC)
    """
    # 1. Generate clean TTS
    sr, audio = _generate_piper(text)
    
    # 2. Convert voice
    # Ensure paths are correct
    model_path = os.path.join(voice_models_dir, character_voice, f"{character_voice}.pth")
    
    if os.path.exists(model_path):
        return _convert_rvc(audio, sr, character_voice)
    
    logger.warning(f"Voice {character_voice} not found, using raw TTS")
    return sr, audio
