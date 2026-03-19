"""
Harvis TUI Microservice

A FastAPI microservice providing a terminal-based UI for Harvis.
"""

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
import json
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
import uuid

app = FastAPI(
    title="Harvis TUI Microservice",
    description="Terminal-based UI for Harvis AI",
    version="0.1.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Backend connection settings
BACKEND_URL = "http://localhost:8000"

# Active TUI sessions
active_sessions: Dict[str, "TUISession"] = {}


class TUISession:
    """Manages a TUI session."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now()
        self.messages: List[dict] = []
        self.current_workspace = "default"
        self.is_active = True


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Harvis TUI Microservice",
        "version": "0.1.0",
        "endpoints": {
            "/health": "Health check",
            "/tui/connect": "Connect TUI interface",
            "/tui/chat": "Chat with Harvis",
            "/tui/workspaces": "List workspaces",
            "/tui/files": "List files in workspace",
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(active_sessions)
    }


@app.get("/tui/connect")
async def connect_tui():
    """Create a new TUI connection."""
    session_id = str(uuid.uuid4())
    session = TUISession(session_id)
    active_sessions[session_id] = session
    
    return {
        "session_id": session_id,
        "welcome": "Welcome to Harvis TUI! 🌶️",
        "instructions": [
            "Type your message and press Enter",
            "Type 'help' for commands",
            "Type 'exit' to disconnect"
        ]
    }


@app.post("/tui/chat")
async def chat(message: dict):
    """Chat endpoint."""
    session_id = message.get("session_id")
    user_message = message.get("message", "")
    
    if not session_id or session_id not in active_sessions:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid session. Connect first via /tui/connect"}
        )
    
    session = active_sessions[session_id]
    
    # Handle special commands
    if user_message.lower() == "help":
        return {
            "response": """Available commands:
  help     - Show this help
  workspaces - List workspaces
  files [path] - List files
  clear    - Clear conversation
  exit     - Disconnect""",
            "type": "command"
        }
    
    elif user_message.lower() == "exit":
        del active_sessions[session_id]
        return {"response": "Goodbye! 👋", "type": "farewell"}
    
    elif user_message.lower() == "clear":
        session.messages = []
        return {"response": "Conversation cleared.", "type": "system"}
    
    elif user_message.lower() == "workspaces":
        return {
            "response": "Current workspace: " + session.current_workspace,
            "type": "info"
        }
    
    else:
        # Echo back for now - would connect to actual AI backend
        session.messages.append({"role": "user", "content": user_message})
        return {
            "response": f"You said: {user_message}\n\n(This is a demo - connect to backend for real AI responses)",
            "type": "echo"
        }


@app.get("/tui/workspaces")
async def list_workspaces():
    """List available workspaces."""
    return {
        "workspaces": [
            {"name": "default", "path": "/home/node/.openclaw/workspace"},
            {"name": "harvis", "path": "/home/node/.openclaw/workspace/Harvis"},
        ]
    }


@app.get("/tui/files/{path:path}")
async def list_files(path: str = ""):
    """List files in a path."""
    return {
        "path": path,
        "files": [
            {"name": "README.md", "type": "file", "size": 1234},
            {"name": "main.py", "type": "file", "size": 5678},
            {"name": "components", "type": "directory"},
        ]
    }


@app.websocket("/ws/tui")
async def websocket_tui(websocket: WebSocket):
    """WebSocket endpoint for real-time TUI updates."""
    await websocket.accept()
    session_id = str(uuid.uuid4())
    active_sessions[session_id] = TUISession(session_id)
    
    try:
        await websocket.send_json({
            "type": "welcome",
            "session_id": session_id,
            "message": "Connected to Harvis TUI! 🌶️"
        })
        
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Process message
            response = await chat(message)
            await websocket.send_json(response)
            
    except WebSocketDisconnect:
        if session_id in active_sessions:
            del active_sessions[session_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
