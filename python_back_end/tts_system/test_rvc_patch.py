import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path.cwd()))

try:
    from python_back_end.tts_system.engines.rvc_engine import get_rvc_engine
    from python_back_end.tts_system.utils.audio_post import process_podcast_master
    import numpy as np
    
    print("Imports successful.")
    
    # Test Post Processing
    audio = np.random.rand(48000).astype(np.float32)
    processed = process_podcast_master(audio, 48000)
    print(f"Post-processing test: Input shape {audio.shape}, Output shape {processed.shape}")
    
    # Test RVC Engine Init
    engine = get_rvc_engine()
    print(f"RVC Engine initialized. Device: {engine.device}")
    
    # Check attributes
    assert hasattr(engine, 'sr_work'), "RVCEngine missing sr_work"
    assert hasattr(engine, 'convert_block'), "RVCEngine missing convert_block"
    assert hasattr(engine, 'calibrate_voice'), "RVCEngine missing calibrate_voice"
    
    # Test VibeVoice Engine Import
    from python_back_end.tts_system.engines.vibevoice_engine import VibeVoiceEngine
    print("VibeVoiceEngine imported successfully.")
    
    # Instantiate (mocking environment if needed)
    # just checking if class loads and method exists
    assert hasattr(VibeVoiceEngine, 'generate_podcast'), "VibeVoiceEngine missing generate_podcast"
    print("VibeVoiceEngine has generate_podcast method.")
    
    print("Verification successful.")
    
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
