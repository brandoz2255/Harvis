
import subprocess
import sys

print("Starting installation...", flush=True)
try:
    with open('install.log', 'w') as f:
        # Install lightweight podcast dependencies
        deps = [
            "piper-tts",
            "fairseq", 
            "faiss-cpu", 
            "pyworld", 
            "torchcrepe", 
            "praat-parselmouth",
            "rvc-python"
        ]
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + deps + ["--break-system-packages"],
            stdout=f,
            stderr=f,
            text=True
        )
    print(f"Installation finished with code {result.returncode}", flush=True)
except Exception as e:
    print(f"Failed to run subprocess: {e}", flush=True)
