"""
Podcast Audio Generator
Converts script to audio using TTS (Chatterbox or ElevenLabs)
"""

import os
import logging
import tempfile
from typing import List, Dict, Any, Optional
from uuid import uuid4
from pathlib import Path

logger = logging.getLogger(__name__)

# Configuration
PODCAST_OUTPUT_PATH = os.getenv("PODCAST_OUTPUT_PATH", "/data/podcasts")
TTS_PROVIDER = os.getenv("PODCAST_TTS_PROVIDER", "chatterbox")

# Voice mappings for different TTS providers
CHATTERBOX_VOICES = {
    "voice_1": None,  # Default voice
    "voice_2": None,  # Different speaker (will use different reference)
}

ELEVENLABS_VOICES = {
    "voice_1": "21m00Tcm4TlvDq8ikWAM",  # Rachel
    "voice_2": "yoZ06aMxZJJ28mfd3POQ",  # Sam
}


class AudioGenerator:
    """Generates podcast audio from script"""
    
    def __init__(self, output_path: Optional[str] = None, tts_provider: Optional[str] = None):
        self.output_path = output_path or PODCAST_OUTPUT_PATH
        self.tts_provider = tts_provider or TTS_PROVIDER
        
        # Ensure output directory exists
        os.makedirs(self.output_path, exist_ok=True)
        os.makedirs(os.path.join(self.output_path, "audio"), exist_ok=True)
        os.makedirs(os.path.join(self.output_path, "transcripts"), exist_ok=True)
    
    async def generate_audio(
        self,
        script: Dict[str, Any],
        output_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate audio from podcast script.
        
        Args:
            script: Script dict with 'transcript' key containing dialogue
            output_filename: Optional filename for output
            
        Returns:
            Dict with audio_path, duration, and any errors
        """
        transcript = script.get("transcript", [])
        speakers = script.get("speakers", [])
        
        if not transcript:
            return {"error": "No transcript provided"}
        
        # Generate unique filename if not provided
        if not output_filename:
            output_filename = f"podcast_{uuid4().hex[:8]}.mp3"
        
        output_path = os.path.join(self.output_path, "audio", output_filename)
        
        if self.tts_provider == "chatterbox":
            return await self._generate_with_chatterbox(transcript, speakers, output_path)
        elif self.tts_provider == "elevenlabs":
            return await self._generate_with_elevenlabs(transcript, speakers, output_path)
        else:
            return await self._generate_with_chatterbox(transcript, speakers, output_path)
    
    async def _generate_with_chatterbox(
        self,
        transcript: List[Dict[str, str]],
        speakers: List[Dict[str, str]],
        output_path: str
    ) -> Dict[str, Any]:
        """Generate audio using Chatterbox TTS"""
        try:
            from chatterbox.tts import ChatterboxTTS
            import torch
            import soundfile as sf
        except ImportError:
            logger.error("Chatterbox TTS not available")
            return {"error": "Chatterbox TTS not installed"}
        
        try:
            # Initialize Chatterbox
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = ChatterboxTTS.from_pretrained(device=device)
            
            # Create speaker voice map
            speaker_names = {s["name"]: i for i, s in enumerate(speakers)}
            
            audio_segments = []
            sample_rate = 24000  # Chatterbox default
            
            for segment in transcript:
                speaker = segment.get("speaker", "Speaker")
                dialogue = segment.get("dialogue", "")
                
                if not dialogue.strip():
                    continue
                
                # Generate audio for this segment
                try:
                    wav = model.generate(dialogue)
                    
                    # Convert to numpy if tensor
                    if hasattr(wav, 'cpu'):
                        wav = wav.cpu().numpy()
                    
                    audio_segments.append(wav)
                    
                    # Add small pause between segments
                    pause = torch.zeros(int(sample_rate * 0.5)).numpy()
                    audio_segments.append(pause)
                    
                except Exception as e:
                    logger.warning(f"Failed to generate segment: {e}")
                    continue
            
            if not audio_segments:
                return {"error": "No audio segments generated"}
            
            # Concatenate all segments
            import numpy as np
            full_audio = np.concatenate(audio_segments)
            
            # Save as MP3 (via WAV first, then convert)
            wav_path = output_path.replace('.mp3', '.wav')
            sf.write(wav_path, full_audio, sample_rate)
            
            # Try to convert to MP3 if pydub is available
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_wav(wav_path)
                audio.export(output_path, format="mp3")
                os.remove(wav_path)  # Clean up WAV
                final_path = output_path
            except ImportError:
                final_path = wav_path
            
            # Calculate duration
            duration_seconds = len(full_audio) / sample_rate
            
            return {
                "audio_path": final_path,
                "duration_seconds": int(duration_seconds),
                "segments_count": len(transcript),
                "provider": "chatterbox"
            }
            
        except Exception as e:
            logger.error(f"Chatterbox generation failed: {e}")
            return {"error": str(e)}
    
    async def _generate_with_elevenlabs(
        self,
        transcript: List[Dict[str, str]],
        speakers: List[Dict[str, str]],
        output_path: str
    ) -> Dict[str, Any]:
        """Generate audio using ElevenLabs API"""
        try:
            import requests
        except ImportError:
            return {"error": "requests library not available"}
        
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            return {"error": "ELEVENLABS_API_KEY not set"}
        
        try:
            # Map speakers to voice IDs
            speaker_voices = {}
            for i, speaker in enumerate(speakers):
                name = speaker["name"]
                voice_key = f"voice_{i + 1}"
                speaker_voices[name] = ELEVENLABS_VOICES.get(voice_key, ELEVENLABS_VOICES["voice_1"])
            
            audio_segments = []
            
            for segment in transcript:
                speaker = segment.get("speaker", "Speaker")
                dialogue = segment.get("dialogue", "")
                
                if not dialogue.strip():
                    continue
                
                voice_id = speaker_voices.get(speaker, ELEVENLABS_VOICES["voice_1"])
                
                # Call ElevenLabs API
                response = requests.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={
                        "xi-api-key": api_key,
                        "Content-Type": "application/json"
                    },
                    json={
                        "text": dialogue,
                        "model_id": "eleven_monolingual_v1",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75
                        }
                    },
                    timeout=60
                )
                
                if response.status_code == 200:
                    audio_segments.append(response.content)
                else:
                    logger.warning(f"ElevenLabs API error: {response.status_code}")
            
            if not audio_segments:
                return {"error": "No audio segments generated"}
            
            # Combine audio segments
            from pydub import AudioSegment
            import io
            
            combined = AudioSegment.empty()
            for audio_bytes in audio_segments:
                segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
                combined += segment
                # Add pause
                combined += AudioSegment.silent(duration=500)
            
            # Export
            combined.export(output_path, format="mp3")
            
            return {
                "audio_path": output_path,
                "duration_seconds": int(len(combined) / 1000),
                "segments_count": len(transcript),
                "provider": "elevenlabs"
            }
            
        except Exception as e:
            logger.error(f"ElevenLabs generation failed: {e}")
            return {"error": str(e)}
    
    def get_audio_url(self, audio_path: str) -> str:
        """Convert file path to URL for serving"""
        # This should be adapted based on how files are served
        filename = os.path.basename(audio_path)
        return f"/api/notebooks/podcasts/audio/{filename}"

