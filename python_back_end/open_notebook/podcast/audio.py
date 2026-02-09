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
PODCAST_OUTPUT_PATH = os.getenv("PODCAST_OUTPUT_PATH", "/app/podcast_data")
TTS_PROVIDER = os.getenv("PODCAST_TTS_PROVIDER", "chatterbox")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://tts-service:8001")
PODCAST_TTS_CFG_SCALE = float(os.getenv("PODCAST_TTS_CFG_SCALE", "1.6"))
PODCAST_TTS_TEMPERATURE = float(os.getenv("PODCAST_TTS_TEMPERATURE", "0.4"))
PODCAST_TTS_NORMALIZE_AUDIO = os.getenv("PODCAST_TTS_NORMALIZE_AUDIO", "true").lower() in ("1", "true", "yes", "y")
PODCAST_TTS_SILENCE_BETWEEN_SPEAKERS = float(os.getenv("PODCAST_TTS_SILENCE_BETWEEN_SPEAKERS", "0.3"))

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
        
        voice_mapping = {
            speaker.get("name"): speaker.get("voice_id")
            for speaker in speakers
            if speaker.get("voice_id")
        }

        # Extract RVC voice mapping if speakers have rvc_voice_id
        rvc_voice_mapping = {
            speaker.get("name"): speaker.get("rvc_voice_id")
            for speaker in speakers
            if speaker.get("rvc_voice_id")
        }

        # If no explicit voice_mapping, build a default one using "__default__"
        # so the TTS service can generate with its default engine (VITS/SpeechT5)
        if not voice_mapping:
            unique_speakers = sorted({
                seg.get("speaker", "Speaker")
                for seg in transcript
                if seg.get("dialogue", "").strip()
            })
            voice_mapping = {name: "__default__" for name in unique_speakers}
            logger.info(f"No voice_ids on speakers, using TTS service default for: {unique_speakers}")

        if not output_filename:
            output_filename = f"podcast_{uuid4().hex[:8]}.wav"
        else:
            output_filename = os.path.splitext(output_filename)[0] + ".wav"
        output_path = os.path.join(self.output_path, "audio", output_filename)

        return await self._generate_with_tts_service(
            transcript, voice_mapping, output_path,
            rvc_voice_mapping=rvc_voice_mapping if rvc_voice_mapping else None
        )

    async def _generate_with_tts_service(
        self,
        transcript: List[Dict[str, str]],
        voice_mapping: Dict[str, str],
        output_path: str,
        rvc_voice_mapping: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Generate audio using the TTS service with voice mapping and optional RVC."""
        try:
            import httpx
        except ImportError:
            return {"error": "httpx library not available"}

        script_segments = [
            {"speaker": segment.get("speaker", "Speaker"), "text": segment.get("dialogue", "")}
            for segment in transcript
            if segment.get("dialogue", "").strip()
        ]

        if not script_segments:
            return {"error": "No valid script segments"}

        payload = {
            "script": script_segments,
            "voice_mapping": voice_mapping,
            "output_format": "wav",
            "normalize_audio": PODCAST_TTS_NORMALIZE_AUDIO,
            "add_silence_between_speakers": PODCAST_TTS_SILENCE_BETWEEN_SPEAKERS,
            "settings": {
                # For Dia/VibeVoice: lower temperature improves consistency; moderate cfg_scale improves adherence
                "cfg_scale": PODCAST_TTS_CFG_SCALE,
                "temperature": PODCAST_TTS_TEMPERATURE,
            }
        }
        
        # Add RVC voice mapping if provided
        if rvc_voice_mapping:
            payload["rvc_voice_mapping"] = rvc_voice_mapping
            logger.info(f"Using RVC voices for speakers: {list(rvc_voice_mapping.keys())}")

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(f"{TTS_SERVICE_URL}/generate/podcast", json=payload)
                if response.status_code != 200:
                    try:
                        return {"error": response.json()}
                    except Exception:
                        return {"error": response.text}

                result = response.json()
                audio_url = result.get("audio_url")
                if not audio_url:
                    return {"error": "TTS service returned no audio URL"}

                audio_response = await client.get(f"{TTS_SERVICE_URL}{audio_url}")
                if audio_response.status_code != 200:
                    return {"error": "Failed to download audio from TTS service"}

                with open(output_path, "wb") as f:
                    f.write(audio_response.content)

            duration_seconds = result.get("duration")
            return {
                "audio_path": output_path,
                "duration_seconds": int(duration_seconds) if duration_seconds else None,
                "segments_count": len(script_segments),
                "provider": "tts-service"
            }
        except Exception as e:
            logger.error(f"TTS service generation failed: {e}")
            return {"error": str(e)}
    
    async def _generate_with_chatterbox(
        self,
        transcript: List[Dict[str, str]],
        speakers: List[Dict[str, str]],
        output_path: str
    ) -> Dict[str, Any]:
        """Generate audio using Chatterbox TTS via central model_manager"""
        try:
            # Use the robust model_manager which handles CPU fallback and monkeypatches
            import sys
            # Ensure parent package is in path content root if needed
            # In a proper app structure getting 'model_manager' should be straightforward
            # But let's be safe usually it is available in context
            try:
                import model_manager
            except ImportError:
                # Fallback implementation if running standalone context
                import sys
                sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
                import model_manager

            import soundfile as sf
            import numpy as np
            import torch
        except ImportError as e:
            logger.error(f"Required modules not available: {e}")
            return {"error": f"Import error: {e}"}
        
        try:
            audio_segments = []
            segment_errors = []
            sample_rate = 24000
            total_segments = 0

            for segment in transcript:
                speaker = segment.get("speaker", "Speaker")
                dialogue = segment.get("dialogue", "")

                if not dialogue.strip():
                    continue

                total_segments += 1

                # Generate audio for this segment using robust manager
                try:
                    # generate_speech returns (sr, audio_numpy_array)
                    # It handles loading, caching, and CPU fallback automatically
                    sr, wav = model_manager.generate_speech(dialogue)
                    sample_rate = sr

                    audio_segments.append(wav)

                    # Add small pause between segments (0.5s)
                    pause = np.zeros(int(sample_rate * 0.5), dtype=np.float32)
                    audio_segments.append(pause)

                except Exception as e:
                    import traceback
                    error_detail = f"Segment {total_segments} ({speaker}): {type(e).__name__}: {e}"
                    segment_errors.append(error_detail)
                    logger.error(f"Failed to generate segment: {error_detail}")
                    logger.error(traceback.format_exc())
                    continue

            if not audio_segments:
                error_msg = f"No audio segments generated. {total_segments} segment(s) attempted, all failed."
                if segment_errors:
                    error_msg += f" Errors: {'; '.join(segment_errors[:5])}"
                logger.error(error_msg)
                return {"error": error_msg}
            
            # Concatenate all segments
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
            segment_errors = []
            total_segments = 0

            for segment in transcript:
                speaker = segment.get("speaker", "Speaker")
                dialogue = segment.get("dialogue", "")

                if not dialogue.strip():
                    continue

                total_segments += 1
                voice_id = speaker_voices.get(speaker, ELEVENLABS_VOICES["voice_1"])

                # Call ElevenLabs API
                try:
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
                        error_detail = f"Segment {total_segments} ({speaker}): HTTP {response.status_code} - {response.text[:200]}"
                        segment_errors.append(error_detail)
                        logger.warning(f"ElevenLabs API error: {error_detail}")
                except Exception as e:
                    error_detail = f"Segment {total_segments} ({speaker}): {type(e).__name__}: {e}"
                    segment_errors.append(error_detail)
                    logger.error(f"ElevenLabs request failed: {error_detail}")

            if not audio_segments:
                error_msg = f"No audio segments generated. {total_segments} segment(s) attempted, all failed."
                if segment_errors:
                    error_msg += f" Errors: {'; '.join(segment_errors[:5])}"
                logger.error(error_msg)
                return {"error": error_msg}
            
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

