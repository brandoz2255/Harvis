# AI Voice Assistant Documentation

This documentation provides comprehensive information about the AI Voice Assistant project, its technologies, and implementation details. Use this as a reference for understanding the project and preparing for technical interviews.

## Table of Contents

1. [Project Overview](project-overview.md)
2. [Core Technologies](core-technologies.md)
3. [Voice Processing](voice-processing.md)
4. [Browser Automation](browser-automation.md)
5. [LLM Integration](llm-integration.md)
6. [System Architecture](system-architecture.md)
7. [Main and Chatterbox TTS Integration](main-chatterbox-integration.md)
8. [CI/CD Pipelines](ci-cd-pipelines.md)
9. [Docker Deployment](docker-deployment.md)
10. [Interview Preparation](interview-prep.md)
11. [Troubleshooting Guide](troubleshooting.md)

## Quick Start

To get started with the project:

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Start the Ollama server:
```bash
ollama serve
```

3. Run the application:
```bash
python new-chatbot.py
```

## Key Features

- Voice-based interaction with AI
- Browser automation capabilities
- Natural language processing
- Text-to-speech and speech-to-text conversion
- Real-time conversation with LLM
- Web search and navigation
- CUDA error handling with fallback to CPU
- Docker security improvements (non-root user)
- Enhanced VRAM management

## Technology Stack

- Python 3.x
- Gradio for UI
- Ollama for LLM
- Selenium for browser automation
- Chatterbox TTS for voice synthesis
- Whisper for speech recognition
- PyTorch for ML operations

For detailed information about each component, please refer to the specific documentation files.
