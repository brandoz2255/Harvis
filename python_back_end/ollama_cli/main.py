
import requests
import json
import argparse

OLLAMA_URL = "http://ollama:11434"
DEFAULT_MODEL = "mistral"

def get_available_models():
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
        return [model["name"] for model in models]
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Ollama: {e}")
        return []

def chat(message, model, history):
    try:
        system_prompt = (
            'You are "Jarves", a voice-first local assistant. '
            "Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural, Be bilangual about 80 percent english and 20 percent spanish"
            'Begin each answer with a short verbal acknowledgment (e.g., "Claro,", "¡Por supuesto!", "Right away").'
        )
        OLLAMA_ENDPOINT = "/api/chat"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "stream": False,
        }

        response = requests.post(
            f"{OLLAMA_URL}{OLLAMA_ENDPOINT}", json=payload, timeout=90
        )
        response.raise_for_status()

        return response.json().get("message", {}).get("content", "").strip()

    except requests.exceptions.RequestException as e:
        return f"Error during chat: {e}"

def main():
    parser = argparse.ArgumentParser(description="Ollama CLI")
    parser.add_argument("message", type=str, help="The message to send to the chat model.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="The chat model to use.")
    parser.add_argument("--list-models", action="store_true", help="List available models.")

    args = parser.parse_args()

    if args.list_models:
        models = get_available_models()
        if models:
            print("Available models:")
            for model in models:
                print(f"- {model}")
        else:
            print("No models available.")
        return

    if args.message:
        response = chat(args.message, args.model, [])
        print(response)

if __name__ == "__main__":
    from tui import OllamaTUI
    app = OllamaTUI()
    app.run()
