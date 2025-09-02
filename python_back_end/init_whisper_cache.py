#!/usr/bin/env python3
"""
Whisper Cache Initialization Script
Ensures Whisper models are available for offline operation
"""
import os
import shutil
import logging

logger = logging.getLogger(__name__)

def init_whisper_cache():
    """Initialize Whisper cache with pre-seeded models"""
    
    # Determine cache directory based on environment
    # In Docker, we may be running as appuser but need to access /root/.cache
    cache_dir = os.path.expanduser("~/.cache/whisper")
    
    # Check if we're in Docker and can access the pre-seeded location
    docker_cache_dir = "/root/.cache/whisper"
    if os.path.exists(docker_cache_dir) and not os.path.exists(cache_dir):
        cache_dir = docker_cache_dir
    
    # Pre-seeded models in the container
    preseeded_dir = "/app/whisper_models"
    
    logger.info(f"🔧 Initializing Whisper cache at: {cache_dir}")
    
    # Create cache directory if it doesn't exist
    os.makedirs(cache_dir, exist_ok=True)
    
    # Models to copy
    models = ["tiny.pt", "base.pt"]
    
    for model in models:
        source_path = os.path.join(preseeded_dir, model)
        dest_path = os.path.join(cache_dir, model)
        
        # Only copy if source exists and destination doesn't
        if os.path.exists(source_path) and not os.path.exists(dest_path):
            try:
                shutil.copy2(source_path, dest_path)
                logger.info(f"✅ Copied pre-seeded model: {model}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to copy {model}: {e}")
        elif os.path.exists(dest_path):
            logger.info(f"✅ Model already exists: {model}")
        else:
            logger.warning(f"⚠️ Pre-seeded model not found: {source_path}")
    
    # Verify cache contents
    if os.path.exists(cache_dir):
        cache_files = os.listdir(cache_dir)
        logger.info(f"📁 Whisper cache contents: {cache_files}")
        
        # Validate file sizes
        for model in models:
            model_path = os.path.join(cache_dir, model)
            if os.path.exists(model_path):
                size = os.path.getsize(model_path)
                logger.info(f"📦 {model}: {size:,} bytes")
    
    logger.info("🚀 Whisper cache initialization complete")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_whisper_cache()