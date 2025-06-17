import logging
import os
from trash.chatterbox import VoiceGenerator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_voice_generation():
    """Test the voice generation functionality."""
    try:
        # Initialize voice generator
        generator = VoiceGenerator()
        
        # Test text
        test_text = "Hello, this is a test of the voice generation system."
        
        # Generate speech
        logger.info("Generating speech...")
        sr, audio = generator.generate_speech(test_text)
        
        # Save audio
        output_file = "test_output.wav"
        logger.info(f"Saving audio to {output_file}...")
        success = generator.save_audio(audio, sr, output_file)
        
        if success:
            logger.info("✅ Test completed successfully!")
            logger.info(f"Audio saved to {os.path.abspath(output_file)}")
        else:
            logger.error("❌ Failed to save audio file")
            
    except Exception as e:
        logger.error(f"❌ Test failed: {str(e)}")

if __name__ == "__main__":
    test_voice_generation() 