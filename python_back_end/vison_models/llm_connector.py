import requests
import os
import torch
import logging
import google.generativeai as genai
from .qwen import Qwen2VL

# Set up logging
logger = logging.getLogger(__name__)

# Global model variable for memory management
qwen_model = None

def log_gpu_memory(stage: str):
    """Log current GPU memory usage"""
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        free = total - allocated
        logger.info(f"🔍 GPU Memory {stage}: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved, {free:.2f}GB free")

def load_qwen_model():
    """Load Qwen2VL model if not already loaded"""
    global qwen_model
    if qwen_model is None:
        log_gpu_memory("before Qwen2VL load")
        
        # Additional cleanup before loading
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            import gc
            gc.collect()
            torch.cuda.empty_cache()
        
        logger.info("🔄 Loading Qwen2VL model")
        try:
            qwen_model = Qwen2VL()
            log_gpu_memory("after Qwen2VL load")
            logger.info("✅ Qwen2VL model loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load Qwen2VL model: {e}")
            # Try to free more memory and retry once
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                import time
                time.sleep(1)
            raise
    return qwen_model

def unload_qwen_model():
    """Unload Qwen2VL model to free GPU memory"""
    global qwen_model
    if qwen_model is not None:
        log_gpu_memory("before Qwen2VL unload")
        logger.info("🗑️ Unloading Qwen2VL model to free GPU memory")
        del qwen_model
        qwen_model = None
        
        # Aggressive GPU cleanup
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            import gc
            gc.collect()
            torch.cuda.empty_cache()
            # Wait for cleanup to complete
            import time
            time.sleep(0.5)
            torch.cuda.empty_cache()
            
        log_gpu_memory("after Qwen2VL unload")
        logger.info("🧹 GPU cache cleared after Qwen2VL unload")

def query_qwen(image_path: str, prompt: str) -> str:
    """Query Qwen2VL model with automatic loading"""
    try:
        model = load_qwen_model()
        return model.predict(image_path, prompt)
    except Exception as e:
        logger.error(f"Qwen2VL query failed: {e}")
        return f"[Qwen error] {e}"

OLLAMA_URL = "http://ollama:11434"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def query_llm(prompt: str, model_name: str = "mistral", system_prompt: str = "") -> str:
    if model_name.startswith("gemini"):
        if not GEMINI_API_KEY:
            return "[LLM error] Gemini API key not configured."
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"[LLM error] Gemini: {e}"
    else:
        try:
            res = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "system": system_prompt,
                    "stream": False
                },
                timeout=60
            )
            res.raise_for_status()
            return res.json().get("response", "").strip()
        except Exception as e:
            return f"[LLM error] Ollama: {e}"

def list_ollama_models() -> list[str]:
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        res.raise_for_status()
        models = res.json().get("models", [])
        return [model["name"] for model in models]
    except Exception as e:
        print(f"Error listing Ollama models: {e}")
        return []