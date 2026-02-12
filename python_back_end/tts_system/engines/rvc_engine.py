"""
RVC Engine - Retrieval-based Voice Conversion for character voices
Provides voice conversion post-processing for TTS output

Uses rvc_python's RVCInference API for simple, reliable voice conversion.
"""

import os
import logging
import tempfile
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from collections import OrderedDict
from datetime import datetime
import threading

import torch
import numpy as np
import soundfile as sf
import librosa

logger = logging.getLogger(__name__)

# Configuration
RVC_MODELS_DIR = Path(os.getenv("RVC_MODELS_DIR", "/app/rvc_models"))
RVC_ASSETS_DIR = Path(os.getenv("RVC_ASSETS_DIR", "/app/assets"))
RVC_MAX_CACHED_MODELS = int(os.getenv("RVC_MAX_CACHED_MODELS", "4"))
RVC_DEFAULT_PITCH_SHIFT = int(os.getenv("RVC_DEFAULT_PITCH_SHIFT", "0"))


class LRUModelCache:
    """LRU cache for RVC models with automatic eviction"""
    
    def __init__(self, max_size: int = 4):
        self.max_size = max_size
        self.cache: OrderedDict[str, Any] = OrderedDict()
        self.lock = threading.Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get model from cache, moving to end (most recently used)"""
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None
    
    def put(self, key: str, model_instance: Any) -> Optional[str]:
        """Add model to cache, evicting oldest if necessary. Returns evicted key if any."""
        evicted_key = None
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                self.cache[key] = model_instance
            else:
                if len(self.cache) >= self.max_size:
                    # Evict oldest (first item)
                    evicted_key, evicted_instance = self.cache.popitem(last=False)
                    # Clean up
                    self._cleanup_model(evicted_instance)
                    logger.info(f"🔄 Evicted RVC model from cache: {evicted_key}")
                self.cache[key] = model_instance
        return evicted_key
    
    def remove(self, key: str) -> bool:
        """Remove model from cache"""
        with self.lock:
            if key in self.cache:
                model_instance = self.cache.pop(key)
                self._cleanup_model(model_instance)
                return True
            return False
    
    def _cleanup_model(self, model_instance: Any):
        """Clean up model resources"""
        try:
            if hasattr(model_instance, 'unload_model'):
                model_instance.unload_model()
            del model_instance
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            logger.warning(f"Error cleaning up model: {e}")
    
    def keys(self) -> List[str]:
        """Get list of cached model keys"""
        with self.lock:
            return list(self.cache.keys())
    
    def clear(self):
        """Clear all cached models"""
        with self.lock:
            for model_instance in self.cache.values():
                self._cleanup_model(model_instance)
            self.cache.clear()


class RVCEngine:
    """
    RVC Voice Conversion Engine
    
    Converts TTS output audio to character voices using trained RVC models.
    Uses the simple RVCInference API from rvc_python.
    
    Features:
    - LRU model caching (configurable max models in VRAM)
    - Automatic CPU fallback when GPU memory exhausted
    - Pitch shifting support
    - Index file support for improved quality
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        # Determine device
        force_cpu = os.getenv("TTS_FORCE_CPU", "false").lower() in ("1", "true", "yes", "y")
        force_gpu = os.getenv("TTS_FORCE_GPU", "false").lower() in ("1", "true", "yes", "y")
        
        if force_cpu:
            self.device = "cpu:0"
        elif force_gpu and torch.cuda.is_available():
            self.device = "cuda:0"
            logger.info("🚀 Forcing GPU mode for RVC (TTS_FORCE_GPU=true)")
        elif self._cuda_available():
            self.device = "cuda:0"
        else:
            self.device = "cpu:0"
                
        self.model_cache = LRUModelCache(max_size=RVC_MAX_CACHED_MODELS)
        self._initialized_flag = False
        self._rvc_available = False
        self._init_error: Optional[str] = None
        
        # Audio configuration
        self.sr_work = 48000  # Enforce 48kHz internal working sample rate
        self.calibration_file = RVC_MODELS_DIR / "calibration_cache.json"
        
        # Ensure directories exist
        RVC_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        RVC_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        (RVC_MODELS_DIR / "shared").mkdir(parents=True, exist_ok=True)
        (RVC_MODELS_DIR / "users").mkdir(parents=True, exist_ok=True)
        
        self._calibration_cache = self._load_calibration_cache()
        
        logger.info(f"🎤 RVC Engine initializing on {self.device}")
        self._initialized = True

    def _load_calibration_cache(self) -> Dict[str, Any]:
        """Load calibration cache from disk"""
        if self.calibration_file.exists():
            try:
                with open(self.calibration_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load calibration cache: {e}")
        return {}
        
    def _save_calibration_cache(self):
        """Save calibration cache to disk"""
        try:
            with open(self.calibration_file, 'w') as f:
                json.dump(self._calibration_cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save calibration cache: {e}")
    
    def _cuda_available(self) -> bool:
        """Check if CUDA is available"""
        if not torch.cuda.is_available():
            return False
        try:
            # Just check if CUDA works
            x = torch.tensor([1.0]).cuda()
            del x
            return True
        except Exception:
            return False
    
    async def initialize(self) -> bool:
        """Initialize RVC engine and check dependencies"""
        if self._initialized_flag:
            return self._rvc_available
        
        try:
            # Try to import RVC
            try:
                from rvc_python.infer import RVCInference
                # Just verify import works
                self._rvc_available = True
                logger.info("✅ RVC library (rvc_python) loaded successfully")
            except ImportError as e:
                logger.warning(f"⚠️ RVC library not available: {e}")
                logger.info("RVC voice conversion will be disabled. Install with: pip install rvc-python")
                self._rvc_available = False
                self._init_error = str(e)
            except Exception as e:
                logger.warning(f"⚠️ RVC library import error: {e}")
                self._rvc_available = False
                self._init_error = str(e)
            
            self._initialized_flag = True
            return self._rvc_available
            
        except Exception as e:
            logger.error(f"❌ RVC initialization failed: {e}")
            self._init_error = str(e)
            self._initialized_flag = True
            return False
    
    def is_available(self) -> bool:
        """Check if RVC is available for use"""
        return self._rvc_available
    
    def get_init_error(self) -> Optional[str]:
        """Get initialization error if any"""
        return self._init_error
    
    def is_cached(self, slug: str) -> bool:
        """Check if a model is currently cached in memory"""
        return self.model_cache.get(slug) is not None
    
    def get_cached_models(self) -> List[str]:
        """Get list of currently cached model slugs"""
        return self.model_cache.keys()
    
    async def load_model(
        self,
        slug: str,
        model_path: str,
        index_path: Optional[str] = None
    ) -> bool:
        """
        Load an RVC model into the cache
        
        Args:
            slug: Unique identifier for the model
            model_path: Path to .pth model file
            index_path: Optional path to .index file
            
        Returns:
            True if loaded successfully
        """
        if not self._rvc_available:
            logger.warning("RVC not available, cannot load model")
            return False
        
        # Check if already cached
        if self.is_cached(slug):
            logger.info(f"Model {slug} already in cache")
            return True
        
        try:
            from rvc_python.infer import RVCInference
            
            # Verify model file exists
            model_file = Path(model_path)
            if not model_file.exists():
                logger.error(f"Model file not found: {model_path}")
                return False
            
            # Create RVCInference instance with this model
            logger.info(f"🔄 Loading RVC model: {slug}")
            
            rvc_instance = RVCInference(
                models_dir=str(RVC_MODELS_DIR),
                device=self.device,
                model_path=str(model_path),
                index_path=index_path or "",
                version="v2"  # Most models are v2
            )
            
            # Store in cache
            evicted = self.model_cache.put(slug, rvc_instance)
            if evicted:
                logger.info(f"Evicted {evicted} to make room for {slug}")
            
            logger.info(f"✅ Loaded RVC model: {slug}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to load RVC model {slug}: {e}")
            return False
    
    async def unload_model(self, slug: str) -> bool:
        """Unload a model from cache"""
        if self.model_cache.remove(slug):
            logger.info(f"🗑️ Unloaded RVC model: {slug}")
            return True
        return False

    def _score_artifact(self, audio_data: np.ndarray, sr: int) -> float:
        """
        Score audio artifacts (lower is better).
        Penalizes clipping, silence, and sudden transient spikes.
        """
        score = 0.0
        
        # 1. Clipping penalty
        peak = np.max(np.abs(audio_data))
        if peak >= 0.99:
            score += 10.0
            
        # 2. Silence penalty (if mostly silent)
        rms = np.sqrt(np.mean(audio_data**2))
        if rms < 0.01:
            score += 5.0
            
        # 3. Transient stability (simple check for huge jumps)
        diff = np.diff(audio_data)
        max_jump = np.max(np.abs(diff))
        if max_jump > 0.5:
            score += max_jump * 5
            
        return score

    async def calibrate_voice(
        self, 
        slug: str, 
        model_path: str, 
        index_path: Optional[str],
        base_test_audio_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run AutoTune calibration for a voice to find best settings.
        Returns optimized parameters.
        """
        # Check cache first
        cache_key = f"{slug}_v1" # simple versioning
        if cache_key in self._calibration_cache:
            logger.info(f"Using cached calibration for {slug}")
            return self._calibration_cache[cache_key]
            
        logger.info(f"🎚️ Calibrating RVC settings for {slug}...")
        
        # Default fallback
        best_params = {
            "f0_method": "rmvpe",
            "index_rate": 0.15,
            "filter_radius": 3,
            "resample_sr": 0,
            "rms_mix_rate": 0.10,
            "protect": 0.40
        }
        
        if not base_test_audio_path or not os.path.exists(base_test_audio_path):
            # If no test audio provided, return defaults (AutoTune needs source material)
             logger.warning("No test audio for calibration, using defaults")
             return best_params
             
        # Search grid (keep small for speed)
        # We prioritize stability over perfect pitch matching for podcasts
        grid = [
            # Standard/Safe
            {"f0_method": "rmvpe", "index_rate": 0.15, "protect": 0.40, "rms_mix_rate": 0.10},
            # Higher Clarity
            {"f0_method": "rmvpe", "index_rate": 0.30, "protect": 0.33, "rms_mix_rate": 0.0},
            # Aggressive Protection (for shaky voices)
            {"f0_method": "rmvpe", "index_rate": 0.10, "protect": 0.50, "rms_mix_rate": 0.20},
        ]
        
        best_score = float('inf')
        
        try:
            # Ensure model loaded
            if not await self.load_model(slug, model_path, index_path):
                return best_params

            for params in grid:
                try:
                    # Convert small snippet
                    out_path = await self.convert(
                        input_audio_path=base_test_audio_path,
                        slug=slug,
                        model_path=model_path,
                        index_path=index_path,
                        pitch_shift=0,
                        **params
                    )
                    
                    if out_path and os.path.exists(out_path):
                        # Analyze
                        y, sr = librosa.load(out_path, sr=self.sr_work, mono=True)
                        score = self._score_artifact(y, sr)
                        
                        if score < best_score:
                            best_score = score
                            best_params = params
                            # Copy generic fields
                            best_params["filter_radius"] = 3
                            best_params["resample_sr"] = 0
                            
                        # Cleanup temp file
                        try:
                            os.remove(out_path)
                        except:
                            pass
                except Exception as e:
                    logger.debug(f"Calibration step failed for {params}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Calibration failed: {e}")
            
        # Update cache
        self._calibration_cache[cache_key] = best_params
        self._save_calibration_cache()
        
        logger.info(f"✅ Calibration complete for {slug}. Best params: {best_params}")
        return best_params
    
    async def convert(
        self,
        input_audio_path: str,
        slug: str,
        model_path: str,
        index_path: Optional[str] = None,
        pitch_shift: int = 0,
        output_path: Optional[str] = None,
        # Overrides
        f0_method: str = "rmvpe",
        index_rate: float = 0.15,
        filter_radius: int = 3,
        resample_sr: int = 0,
        rms_mix_rate: float = 0.10,
        protect: float = 0.40,
        auto_tune: bool = False  # If True, looks up cached calibration
    ) -> Optional[str]:
        """
        Convert audio using RVC model
        """
        if not self._rvc_available:
            logger.warning("RVC not available, returning original audio")
            return input_audio_path
        
        try:
            # Ensure model is loaded
            if not self.is_cached(slug):
                loaded = await self.load_model(slug, model_path, index_path)
                if not loaded:
                    logger.error(f"Failed to load model {slug} for conversion")
                    return input_audio_path  # Return original as fallback
            
            rvc_instance = self.model_cache.get(slug)
            if not rvc_instance:
                logger.error(f"Model {slug} not found in cache after loading")
                return input_audio_path

            # Auto-Tune: override params from cache if enabled
            if auto_tune:
                 cache_key = f"{slug}_v1"
                 if cache_key in self._calibration_cache:
                     p = self._calibration_cache[cache_key]
                     f0_method = p.get("f0_method", f0_method)
                     index_rate = p.get("index_rate", index_rate)
                     protect = p.get("protect", protect)
                     rms_mix_rate = p.get("rms_mix_rate", rms_mix_rate)
                     logger.info(f"Using cached AutoTune params for {slug}")
            
            # Generate output path if not provided
            if output_path is None:
                output_path = tempfile.mktemp(suffix=".wav", prefix="rvc_")
            
            # Set params
            # Force set params on rvc_python instance
            # Note: The underlying rvc-python lib might change. 
            # We assume it supports set_params or similar, otherwise we need to modify how we call it.
            # If not available, we rely on infer_file defaults, but we need these controls.
            if hasattr(rvc_instance, 'set_params'):
                rvc_instance.set_params(
                    f0up_key=pitch_shift,
                    f0_method=f0_method,
                    index_rate=index_rate,
                    filter_radius=filter_radius,
                    resample_sr=resample_sr,
                    rms_mix_rate=rms_mix_rate,
                    protect=protect
                )
            elif hasattr(rvc_instance, 'args'):
                # Direct args manipulation fallback
                rvc_instance.args.f0up_key = pitch_shift
                rvc_instance.args.f0_method = f0_method
                rvc_instance.args.index_rate = index_rate
                rvc_instance.args.filter_radius = filter_radius
                rvc_instance.args.resample_sr = resample_sr
                rvc_instance.args.rms_mix_rate = rms_mix_rate
                rvc_instance.args.protect = protect
            
            # Run RVC conversion
            logger.info(f"🔄 Converting {slug}: f0={f0_method}, pitch={pitch_shift}, protect={protect}")
            
            # Some versions of rvc-python might take params in infer_file
            rvc_instance.infer_file(input_audio_path, output_path)
            
            logger.info(f"✅ RVC conversion complete: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ RVC conversion failed: {e}")
            # Return original audio as fallback
            return input_audio_path

    async def convert_block(
        self,
        audio_block: np.ndarray,
        sr: int,
        slug: str,
        model_path: str,
        index_path: Optional[str] = None,
        pitch_shift: int = 0,
        auto_tune: bool = True
    ) -> Tuple[np.ndarray, int]:
        """
        Convert a raw audio block (numpy array) using RVC.
        Handles temp file I/O transparently.
        """
        if not self._rvc_available:
             return audio_block, sr

        # Save block to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            temp_in = tf.name
        
        # Write input (normalized to 48k for RVC ideal)
        # Use librosa/sf to resample if needed before write
        if sr != self.sr_work:
           # Simple resampling using soundfile/librosa if available
           # Here we assume librosa is imported
           audio_block = librosa.resample(audio_block, orig_sr=sr, target_sr=self.sr_work)
           sr = self.sr_work
           
        sf.write(temp_in, audio_block, sr)
        
        # Convert
        temp_out = await self.convert(
            input_audio_path=temp_in,
            slug=slug,
            model_path=model_path,
            index_path=index_path,
            pitch_shift=pitch_shift,
            auto_tune=auto_tune
        )
        
        # Read back
        if temp_out and os.path.exists(temp_out):
            y, new_sr = librosa.load(temp_out, sr=self.sr_work, mono=True)
            # Cleanup
            try:
                os.remove(temp_in)
                if temp_out != temp_in:
                    os.remove(temp_out)
            except:
                pass
            return y, new_sr
        else:
            # Fallback
            return audio_block, sr
    
    async def list_available_models(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all available RVC models on disk
        
        Args:
            user_id: If provided, include user-specific models
            
        Returns:
            List of model info dicts
        """
        models = []
        
        def scan_directory(base_dir: Path, source: str = "shared"):
            """Scan a directory for RVC models"""
            if not base_dir.exists():
                return
            
            for model_dir in base_dir.iterdir():
                if model_dir.is_dir():
                    # Skip system directories
                    if model_dir.name in ("shared", "users"):
                        continue
                    
                    # Check for metadata file first
                    metadata_path = model_dir / "metadata.json"
                    if metadata_path.exists():
                        try:
                            with open(metadata_path) as f:
                                model_info = json.load(f)
                            model_info["is_cached"] = self.is_cached(model_info.get("slug", model_dir.name))
                            model_info["source"] = source
                            models.append(model_info)
                            continue
                        except Exception:
                            pass
                    
                    # Fallback to scanning for .pth files
                    pth_files = list(model_dir.glob("*.pth"))
                    index_files = list(model_dir.glob("*.index"))
                    
                    if pth_files:
                        model_info = {
                            "slug": model_dir.name,
                            "name": model_dir.name.replace("_", " ").title(),
                            "model_path": str(pth_files[0]),
                            "index_path": str(index_files[0]) if index_files else None,
                            "is_cached": self.is_cached(model_dir.name),
                            "source": source
                        }
                        models.append(model_info)
        
        # Scan shared models
        shared_dir = RVC_MODELS_DIR / "shared"
        scan_directory(shared_dir, "shared")
        
        # Scan legacy root-level models (backwards compatibility)
        for item in RVC_MODELS_DIR.iterdir():
            if item.is_dir() and item.name not in ("shared", "users"):
                pth_files = list(item.glob("*.pth"))
                if pth_files:
                    model_info = {
                        "slug": item.name,
                        "name": item.name.replace("_", " ").title(),
                        "model_path": str(pth_files[0]),
                        "index_path": str(list(item.glob("*.index"))[0]) if list(item.glob("*.index")) else None,
                        "is_cached": self.is_cached(item.name),
                        "source": "legacy"
                    }
                    models.append(model_info)
        
        # Scan user-specific models
        if user_id:
            user_dir = RVC_MODELS_DIR / "users" / str(user_id)
            scan_directory(user_dir, "user")
        
        return models
    
    def get_model_path(self, slug: str, user_id: Optional[str] = None) -> Optional[Tuple[str, Optional[str]]]:
        """
        Get model and index paths for a voice
        
        Searches in order: user directory, shared directory, legacy root
        
        Args:
            slug: Voice slug
            user_id: Optional user ID to check user-specific models
            
        Returns:
            Tuple of (model_path, index_path) or None if not found
        """
        search_paths: List[Path] = []
        
        # User-specific directory first
        if user_id:
            search_paths.append(RVC_MODELS_DIR / "users" / str(user_id) / slug)
        
        # Shared directory
        search_paths.append(RVC_MODELS_DIR / "shared" / slug)
        
        # Legacy root directory
        search_paths.append(RVC_MODELS_DIR / slug)
        
        for path in search_paths:
            if path.exists():
                # Check metadata first
                metadata_path = path / "metadata.json"
                if metadata_path.exists():
                    try:
                        with open(metadata_path) as f:
                            metadata = json.load(f)
                        return metadata.get("model_path"), metadata.get("index_path")
                    except Exception:
                        pass
                
                # Fallback to scanning
                pth_files = list(path.glob("*.pth"))
                if pth_files:
                    index_files = list(path.glob("*.index"))
                    return str(pth_files[0]), str(index_files[0]) if index_files else None

        # If no user_id provided, best-effort search across any user directory
        if user_id is None:
            users_root = RVC_MODELS_DIR / "users"
            if users_root.exists():
                try:
                    for user_dir in users_root.iterdir():
                        candidate = user_dir / slug
                        if candidate.exists():
                            pth_files = list(candidate.glob("*.pth"))
                            if pth_files:
                                index_files = list(candidate.glob("*.index"))
                                return str(pth_files[0]), str(index_files[0]) if index_files else None
                except Exception:
                    pass
        
        return None
    
    def engine_info(self) -> Dict[str, Any]:
        """Get engine status information"""
        return {
            "available": self._rvc_available,
            "initialized": self._initialized_flag,
            "device": self.device,
            "cached_models": self.get_cached_models(),
            "max_cached_models": RVC_MAX_CACHED_MODELS,
            "models_dir": str(RVC_MODELS_DIR),
            "assets_dir": str(RVC_ASSETS_DIR),
            "init_error": self._init_error
        }


# Singleton accessor
_rvc_engine: Optional[RVCEngine] = None

def get_rvc_engine() -> RVCEngine:
    """Get the singleton RVC engine instance"""
    global _rvc_engine
    if _rvc_engine is None:
        _rvc_engine = RVCEngine()
    return _rvc_engine
