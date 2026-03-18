"""
Podcast Generator - Main orchestrator
Combines script generation and audio synthesis
"""

import os
import logging
from typing import Dict, Any, List, Optional, Callable, AsyncGenerator
from uuid import UUID
from datetime import datetime

from .script import ScriptGenerator, get_podcast_styles, get_default_speakers
from .audio import AudioGenerator

logger = logging.getLogger(__name__)

# Progress step constants
STEP_OUTLINE = "outline"
STEP_SCRIPT = "script"
STEP_AUDIO = "audio"
STEP_COMPLETED = "completed"
STEP_ERROR = "error"


class PodcastGenerator:
    """
    Main podcast generation orchestrator.
    Handles the full pipeline from content to audio.
    """
    
    def __init__(
        self,
        output_path: Optional[str] = None,
        tts_provider: Optional[str] = None
    ):
        self.script_generator = ScriptGenerator()
        self.audio_generator = AudioGenerator(output_path, tts_provider)
    
    async def generate(
        self,
        content: str,
        title: str,
        speakers: int = 2,
        duration_minutes: int = 10,
        style: str = "conversational",
        custom_speakers: Optional[List[Dict[str, str]]] = None,
        generate_audio: bool = True,
        progress_callback: Optional[Callable[[str, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Generate a complete podcast from content.
        
        Args:
            content: The source content to create podcast from
            title: Podcast episode title
            speakers: Number of speakers (1-4)
            duration_minutes: Target duration in minutes
            style: Podcast style (conversational, interview, educational, etc.)
            custom_speakers: Optional custom speaker profiles
            generate_audio: Whether to generate audio (can be False for script-only)
            progress_callback: Optional callback(step, message) for progress updates
            
        Returns:
            Dict with script, audio_path, duration, transcript, etc.
        """
        result = {
            "title": title,
            "style": style,
            "duration_minutes": duration_minutes,
            "status": "generating",
            "started_at": datetime.utcnow().isoformat()
        }
        
        def report_progress(step: str, message: str):
            if progress_callback:
                try:
                    progress_callback(step, message)
                except Exception:
                    pass
        
        try:
            # Get speaker profiles
            if custom_speakers:
                speaker_profiles = custom_speakers[:speakers]
            else:
                default_speakers = get_default_speakers()
                speaker_profiles = default_speakers[:speakers]
            
            # Generate outline first
            report_progress(STEP_OUTLINE, "Generating podcast outline...")
            logger.info(f"Generating podcast outline for: {title}")
            outline = await self.script_generator.generate_outline(
                content=content,
                title=title,
                duration_minutes=duration_minutes,
                style=style
            )
            result["outline"] = outline
            
            # Generate script
            report_progress(STEP_SCRIPT, "Writing podcast script...")
            logger.info(f"Generating podcast script for: {title}")
            script = await self.script_generator.generate_script(
                content=content,
                title=title,
                speakers=speaker_profiles,
                duration_minutes=duration_minutes,
                style=style,
                outline=outline
            )
            result["script"] = script
            result["transcript"] = script.get("transcript", [])
            
            # Generate audio if requested
            if generate_audio:
                report_progress(STEP_AUDIO, "Creating podcast audio...")
                logger.info(f"Generating podcast audio for: {title}")
                audio_result = await self.audio_generator.generate_audio(script)
                
                if "error" in audio_result:
                    logger.error(f"Audio generation failed: {audio_result['error']}")
                    result["audio_error"] = audio_result["error"]
                    result["status"] = "script_only"
                else:
                    result["audio_path"] = audio_result.get("audio_path")
                    result["audio_url"] = self.audio_generator.get_audio_url(
                        audio_result.get("audio_path", "")
                    )
                    result["duration_seconds"] = audio_result.get("duration_seconds")
                    result["status"] = "completed"
            else:
                result["status"] = "script_only"
            
            result["completed_at"] = datetime.utcnow().isoformat()
            report_progress(STEP_COMPLETED, "Podcast generation complete!")
            
        except Exception as e:
            logger.error(f"Podcast generation failed: {e}")
            result["status"] = "error"
            result["error"] = str(e)
            report_progress(STEP_ERROR, str(e))
        
        return result
    
    async def generate_with_progress(
        self,
        content: str,
        title: str,
        speakers: int = 2,
        duration_minutes: int = 10,
        style: str = "conversational",
        custom_speakers: Optional[List[Dict[str, str]]] = None,
        generate_audio: bool = True
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Generate a podcast with SSE-compatible progress updates.
        
        Yields progress events and final result for streaming to client.
        
        Yields:
            Dict with 'event' (progress/result/error) and 'data' fields
        """
        result = {
            "title": title,
            "style": style,
            "duration_minutes": duration_minutes,
            "status": "generating",
            "started_at": datetime.utcnow().isoformat()
        }
        
        try:
            # Get speaker profiles
            if custom_speakers:
                speaker_profiles = custom_speakers[:speakers]
            else:
                default_speakers = get_default_speakers()
                speaker_profiles = default_speakers[:speakers]
            
            # Generate outline first
            yield {"event": "progress", "data": {"step": STEP_OUTLINE, "message": "Generating podcast outline..."}}
            logger.info(f"Generating podcast outline for: {title}")
            outline = await self.script_generator.generate_outline(
                content=content,
                title=title,
                duration_minutes=duration_minutes,
                style=style
            )
            result["outline"] = outline
            
            # Generate script
            yield {"event": "progress", "data": {"step": STEP_SCRIPT, "message": "Writing podcast script..."}}
            logger.info(f"Generating podcast script for: {title}")
            script = await self.script_generator.generate_script(
                content=content,
                title=title,
                speakers=speaker_profiles,
                duration_minutes=duration_minutes,
                style=style,
                outline=outline
            )
            result["script"] = script
            result["transcript"] = script.get("transcript", [])
            
            # Generate audio if requested
            if generate_audio:
                yield {"event": "progress", "data": {"step": STEP_AUDIO, "message": "Creating podcast audio..."}}
                logger.info(f"Generating podcast audio for: {title}")
                audio_result = await self.audio_generator.generate_audio(script)
                
                if "error" in audio_result:
                    logger.error(f"Audio generation failed: {audio_result['error']}")
                    result["audio_error"] = audio_result["error"]
                    result["status"] = "script_only"
                else:
                    result["audio_path"] = audio_result.get("audio_path")
                    result["audio_url"] = self.audio_generator.get_audio_url(
                        audio_result.get("audio_path", "")
                    )
                    result["duration_seconds"] = audio_result.get("duration_seconds")
                    result["status"] = "completed"
            else:
                result["status"] = "script_only"
            
            result["completed_at"] = datetime.utcnow().isoformat()
            
            # Yield final result
            yield {"event": "result", "data": result}
            
        except Exception as e:
            logger.error(f"Podcast generation failed: {e}")
            result["status"] = "error"
            result["error"] = str(e)
            yield {"event": "error", "data": {"error": str(e), "result": result}}
    
    async def generate_script_only(
        self,
        content: str,
        title: str,
        speakers: int = 2,
        duration_minutes: int = 10,
        style: str = "conversational"
    ) -> Dict[str, Any]:
        """Generate only the script without audio"""
        return await self.generate(
            content=content,
            title=title,
            speakers=speakers,
            duration_minutes=duration_minutes,
            style=style,
            generate_audio=False
        )
    
    @staticmethod
    def get_available_styles() -> Dict[str, str]:
        """Get available podcast styles"""
        return get_podcast_styles()
    
    @staticmethod
    def get_default_speaker_profiles() -> List[Dict[str, str]]:
        """Get default speaker profiles"""
        return get_default_speakers()


# Convenience function for background task execution
async def run_podcast_generation(
    notebook_id: UUID,
    user_id: int,
    title: str,
    content: str,
    speakers: int = 2,
    duration_minutes: int = 10,
    style: str = "conversational",
    db_callback=None
) -> Dict[str, Any]:
    """
    Run podcast generation as a background task.
    
    Args:
        notebook_id: The notebook UUID
        user_id: The user ID
        title: Episode title
        content: Source content
        speakers: Number of speakers
        duration_minutes: Target duration
        style: Podcast style
        db_callback: Optional callback to update database
        
    Returns:
        Generation result
    """
    generator = PodcastGenerator()
    
    result = await generator.generate(
        content=content,
        title=title,
        speakers=speakers,
        duration_minutes=duration_minutes,
        style=style
    )
    
    # Call database callback if provided
    if db_callback and callable(db_callback):
        await db_callback(notebook_id, user_id, result)
    
    return result

