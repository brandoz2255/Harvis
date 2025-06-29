import os
import google.generativeai as genai
from fastapi import HTTPException
from typing import List, Dict, Any

# ─── Gemini Configuration ──────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")

def query_gemini(prompt: str, history: List[Dict[str, Any]]) -> str:
    """
    Sends a prompt and chat history to the Gemini 1.5 Flash model.

    Args:
        prompt: The user's message.
        history: The conversation history.

    Returns:
        The model's response text.
    
    Raises:
        HTTPException: If the API key is not configured or an API error occurs.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured on the server.")
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Translate history to Gemini's format
        gemini_history = []
        for item in history:
            # Ensure content is a non-empty string
            content = item.get("content")
            if not content or not isinstance(content, str):
                continue

            # Map roles: 'user' to 'user', 'assistant' to 'model'
            role = "user" if item.get("role") == "user" else "model"
            gemini_history.append({"role": role, "parts": [{"text": content}]})

        # Start chat and send message
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(prompt)
        return response.text
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred with the Gemini API: {e}")

def is_gemini_configured() -> bool:
    """Checks if the Gemini API key is available."""
    return bool(GEMINI_API_KEY)
