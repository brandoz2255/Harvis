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
            # Add timeout for CUDA loading to prevent hanging
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError("TTS model loading timed out")
            
            if tts_device == "cuda":
                # Set 30 second timeout for CUDA loading
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(30)
                try:
                    tts_model = ChatterboxTTS.from_pretrained(device=tts_device)
                    signal.alarm(0)  # Cancel timeout
                except TimeoutError:
                    signal.alarm(0)  # Cancel timeout
                    logger.warning("⏰ TTS CUDA loading timed out, falling back to CPU...")
                    tts_device = "cpu"
                    tts_model = ChatterboxTTS.from_pretrained(device="cpu")
            else:
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
            logger.info("🔄 Loading Whisper model with surgical GPU fixes")
            
            # SURGICAL FIX 1: Force CUDA init early to prevent hanging
            import signal
            def cuda_timeout_handler(signum, frame):
                raise TimeoutError("CUDA operation timed out")
            
            if torch.cuda.is_available():
                logger.info("🔧 Pre-warming CUDA to prevent init hangs...")
                signal.signal(signal.SIGALRM, cuda_timeout_handler)
                signal.alarm(15)  # 15 second timeout for CUDA init
                try:
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    _ = torch.cuda.current_device()
                    logger.info("✅ CUDA pre-warm successful")
                    signal.alarm(0)
                except Exception as cuda_e:
                    signal.alarm(0)
                    logger.error(f"❌ CUDA pre-warm failed: {cuda_e}")
                    raise RuntimeError(f"CUDA initialization failed: {cuda_e}")
            
            # SURGICAL FIX 2: Check if model already exists in cache (avoids download entirely)
            import os
            cache_dir = os.path.expanduser("~/.cache/whisper")
            logger.info(f"📁 Checking Whisper cache directory: {cache_dir}")
            
            if os.path.exists(cache_dir):
                files = os.listdir(cache_dir)
                logger.info(f"📁 Whisper cache contents: {files}")
                # Look for any .pt files (model files)
                model_files = [f for f in files if f.endswith('.pt')]
                if model_files:
                    logger.info(f"✅ Found existing Whisper models: {model_files}")
                    # SURGICAL FIX 3: Validate cached models and load with timeout
                    for model_name in ['tiny', 'base', 'small']:  # Start with smallest for faster testing
                        expected_file = f"{model_name}.pt"
                        if expected_file in model_files:
                            model_path = os.path.join(cache_dir, expected_file)
                            file_size = os.path.getsize(model_path)
                            
                            # Check minimum expected sizes to detect corruption
                            min_sizes = {'tiny': 30_000_000, 'base': 140_000_000, 'small': 460_000_000}
                            if file_size < min_sizes.get(model_name, 30_000_000):
                                logger.warning(f"🗑️ Corrupted cache detected for {model_name}: {file_size} bytes (expected >{min_sizes[model_name]})")
                                os.remove(model_path)
                                continue
                            
                            logger.info(f"🎯 Loading cached Whisper '{model_name}' model ({file_size} bytes)...")
                            
                            # Load with timeout protection
                            signal.signal(signal.SIGALRM, cuda_timeout_handler)
                            signal.alarm(45)  # 45 second timeout for model loading
                            try:
                                whisper_model = whisper.load_model(model_name, device="cuda")
                                logger.info(f"✅ Successfully loaded cached Whisper '{model_name}' model")
                                signal.alarm(0)
                                return whisper_model
                            except Exception as load_e:
                                signal.alarm(0)
                                logger.warning(f"⚠️ Failed to load cached {model_name}: {load_e}")
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
                    'tiny': 'https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt',
                    'base': 'https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt', 
                    'small': 'https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt'
                }
                
                if model_name not in model_urls:
                    return False, f"Model '{model_name}' not supported"
                
                url = model_urls[model_name]
                model_path = os.path.join(cache_dir, f"{model_name}.pt")
                
                try:
                    logger.info(f"🌐 Downloading Whisper '{model_name}' model from: {url}")
                    
                    # Download with progress bar and extended timeout for large models
                    response = requests.get(url, stream=True, timeout=(30, 300))  # 30s connect, 5min read timeout
                    response.raise_for_status()
                    
                    total_size = int(response.headers.get('content-length', 0))
                    logger.info(f"📦 Model size: {total_size / 1024 / 1024:.1f} MB")
                    
                    with open(model_path, 'wb') as f:
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
                                        logger.info(f"📥 Download progress: {progress:.1f}% ({downloaded / 1024 / 1024:.1f}MB)")
                    
                    logger.info(f"✅ Successfully downloaded Whisper '{model_name}' model")
                    return True, None
                    
                except requests.exceptions.Timeout:
                    logger.error(f"⏰ Download timeout for '{model_name}' model")
                    return False, "timeout"
                except Exception as e:
                    logger.error(f"❌ Download failed for '{model_name}': {e}")
                    return False, str(e)
            
            # SURGICAL FIX 4: Start with tiny model for fastest download, force GPU loading
            logger.info("🎯 Starting with tiny model for fastest initialization")
            
            for model_name in ['tiny', 'base', 'small']:
                logger.info(f"📥 Attempting to download {model_name} model...")
                success, error = download_whisper_model_direct(model_name)
                
                if success:
                    logger.info(f"✅ Downloaded {model_name} model, now loading with GPU...")
                    
                    # Load with timeout and force GPU
                    signal.signal(signal.SIGALRM, cuda_timeout_handler)
                    signal.alarm(60)  # 60 second timeout for fresh model loading
                    try:
                        whisper_model = whisper.load_model(model_name, device="cuda")
                        logger.info(f"✅ Successfully loaded Whisper '{model_name}' model on GPU")
                        signal.alarm(0)
                        break
                    except Exception as load_e:
                        signal.alarm(0)
                        logger.error(f"❌ Failed to load downloaded {model_name}: {load_e}")
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
                    if model_name == 'small':  # Last attempt
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
                result = subprocess.run(['which', 'whisper'], capture_output=True, text=True)
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
            if f.endswith('.pt'):
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

def transcribe_with_whisper_optimized(audio_path):
    """Transcribe audio with VRAM optimization"""
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
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_json:
                cmd = ['whisper', audio_path, '--output_format', 'json', '--output_dir', '/tmp', '--model', 'tiny']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                
                if result.returncode == 0:
                    # Parse the output JSON file
                    json_file = audio_path.replace('.ogg', '.json').replace('/tmp/', '/tmp/')
                    base_name = os.path.splitext(os.path.basename(audio_path))[0]
                    json_file = f"/tmp/{base_name}.json"
                    
                    try:
                        with open(json_file, 'r') as f:
                            json_result = json.load(f)
                        os.unlink(json_file)  # Cleanup
                        logger.info(f"✅ System whisper transcription completed: {json_result.get('text', '')[:100]}...")
                        return json_result
                    except Exception as parse_e:
                        logger.error(f"❌ Failed to parse system whisper JSON: {parse_e}")
                        # Fallback to stdout parsing
                        if result.stdout:
                            return {"text": result.stdout.strip()}
                        else:
                            raise RuntimeError(f"System whisper failed: {result.stderr}")
                else:
                    raise RuntimeError(f"System whisper command failed: {result.stderr}")
        else:
            # Use Python whisper library
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
        # Unload Whisper to free VRAM (only if using Python whisper)
        if whisper_model != "system_whisper":
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
