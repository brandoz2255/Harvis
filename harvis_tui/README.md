# TUI Microservice - Terminal Interface for Harvis

A FastAPI microservice with Textual TUI that provides a terminal-based interface
similar to the newjfrontend web interface.

## Features
- 🖥️ Terminal-based UI for interacting with Harvis
- 💬 Chat interface with the AI assistant
- 📁 File/workspace navigation
- 🔌 WebSocket connection to backend
- 🎨 Rich terminal UI with colors, layouts, and keyboard shortcuts

## Quick Start

```bash
# Run the TUI microservice
uvicorn harvis_tui.main:app --host 0.0.0.0 --port 8001

# Then connect via terminal
curl http://localhost:8001/tui/connect
```

## Keyboard Shortcuts
- `Ctrl+C` - Exit
- `Enter` - Send message
- `Ctrl+L` - Clear screen
- `?` - Show help
