
import logging
import asyncio
import os
import sys

# Ensure python_back_end is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from open_notebook.podcast.audio import AudioGenerator

async def test_audio_generator():
    logger.info("🧪 Testing AudioGenerator with Chatterbox (expecting CPU fallback)...")
    
    generator = AudioGenerator(output_path="/tmp/podcast_test")
    
    script = {
        "transcript": [
            {"speaker": "Host", "dialogue": "This is a test of the emergency podcast system."}
        ],
        "speakers": [
            {"name": "Host"} 
        ]
    }
    
    result = await generator.generate_audio(script, output_filename="test_fallback.mp3")
    
    if "error" in result:
        logger.error(f"❌ Generation Failed: {result['error']}")
        sys.exit(1)
    else:
        logger.info(f"✅ Generation Success: {result['audio_path']}")
        # Verify file exists and has size
        if os.path.exists(result['audio_path']) and os.path.getsize(result['audio_path']) > 1000:
            logger.info("✅ Audio file is valid.")
        else:
            logger.error("❌ Audio file missing or too small.")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_audio_generator())
