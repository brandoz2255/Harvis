"""
Model Management System for GPU Memory Optimization
Handles loading/unloading of TTS, Whisper, and Qwen2VL models

IMPORTANT: TTS (ChatterboxTTS) is loaded LAZILY to avoid allocating VRAM/RAM
when running in text_only mode. This prevents unnecessary memory usage.
"""

import os
import torch
import logging
import time
import gc
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Lazy TTS Import ─────────────────────────────────────────────────────────
# ChatterboxTTS is NOT imported at module level to avoid allocating memory
# when text_only mode is used. It will be imported on first use.
ChatterboxTTS = None  # Will be lazily loaded


def _lazy_import_chatterbox():
    """Lazily import ChatterboxTTS only when needed."""
    global ChatterboxTTS
    if ChatterboxTTS is None:
        try:
            from chatterbox.tts import ChatterboxTTS as _ChatterboxTTS

            ChatterboxTTS = _ChatterboxTTS
            logger.info("✅ ChatterboxTTS loaded (lazy import)")
        except ImportError as e:
            logger.error(f"❌ Failed to import ChatterboxTTS: {e}")
            raise
    return ChatterboxTTS


# ─── Lazy Whisper Import ─────────────────────────────────────────────────────
whisper = None  # Will be lazily loaded


def _lazy_import_whisper():
    """Lazily import Whisper only when needed."""
    global whisper
    if whisper is None:
        try:
            import whisper as _whisper

            whisper = _whisper
            logger.info("✅ Whisper loaded (lazy import)")
        except ImportError:
            try:
                import openai_whisper as _whisper

                whisper = _whisper
                logger.info("✅ Whisper (openai-whisper) loaded (lazy import)")
            except ImportError:
                logger.error(
                    "❌ No whisper package found. Install with: pip install openai-whisper"
                )
                return None
    return whisper


# ─── Global Model Variables ─────────────────────────────────────────────────
tts_model = None
whisper_model = None


# ─── VRAM Management ────────────────────────────────────────────────────────
def get_vram_threshold():
    if not torch.cuda.is_available():
        return float("inf")

    total_mem = torch.cuda.get_device_properties(0).total_memory
    return max(int(total_mem * 0.8), 10 * 1024**3)


THRESHOLD_BYTES = get_vram_threshold()
logger.info(f"VRAM threshold set to {THRESHOLD_BYTES / 1024**3:.1f} GiB")


def wait_for_vram(threshold=THRESHOLD_BYTES, interval=0.5):
    if not torch.cuda.is_available():
        return
    used = torch.cuda.memory_allocated()
    while used > threshold:
        logger.info(
            f"VRAM {used / 1024**3:.1f} GiB > {threshold / 1024**3:.1f} GiB. Waiting…"
        )
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
        logger.info(
            f"🔍 GPU Memory {stage}: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved, {free:.2f}GB free"
        )


def get_gpu_memory_stats():
    """Get detailed GPU memory statistics"""
    if not torch.cuda.is_available():
        return {"available": False, "message": "CUDA not available"}

    allocated = torch.cuda.memory_allocated()
    reserved = torch.cuda.memory_reserved()
    total = torch.cuda.get_device_properties(0).total_memory
    free = total - allocated

    stats = {
        "available": True,
        "allocated_gb": allocated / 1024**3,
        "reserved_gb": reserved / 1024**3,
        "total_gb": total / 1024**3,
        "free_gb": free / 1024**3,
        "allocated_bytes": allocated,
        "reserved_bytes": reserved,
        "total_bytes": total,
        "free_bytes": free,
        "usage_percent": (allocated / total) * 100,
        "device_name": torch.cuda.get_device_name(0),
        "device_count": torch.cuda.device_count(),
    }

    return stats


def check_memory_pressure():
    """Check if system is under memory pressure and suggest actions"""
    stats = get_gpu_memory_stats()

    if not stats["available"]:
        return {
            "pressure_level": "unknown",
            "message": "CUDA not available",
            "recommendations": [],
        }

    usage_percent = stats["usage_percent"]
    recommendations = []

    if usage_percent > 90:
        pressure_level = "critical"
        recommendations = [
            "Unload all models immediately",
            "Enable aggressive auto-unloading",
            "Consider using smaller models",
            "Check for memory leaks",
        ]
    elif usage_percent > 75:
        pressure_level = "high"
        recommendations = [
            "Unload unused models",
            "Enable auto-unloading for all models",
            "Monitor model usage patterns",
        ]
    elif usage_percent > 50:
        pressure_level = "moderate"
        recommendations = [
            "Consider enabling auto-unloading",
            "Monitor memory usage trends",
        ]
    else:
        pressure_level = "low"
        recommendations = ["Memory usage is healthy"]

    return {
        "pressure_level": pressure_level,
        "usage_percent": usage_percent,
        "free_gb": stats["free_gb"],
        "allocated_gb": stats["allocated_gb"],
        "total_gb": stats["total_gb"],
        "recommendations": recommendations,
        "auto_cleanup_suggested": pressure_level in ["high", "critical"],
    }


def auto_cleanup_if_needed(threshold_percent=75):
    """Automatically cleanup models if memory usage exceeds threshold"""
    pressure = check_memory_pressure()

    if not pressure.get("auto_cleanup_suggested", False):
        return False

    logger.warning(
        f"🚨 Memory pressure detected: {pressure['pressure_level']} ({pressure['usage_percent']:.1f}% used)"
    )
    logger.info("🧹 Performing automatic model cleanup...")

    # Unload models in order of priority
    cleanup_actions = []

    global tts_model, whisper_model

    if tts_model is not None:
        unload_tts_model()
        cleanup_actions.append("TTS model unloaded")

    if whisper_model is not None:
        unload_whisper_model()
        cleanup_actions.append("Whisper model unloaded")

    # Also unload Qwen model if available
    try:
        from vison_models.llm_connector import unload_qwen_model

        unload_qwen_model()
        cleanup_actions.append("Qwen2VL model unloaded")
    except Exception as e:
        logger.warning(f"Could not unload Qwen model: {e}")

    # Force aggressive cleanup
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        gc.collect()
        torch.cuda.empty_cache()
        cleanup_actions.append("GPU cache cleared")

    logger.info(f"✅ Cleanup completed: {', '.join(cleanup_actions)}")

    # Check memory again
    new_pressure = check_memory_pressure()
    logger.info(
        f"📊 Memory after cleanup: {new_pressure['usage_percent']:.1f}% used, {new_pressure['free_gb']:.2f}GB free"
    )

    return True


# ─── Model Loading Functions ────────────────────────────────────────────────
def load_tts_model(force_cpu=False):
    """Load TTS model with memory management.

    NOTE: ChatterboxTTS is lazily imported here to avoid allocating VRAM/RAM
    when text_only mode is used.
    """
    global tts_model, ChatterboxTTS
    tts_device = "cuda" if torch.cuda.is_available() and not force_cpu else "cpu"

    if tts_model is None:
        try:
            # Lazy import ChatterboxTTS only when needed
            ChatterboxTTS = _lazy_import_chatterbox()
            logger.info(f"🔊 Loading TTS model on device: {tts_device}")

            # LOG CACHE CONFIGURATION
            hf_cache = os.environ.get(
                "TRANSFORMERS_CACHE", os.environ.get("HF_HOME", "~/.cache/huggingface")
            )
            hf_cache_expanded = os.path.expanduser(hf_cache)
            logger.info(f"📁 HuggingFace cache directory: {hf_cache_expanded}")

            if os.path.exists(hf_cache_expanded):
                try:
                    cache_contents = os.listdir(hf_cache_expanded)
                    logger.info(
                        f"📦 HF cache contains {len(cache_contents)} items: {cache_contents[:5]}"
                    )
                    # Check for model directories
                    model_dirs = [d for d in cache_contents if d.startswith("models--")]
                    if model_dirs:
                        logger.info(
                            f"✅ Found {len(model_dirs)} cached models: {model_dirs}"
                        )
                except Exception as e:
                    logger.warning(f"⚠️ Could not list cache contents: {e}")
            else:
                logger.warning(
                    f"⚠️ HF cache directory does not exist: {hf_cache_expanded}"
                )
            # Note: Removed signal-based timeouts for thread-safety
            # Request-level timeouts are handled by Nginx (3600s)

            if tts_device == "cuda":
                # COMPREHENSIVE CUDA DIAGNOSTICS
                logger.info("🔧 Starting comprehensive CUDA diagnostics for TTS...")

                if torch.cuda.is_available():
                    try:
                        # Test basic CUDA operations
                        logger.info(
                            f"📊 CUDA Device Count: {torch.cuda.device_count()}"
                        )
                        logger.info(
                            f"📊 Current CUDA Device: {torch.cuda.current_device()}"
                        )
                        logger.info(
                            f"📊 CUDA Device Name: {torch.cuda.get_device_name()}"
                        )

                        # Test CUDA memory operations
                        logger.info("🧪 Testing basic CUDA memory operations...")
                        test_tensor = torch.ones(100, device="cuda")
                        logger.info(
                            f"✅ Basic CUDA tensor creation successful: {test_tensor.device}"
                        )
                        del test_tensor

                        # Check for active CUDA contexts
                        try:
                            import pynvml

                            pynvml.nvmlInit()
                            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                            logger.info(
                                f"📊 GPU Memory via NVML: {info.used / 1024**3:.2f}GB used / {info.total / 1024**3:.2f}GB total"
                            )
                        except ImportError:
                            logger.warning(
                                "⚠️ pynvml not available, skipping NVML memory check"
                            )
                        except Exception as nvml_e:
                            logger.warning(f"⚠️ NVML check failed: {nvml_e}")

                    except Exception as cuda_test_e:
                        logger.error(f"❌ Basic CUDA test failed: {cuda_test_e}")
                        logger.warning(
                            "⚠️ CUDA is broken - will load TTS on CPU directly"
                        )
                        # Reset CUDA to clear the error state
                        try:
                            torch.cuda.reset_peak_memory_stats()
                            torch.cuda.empty_cache()
                        except:
                            pass
                        # Skip CUDA entirely, go straight to CPU
                        tts_device = "cpu"

                # CRITICAL: Force GPU memory cleanup before TTS loading (only if using CUDA)
                if tts_device == "cuda" and torch.cuda.is_available():
                    logger.info(
                        "🔧 Performing aggressive GPU memory cleanup before TTS..."
                    )
                    try:
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()
                        # Force garbage collection
                        import gc

                        gc.collect()
                        torch.cuda.empty_cache()
                        # Wait for cleanup to complete
                        import time

                        time.sleep(1.0)
                        log_gpu_memory("before TTS load after cleanup")
                    except Exception as cleanup_e:
                        logger.warning(
                            f"⚠️ GPU cleanup failed (continuing anyway): {cleanup_e}"
                        )

                # Load TTS model without signal-based timeout (thread-safe)
                try:
                    logger.info(
                        f"🚀 Attempting ChatterboxTTS.from_pretrained(device='{tts_device}')..."
                    )

                    # CRITICAL: Lazy import ChatterboxTTS before using it
                    _lazy_import_chatterbox()

                    # ChatterboxTTS is imported at module level - verify it's available
                    if ChatterboxTTS is None:
                        raise ImportError("ChatterboxTTS module not available")
                    logger.info("✅ ChatterboxTTS module available")

                    # Attempt TTS model loading with additional error context
                    # Enable transformers logging to see what's happening
                    import transformers

                    transformers.logging.set_verbosity_info()

                    logger.info(
                        f"🔄 Loading ChatterboxTTS with cache_dir={hf_cache_expanded}"
                    )
                    logger.info(
                        "📥 This may use cached models or download if cache is missing..."
                    )

                    tts_model = ChatterboxTTS.from_pretrained(device=tts_device)
                    logger.info(
                        f"✅ TTS model loaded successfully on {tts_device.upper()}"
                    )

                    # Reset logging verbosity
                    transformers.logging.set_verbosity_warning()

                except Exception as cuda_load_e:
                    # ─── INTELLIGENT OOM RECOVERY ─────────────────────────────────────────────
                    # Check if this is an OOM error
                    error_str = str(cuda_load_e).lower()
                    if "out of memory" in error_str or "cuda error" in error_str:
                        logger.warning(
                            f"🚨 CUDA OOM detected during TTS load: {cuda_load_e}"
                        )
                        logger.info(
                            "🧠 Attempting INTELLIGENT OOM RECOVERY: Unloading Ollama models..."
                        )

                        try:
                            import requests

                            # 1. Get running Ollama models
                            ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
                            try:
                                ps_resp = requests.get(
                                    f"{ollama_url}/api/ps", timeout=2
                                )
                                if ps_resp.status_code == 200:
                                    running_models = ps_resp.json().get("models", [])
                                    for model_info in running_models:
                                        model_name = model_info.get("name")
                                        logger.info(
                                            f"🔫 Force-unloading Ollama model: {model_name}"
                                        )
                                        # Force unload
                                        requests.post(
                                            f"{ollama_url}/api/generate",
                                            json={"model": model_name, "keep_alive": 0},
                                            timeout=2,
                                        )
                            except Exception as ollama_e:
                                logger.error(
                                    f"❌ Failed to query/unload Ollama: {ollama_e}"
                                )

                            # 2. Aggressive PyTorch cleanup
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                                torch.cuda.synchronize()
                                import gc

                                gc.collect()
                                torch.cuda.empty_cache()
                                time.sleep(1)  # Wait for VRAM to release

                            logger.info("🔄 Retrying TTS load after OOM recovery...")

                            # 3. Retry loading on CUDA
                            # CRITICAL: Ensure ChatterboxTTS is imported for retry
                            _lazy_import_chatterbox()
                            tts_model = ChatterboxTTS.from_pretrained(device="cuda")
                            logger.info(
                                "✅ TTS model loaded successfully on CUDA (after OOM recovery)"
                            )
                            return tts_model

                        except Exception as retry_e:
                            logger.error(f"❌ OOM Recovery failed: {retry_e}")
                            # Proceed to CPU fallback below
                    # ──────────────────────────────────────────────────────────────────────────

                    logger.error(f"❌ TTS CUDA loading failed: {cuda_load_e}")
                    logger.error(f"❌ Exception type: {type(cuda_load_e).__name__}")
                    logger.error(f"❌ Exception args: {cuda_load_e.args}")

                    # Try to get more detailed error information
                    import traceback

                    logger.error(f"❌ Full traceback: {traceback.format_exc()}")

                    # Attempt CPU fallback with detailed logging
                    logger.warning("🔄 Attempting CPU fallback after CUDA failure...")
                    try:
                        tts_device = "cpu"
                        # CRITICAL: Ensure ChatterboxTTS is imported before CPU fallback
                        _lazy_import_chatterbox()
                        tts_model = ChatterboxTTS.from_pretrained(device="cpu")
                        logger.info(
                            "✅ TTS model loaded successfully on CPU (CUDA failure fallback)"
                        )
                    except Exception as cpu_fallback_e:
                        logger.error(f"❌ CPU fallback also failed: {cpu_fallback_e}")
                        # DON'T RAISE - return None and handle gracefully
                        logger.error(
                            "❌ TTS completely unavailable - continuing without TTS"
                        )
                        return None
            else:
                # CRITICAL: Ensure ChatterboxTTS is imported
                _lazy_import_chatterbox()
                tts_model = ChatterboxTTS.from_pretrained(device=tts_device)
        except Exception as e:
            if "cuda" in str(e).lower():
                logger.warning(f"⚠️ CUDA load failed: {e}. Falling back to CPU...")
                try:
                    # CRITICAL: Ensure ChatterboxTTS is imported before CPU fallback
                    _lazy_import_chatterbox()
                    tts_model = ChatterboxTTS.from_pretrained(device="cpu")
                    logger.info("✅ Successfully loaded TTS model on CPU")
                except Exception as e2:
                    logger.error(f"❌ Failed to load TTS model on CPU: {e2}")
                    raise RuntimeError(
                        "TTS model loading failed on both CUDA and CPU."
                    ) from e2
            else:
                logger.error(f"❌ TTS model loading error: {e}")
                raise
    return tts_model


def load_whisper_model():
    """Load Whisper model with memory management.

    NOTE: Whisper is lazily imported here to avoid allocating memory
    when not needed.
    """
    global whisper_model, whisper
    if whisper_model is None:
        # Lazy import whisper only when needed
        whisper = _lazy_import_whisper()
        if whisper is None:
            logger.error(
                "❌ Whisper not available - install with: pip install openai-whisper"
            )
            return None

        try:
            logger.info("🔄 Loading Whisper model with surgical GPU fixes")

            # LOG WHISPER CACHE CONFIGURATION
            whisper_cache = os.environ.get(
                "WHISPER_CACHE", os.path.expanduser("~/.cache/whisper")
            )
            logger.info(f"📁 Whisper cache directory: {whisper_cache}")

            if os.path.exists(whisper_cache):
                try:
                    cache_files = os.listdir(whisper_cache)
                    logger.info(f"📦 Whisper cache contains: {cache_files}")
                    pt_files = [f for f in cache_files if f.endswith(".pt")]
                    if pt_files:
                        logger.info(
                            f"✅ Found {len(pt_files)} cached Whisper models: {pt_files}"
                        )
                except Exception as e:
                    logger.warning(f"⚠️ Could not list Whisper cache: {e}")
            else:
                logger.warning(
                    f"⚠️ Whisper cache directory does not exist: {whisper_cache}"
                )

            # SURGICAL FIX 1: Force CUDA init early to prevent hanging
            # Note: Using threading instead of signal for thread-safety
            if torch.cuda.is_available():
                logger.info("🔧 Pre-warming CUDA to prevent init hangs...")
                try:
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    _ = torch.cuda.current_device()
                    logger.info("✅ CUDA pre-warm successful")
                except Exception as cuda_e:
                    logger.error(f"❌ CUDA pre-warm failed: {cuda_e}")
                    # Don't raise - continue with CPU fallback
                    logger.warning("⚠️ Continuing with CPU fallback for Whisper")

            # SURGICAL FIX 2: Check if model already exists in cache (avoids download entirely)
            # Use the same whisper_cache from env var (set by Docker Compose init script)
            cache_dir = whisper_cache
            logger.info(f"📁 Checking Whisper cache directory: {cache_dir}")

            if os.path.exists(cache_dir):
                files = os.listdir(cache_dir)
                logger.info(f"📁 Whisper cache contents: {files}")
                # Look for any .pt files (model files)
                model_files = [f for f in files if f.endswith(".pt")]
                if model_files:
                    logger.info(f"✅ Found existing Whisper models: {model_files}")
                    # SURGICAL FIX 3: Validate cached models and load with timeout
                    # Prioritize 'base' since that's what the init script downloads
                    for model_name in ["base", "tiny", "small"]:
                        expected_file = f"{model_name}.pt"
                        if expected_file in model_files:
                            model_path = os.path.join(cache_dir, expected_file)
                            file_size = os.path.getsize(model_path)

                            # Check minimum expected sizes to detect corruption
                            min_sizes = {
                                "tiny": 30_000_000,
                                "base": 140_000_000,
                                "small": 460_000_000,
                            }
                            if file_size < min_sizes.get(model_name, 30_000_000):
                                logger.warning(
                                    f"🗑️ Corrupted cache detected for {model_name}: {file_size} bytes (expected >{min_sizes[model_name]})"
                                )
                                os.remove(model_path)
                                continue

                            logger.info(
                                f"🎯 Loading cached Whisper '{model_name}' model ({file_size} bytes)..."
                            )

                            # Load from cache (no signal timeout for thread-safety)
                            try:
                                logger.info(f"📥 Loading from cache: {cache_dir}")
                                whisper_model = whisper.load_model(
                                    model_name, device="cuda", download_root=cache_dir
                                )
                                logger.info(
                                    f"✅ Successfully loaded cached Whisper '{model_name}' model on GPU"
                                )
                                return whisper_model
                            except Exception as load_e:
                                logger.warning(
                                    f"⚠️ Failed to load cached {model_name}: {load_e}"
                                )
                                continue
            else:
                logger.info("📁 Creating Whisper cache directory...")
                os.makedirs(cache_dir, exist_ok=True)

            # If no cached models found, download directly with timeout
            logger.warning("⚠️ No cached Whisper models found - downloading directly")

            def download_whisper_model_direct(model_name):
                """Download Whisper model directly using requests with timeout"""
                import requests
                from tqdm import tqdm

                # Whisper model URLs (from the documentation)
                model_urls = {
                    "tiny": "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
                    "base": "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
                    "small": "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
                }

                if model_name not in model_urls:
                    return False, f"Model '{model_name}' not supported"

                url = model_urls[model_name]
                model_path = os.path.join(cache_dir, f"{model_name}.pt")

                try:
                    logger.info(
                        f"🌐 Downloading Whisper '{model_name}' model from: {url}"
                    )

                    # Download with progress bar and extended timeout for large models
                    response = requests.get(
                        url, stream=True, timeout=(30, 300)
                    )  # 30s connect, 5min read timeout
                    response.raise_for_status()

                    total_size = int(response.headers.get("content-length", 0))
                    logger.info(f"📦 Model size: {total_size / 1024 / 1024:.1f} MB")

                    with open(model_path, "wb") as f:
                        if total_size == 0:
                            f.write(response.content)
                        else:
                            downloaded = 0
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    # Log progress every 10MB
                                    if downloaded % (10 * 1024 * 1024) < 8192:
                                        progress = (downloaded / total_size) * 100
                                        logger.info(
                                            f"📥 Download progress: {progress:.1f}% ({downloaded / 1024 / 1024:.1f}MB)"
                                        )

                    logger.info(
                        f"✅ Successfully downloaded Whisper '{model_name}' model"
                    )
                    return True, None

                except requests.exceptions.Timeout:
                    logger.error(f"⏰ Download timeout for '{model_name}' model")
                    return False, "timeout"
                except Exception as e:
                    logger.error(f"❌ Download failed for '{model_name}': {e}")
                    return False, str(e)

            # SURGICAL FIX 4: Start with tiny model for fastest download, force GPU loading
            logger.info("🎯 Starting with tiny model for fastest initialization")

            for model_name in ["tiny", "base", "small"]:
                logger.info(f"📥 Attempting to download {model_name} model...")
                success, error = download_whisper_model_direct(model_name)

                if success:
                    logger.info(
                        f"✅ Downloaded {model_name} model, now loading with GPU..."
                    )

                    # Load freshly downloaded model (no signal timeout for thread-safety)
                    try:
                        whisper_model = whisper.load_model(model_name, device="cuda")
                        logger.info(
                            f"✅ Successfully loaded Whisper '{model_name}' model on GPU"
                        )
                        break
                    except Exception as load_e:
                        logger.error(
                            f"❌ Failed to load downloaded {model_name}: {load_e}"
                        )
                        # Remove corrupted download
                        try:
                            corrupted_path = os.path.join(cache_dir, f"{model_name}.pt")
                            if os.path.exists(corrupted_path):
                                os.remove(corrupted_path)
                                logger.info(f"🗑️ Removed corrupted {model_name} model")
                        except:
                            pass
                        continue
                else:
                    logger.warning(f"{model_name} model download failed: {error}")
                    if model_name == "small":  # Last attempt
                        logger.error(f"❌ All Whisper model downloads failed: {error}")
                        return None

            logger.info("✅ Whisper model loaded successfully")

        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            import traceback

            logger.error(f"❌ Full traceback: {traceback.format_exc()}")

            # Try system whisper as fallback
            logger.info("🔄 Trying system whisper command as fallback...")
            try:
                import subprocess

                result = subprocess.run(
                    ["which", "whisper"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    logger.info("✅ System whisper found, using as fallback")
                    return "system_whisper"  # Special marker for system whisper
                else:
                    logger.warning("⚠️ System whisper not found")
            except Exception as fallback_e:
                logger.error(f"❌ System whisper fallback failed: {fallback_e}")

            return None
    return whisper_model


# ─── Model Unloading Functions ──────────────────────────────────────────────
def unload_tts_model():
    """Unload TTS model to free both GPU VRAM and CPU RAM"""
    global tts_model

    if tts_model is not None:
        logger.info("🗑️ Unloading TTS model to free GPU VRAM and CPU RAM")

        # Move model to CPU first if on CUDA (helps release VRAM faster)
        try:
            if hasattr(tts_model, "to"):
                tts_model.to("cpu")
        except Exception as e:
            logger.debug(f"Could not move TTS model to CPU: {e}")

        # Clear any internal caches/buffers the model might have
        try:
            if hasattr(tts_model, "cpu"):
                tts_model.cpu()
            # Clear any state_dict that might be cached
            if hasattr(tts_model, "_modules"):
                for module in tts_model._modules.values():
                    if module is not None and hasattr(module, "_parameters"):
                        for param in list(module._parameters.values()):
                            if param is not None:
                                param.data = torch.empty(0)
        except Exception as e:
            logger.debug(f"Could not clear TTS internal state: {e}")

        # Delete the model reference
        del tts_model
        tts_model = None

        # Aggressive GPU cleanup (if CUDA available)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

        # CRITICAL: Always run garbage collection for CPU RAM cleanup
        # Run multiple passes as cyclic GC may need multiple iterations
        gc.collect()
        gc.collect()
        gc.collect()

        # Final CUDA cleanup after GC
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.info("✅ TTS model unloaded (VRAM + CPU RAM freed)")
        log_gpu_memory("after TTS unload")


def unload_whisper_model():
    """Unload Whisper model to free both GPU VRAM and CPU RAM"""
    global whisper_model

    if whisper_model is not None:
        logger.info("🗑️ Unloading Whisper model to free GPU VRAM and CPU RAM")

        # Move model to CPU first if on CUDA (helps release VRAM faster)
        try:
            if hasattr(whisper_model, "to"):
                whisper_model.to("cpu")
        except Exception as e:
            logger.debug(f"Could not move Whisper model to CPU: {e}")

        # Clear any internal caches/buffers
        try:
            if hasattr(whisper_model, "cpu"):
                whisper_model.cpu()
        except Exception as e:
            logger.debug(f"Could not clear Whisper internal state: {e}")

        # Delete the model reference
        del whisper_model
        whisper_model = None

        # Aggressive GPU cleanup (if CUDA available)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

        # CRITICAL: Always run garbage collection for CPU RAM cleanup
        gc.collect()
        gc.collect()
        gc.collect()

        # Final CUDA cleanup after GC
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.info("✅ Whisper model unloaded (VRAM + CPU RAM freed)")
        log_gpu_memory("after Whisper unload")


def unload_models():
    """Unload TTS and Whisper models to free both GPU VRAM and CPU RAM"""
    global tts_model, whisper_model

    log_gpu_memory("before unload")

    # Move models to CPU first to release VRAM faster
    for model, name in [(tts_model, "TTS"), (whisper_model, "Whisper")]:
        if model is not None:
            try:
                if hasattr(model, "to"):
                    model.to("cpu")
            except Exception as e:
                logger.debug(f"Could not move {name} model to CPU: {e}")

    if tts_model is not None:
        logger.info("🗑️ Unloading TTS model to free VRAM + CPU RAM")
        del tts_model
        tts_model = None

    if whisper_model is not None:
        logger.info("🗑️ Unloading Whisper model to free VRAM + CPU RAM")
        del whisper_model
        whisper_model = None

    # Aggressive GPU cleanup (if CUDA available)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()

    # CRITICAL: Always run garbage collection for CPU RAM cleanup
    # Run multiple passes as cyclic GC may need multiple iterations
    gc.collect()
    gc.collect()
    gc.collect()

    # Final CUDA cleanup after GC
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    logger.info("✅ All models unloaded (VRAM + CPU RAM freed)")
    log_gpu_memory("after unload")


def unload_running_ollama_models():
    """Unload all running Ollama models"""
    try:
        import requests

        ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        api_key = os.getenv("OLLAMA_API_KEY", "key")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key != "key" else {}

        # Get running models
        logger.info("🔍 Checking for running Ollama models...")
        response = requests.get(f"{ollama_url}/api/ps", headers=headers, timeout=5)

        if response.status_code == 200:
            models = response.json().get("models", [])
            if not models:
                logger.info("✅ No Ollama models currently running")
                return

            logger.info(
                f"Found {len(models)} running Ollama models: {[m['name'] for m in models]}"
            )

            from vison_models.llm_connector import unload_ollama_model

            for model in models:
                model_name = model.get("name")
                if model_name:
                    logger.info(f"🔫 Unloading Ollama model: {model_name}")
                    unload_ollama_model(model_name, ollama_url)
        else:
            logger.warning(f"⚠️ Failed to check running models: {response.status_code}")

    except Exception as e:
        logger.error(f"❌ Error unloading Ollama models: {e}")


def unload_all_models():
    """Unload all models including Qwen2VL to free maximum GPU memory"""
    logger.info("🗑️ Unloading ALL models to free GPU memory for vision processing")

    log_gpu_memory("before full unload")

    # Unload TTS and Whisper
    unload_models()

    # Unload Qwen2VL
    try:
        from vison_models.llm_connector import unload_qwen_model

        unload_qwen_model()
    except Exception as e:
        logger.warning(f"Could not unload Qwen2VL: {e}")

    # Unload any running Ollama models
    unload_running_ollama_models()

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


# ─── Text Chunking for Long TTS ──────────────────────────────────────────────
def chunk_text_for_tts(text: str, max_chars: int = 500) -> list:
    """
    Split long text into chunks for stable TTS generation.
    Chatterbox can hallucinate on very long texts, so we chunk at sentence boundaries.
    """
    if len(text) <= max_chars:
        return [text]

    import re

    # Split on sentence endings while keeping the punctuation
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        # If adding this sentence would exceed max_chars, start a new chunk
        if len(current_chunk) + len(sentence) + 1 > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk = (
                current_chunk + " " + sentence if current_chunk else sentence
            )

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    logger.info(f"📝 Split text into {len(chunks)} chunks for stable TTS")
    return chunks


# ─── TTS Generation Function ────────────────────────────────────────────────
def generate_speech(
    text,
    model=None,
    audio_prompt=None,
    exaggeration=0.5,
    temperature=0.6,
    cfg_weight=2.5,
):
    """
    Generate speech using TTS model.

    Parameters tuned to prevent hallucination:
    - temperature=0.6 (lower = more stable, less random)
    - cfg_weight=2.5 (higher = follows input text more closely)
    - exaggeration=0.5 (controls expressiveness)
    """
    from chatterbox.tts import punc_norm
    import numpy as np

    if model is None:
        model = load_tts_model()

    try:
        logger.info(f"🎙️ Generating speech for text (length: {len(text)} chars)")
        logger.info(
            f"🔧 TTS params: temp={temperature}, cfg={cfg_weight}, exag={exaggeration}"
        )
        normalized = punc_norm(text)
        logger.info(f"📝 Normalized text: {normalized[:100]}...")

        # Chunk long texts to prevent hallucination
        chunks = chunk_text_for_tts(normalized, max_chars=500)
        all_wavs = []

        for i, chunk in enumerate(chunks):
            logger.info(
                f"🔊 Generating chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)"
            )

            if torch.cuda.is_available():
                try:
                    logger.info(f"🔊 TTS on CUDA: temp={temperature}, cfg={cfg_weight}")
                    chunk_wav = model.generate(
                        chunk,
                        audio_prompt_path=audio_prompt,
                        exaggeration=exaggeration,
                        temperature=temperature,
                        cfg_weight=cfg_weight,
                    )
                    logger.info(f"✅ Chunk {i + 1} generated, shape: {chunk_wav.shape}")
                except RuntimeError as e:
                    if "CUDA" in str(e):
                        logger.error(f"CUDA Error on chunk {i + 1}: {e}")
                        torch.cuda.empty_cache()
                        try:
                            chunk_wav = model.generate(
                                chunk,
                                audio_prompt_path=audio_prompt,
                                exaggeration=exaggeration,
                                temperature=temperature,
                                cfg_weight=cfg_weight,
                            )
                        except RuntimeError as e2:
                            logger.error(f"CUDA Retry Failed on chunk {i + 1}: {e2}")
                            raise ValueError(
                                "CUDA error persisted after cache clear"
                            ) from e2
                    else:
                        raise
            else:
                chunk_wav = model.generate(
                    chunk,
                    audio_prompt_path=audio_prompt,
                    exaggeration=exaggeration,
                    temperature=temperature,
                    cfg_weight=cfg_weight,
                    device="cpu",
                )

            all_wavs.append(chunk_wav.squeeze(0).numpy())

        # Concatenate all chunks
        if len(all_wavs) > 1:
            wav = np.concatenate(all_wavs)
            logger.info(
                f"✅ Concatenated {len(all_wavs)} chunks, total length: {len(wav)} samples"
            )
        else:
            wav = all_wavs[0]

        return (model.sr, wav)
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        raise


# ─── VRAM-Optimized Sequential Model Functions ─────────────────────────────
def diagnose_whisper_issues():
    """Quick diagnostic to identify Whisper loading issues"""
    logger.info("🔍 WHISPER DIAGNOSTIC START")

    # Test 1: Check network connectivity
    try:
        import requests

        response = requests.get("https://openaipublic.azureedge.net", timeout=10)
        logger.info(f"✅ Network OK: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Network issue: {e}")

    # Test 2: Check cache directory
    import os

    cache_dir = os.path.expanduser("~/.cache/whisper")
    if os.path.exists(cache_dir):
        files = os.listdir(cache_dir)
        logger.info(f"📁 Cache files: {files}")
        # Check for corrupted files
        for f in files:
            if f.endswith(".pt"):
                size = os.path.getsize(os.path.join(cache_dir, f))
                logger.info(f"📦 {f}: {size} bytes")
    else:
        logger.info("📁 No cache directory found")

    # Test 3: Check CUDA availability
    try:
        import torch

        logger.info(f"🔧 CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            logger.info(f"🔧 CUDA devices: {torch.cuda.device_count()}")
            logger.info(f"🔧 Current device: {torch.cuda.current_device()}")
    except Exception as e:
        logger.error(f"❌ CUDA check failed: {e}")

    logger.info("🔍 WHISPER DIAGNOSTIC END")


def use_whisper_model_optimized():
    """Load Whisper model with VRAM optimization and surgical fixes"""
    global whisper_model, tts_model

    logger.info("🔄 Starting VRAM-optimized Whisper loading")
    log_gpu_memory("before Whisper optimization")

    # Run diagnostics first
    diagnose_whisper_issues()

    # Unload TTS model to free VRAM for Whisper
    unload_tts_model()

    # Load Whisper model with timeout and fallbacks
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


def transcribe_with_whisper_optimized(audio_path, auto_unload=True):
    """Transcribe audio with VRAM optimization and optional auto-unload"""
    logger.info(f"🎤 Starting VRAM-optimized transcription for: {audio_path}")

    # Load Whisper with optimization
    whisper_model = use_whisper_model_optimized()

    if whisper_model is None:
        raise RuntimeError("Failed to load Whisper model")

    try:
        # Check if using system whisper fallback
        if whisper_model == "system_whisper":
            logger.info("🔧 Using system whisper command for transcription")
            import subprocess
            import json
            import tempfile

            # Use system whisper command with JSON output
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp_json:
                # Use system temp directory instead of hardcoded /tmp for security
                temp_dir = tempfile.gettempdir()
                cmd = [
                    "whisper",
                    audio_path,
                    "--output_format",
                    "json",
                    "--output_dir",
                    temp_dir,
                    "--model",
                    "tiny",
                ]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300
                )

                if result.returncode == 0:
                    # Parse the output JSON file
                    base_name = os.path.splitext(os.path.basename(audio_path))[0]
                    json_file = os.path.join(temp_dir, f"{base_name}.json")

                    try:
                        with open(json_file, "r") as f:
                            json_result = json.load(f)
                        os.unlink(json_file)  # Cleanup
                        logger.info(
                            f"✅ System whisper transcription completed: {json_result.get('text', '')[:100]}..."
                        )
                        return json_result
                    except Exception as parse_e:
                        logger.error(
                            f"❌ Failed to parse system whisper JSON: {parse_e}"
                        )
                        # Fallback to stdout parsing
                        if result.stdout:
                            return {"text": result.stdout.strip()}
                        else:
                            raise RuntimeError(
                                f"System whisper failed: {result.stderr}"
                            )
                else:
                    raise RuntimeError(
                        f"System whisper command failed: {result.stderr}"
                    )
        else:
            # Use Python whisper library
            logger.info(f"🎤 Starting Whisper transcription for: {audio_path}")
            logger.info(f"🔧 Using model on device: {whisper_model.device}")

            result = whisper_model.transcribe(
                audio_path, fp16=False, language="en", task="transcribe", verbose=True
            )

            logger.info(
                f"✅ Transcription completed: {result.get('text', '')[:100]}..."
            )
            logger.info(f"📊 Transcription segments: {len(result.get('segments', []))}")
            return result

    except Exception as e:
        logger.error(f"❌ Transcription failed: {e}")
        raise
    finally:
        # Automatically unload Whisper to free VRAM (configurable)
        if whisper_model != "system_whisper" and auto_unload:
            logger.info("🗑️ Auto-unloading Whisper after transcription")
            unload_whisper_model()
        elif whisper_model != "system_whisper":
            logger.info("ℹ️ Keeping Whisper model loaded (auto_unload=False)")
        # System whisper doesn't need unloading since it's not loaded in Python


def generate_speech_optimized(
    text,
    audio_prompt=None,
    exaggeration=0.5,
    temperature=0.6,
    cfg_weight=2.5,
    auto_unload=True,
):
    """
    Generate speech with VRAM optimization and optional auto-unload.

    Parameters tuned to prevent hallucination:
    - temperature=0.6 (lower = more stable, less random)
    - cfg_weight=2.5 (higher = follows input text more closely)
    """
    logger.info(f"🔊 Starting VRAM-optimized TTS generation for: {text[:50]}...")
    logger.info(
        f"🔧 TTS params: temp={temperature}, cfg={cfg_weight}, exag={exaggeration}"
    )

    # Load TTS with optimization
    tts_model = use_tts_model_optimized()

    if tts_model is None:
        logger.error("❌ TTS model is unavailable - cannot generate speech")
        # Return a placeholder response instead of crashing
        return None, None

    try:
        # Generate speech
        result = generate_speech(
            text, tts_model, audio_prompt, exaggeration, temperature, cfg_weight
        )

        logger.info("✅ TTS generation completed")
        return result

    except Exception as e:
        logger.error(f"❌ TTS generation failed: {e}")
        raise
    finally:
        # Automatically unload TTS to free VRAM (configurable)
        if auto_unload:
            logger.info("🗑️ Auto-unloading TTS after generation")
            unload_tts_model()
        else:
            logger.info("ℹ️ Keeping TTS model loaded (auto_unload=False)")


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
