"""
Voice and TTS data models
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class VoiceType(str, Enum):
    USER = "user"
    BUILTIN = "builtin"


class Voice(BaseModel):
    """Represents a cloned or built-in voice"""
    voice_id: str
    voice_name: str
    description: Optional[str] = None
    voice_type: VoiceType = VoiceType.USER
    reference_audio_path: Optional[str] = None
    reference_duration: float = 0.0
    quality_score: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    user_id: Optional[str] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class VoicePreset(BaseModel):
    """Built-in voice preset metadata"""
    preset_id: str
    name: str
    description: str
    category: str  # e.g., "character", "narrator", "host"
    sample_text: str  # Text to use for preview
    icon: Optional[str] = None  # Icon identifier
    requires_activation: bool = True  # Needs user to provide reference audio


class GenerationSettings(BaseModel):
    """Settings for TTS generation"""
    cfg_scale: float = Field(default=1.3, ge=0.5, le=3.0)
    inference_steps: int = Field(default=10, ge=5, le=50)
    temperature: float = Field(default=0.7, ge=0.1, le=1.5)
    seed: Optional[int] = None


class ScriptSegment(BaseModel):
    """A single segment of podcast script"""
    speaker: str  # Speaker identifier (e.g., "1", "2", "host")
    text: str
    voice_id: Optional[str] = None  # Override voice for this segment


class PodcastRequest(BaseModel):
    """Request to generate a podcast"""
    script: List[ScriptSegment]
    voice_mapping: Dict[str, str]  # speaker_id -> voice_id
    settings: Optional[GenerationSettings] = None
    output_format: str = Field(default="wav", pattern="^(wav|mp3|ogg)$")
    normalize_audio: bool = True
    add_silence_between_speakers: float = Field(default=0.3, ge=0, le=2.0)


class SpeechRequest(BaseModel):
    """Request to generate single-speaker speech"""
    text: str
    voice_id: str
    settings: Optional[GenerationSettings] = None
    output_format: str = Field(default="wav", pattern="^(wav|mp3|ogg)$")


class GenerationResult(BaseModel):
    """Result of audio generation"""
    success: bool
    job_id: str
    audio_url: Optional[str] = None
    audio_path: Optional[str] = None
    duration: Optional[float] = None
    generation_time: Optional[float] = None
    error: Optional[str] = None


class VoiceCloneResult(BaseModel):
    """Result of voice cloning"""
    success: bool
    voice: Optional[Voice] = None
    error: Optional[str] = None
