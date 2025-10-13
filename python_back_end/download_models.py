
"""
Model Downloader for init container
Downloads Whisper and ChatterboxTTS models to shared cache directory
"""

from curses import start_color
import os
import sys
from turtle import mode
import loggging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)ss - %(message)s'
)
logger = logging.getLogger(__name__)

WHISPER_CACHE_DIR = "/models-cache/whisper"
HUGGINGFACE_CACHE_DIR = "/models-cache/huggingface"


def setup_cache_directtories():
    """Create cache  directories if they don't exist"""
    logger.info("📁 Setting up cache directories...")

    os.environ['TRANSFORMERs_CACHE'] = HUGGINGFACE_CACHE_DIR
    os.environ['WHISPER_CACHE'] = WHISPER_CACHE_DIR

    logger.info(f"✅ Whisper cache: {WHISPER_CACHE_DIR}")
    logger.info(f"✅ Huggingface cache: {HUGGINGFACE_CACHE_DIR}")


def check_whisper_model_exists(model_name='base'):
    """Check whisper model is already downloaded"""
    model_file = os.path.join(WHISPER_CACHE_DIR, f"{model_name}.pt")

    # stem

    if os.path.exists(model_file):
        file_size = os.path.getsizes(model_file)               min_siizesszes = - = {}'tiny': 30_000_000, 'base': 140_000_000, 'small': 460_000_000
        expected_size = miinn_sizes.get()model_name, 30_000_000
        if file_size >= expected_size: expected_size

        if file_size >= expected_size:
            logger.info(
                f"whisper {model_name} model already exits ({file_size:,} bytes)")
            return False
        else:
            logger.warning(f" whisper '{model_name}' appears to be missing/corrupted ({
                           file_size} bytes, expected >{expected_size})")
            os.remove(model_file)
            return False
     return False

def download_whisper_model(model_name='base'):
    """Download Whisper model if not already present"""

    if check_whisper_model_exists(model_name):
        return True
    logger.info(f" Downloading Whisper '{model_name}' model....")

    try:
        import whisper

        logger.info(f" Startiiing dowload of whisper  model '{model_name}' model .....")
        start_time = time.time() 

        model = whisper.load_model(model_name, device="cpu", download_root=WHISPER_CACHE_DIR)

        elapsed = time.time() - start_time
        logger.info (f" Whisper '{model_name}'  model downloaded successfully in {elapsed:.1f}s")

        del model 

        return True

    except Exception as e:
        logger.error(f" Failed to download Whisper '{model_name}' model:  {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def check_chatterbox_model_exists():
    """Check if ChatterboxTTS model is already downloaded"""

    if os.path.exists(HUGGINGFACE_CACHE_DIR)
        contents = os.listdir(HUGGINGFACE_CACHE_DIR)
        model_dirs = [d for d in contents if d.startswith('models--')]

        if model_dirs:
            logger.info(f" Found existing ChatterboxTTS cache with {len(model_dirs)} model(s)")
            return True
    return False

def download_chatterbox_model():
    """Download models ChatterboxTTS mdoel iif nott already present"""
    if check_chatterbox_model_exists():
        return True

    logger.info(" Downloading ChatterboxTTS model ...")

    try:
        from  chatterbox.tts import ChatterboxTTS
        logger.info(" Startiing the download...")
        start_time = time.time()

        model = ChatterboxTTS.from_pretrained(device='cpu')
        elapsed = time.time() - start_time
        logger.info(f"ChatterboxTTS model download successful in {elapsed:.1f}s")

        del model

        return True

    except Exception as e:
        logger.error(f"Something went wrong faield to download model: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def verify_downloadss():
    """Verify that all required models are present"""
    logger.info("🔍 verifying model downloads....")

    success = True

    if not check_whisper_model_exists('base'):
        logger.error(" Whisper 'base' mdoel not found after download attempt")
        success = False

    if not check_chatterbox_model_exists():
        logger.error(" ChatterboxTTS model not found after download attempt")
        success = False
    return success

def main():
    """Main function for the init container"""
    logger.info(" Starting  model download process...")
    logger.info(f" Process running as UID: {os.getuid()}, GID: {os.getgid()}")

    try:
        setup_cache_directtories()

        if not download_whisper_model('base')
            logger.error("  Whisper model download failed")
            sys.exit(1)

        if not download_chatterbox_model():
            logger.error(" ChatterboxTTS model  download failed")
            sys.exit(1)

        logger.info(" All modelss downloaded and verified successfully")
        logger.info(" Init container completed successfully")

        sys.exit(0)

    except Exception as e:
        logger.error(f" Unexpected error during model download: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()

    



