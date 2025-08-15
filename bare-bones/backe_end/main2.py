from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

# CORS setup (same as before)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/hello")
def hello():
    return {"message": "Hello from FastAPI!"}

@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    user_message = data.get("message", "")
    chat_history = data.get("history", [])

    # Prepare prompt with optional history
    prompt = ""
    for turn in chat_history:
        prompt += f"User: {turn.get('user', '')}\nAssistant: {turn.get('assistant', '')}\n"
    prompt += f"User: {user_message}\nAssistant:"

    # Call Ollama to get AI response
    try:
        response = requests.post("http://ollama:11434/api/generate", json={
            "model": "gemma3:1b",  # or any model you've pulled
            "prompt": prompt,
            "stream": False
        }, timeout=90)
        response.raise_for_status()
        ollama_data = response.json()
        assistant_reply = ollama_data.get("response", "Sorry, no reply.")

    except Exception as e:
        print("Error talking to Ollama:", e)
        assistant_reply = "Ollama backend is not responding."

    # Update history and return
    chat_history.append({"user": user_message, "assistant": assistant_reply})
    return {
        "reply": assistant_reply,
        "history": chat_history
    }
