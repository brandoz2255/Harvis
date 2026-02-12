"""
VibeVoice Engine - Voice Cloning and TTS using microsoft/VibeVoice-1.5B
With optional RVC (Retrieval-based Voice Conversion) post-processing
"""

import os
import re
import uuid
import time
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

import torch
import numpy as np
import soundfile as sf
import librosa

logger = logging.getLogger(__name__)

# torchaudio is optional - use librosa/soundfile as fallback
try:
    import torchaudio
    TORCHAUDIO_AVAILABLE = True
except (ImportError, OSError) as e:
    logger.warning(f"torchaudio not available: {e}")
    TORCHAUDIO_AVAILABLE = False
    torchaudio = None

# RVC Engine (lazy import to avoid circular dependencies)
_rvc_engine = None

def _get_rvc_engine():
    """Lazy load RVC engine"""
    global _rvc_engine
    if _rvc_engine is None:
        try:
            from .rvc_engine import get_rvc_engine
            _rvc_engine = get_rvc_engine()
        except ImportError:
            logger.warning("RVC engine not available")
            _rvc_engine = None
    return _rvc_engine


def _write_audio_with_soundfile(audio_path: str, waveform: torch.Tensor, sample_rate: int) -> None:
    """Write audio using soundfile to avoid torchcodec/FFmpeg dependency issues."""
    audio_data = waveform.detach().cpu().numpy()
    if audio_data.ndim == 2 and audio_data.shape[0] == 1:
        audio_data = audio_data.squeeze(0)
    elif audio_data.ndim == 2 and audio_data.shape[0] < audio_data.shape[1]:
        # Convert (channels, samples) -> (samples, channels)
        audio_data = audio_data.T
    audio_data = audio_data.astype(np.float32, copy=False)
    sf.write(audio_path, audio_data, sample_rate)


def _patch_torchaudio_save() -> None:
    """Patch torchaudio.save to fall back to soundfile when torchcodec is missing."""
    if not TORCHAUDIO_AVAILABLE:
        return
    try:
        original_save = torchaudio.save
    except Exception:
        return

    def _safe_save(filepath, waveform, sample_rate, *args, **kwargs):
        try:
            return original_save(filepath, waveform, sample_rate, *args, **kwargs)
        except Exception as e:
            if "torchcodec" not in str(e).lower():
                raise
            logger.warning("torchaudio.save failed (torchcodec missing). Falling back to soundfile.")
            _write_audio_with_soundfile(str(filepath), waveform, sample_rate)
            return None

    torchaudio.save = _safe_save


if TORCHAUDIO_AVAILABLE:
    _patch_torchaudio_save()


def _resample_audio(waveform: torch.Tensor, orig_sr: int, target_sr: int) -> torch.Tensor:
    """Resample audio using torchaudio if available, otherwise librosa."""
    if orig_sr == target_sr:
        return waveform
    
    if TORCHAUDIO_AVAILABLE:
        resampler = torchaudio.transforms.Resample(orig_sr, target_sr)
        return resampler(waveform)
    else:
        # Use librosa for resampling
        audio_np = waveform.numpy()
        if audio_np.ndim == 2:
            # Multi-channel: resample each channel
            resampled = np.stack([
                librosa.resample(audio_np[i], orig_sr=orig_sr, target_sr=target_sr)
                for i in range(audio_np.shape[0])
            ])
        else:
            resampled = librosa.resample(audio_np, orig_sr=orig_sr, target_sr=target_sr)
        return torch.from_numpy(resampled)

# Configuration
VOICES_DIR = Path(os.getenv("VOICES_DIR", "/app/voices"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/app/output"))
MODEL_CACHE_DIR = Path(os.getenv("MODEL_CACHE_DIR", "/app/models"))
QUANTIZE_4BIT = os.getenv("QUANTIZE_4BIT", "true").lower() == "true"


class VibeVoiceEngine:
    """
    VibeVoice TTS Engine using microsoft/VibeVoice-1.5B
    
    Features:
    - Zero-shot voice cloning from 10-60 second samples
    - Multi-speaker podcast generation
    - 4-bit quantization for 6-8GB VRAM usage
    """
    
    def __init__(self):
        self.model = None
        self.processor = None
        self.vocoder = None
        
        # Determine device
        force_cpu = os.getenv("TTS_FORCE_CPU", "false").lower() in ("1", "true", "yes", "y")
        force_gpu = os.getenv("TTS_FORCE_GPU", "false").lower() in ("1", "true", "yes", "y")
        
        if force_cpu:
            self.device = "cpu"
        elif force_gpu and torch.cuda.is_available():
            # Force GPU even if compute capability check fails (for nightly PyTorch with sm_120)
            self.device = "cuda"
            logger.info("🚀 Forcing GPU mode (TTS_FORCE_GPU=true)")
        elif self._cuda_supported():
            self.device = "cuda"
        else:
            self.device = "cpu"
            
        self.sample_rate = 24000
        self._initialized = False
        self._init_error: Optional[str] = None
        
        # Ensure directories exist
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load built-in presets
        self.presets = self._load_presets()
    
    def _cuda_supported(self) -> bool:
        """
        Return True if the current PyTorch build can run on the detected GPU.

        Our docker image currently ships with wheels that support up to sm_90.
        Newer GPUs (e.g., sm_120) will report CUDA available but cannot execute kernels.
        """
        if not torch.cuda.is_available():
            return False
        try:
            major, minor = torch.cuda.get_device_capability(0)
        except Exception:
            return False
        # PyTorch wheels in this stack support up to sm_90 (major 9).
        return major <= 9

    def _load_audio(self, audio_path: str) -> Tuple[torch.Tensor, int]:
        """Load audio using soundfile (avoids torchcodec dependency issues)"""
        try:
            # Use soundfile which doesn't require torchcodec
            audio_data, sample_rate = sf.read(audio_path)
            
            # Convert to float32 if needed
            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32)
            
            # Handle stereo to mono conversion
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
            
            # Convert to torch tensor with shape (1, samples)
            waveform = torch.from_numpy(audio_data).unsqueeze(0)
            
            return waveform, sample_rate
        except Exception as e:
            logger.warning(f"soundfile failed, trying librosa: {e}")
            # Fallback to librosa
            audio_data, sample_rate = librosa.load(audio_path, sr=None, mono=True)
            waveform = torch.from_numpy(audio_data).unsqueeze(0)
            return waveform, sample_rate

    def _save_audio(self, audio_path: str, waveform: torch.Tensor, sample_rate: int) -> None:
        """Save audio using soundfile to avoid torchcodec/FFmpeg dependency issues."""
        try:
            _write_audio_with_soundfile(audio_path, waveform, sample_rate)
        except Exception as e:
            logger.error(f"Failed to save audio with soundfile: {e}")
            raise
        
    def _load_presets(self) -> Dict[str, Any]:
        """Load built-in voice preset metadata"""
        presets_file = Path(__file__).parent.parent / "presets" / "built_in_voices.json"
        if presets_file.exists():
            with open(presets_file) as f:
                return json.load(f)
        return {}
    
    async def initialize(self):
        """Initialize the VibeVoice model"""
        if self._initialized:
            return
            
        logger.info("🎙️ Initializing VibeVoice Engine...")
        logger.info(f"   Device: {self.device}")
        logger.info(f"   4-bit quantization: {QUANTIZE_4BIT}")
        
        try:
            # Import here to avoid loading at module level
            from transformers import AutoProcessor, AutoModelForTextToWaveform
            
            model_name = "microsoft/speecht5_tts"  # Fallback model
            
            # Try to load VibeVoice if available
            dia_loaded = False
            enable_dia = os.getenv("TTS_ENABLE_DIA", "false").lower() in ("1", "true", "yes", "y")
            try:
                if not enable_dia:
                    raise ImportError("Dia disabled (TTS_ENABLE_DIA=false)")
                # Check if VibeVoice/Dia is available (installed from https://github.com/nari-labs/dia)
                from dia.model import Dia, ComputeDtype  # type: ignore

                # Allow forcing CPU for Dia (useful on GPUs unsupported by the torch wheel)
                force_cpu_for_dia = os.getenv("TTS_FORCE_CPU_FOR_DIA", "true").lower() in ("1", "true", "yes", "y")
                dia_device = "cpu" if (force_cpu_for_dia and self.device == "cpu") else self.device
                if self.device == "cuda" and not self._cuda_supported():
                    dia_device = "cpu"
                    logger.warning("⚠️ CUDA device detected but not supported by current PyTorch wheel; forcing Dia to CPU")
                if force_cpu_for_dia and dia_device == "cuda" and self._cuda_supported() is False:
                    dia_device = "cpu"

                logger.info(f"📦 Loading VibeVoice/Dia model on {dia_device}...")
                dia_compute_dtype = (
                    ComputeDtype.FLOAT32
                    if dia_device == "cpu"
                    else (ComputeDtype.BFLOAT16 if QUANTIZE_4BIT else ComputeDtype.FLOAT16)
                )
                self.model = Dia.from_pretrained(
                    "nari-labs/Dia-1.6B",
                    compute_dtype=dia_compute_dtype,
                    device=dia_device
                )
                self._engine_type = "dia"
                dia_loaded = True
                logger.info("✅ VibeVoice/Dia model loaded!")

            except Exception as dia_error:
                logger.warning(f"⚠️ Dia init failed, falling back to VITS: {dia_error}")
                self._init_error = str(dia_error)

            if not dia_loaded:
                # Prefer SpeechT5 voice-cloning fallback (uses speaker embeddings)
                speecht5_loaded = False
                try:
                    from transformers import SpeechT5Processor, SpeechT5ForTextToSpeech, SpeechT5HifiGan

                    logger.info("📦 Loading SpeechT5 voice-cloning model...")
                    # Respect TTS_FORCE_GPU for RTX 50 series with PyTorch nightly
                    force_gpu = os.getenv("TTS_FORCE_GPU", "false").lower() in ("1", "true", "yes", "y")
                    if force_gpu and torch.cuda.is_available():
                        tts_device = "cuda"
                        logger.info("🚀 Forcing GPU mode for SpeechT5 (TTS_FORCE_GPU=true)")
                    else:
                        tts_device = "cuda" if self._cuda_supported() else "cpu"
                    self.device = tts_device

                    self.processor = SpeechT5Processor.from_pretrained(
                        "microsoft/speecht5_tts",
                        cache_dir=str(MODEL_CACHE_DIR)
                    )
                    self.model = SpeechT5ForTextToSpeech.from_pretrained(
                        "microsoft/speecht5_tts",
                        cache_dir=str(MODEL_CACHE_DIR)
                    ).to(tts_device)
                    self.vocoder = SpeechT5HifiGan.from_pretrained(
                        "microsoft/speecht5_hifigan",
                        cache_dir=str(MODEL_CACHE_DIR)
                    ).to(tts_device)
                    self._engine_type = "speecht5"
                    self.sample_rate = 16000
                    speecht5_loaded = True
                    logger.info(f"✅ SpeechT5 loaded on {tts_device}!")
                except Exception as speecht5_error:
                    logger.warning(f"⚠️ SpeechT5 not available: {speecht5_error}")

                if not speecht5_loaded:
                    # Final fallback to VITS (does not support voice cloning, but keeps service functional)
                    try:
                        from transformers import VitsModel, AutoTokenizer

                        vits_model_name = "facebook/mms-tts-eng"
                        self.processor = AutoTokenizer.from_pretrained(
                            vits_model_name,
                            cache_dir=str(MODEL_CACHE_DIR)
                        )
                        self.model = VitsModel.from_pretrained(
                            vits_model_name,
                            cache_dir=str(MODEL_CACHE_DIR)
                        )
                        # Only move to CUDA if supported by this PyTorch build
                        vits_device = "cuda" if self._cuda_supported() else "cpu"
                        self.model.to(vits_device)
                        self._engine_type = "vits"
                        self.device = vits_device
                        self.sample_rate = self.model.config.sampling_rate
                        logger.info(f"✅ VITS model loaded on {vits_device}!")
                    except Exception as vits_error:
                        logger.warning(f"⚠️ VITS not available: {vits_error}, running in demo mode")
                        self._engine_type = "demo"
                        self.device = "cpu"
                        logger.info("✅ TTS Engine running in demo mode (no actual audio generation)")
            
            self._initialized = True
            logger.info("✅ TTS Engine ready!")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize TTS engine: {e}")
            self._init_error = str(e)
            raise
    
    def get_engine_info(self) -> Dict[str, Any]:
        """Get engine status and info"""
        # Check if GPU is actually available (CUDA accessible)
        gpu_available = torch.cuda.is_available()
        force_gpu = os.getenv("TTS_FORCE_GPU", "false").lower() in ("1", "true", "yes", "y")
        gpu_in_use = self.device == "cuda"
        return {
            "initialized": self._initialized,
            "engine_type": getattr(self, "_engine_type", "unknown"),
            "device": self.device,
            "quantization": QUANTIZE_4BIT,
            "sample_rate": self.sample_rate,
            "voices_dir": str(VOICES_DIR),
            "output_dir": str(OUTPUT_DIR),
            "gpu_available": gpu_available,
            "gpu_in_use": gpu_in_use,
            "gpu_forced": force_gpu,
            "gpu_name": torch.cuda.get_device_name(0) if gpu_available else None,
            "init_error": self._init_error
        }
    
    async def clone_voice(
        self,
        audio_path: str,
        voice_name: str,
        description: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clone a voice from an audio sample
        
        Args:
            audio_path: Path to reference audio (10-60 seconds)
            voice_name: Name for the cloned voice
            description: Optional description
            user_id: Optional user identifier
            
        Returns:
            Voice data dictionary
        """
        if not self._initialized:
            await self.initialize()
            
        voice_id = f"voice_{uuid.uuid4().hex[:12]}"
        
        try:
            # Load and validate audio (using soundfile to avoid torchcodec issues)
            waveform, sample_rate = self._load_audio(str(audio_path))
            
            # Convert to mono if stereo
            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0, keepdim=True)
            
            # Resample if necessary
            if sample_rate != self.sample_rate:
                waveform = _resample_audio(waveform, sample_rate, self.sample_rate)
            
            # Calculate duration
            duration = waveform.shape[1] / self.sample_rate
            
            # Validate minimum duration (no maximum - allows long clips like 7+ minutes)
            if duration < 5:
                return {
                    "success": False,
                    "error": f"Audio too short ({duration:.1f}s). Minimum 10 seconds required."
                }
            # Log info for long clips but allow them
            if duration > 120:
                logger.info(f"Processing long audio clip: {duration:.1f}s ({duration/60:.1f} minutes)")
            
            # Save reference audio
            voice_dir = VOICES_DIR / voice_id
            voice_dir.mkdir(parents=True, exist_ok=True)
            
            reference_path = voice_dir / "reference.wav"
            self._save_audio(str(reference_path), waveform, self.sample_rate)
            
            # Extract speaker embedding (used by SpeechT5 voice cloning)
            try:
                embedding = self._extract_speaker_embedding(waveform)
                torch.save(embedding, voice_dir / "embedding.pt")
            except Exception as emb_error:
                logger.warning(f"⚠️ Failed to extract speaker embedding: {emb_error}")
            
            # Calculate quality score (simple SNR-based estimate)
            quality_score = self._estimate_audio_quality(waveform)
            
            # Save voice metadata
            voice_data = {
                "voice_id": voice_id,
                "voice_name": voice_name,
                "description": description,
                "voice_type": "user",
                "reference_audio_path": str(reference_path),
                "reference_duration": duration,
                "quality_score": quality_score,
                "created_at": datetime.utcnow().isoformat(),
                "user_id": user_id
            }
            
            with open(voice_dir / "metadata.json", "w") as f:
                json.dump(voice_data, f, indent=2)
            
            logger.info(f"✅ Voice cloned: {voice_name} ({voice_id})")
            
            return {
                "success": True,
                "voice": voice_data
            }
            
        except Exception as e:
            logger.error(f"❌ Voice cloning failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _extract_speaker_embedding(self, waveform: torch.Tensor) -> torch.Tensor:
        """Extract speaker embedding from audio"""
        # Simple average embedding for SpeechT5
        # In production, use a proper speaker encoder like resemblyzer
        try:
            # Try new SpeechBrain 1.0+ API first
            try:
                from speechbrain.inference.speaker import SpeakerRecognition
                classifier = SpeakerRecognition.from_hparams(
                    source="speechbrain/spkrec-xvect-voxceleb",
                    savedir=str(MODEL_CACHE_DIR / "spkrec")
                )
            except (ImportError, ModuleNotFoundError):
                # Fallback to legacy API for older versions
                from speechbrain.pretrained import EncoderClassifier
                classifier = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-xvect-voxceleb",
                    savedir=str(MODEL_CACHE_DIR / "spkrec")
                )
            embedding = classifier.encode_batch(waveform)
            return embedding.squeeze()
        except (ImportError, Exception) as e:
            logger.warning(f"⚠️ SpeechBrain embedding extraction failed: {e}")
            # Fallback: random embedding (not recommended for production)
            logger.warning("⚠️ SpeechBrain not available, using random embedding")
            return torch.randn(512)
    
    def _estimate_audio_quality(self, waveform: torch.Tensor) -> float:
        """Estimate audio quality score (0-1)"""
        # Simple signal-to-noise ratio based quality estimate
        signal_power = torch.mean(waveform ** 2).item()
        if signal_power > 0:
            # Normalize to 0-1 range
            snr_estimate = min(1.0, max(0.0, np.log10(signal_power * 1000 + 1) / 3))
            return round(snr_estimate, 2)
        return 0.5
    
    async def list_voices(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all available voices"""
        voices = []
        
        # Load user voices
        for voice_dir in VOICES_DIR.iterdir():
            if voice_dir.is_dir():
                metadata_path = voice_dir / "metadata.json"
                if metadata_path.exists():
                    with open(metadata_path) as f:
                        voice_data = json.load(f)
                        # Filter by user if specified
                        if user_id is None or voice_data.get("user_id") == user_id:
                            voices.append(voice_data)
        
        # Add built-in presets
        for preset_id, preset_data in self.presets.items():
            voices.append({
                "voice_id": preset_id,
                "voice_name": preset_data.get("name", preset_id),
                "description": preset_data.get("description", ""),
                "voice_type": "builtin",
                "category": preset_data.get("category", "general"),
                "requires_activation": preset_data.get("requires_activation", True),
                "activated": (VOICES_DIR / preset_id / "reference.wav").exists()
            })
        
        return voices
    
    async def get_voice(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific voice by ID"""
        voice_dir = VOICES_DIR / voice_id
        metadata_path = voice_dir / "metadata.json"
        
        if metadata_path.exists():
            with open(metadata_path) as f:
                return json.load(f)
        
        # Check built-in presets
        if voice_id in self.presets:
            preset = self.presets[voice_id]
            return {
                "voice_id": voice_id,
                "voice_name": preset.get("name", voice_id),
                "description": preset.get("description", ""),
                "voice_type": "builtin"
            }
        
        return None
    
    async def delete_voice(self, voice_id: str) -> bool:
        """Delete a user voice"""
        voice_dir = VOICES_DIR / voice_id
        
        if not voice_dir.exists():
            return False
        
        # Don't allow deleting built-in presets base data
        metadata_path = voice_dir / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                voice_data = json.load(f)
                if voice_data.get("voice_type") == "builtin":
                    logger.warning(f"Cannot delete built-in preset: {voice_id}")
                    return False
        
        import shutil
        shutil.rmtree(voice_dir)
        logger.info(f"🗑️ Voice deleted: {voice_id}")
        return True
    
    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        settings: Optional[Dict[str, Any]] = None,
        rvc_voice_slug: Optional[str] = None,
        rvc_model_path: Optional[str] = None,
        rvc_index_path: Optional[str] = None,
        rvc_pitch_shift: int = 0
    ) -> Tuple[Optional[str], Optional[float]]:
        """
        Generate speech for a single text segment
        
        Args:
            text: Text to synthesize
            voice_id: Base voice ID for TTS
            settings: TTS generation settings
            rvc_voice_slug: Optional RVC voice slug for post-processing
            rvc_model_path: Path to RVC model file
            rvc_index_path: Optional path to RVC index file
            rvc_pitch_shift: Pitch shift in semitones for RVC
        
        Returns:
            Tuple of (audio_path, duration) or (None, None) on error
        """
        if not self._initialized:
            await self.initialize()
        
        settings = settings or {}
        output_id = f"speech_{uuid.uuid4().hex[:12]}"
        output_path = OUTPUT_DIR / f"{output_id}.wav"
        
        try:
            engine_type = getattr(self, "_engine_type", "")

            # For engines that don't need voice references (vits, demo),
            # allow a special "__default__" voice_id to skip reference loading.
            if voice_id == "__default__":
                voice_dir = None
                reference_path = None
            else:
                # Load voice reference (only required for voice-cloning engines)
                voice_dir = VOICES_DIR / voice_id
                reference_path = voice_dir / "reference.wav"

            # Only require reference for voice-cloning engines
            if engine_type == "dia" and (reference_path is None or not reference_path.exists()):
                logger.error(f"Voice reference not found: {voice_id}")
                return None, None
            
            # Generate based on engine type
            
            if engine_type == "dia":
                # Use Dia/VibeVoice
                audio = self.model.generate(
                    text,
                    audio_prompt=str(reference_path),
                    cfg_scale=settings.get("cfg_scale", 1.3),
                    temperature=settings.get("temperature", 0.7)
                )
                waveform = torch.from_numpy(audio).unsqueeze(0)
                
            elif engine_type == "speecht5":
                # SpeechT5 voice cloning via speaker embedding
                if not self.processor or not self.model or not self.vocoder:
                    logger.error("SpeechT5 not initialized")
                    return None, None

                # Load speaker embedding if available; otherwise compute from reference audio
                speaker_embedding = None
                if voice_dir is not None:
                    emb_path = voice_dir / "embedding.pt"
                    if emb_path.exists():
                        speaker_embedding = torch.load(emb_path, map_location=self.device)
                    elif reference_path is not None and reference_path.exists():
                        ref_wave, ref_sr = self._load_audio(str(reference_path))
                        if ref_sr != self.sample_rate:
                            ref_wave = _resample_audio(ref_wave, ref_sr, self.sample_rate)
                        speaker_embedding = self._extract_speaker_embedding(ref_wave)
                        try:
                            torch.save(speaker_embedding, emb_path)
                        except Exception:
                            pass

                # Fallback: use default speaker embedding
                if speaker_embedding is None:
                    # Try CMU Arctic xvectors first (best quality)
                    try:
                        from datasets import load_dataset
                        embeddings_dataset = load_dataset(
                            "Matthijs/cmu-arctic-xvectors",
                            split="validation",
                            cache_dir=str(MODEL_CACHE_DIR),
                        )
                        speaker_embedding = torch.tensor(
                            embeddings_dataset[7306]["xvector"]
                        ).unsqueeze(0)
                        logger.info("Using default CMU Arctic speaker embedding for SpeechT5")
                    except Exception:
                        # Deterministic fallback: seeded random embedding (512-dim, normalised)
                        # Produces a consistent neutral voice without any external data
                        logger.warning("CMU Arctic xvectors unavailable, using deterministic default embedding")
                        rng = torch.Generator().manual_seed(42)
                        speaker_embedding = torch.randn(1, 512, generator=rng)
                        speaker_embedding = speaker_embedding / speaker_embedding.norm()

                # Ensure expected shape [1, 512]
                if speaker_embedding.dim() == 1:
                    speaker_embedding = speaker_embedding.unsqueeze(0)

                # SpeechT5 has a 600-token input limit.  Split long text
                # into sentence-sized chunks, generate each, and concatenate.
                MAX_TOKENS = 580  # leave a small margin below the 600 hard limit
                sentences = re.split(r'(?<=[.!?])\s+', text.strip())
                chunks: List[str] = []
                current_chunk = ""
                for sentence in sentences:
                    test = (current_chunk + " " + sentence).strip() if current_chunk else sentence
                    token_count = len(self.processor(text=test, return_tensors="pt")["input_ids"][0])
                    if token_count > MAX_TOKENS and current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = sentence
                    else:
                        current_chunk = test
                if current_chunk:
                    chunks.append(current_chunk)

                # If a single sentence still exceeds the limit, hard-split by words
                final_chunks: List[str] = []
                for chunk in chunks:
                    token_count = len(self.processor(text=chunk, return_tensors="pt")["input_ids"][0])
                    if token_count <= MAX_TOKENS:
                        final_chunks.append(chunk)
                    else:
                        words = chunk.split()
                        sub = ""
                        for word in words:
                            test_sub = (sub + " " + word).strip() if sub else word
                            if len(self.processor(text=test_sub, return_tensors="pt")["input_ids"][0]) > MAX_TOKENS and sub:
                                final_chunks.append(sub)
                                sub = word
                            else:
                                sub = test_sub
                        if sub:
                            final_chunks.append(sub)

                speaker_embedding = speaker_embedding.to(self.device)
                speech_parts = []
                for chunk_text in final_chunks:
                    inputs = self.processor(text=chunk_text, return_tensors="pt")
                    input_ids = inputs["input_ids"].to(self.device)
                    with torch.no_grad():
                        part = self.model.generate_speech(input_ids, speaker_embedding, vocoder=self.vocoder)
                    speech_parts.append(part.cpu())

                if not speech_parts:
                    logger.error("SpeechT5 produced no audio chunks")
                    return None, None

                waveform = torch.cat(speech_parts, dim=0).unsqueeze(0)

            elif engine_type == "vits":
                # Use VITS (doesn't use voice cloning, just generates speech)
                inputs = self.processor(text=text, return_tensors="pt").to(self.device)
                
                with torch.no_grad():
                    output = self.model(**inputs)
                    waveform = output.waveform.cpu()
                
            elif engine_type == "demo":
                # Demo mode - generate silence with a message
                logger.warning("Demo mode: generating placeholder audio")
                duration_seconds = len(text) * 0.05  # ~50ms per character
                samples = int(duration_seconds * self.sample_rate)
                waveform = torch.zeros(1, samples)
                
            else:
                logger.error(f"Unknown engine type: {engine_type}")
                return None, None
            
            # Save audio
            self._save_audio(str(output_path), waveform, self.sample_rate)
            
            # Apply RVC post-processing if requested
            final_output_path = str(output_path)
            if rvc_voice_slug and rvc_model_path:
                rvc_engine = _get_rvc_engine()
                if rvc_engine and rvc_engine.is_available():
                    logger.info(f"🎭 Applying RVC voice conversion: {rvc_voice_slug}")
                    rvc_output = await rvc_engine.convert(
                        input_audio_path=str(output_path),
                        slug=rvc_voice_slug,
                        model_path=rvc_model_path,
                        index_path=rvc_index_path,
                        pitch_shift=rvc_pitch_shift
                    )
                    if rvc_output and rvc_output != str(output_path):
                        # RVC conversion successful, use the converted audio
                        final_output_path = rvc_output
                        # Reload waveform for duration calculation
                        waveform, _ = self._load_audio(final_output_path)
                        logger.info(f"✅ RVC conversion applied: {rvc_voice_slug}")
                    else:
                        logger.warning(f"⚠️ RVC conversion returned original, using base TTS output")
                else:
                    logger.warning("⚠️ RVC not available, using base TTS output")
            
            duration = waveform.shape[1] / self.sample_rate
            return final_output_path, duration
            
        except Exception as e:
            logger.error(f"❌ Speech generation failed: {e}")
            return None, None
    
    async def generate_podcast(
        self,
        script: List[Dict[str, str]],
        voice_mapping: Dict[str, str],
        settings: Optional[Dict[str, Any]] = None,
        rvc_voice_mapping: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Generate multi-speaker podcast audio
        
        Args:
            script: List of {"speaker": "1", "text": "Hello"}
            voice_mapping: {"1": "voice_id_1", "2": "voice_id_2"} for base TTS
            settings: Generation settings
            rvc_voice_mapping: Optional RVC voice config per speaker:
                {"speaker_name": {"slug": "peter_griffin", "model_path": "...", "index_path": "...", "pitch_shift": 0}}
            
        Returns:
            Result with audio_url, duration, etc.
        """
        rvc_voice_mapping = rvc_voice_mapping or {}
        if not self._initialized:
            await self.initialize()
        
        settings = settings or {}
        job_id = f"podcast_{uuid.uuid4().hex[:12]}"
        output_path = OUTPUT_DIR / f"{job_id}.wav"
        
        start_time = time.time()
        
        try:
            generated_segments = []
            
            # Step 1: Generate Base Audio for all segments
            for i, line in enumerate(script):
                speaker = line.get("speaker", "1")
                text = line.get("text", "")
                
                if not text.strip():
                    continue
                    
                voice_id = line.get("voice_id") or voice_mapping.get(speaker)
                
                # Check for RVC (we don't apply it yet, just base TTS)
                # But we must validate voice_id for base TTS
                needs_voice_ref = self._engine_type == "dia"

                if not voice_id:
                    if needs_voice_ref:
                        logger.warning(f"No voice mapping for speaker {speaker}")
                        continue
                    else:
                        voice_id = "__default__"

                if voice_id != "__default__":
                    voice_dir = VOICES_DIR / voice_id
                    if not voice_dir.exists():
                        if needs_voice_ref:
                            logger.warning(f"Voice not found for speaker {speaker}: {voice_id}")
                            continue
                        else:
                            voice_id = "__default__"
                
                # Generate base TTS
                # Note: We intentionally DO NOT pass rvc params here.
                # RVC will be applied in block processing step.
                audio_path, duration = await self.generate_speech(
                    text=text, 
                    voice_id=voice_id, 
                    settings=settings
                )
                
                if audio_path:
                    generated_segments.append({
                        "index": i,
                        "speaker": speaker,
                        "audio_path": str(audio_path),
                        "duration": duration,
                        "text": text,
                        "voice_id": voice_id
                    })
                else:
                    logger.warning(f"Failed to generate segment {i}: {text[:20]}...")
            
            # Step 2: Apply RVC transformations (Block Processing)
            if rvc_voice_mapping:
                rvc_engine = _get_rvc_engine()
                if rvc_engine and rvc_engine.is_available():
                    
                    # Identify speakers needing RVC
                    rvc_tasks = {} # speaker -> list of segment indices
                    for idx, seg in enumerate(generated_segments):
                        spk = seg["speaker"]
                        if spk in rvc_voice_mapping:
                            if spk not in rvc_tasks:
                                rvc_tasks[spk] = []
                            rvc_tasks[spk].append(idx)
                    
                    # Process each RVC speaker
                    for spk, indices in rvc_tasks.items():
                        config = rvc_voice_mapping[spk]
                        slug = config.get("slug")
                        
                        logger.info(f"🎭 Processing block RVC for speaker: {spk} ({len(indices)} segments)")
                        
                        # 2a. Concatenate segments
                        block_audio = []
                        segment_lengths = []
                        
                        spacer_sr = 48000
                        spacer = np.zeros(int(0.1 * spacer_sr), dtype=np.float32) # 100ms spacer
                        
                        valid_segments = True
                        first_seg_path = None
                        
                        for idx in indices:
                            seg = generated_segments[idx]
                            path = seg["audio_path"]
                            if not first_seg_path: first_seg_path = path
                            
                            try:
                                # Use librosa to consistency with RVC engine
                                y, sr = librosa.load(path, sr=spacer_sr, mono=True)
                                block_audio.append(y)
                                block_audio.append(spacer)
                                segment_lengths.append(len(y))
                            except Exception as e:
                                logger.error(f"Error loading segment {idx} for block RVC: {e}")
                                valid_segments = False
                                break
                        
                        if not valid_segments or not block_audio:
                            continue
                            
                        full_block = np.concatenate(block_audio)
                        
                        # 2b. Auto-Tune Calibration (if needed)
                        try:
                            await rvc_engine.calibrate_voice(
                                slug=slug,
                                model_path=config.get("model_path"),
                                index_path=config.get("index_path"),
                                base_test_audio_path=first_seg_path
                            )
                        except Exception as e:
                            logger.warning(f"AutoTune skipped/failed: {e}")
                        
                        # 2c. Convert Block
                        converted_audio, conv_sr = await rvc_engine.convert_block(
                            audio_block=full_block,
                            sr=spacer_sr,
                            slug=slug,
                            model_path=config.get("model_path"),
                            index_path=config.get("index_path"),
                            pitch_shift=config.get("pitch_shift", 0),
                            auto_tune=True
                        )
                        
                        # 2d. Slice back
                        current_sample = 0
                        spacer_len_conv = int(0.1 * conv_sr)
                        
                        for i, original_len in enumerate(segment_lengths):
                            # Scale if SR changed (though convert_block usually returns same SR if resample_sr=0)
                            scale = conv_sr / spacer_sr
                            target_len = int(original_len * scale)
                            
                            start = current_sample
                            end = start + target_len
                            
                            if end > len(converted_audio):
                                end = len(converted_audio)
                                
                            seg_audio = converted_audio[start:end]
                            current_sample = end + int(spacer_len_conv * scale) # Skip spacer
                            
                            if len(seg_audio) > 0:
                                # Save back to file
                                seg_idx = indices[i]
                                seg = generated_segments[seg_idx]
                                
                                out_path = OUTPUT_DIR / f"{Path(seg['audio_path']).stem}_rvc.wav"
                                sf.write(str(out_path), seg_audio, conv_sr)
                                
                                # Update segment info
                                generated_segments[seg_idx]["audio_path"] = str(out_path)
                                generated_segments[seg_idx]["duration"] = len(seg_audio) / conv_sr
            
            # Step 3: Stitch Final Podcast
            if not generated_segments:
                return {
                    "success": False,
                    "job_id": job_id,
                    "error": "No audio segments generated"
                }

            final_audio_segments = []
            silence_duration = settings.get("add_silence_between_speakers", 0.5)
            # Using 48kHz for final master
            master_sr = 48000
            silence = np.zeros(int(silence_duration * master_sr), dtype=np.float32)
            
            for seg in generated_segments:
                try:
                    y, sr = librosa.load(seg["audio_path"], sr=master_sr, mono=True)
                    final_audio_segments.append(y)
                    final_audio_segments.append(silence)
                except Exception as e:
                    logger.error(f"Failed to load segment for stitching: {e}")
            
            if final_audio_segments:
                full_audio = np.concatenate(final_audio_segments)
                
                # Post-Processing
                try:
                    from ..utils.audio_post import process_podcast_master
                    full_audio = process_podcast_master(full_audio, master_sr)
                except Exception as e:
                    logger.error(f"Post-processing failed: {e}")
                
                # Save Final
                # We need to save as torch tensor using internal helper if we want consistency?
                # But internal helper _save_audio uses torchaudio or soundfile.
                # Let's just use soundfile directly for 48k float32
                sf.write(str(output_path), full_audio, master_sr)
                
                duration = len(full_audio) / master_sr
                generation_time = time.time() - start_time
                
                logger.info(f"✅ Podcast generated: {job_id} ({duration:.1f}s)")
                
                return {
                    "success": True,
                    "job_id": job_id,
                    "audio_url": f"/audio/{job_id}.wav",
                    "audio_path": str(output_path),
                    "duration": duration,
                    "generation_time": generation_time,
                    "segments_count": len(script)
                }
            
            return {
                "success": False,
                "error": "Stitching failed"
            }
            
        except Exception as e:
            logger.error(f"❌ Podcast generation failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "job_id": job_id,
                "error": str(e)
            }
    
    def get_presets(self) -> Dict[str, Any]:
        """Get built-in voice presets"""
        return self.presets
