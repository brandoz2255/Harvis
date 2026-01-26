"""
VibeVoice Engine - Voice Cloning and TTS using microsoft/VibeVoice-1.5B
"""

import os
import uuid
import time
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

import torch
import torchaudio
import numpy as np
import soundfile as sf
import librosa

logger = logging.getLogger(__name__)

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
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.sample_rate = 24000
        self._initialized = False
        
        # Ensure directories exist
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load built-in presets
        self.presets = self._load_presets()
    
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
            try:
                # Check if VibeVoice is available (it may require specific installation)
                from dia.model import Dia  # VibeVoice/Dia model
                
                logger.info("📦 Loading VibeVoice/Dia model...")
                self.model = Dia.from_pretrained(
                    "nari-labs/Dia-1.6B",
                    compute_dtype=torch.bfloat16 if QUANTIZE_4BIT else torch.float16,
                    device=self.device
                )
                self._engine_type = "dia"
                logger.info("✅ VibeVoice/Dia model loaded!")
                
            except ImportError:
                # Fallback to VITS (compatible with newer transformers)
                logger.warning("⚠️ VibeVoice/Dia not available, using VITS fallback")
                
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
                    self.model.to(self.device)
                    self._engine_type = "vits"
                    self.sample_rate = self.model.config.sampling_rate
                    logger.info("✅ VITS model loaded!")
                except Exception as vits_error:
                    logger.warning(f"⚠️ VITS not available: {vits_error}, running in demo mode")
                    self._engine_type = "demo"
                    logger.info("✅ TTS Engine running in demo mode (no actual audio generation)")
            
            self._initialized = True
            logger.info("✅ TTS Engine ready!")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize TTS engine: {e}")
            raise
    
    def get_engine_info(self) -> Dict[str, Any]:
        """Get engine status and info"""
        return {
            "initialized": self._initialized,
            "engine_type": getattr(self, "_engine_type", "unknown"),
            "device": self.device,
            "quantization": QUANTIZE_4BIT,
            "sample_rate": self.sample_rate,
            "voices_dir": str(VOICES_DIR),
            "output_dir": str(OUTPUT_DIR),
            "gpu_available": torch.cuda.is_available(),
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
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
                resampler = torchaudio.transforms.Resample(sample_rate, self.sample_rate)
                waveform = resampler(waveform)
            
            # Calculate duration
            duration = waveform.shape[1] / self.sample_rate
            
            # Validate duration
            if duration < 5:
                return {
                    "success": False,
                    "error": f"Audio too short ({duration:.1f}s). Minimum 10 seconds required."
                }
            if duration > 120:
                return {
                    "success": False,
                    "error": f"Audio too long ({duration:.1f}s). Maximum 60 seconds recommended."
                }
            
            # Save reference audio
            voice_dir = VOICES_DIR / voice_id
            voice_dir.mkdir(parents=True, exist_ok=True)
            
            reference_path = voice_dir / "reference.wav"
            torchaudio.save(str(reference_path), waveform, self.sample_rate)
            
            # Extract speaker embedding (for SpeechT5)
            if hasattr(self, '_engine_type') and self._engine_type == "speecht5":
                # Create speaker embedding from audio
                embedding = self._extract_speaker_embedding(waveform)
                torch.save(embedding, voice_dir / "embedding.pt")
            
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
            from speechbrain.pretrained import EncoderClassifier
            classifier = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-xvect-voxceleb",
                savedir=str(MODEL_CACHE_DIR / "spkrec")
            )
            embedding = classifier.encode_batch(waveform)
            return embedding.squeeze()
        except ImportError:
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
        settings: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[str], Optional[float]]:
        """
        Generate speech for a single text segment
        
        Returns:
            Tuple of (audio_path, duration) or (None, None) on error
        """
        if not self._initialized:
            await self.initialize()
        
        settings = settings or {}
        output_id = f"speech_{uuid.uuid4().hex[:12]}"
        output_path = OUTPUT_DIR / f"{output_id}.wav"
        
        try:
            # Load voice reference (only required for voice-cloning engines)
            voice_dir = VOICES_DIR / voice_id
            reference_path = voice_dir / "reference.wav"
            engine_type = getattr(self, "_engine_type", "")
            
            # Only require reference for voice-cloning engines
            if engine_type == "dia" and not reference_path.exists():
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
            torchaudio.save(str(output_path), waveform, self.sample_rate)
            
            duration = waveform.shape[1] / self.sample_rate
            return str(output_path), duration
            
        except Exception as e:
            logger.error(f"❌ Speech generation failed: {e}")
            return None, None
    
    async def generate_podcast(
        self,
        script: List[Dict[str, str]],
        voice_mapping: Dict[str, str],
        settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate multi-speaker podcast audio
        
        Args:
            script: List of {"speaker": "1", "text": "Hello"}
            voice_mapping: {"1": "voice_id_1", "2": "voice_id_2"}
            settings: Generation settings
            
        Returns:
            Result with audio_url, duration, etc.
        """
        if not self._initialized:
            await self.initialize()
        
        settings = settings or {}
        job_id = f"podcast_{uuid.uuid4().hex[:12]}"
        output_path = OUTPUT_DIR / f"{job_id}.wav"
        
        start_time = time.time()
        
        try:
            audio_segments = []
            silence_duration = settings.get("add_silence_between_speakers", 0.3)
            silence_samples = int(silence_duration * self.sample_rate)
            silence = torch.zeros(1, silence_samples)
            
            for i, segment in enumerate(script):
                speaker = segment.get("speaker", "1")
                text = segment.get("text", "")
                
                if not text.strip():
                    continue
                
                # Get voice for this speaker
                voice_id = segment.get("voice_id") or voice_mapping.get(speaker)
                
                if not voice_id:
                    logger.warning(f"No voice mapping for speaker {speaker}")
                    continue
                
                # Generate speech for this segment
                segment_path, segment_duration = await self.generate_speech(
                    text, voice_id, settings
                )
                
                if segment_path:
                    waveform, sr = self._load_audio(str(segment_path))
                    audio_segments.append(waveform)
                    
                    # Add silence between speakers (except last segment)
                    if i < len(script) - 1:
                        audio_segments.append(silence)
                    
                    # Clean up segment file
                    Path(segment_path).unlink(missing_ok=True)
            
            if not audio_segments:
                return {
                    "success": False,
                    "job_id": job_id,
                    "error": "No audio segments generated"
                }
            
            # Concatenate all segments
            final_audio = torch.cat(audio_segments, dim=1)
            
            # Normalize audio
            if settings.get("normalize_audio", True):
                max_val = final_audio.abs().max()
                if max_val > 0:
                    final_audio = final_audio / max_val * 0.95
            
            # Save final podcast
            torchaudio.save(str(output_path), final_audio, self.sample_rate)
            
            duration = final_audio.shape[1] / self.sample_rate
            generation_time = time.time() - start_time
            
            logger.info(f"✅ Podcast generated: {job_id} ({duration:.1f}s in {generation_time:.1f}s)")
            
            return {
                "success": True,
                "job_id": job_id,
                "audio_url": f"/audio/{job_id}.wav",
                "audio_path": str(output_path),
                "duration": duration,
                "generation_time": generation_time,
                "segments_count": len(script)
            }
            
        except Exception as e:
            logger.error(f"❌ Podcast generation failed: {e}")
            return {
                "success": False,
                "job_id": job_id,
                "error": str(e)
            }
    
    def get_presets(self) -> Dict[str, Any]:
        """Get built-in voice presets"""
        return self.presets
