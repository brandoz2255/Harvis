import requests
import os
import google.generativeai as genai
from .qwen import Qwen2VL

qwen_model = Qwen2VL()

def query_qwen(image_path: str, prompt: str) -> str:
    try:
        return qwen_model.predict(image_path, prompt)
    except Exception as e:
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