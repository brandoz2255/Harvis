"""
Podcast Script Generator
Generates conversational podcast scripts from content using LLM
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
import requests

from jinja2 import Environment, FileSystemLoader, BaseLoader

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
CLOUD_OLLAMA_URL = os.getenv("OLLAMA_CLOUD_URL", "https://coyotegpt.ngrok.app/ollama")
DEFAULT_MODEL = os.getenv("PODCAST_MODEL", "mistral")

# Default speaker profiles
DEFAULT_SPEAKERS = [
    {
        "name": "Alex",
        "role": "Host",
        "personality": "Curious, engaging, asks clarifying questions",
        "voice_id": "voice_1"
    },
    {
        "name": "Jordan", 
        "role": "Expert",
        "personality": "Knowledgeable, explains concepts clearly, provides examples",
        "voice_id": "voice_2"
    }
]

# Podcast styles
PODCAST_STYLES = {
    "conversational": "A casual, friendly discussion between two people exploring the topic together",
    "interview": "A formal interview format where one person asks questions and another provides expertise",
    "educational": "A structured educational format designed to teach the listener about the topic",
    "debate": "A debate-style discussion where speakers present different perspectives",
    "storytelling": "A narrative format that tells the story of the topic in an engaging way"
}


class ScriptGenerator:
    """Generates podcast scripts from content"""
    
    def __init__(self, prompts_dir: Optional[str] = None):
        self.prompts_dir = prompts_dir or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), '..', 'prompts'
        )
        
        # Try to load Jinja environment if prompts exist
        if os.path.exists(self.prompts_dir):
            self.jinja_env = Environment(loader=FileSystemLoader(self.prompts_dir))
        else:
            self.jinja_env = None
    
    async def generate_outline(
        self,
        content: str,
        title: str,
        duration_minutes: int = 10,
        style: str = "conversational"
    ) -> str:
        """Generate podcast outline from content"""
        
        prompt = f"""Create an outline for a {duration_minutes}-minute podcast episode.

TITLE: {title}
STYLE: {PODCAST_STYLES.get(style, PODCAST_STYLES['conversational'])}

CONTENT TO COVER:
{content}

Create a structured outline with:
1. Introduction (1-2 minutes)
2. Main segments (covering key topics)
3. Conclusion (1-2 minutes)

For each segment, include:
- Topic
- Key points to cover
- Approximate duration
- Suggested speaker focus

OUTLINE:"""

        return await self._call_llm(prompt)
    
    async def generate_script(
        self,
        content: str,
        title: str,
        speakers: List[Dict[str, str]] = None,
        duration_minutes: int = 10,
        style: str = "conversational",
        outline: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate full podcast script"""
        
        if speakers is None:
            speakers = DEFAULT_SPEAKERS[:2]
        
        # Generate outline if not provided
        if not outline:
            outline = await self.generate_outline(content, title, duration_minutes, style)
        
        # Build speaker description
        speaker_desc = "\n".join([
            f"- {s['name']} ({s.get('role', 'Speaker')}): {s.get('personality', 'Friendly and engaging')}"
            for s in speakers
        ])
        speaker_names = [s['name'] for s in speakers]
        
        # Calculate target turns (roughly 6-8 turns per minute)
        target_turns = duration_minutes * 7
        
        prompt = f"""Generate a podcast script for the following episode.

TITLE: {title}
STYLE: {PODCAST_STYLES.get(style, PODCAST_STYLES['conversational'])}
TARGET DURATION: {duration_minutes} minutes (approximately {target_turns} dialogue turns)

SPEAKERS:
{speaker_desc}

OUTLINE:
{outline}

CONTENT TO DISCUSS:
{content}

Generate a natural, engaging conversation between the speakers. 
Return the script as a JSON object with this format:

{{
    "title": "{title}",
    "duration_minutes": {duration_minutes},
    "transcript": [
        {{"speaker": "Speaker Name", "dialogue": "What they say..."}},
        ...
    ]
}}

Guidelines:
- Make the dialogue natural and conversational
- Include reactions, follow-up questions, and transitions
- Each speaker should contribute meaningfully
- Cover all key points from the outline
- End with a clear conclusion
- Only use these speaker names: {', '.join(speaker_names)}

SCRIPT (JSON only, no markdown):"""

        response = await self._call_llm(prompt)
        
        # Parse the JSON response
        try:
            # Clean up response if needed
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            response = response.strip()
            
            script_data = json.loads(response)
            script_data["speakers"] = speakers
            script_data["outline"] = outline
            return script_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse script JSON: {e}")
            # Return a basic structure with the raw response
            return {
                "title": title,
                "duration_minutes": duration_minutes,
                "speakers": speakers,
                "outline": outline,
                "transcript": [
                    {"speaker": speakers[0]["name"], "dialogue": response}
                ],
                "parse_error": str(e)
            }
    
    async def _call_llm(self, prompt: str, model: str = None) -> str:
        """Call LLM for script generation"""
        model = model or DEFAULT_MODEL
        
        # Try local Ollama
        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.8,  # Higher creativity for podcasts
                        "top_p": 0.95,
                    }
                },
                timeout=180  # Longer timeout for script generation
            )
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("response", "")
                from ..utils import clean_thinking_content
                return clean_thinking_content(result)
        except Exception as e:
            logger.warning(f"Local Ollama failed: {e}")
        
        # Try cloud fallback
        try:
            response = requests.post(
                f"{CLOUD_OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=180
            )
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("response", "")
                from ..utils import clean_thinking_content
                return clean_thinking_content(result)
        except Exception as e:
            logger.error(f"Cloud Ollama also failed: {e}")
            raise
        
        raise Exception("All LLM providers failed for script generation")


def get_podcast_styles() -> Dict[str, str]:
    """Get available podcast styles"""
    return PODCAST_STYLES


def get_default_speakers() -> List[Dict[str, str]]:
    """Get default speaker profiles"""
    return DEFAULT_SPEAKERS

