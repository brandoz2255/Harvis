"""
Model Downloader for init container
Downloads Whisper and ChatterboxTTS models to shared cache directory
"""

import os
import sys
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

WHISPER_CACHE_DIR = "/models-cache/whisper"
HUGGINGFACE_CACHE_DIR = "/models-cache/huggingface"


def setup_cache_directories():
    """Create cache directories if they don't exist"""
    logger.info("📁 Setting up cache directories...")

    os.makedirs(WHISPER_CACHE_DIR, exist_ok=True)
    os.makedirs(HUGGINGFACE_CACHE_DIR, exist_ok=True)

    os.environ['TRANSFORMERS_CACHE'] = HUGGINGFACE_CACHE_DIR
    os.environ['WHISPER_CACHE'] = WHISPER_CACHE_DIR

    logger.info(f"✅ Whisper cache: {WHISPER_CACHE_DIR}")
    logger.info(f"✅ Huggingface cache: {HUGGINGFACE_CACHE_DIR}")


def check_whisper_model_exists(model_name='base'):
    """Check if whisper model is already downloaded"""
    model_file = os.path.join(WHISPER_CACHE_DIR, f"{model_name}.pt")

    if os.path.exists(model_file):
        file_size = os.path.getsize(model_file)
        min_sizes = {'tiny': 30_000_000, 'base': 140_000_000, 'small': 460_000_000}
        expected_size = min_sizes.get(model_name, 30_000_000)

        if file_size >= expected_size:
            logger.info(f"✅ Whisper {model_name} model already exists ({file_size:,} bytes)")
            return True
        else:
            logger.warning(f"⚠️ Whisper '{model_name}' appears to be missing/corrupted ({file_size} bytes, expected >{expected_size})")
            os.remove(model_file)
            return False
    return False


def download_whisper_model(model_name='base'):
    """Download Whisper model if not already present"""

    if check_whisper_model_exists(model_name):
        return True

    logger.info(f"📥 Downloading Whisper '{model_name}' model....")

    try:
        import whisper

        logger.info(f"🚀 Starting download of whisper model '{model_name}'...")
        start_time = time.time()

        model = whisper.load_model(model_name, device="cpu", download_root=WHISPER_CACHE_DIR)

        elapsed = time.time() - start_time
        logger.info(f"✅ Whisper '{model_name}' model downloaded successfully in {elapsed:.1f}s")

        del model
        return True

    except Exception as e:
        logger.error(f"❌ Failed to download Whisper '{model_name}' model: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def check_chatterbox_model_exists():
    """Check if ChatterboxTTS model is already downloaded"""

    if os.path.exists(HUGGINGFACE_CACHE_DIR):
        contents = os.listdir(HUGGINGFACE_CACHE_DIR)
        model_dirs = [d for d in contents if d.startswith('models--')]

        if model_dirs:
            logger.info(f"✅ Found existing ChatterboxTTS cache with {len(model_dirs)} model(s)")
            # Verify that the cache contains actual model files
            for model_dir in model_dirs:
                model_path = os.path.join(HUGGINGFACE_CACHE_DIR, model_dir)
                # Check if snapshots directory exists (HF cache structure)
                snapshots_dir = os.path.join(model_path, 'snapshots')
                if os.path.exists(snapshots_dir) and os.listdir(snapshots_dir):
                    logger.info(f"✅ Validated cache structure for {model_dir}")
                    return True
            logger.warning("⚠️ Model directories found but no valid snapshots - cache may be incomplete")
            return False
    return False


def download_chatterbox_model():
    """Download ChatterboxTTS model if not already present"""
    if check_chatterbox_model_exists():
        return True

    logger.info("📥 Downloading ChatterboxTTS model...")

    try:
        from chatterbox.tts import ChatterboxTTS
        logger.info("🚀 Starting the download...")
        start_time = time.time()

        model = ChatterboxTTS.from_pretrained(device='cpu')
        elapsed = time.time() - start_time
        logger.info(f"✅ ChatterboxTTS model download successful in {elapsed:.1f}s")

        del model
        return True

    except Exception as e:
        logger.error(f"❌ Something went wrong, failed to download model: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def verify_downloads():
    """Verify that all required models are present"""
    logger.info("🔍 Verifying model downloads....")

    success = True

    if not check_whisper_model_exists('base'):
        logger.error("❌ Whisper 'base' model not found after download attempt")
        success = False

    # Check if HuggingFace cache directory has any content
    if os.path.exists(HUGGINGFACE_CACHE_DIR):
        hf_contents = os.listdir(HUGGINGFACE_CACHE_DIR)
        if len(hf_contents) > 0:
            logger.info(f"✅ HuggingFace cache populated with {len(hf_contents)} items")
        else:
            logger.error("❌ ChatterboxTTS model not found - HuggingFace cache is empty")
            success = False
    else:
        logger.error("❌ ChatterboxTTS model not found - HuggingFace cache directory doesn't exist")
        success = False

    return success


def fix_cache_permissions():
    """Ensure cache directories have correct permissions for app container"""
    logger.info("🔧 Setting cache directory permissions...")

    try:
        # Set permissions to 755 (rwxr-xr-x) so app container can read
        import stat

        for cache_dir in [WHISPER_CACHE_DIR, HUGGINGFACE_CACHE_DIR]:
            if os.path.exists(cache_dir):
                # Set directory permissions
                os.chmod(cache_dir, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

                # Recursively set permissions on all files and subdirectories
                for root, dirs, files in os.walk(cache_dir):
                    for d in dirs:
                        dir_path = os.path.join(root, d)
                        os.chmod(dir_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                    for f in files:
                        file_path = os.path.join(root, f)
                        os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

                logger.info(f"✅ Fixed permissions for {cache_dir}")

        return True

    except Exception as e:
        logger.error(f"❌ Failed to fix permissions: {e}")
        return False


def main():
    """Main function for the init container"""
    logger.info("🚀 Starting model download process...")
    logger.info(f"👤 Process running as UID: {os.getuid()}, GID: {os.getgid()}")

    try:
        setup_cache_directories()

        if not download_whisper_model('base'):
            logger.error("❌ Whisper model download failed")
            sys.exit(1)

        if not download_chatterbox_model():
            logger.error("❌ ChatterboxTTS model download failed")
            sys.exit(1)

        if not verify_downloads():
            logger.error("❌ Model verification failed")
            sys.exit(1)

        # CRITICAL: Fix permissions so app container can read the cache
        if not fix_cache_permissions():
            logger.error("❌ Failed to set proper cache permissions")
            sys.exit(1)

        logger.info("✅ All models downloaded and verified successfully")
        logger.info("✅ Cache permissions set correctly")
        logger.info("✅ Init container completed successfully")

        sys.exit(0)

    except Exception as e:
        logger.error(f"❌ Unexpected error during model download: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
