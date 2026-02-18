"""
Model Downloader for init container
Downloads Whisper, ChatterboxTTS, and Qwen3-TTS models to shared cache directory
"""

import os
import sys
import logging
import time

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

WHISPER_CACHE_DIR = "/models-cache/whisper"
HUGGINGFACE_CACHE_DIR = "/models-cache/huggingface"

# Qwen3-TTS model IDs (from Alibaba) - Base models for voice cloning
QWEN_TTS_MODEL_1_7B = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
QWEN_TTS_MODEL_0_6B = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
QWEN_TTS_TOKENIZER = "Qwen/Qwen3-TTS-Tokenizer-12Hz"


def setup_cache_directories():
    """Create cache directories if they don't exist"""
    logger.info("📁 Setting up cache directories...")

    os.makedirs(WHISPER_CACHE_DIR, exist_ok=True)
    os.makedirs(HUGGINGFACE_CACHE_DIR, exist_ok=True)

    os.environ["TRANSFORMERS_CACHE"] = HUGGINGFACE_CACHE_DIR
    os.environ["WHISPER_CACHE"] = WHISPER_CACHE_DIR

    logger.info(f"✅ Whisper cache: {WHISPER_CACHE_DIR}")
    logger.info(f"✅ Huggingface cache: {HUGGINGFACE_CACHE_DIR}")


def check_whisper_model_exists(model_name="base"):
    """Check if whisper model is already downloaded"""
    model_file = os.path.join(WHISPER_CACHE_DIR, f"{model_name}.pt")

    if os.path.exists(model_file):
        file_size = os.path.getsize(model_file)
        min_sizes = {"tiny": 30_000_000, "base": 140_000_000, "small": 460_000_000}
        expected_size = min_sizes.get(model_name, 30_000_000)

        if file_size >= expected_size:
            logger.info(
                f"✅ Whisper {model_name} model already exists ({file_size:,} bytes)"
            )
            return True
        else:
            logger.warning(
                f"⚠️ Whisper '{model_name}' appears to be missing/corrupted ({file_size} bytes, expected >{expected_size})"
            )
            os.remove(model_file)
            return False
    return False


def download_whisper_model(model_name="base"):
    """Download Whisper model if not already present"""

    if check_whisper_model_exists(model_name):
        return True

    logger.info(f"📥 Downloading Whisper '{model_name}' model....")

    try:
        import whisper

        logger.info(f"🚀 Starting download of whisper model '{model_name}'...")
        start_time = time.time()

        model = whisper.load_model(
            model_name, device="cpu", download_root=WHISPER_CACHE_DIR
        )

        elapsed = time.time() - start_time
        logger.info(
            f"✅ Whisper '{model_name}' model downloaded successfully in {elapsed:.1f}s"
        )

        del model
        return True

    except Exception as e:
        logger.error(f"❌ Failed to download Whisper '{model_name}' model: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def check_chatterbox_model_exists():
    """Check if ChatterboxTTS model is already downloaded"""

    # Check both direct path and hub subdirectory (HF cache structure)
    cache_paths = [HUGGINGFACE_CACHE_DIR, os.path.join(HUGGINGFACE_CACHE_DIR, "hub")]

    for cache_path in cache_paths:
        if os.path.exists(cache_path):
            contents = os.listdir(cache_path)
            model_dirs = [d for d in contents if d.startswith("models--")]

            if model_dirs:
                logger.info(
                    f"✅ Found existing ChatterboxTTS cache with {len(model_dirs)} model(s) in {cache_path}"
                )
                # Verify that the cache contains actual model files
                for model_dir in model_dirs:
                    model_path = os.path.join(cache_path, model_dir)
                    # Check if snapshots directory exists (HF cache structure)
                    snapshots_dir = os.path.join(model_path, "snapshots")
                    if os.path.exists(snapshots_dir) and os.listdir(snapshots_dir):
                        logger.info(f"✅ Validated cache structure for {model_dir}")
                        return True
                logger.warning(
                    "⚠️ Model directories found but no valid snapshots - cache may be incomplete"
                )
                return False
    return False


def download_chatterbox_model():
    """Download ChatterboxTTS model if not already present"""
    # First check if models are already cached
    if check_chatterbox_model_exists():
        logger.info("✅ ChatterboxTTS model already cached - skipping download")
        return True

    logger.info("📥 Downloading ChatterboxTTS model...")

    try:
        # Use HuggingFace Hub to download the model files directly
        from huggingface_hub import snapshot_download

        logger.info("🚀 Starting the download...")
        start_time = time.time()

        # Download the model files to HuggingFace cache
        model_path = snapshot_download(
            repo_id="chatterboxai/chatterbox-tts",
            cache_dir=HUGGINGFACE_CACHE_DIR,
            local_files_only=False,
            resume_download=True,
        )

        elapsed = time.time() - start_time
        logger.info(f"✅ ChatterboxTTS model downloaded to cache in {elapsed:.1f}s")
        logger.info(f"   Path: {model_path}")

        # Try to verify the model can be loaded (this may fail due to perth, but files are cached)
        try:
            from chatterbox.tts import ChatterboxTTS

            model = ChatterboxTTS.from_pretrained(device="cpu")
            logger.info("✅ Model verification successful")
            del model
        except TypeError as te:
            # perth watermarking issue - files are cached but watermarker fails
            if "'NoneType' object is not callable" in str(te):
                logger.warning(
                    "⚠️ ChatterboxTTS watermarker issue (perth), but model files are cached"
                )
                logger.info(
                    "✅ Model files cached successfully - will work on backend restart"
                )
            else:
                raise

        return True

    except Exception as e:
        logger.error(f"❌ Failed to download model: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def check_qwen_tts_model_exists(use_1_7b=True):
    """Check if Qwen3-TTS model is already downloaded and complete"""
    model_id = QWEN_TTS_MODEL_1_7B if use_1_7b else QWEN_TTS_MODEL_0_6B
    model_dir_name = f"models--{model_id.replace('/', '--')}"
    tokenizer_dir_name = f"models--{QWEN_TTS_TOKENIZER.replace('/', '--')}"

    # Check both direct path and hub subdirectory (HF cache structure)
    cache_paths = [HUGGINGFACE_CACHE_DIR, os.path.join(HUGGINGFACE_CACHE_DIR, "hub")]

    model_found = False
    tokenizer_found = False

    for cache_path in cache_paths:
        model_path = os.path.join(cache_path, model_dir_name)
        if os.path.exists(model_path):
            snapshots_dir = os.path.join(model_path, "snapshots")
            if os.path.exists(snapshots_dir) and os.listdir(snapshots_dir):
                # Deep validation: check that speech_tokenizer has preprocessor_config.json
                snapshot_dirs = os.listdir(snapshots_dir)
                for snap in snapshot_dirs:
                    snap_path = os.path.join(snapshots_dir, snap)
                    speech_tok = os.path.join(
                        snap_path, "speech_tokenizer", "preprocessor_config.json"
                    )
                    if os.path.isdir(snap_path) and os.path.exists(speech_tok):
                        logger.info(
                            f"✅ Found complete Qwen3-TTS model cache at {model_path}"
                        )
                        model_found = True
                        break
                if not model_found:
                    logger.warning(
                        f"⚠️ Qwen3-TTS model cache at {model_path} is incomplete (missing speech_tokenizer)"
                    )
                    # Remove the incomplete cache so it gets re-downloaded
                    import shutil

                    try:
                        shutil.rmtree(model_path)
                        logger.info(f"🗑️ Removed incomplete model cache: {model_path}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not remove incomplete cache: {e}")

        tokenizer_path = os.path.join(cache_path, tokenizer_dir_name)
        if os.path.exists(tokenizer_path):
            snapshots_dir = os.path.join(tokenizer_path, "snapshots")
            if os.path.exists(snapshots_dir) and os.listdir(snapshots_dir):
                logger.info(f"✅ Found Qwen3-TTS tokenizer cache at {tokenizer_path}")
                tokenizer_found = True

    return model_found and tokenizer_found


def download_qwen_tts_model(use_1_7b=True):
    """Download Qwen3-TTS model and tokenizer if not already present"""
    model_id = QWEN_TTS_MODEL_1_7B if use_1_7b else QWEN_TTS_MODEL_0_6B

    # First check if model is already cached
    if check_qwen_tts_model_exists(use_1_7b):
        logger.info(
            f"✅ Qwen3-TTS model ({model_id}) already cached - skipping download"
        )
        return True

    try:
        from huggingface_hub import snapshot_download

        # Download the tokenizer first (required by all Qwen3-TTS models)
        logger.info(f"📥 Downloading Qwen3-TTS tokenizer: {QWEN_TTS_TOKENIZER}...")
        start_time = time.time()
        tokenizer_path = snapshot_download(
            repo_id=QWEN_TTS_TOKENIZER,
            cache_dir=HUGGINGFACE_CACHE_DIR,
            local_files_only=False,
            resume_download=True,
        )
        elapsed = time.time() - start_time
        logger.info(f"✅ Qwen3-TTS tokenizer downloaded in {elapsed:.1f}s")
        logger.info(f"   Path: {tokenizer_path}")

        # Download the main model
        logger.info(f"📥 Downloading Qwen3-TTS model: {model_id}...")
        start_time = time.time()

        # Download with explicit settings to ensure all files including subdirectories are downloaded
        model_path = snapshot_download(
            repo_id=model_id,
            cache_dir=HUGGINGFACE_CACHE_DIR,
            local_files_only=False,
            resume_download=True,
            local_dir_use_symlinks=False,  # Ensure actual files, not symlinks
        )
        elapsed = time.time() - start_time
        logger.info(f"✅ Qwen3-TTS model downloaded in {elapsed:.1f}s")
        logger.info(f"   Path: {model_path}")

        # Verify speech_tokenizer subdirectory exists and has required files
        import glob

        speech_tokenizer_paths = glob.glob(
            os.path.join(model_path, "**/speech_tokenizer"), recursive=True
        )
        if speech_tokenizer_paths:
            for st_path in speech_tokenizer_paths:
                preprocessor_config = os.path.join(st_path, "preprocessor_config.json")
                if os.path.exists(preprocessor_config):
                    logger.info(f"✅ Verified speech_tokenizer at: {st_path}")
                else:
                    logger.warning(
                        f"⚠️ speech_tokenizer missing preprocessor_config.json at: {st_path}"
                    )
        else:
            logger.warning("⚠️ No speech_tokenizer directory found in downloaded model")

        # Verify the download by checking if qwen-tts can import
        try:
            from qwen_tts import Qwen3TTSModel

            logger.info("✅ qwen-tts library verified")
        except ImportError:
            logger.warning(
                "⚠️ qwen-tts library not installed - will be needed at runtime"
            )
            logger.info("   Install with: pip install qwen-tts")

        return True

    except Exception as e:
        logger.error(f"❌ Failed to download Qwen3-TTS model: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def verify_downloads():
    """Verify that all required models are present"""
    logger.info("🔍 Verifying model downloads....")

    # Check environment variables for which models should be verified
    verify_qwen_tts = os.environ.get("DOWNLOAD_QWEN_TTS", "true").lower() == "true"
    verify_chatterbox = (
        os.environ.get("DOWNLOAD_CHATTERBOX_TTS", "true").lower() == "true"
    )

    success = True

    # Verify Whisper
    if not check_whisper_model_exists("base"):
        logger.error("❌ Whisper 'base' model not found after download attempt")
        success = False
    else:
        logger.info("✅ Whisper 'base' model verified")

    # Check if HuggingFace cache directory has any content
    if os.path.exists(HUGGINGFACE_CACHE_DIR):
        hf_contents = os.listdir(HUGGINGFACE_CACHE_DIR)
        if len(hf_contents) > 0:
            logger.info(f"✅ HuggingFace cache populated with {len(hf_contents)} items")

            # Verify Chatterbox if enabled
            if verify_chatterbox:
                if check_chatterbox_model_exists():
                    logger.info("✅ ChatterboxTTS model verified")
                else:
                    logger.warning("⚠️ ChatterboxTTS model not found in cache")
                    # Don't fail - might be optional

            # Verify Qwen3-TTS if enabled
            if verify_qwen_tts:
                if check_qwen_tts_model_exists(
                    use_1_7b=True
                ) or check_qwen_tts_model_exists(use_1_7b=False):
                    logger.info("✅ Qwen3-TTS model verified")
                else:
                    logger.warning("⚠️ Qwen3-TTS model not found in cache")
                    # Don't fail - Qwen3-TTS is optional
        else:
            if verify_chatterbox or verify_qwen_tts:
                logger.warning(
                    "⚠️ HuggingFace cache is empty - TTS models may not be available"
                )
    else:
        if verify_chatterbox or verify_qwen_tts:
            logger.warning("⚠️ HuggingFace cache directory doesn't exist")

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
                os.chmod(
                    cache_dir,
                    stat.S_IRWXU
                    | stat.S_IRGRP
                    | stat.S_IXGRP
                    | stat.S_IROTH
                    | stat.S_IXOTH,
                )

                # Recursively set permissions on all files and subdirectories
                for root, dirs, files in os.walk(cache_dir):
                    for d in dirs:
                        dir_path = os.path.join(root, d)
                        os.chmod(
                            dir_path,
                            stat.S_IRWXU
                            | stat.S_IRGRP
                            | stat.S_IXGRP
                            | stat.S_IROTH
                            | stat.S_IXOTH,
                        )
                    for f in files:
                        file_path = os.path.join(root, f)
                        os.chmod(
                            file_path,
                            stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH,
                        )

                logger.info(f"✅ Fixed permissions for {cache_dir}")

        return True

    except Exception as e:
        logger.error(f"❌ Failed to fix permissions: {e}")
        return False


def main():
    """Main function for the init container"""
    logger.info("🚀 Starting model download process...")
    logger.info(f"👤 Process running as UID: {os.getuid()}, GID: {os.getgid()}")

    # Check environment variable to determine which TTS models to download
    download_qwen_tts = os.environ.get("DOWNLOAD_QWEN_TTS", "true").lower() == "true"
    download_chatterbox = (
        os.environ.get("DOWNLOAD_CHATTERBOX_TTS", "true").lower() == "true"
    )

    try:
        setup_cache_directories()

        # Check if models are already cached - if so, skip everything
        whisper_cached = check_whisper_model_exists("base")
        chatterbox_cached = (
            check_chatterbox_model_exists() if download_chatterbox else True
        )
        # Check BOTH 1.7B (GPU) and 0.6B (CPU fallback) models
        qwen_1_7b_cached = (
            check_qwen_tts_model_exists(use_1_7b=True) if download_qwen_tts else True
        )
        qwen_0_6b_cached = (
            check_qwen_tts_model_exists(use_1_7b=False) if download_qwen_tts else True
        )
        qwen_tts_cached = qwen_1_7b_cached and qwen_0_6b_cached

        if whisper_cached and chatterbox_cached and qwen_tts_cached:
            logger.info("✅ All models already cached - skipping download")
            logger.info("✅ Init container completed successfully")
            sys.exit(0)

        # Download Whisper if needed
        if not whisper_cached:
            if not download_whisper_model("base"):
                logger.error("❌ Whisper model download failed")
                sys.exit(1)
        else:
            logger.info("✅ Whisper model already cached")

        # Download Chatterbox if needed and enabled
        if download_chatterbox:
            if not chatterbox_cached:
                if not download_chatterbox_model():
                    logger.error("❌ ChatterboxTTS model download failed")
                    sys.exit(1)
            else:
                logger.info("✅ ChatterboxTTS model already cached")
        else:
            logger.info(
                "ℹ️ ChatterboxTTS download disabled via DOWNLOAD_CHATTERBOX_TTS=false"
            )

        # Download Qwen TTS if needed and enabled
        if download_qwen_tts:
            if not qwen_tts_cached:
                # Download 1.7B (primary GPU model)
                if not download_qwen_tts_model(use_1_7b=True):
                    logger.warning("⚠️ Qwen3-TTS 1.7B download failed")
                    logger.warning("⚠️ Continuing without Qwen3-TTS 1.7B")

                # Also download 0.6B (used for CPU fallback when GPU OOM)
                if not check_qwen_tts_model_exists(use_1_7b=False):
                    logger.info("📥 Downloading Qwen3-TTS 0.6B (CPU fallback model)...")
                    if not download_qwen_tts_model(use_1_7b=False):
                        logger.warning("⚠️ Qwen3-TTS 0.6B download failed")
                        logger.warning("⚠️ CPU fallback TTS will not be available")
            else:
                logger.info("✅ Qwen TTS model already cached")
        else:
            logger.info("ℹ️ Qwen TTS download disabled via DOWNLOAD_QWEN_TTS=false")

        if not verify_downloads():
            logger.error("❌ Model verification failed")
            sys.exit(1)

        # Best effort: Try to fix permissions so app container can read the cache
        # Don't fail if this doesn't work (NFS may not allow chmod)
        if not fix_cache_permissions():
            logger.warning(
                "⚠️ Could not set cache permissions - NFS may not allow chmod"
            )
            logger.warning(
                "⚠️ This is expected on NFS mounts and should not cause issues"
            )

        logger.info("✅ All models downloaded and verified successfully")
        logger.info("✅ Init container completed successfully")

        sys.exit(0)

    except Exception as e:
        logger.error(f"❌ Unexpected error during model download: {e}")
        import traceback

        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
