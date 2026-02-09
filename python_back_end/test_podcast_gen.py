
import asyncio
import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("test_podcast.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Add current directory to path
sys.path.append(os.getcwd())

# Set environment variables for host execution
os.environ["OLLAMA_URL"] = "http://localhost:11434"
os.environ["TTS_SERVICE_URL"] = "http://localhost:8001"
# Ensure we use the correct model available locally
os.environ["PODCAST_MODEL"] = "gpt-oss:latest" 
os.environ["PODCAST_OUTPUT_PATH"] = os.path.join(os.getcwd(), "test_podcast_output")

async def test_generation():
    try:
        from open_notebook.podcast import PodcastGenerator
        
        print(f"Using OLLAMA_URL: {os.environ['OLLAMA_URL']}")
        print(f"Using TTS_SERVICE_URL: {os.environ['TTS_SERVICE_URL']}")
        
        print("Initializing PodcastGenerator...")
        generator = PodcastGenerator()
        
        print("Starting generation...")
        # Simulating a very short podcast for testing
        content = """
        The concept of agentic coding is revolutionizing how we build software. 
        Instead of just completion, agents can plan, execute, and verify their work.
        This changes the developer's role from writer to architect and reviewer.
        """
        
        result = await generator.generate(
            content=content,
            title="Agentic Coding Test",
            speakers=2,
            duration_minutes=1, # Very short for test
            style="conversational",
            generate_audio=True
        )
        
        logger.info("\\nGeneration Result:")
        logger.info(f"Status: {result.get('status')}")
        if result.get('status') == 'error':
            logger.info(f"Error: {result.get('error')}")
            logger.info(f"Audio Error: {result.get('audio_error')}")
        else:
            logger.info(f"Audio Path: {result.get('audio_path')}")
            logger.info(f"Transcript Length: {len(result.get('transcript', []))}")
            if result.get('audio_path'):
                 logger.info(f"Audio file created at: {result.get('audio_path')}")
            
    except Exception as e:
        logger.exception(f"Test failed with exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_generation())
