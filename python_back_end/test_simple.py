
import sys
print("Python started", flush=True)
try:
    import torch
    print(f"Torch imported: {torch.__version__}", flush=True)
    print(f"CUDA available: {torch.cuda.is_available()}", flush=True)
    if torch.cuda.is_available():
        print(f"CUDA device: {torch.cuda.get_device_name(0)}", flush=True)
except ImportError:
    print("Torch not found", flush=True)
except Exception as e:
    print(f"Error: {e}", flush=True)
print("Done", flush=True)
