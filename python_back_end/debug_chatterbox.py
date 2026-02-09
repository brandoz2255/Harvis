
import sys
import traceback

print("Testing chatterbox import...", flush=True)
try:
    import chatterbox
    print(f"Chatterbox package: {chatterbox.__file__}", flush=True)
    from chatterbox.tts import ChatterboxTTS
    print("ChatterboxTTS imported successfully", flush=True)
except Exception:
    traceback.print_exc()
except ImportError:
    traceback.print_exc()
