# The Jarvis Project

The Jarvis Project is a sophisticated, voice-activated AI assistant designed to be a proactive and interactive partner on your computer. It combines the power of large language models, voice synthesis, and system automation to provide a seamless interface for controlling your digital environment, retrieving information, and assisting with various tasks.

## Core Features

- **Voice-First Interaction:** Control Jarvis and receive responses primarily through natural voice commands.
- **Vibe Coding (AI-Powered Development):** A dedicated, voice-first, AI-powered development environment. It allows users to write, execute, and debug code through conversational voice and text commands. It operates in two modes:
    - **Assistant Mode:** Turn-by-turn interaction for collaborative, step-by-step coding.
    - **Vibe Mode:** Continuous execution for automating larger tasks with verbal updates and explicit user confirmation for critical actions.
- **Desktop Automation:** Jarvis can interact with your operating system, open applications, and manage files.
- **Browser Automation:** Perform web searches, navigate to websites, and interact with web pages using simple voice commands.
- **Real-time Screen Analysis:** Jarvis can "see" your screen, understand the context of your current task, and provide relevant assistance, powered by Qwen2-VL AI for visual understanding.
- **AI-Powered Chat:** Engage in contextual conversations, ask questions, and get intelligent responses from a powerful language model such  as Mistral.
- **Extensible and Modular:** Built with a modern tech stack that allows for easy expansion and customization.

## Tech Stack

### Frontend
- **Framework:** Next.js (React)
- **Language:** TypeScript
- **Styling:** Tailwind CSS

### Backend
- **API:** Python (FastAPI) & Node.js (Next.js API Routes)
- **AI/LLM:** 
  - Ollama for local language model hosting
  - Qwen2-VL for visual understanding
  - **VibeAgent:** Located in `python_back_end/ollama_cli/vibe_agent.py`, this module orchestrates the AI-powered coding experience.
- **Speech-to-Text (STT):** Whisper
- **Text-to-Speech (TTS):** Chatterbox TTS

### Infrastructure & Deployment
- **Containerization:** Docker & Docker Compose
- **Web Server:** Nginx
- **CI/CD:** GitHub Actions

## Getting Started

### Prerequisites

- Docker and Docker Compose
- An NVIDIA GPU with CUDA drivers is recommended for optimal performance, but not strictly required.
- `ffmpeg` for audio processing.

### Installation & Usage

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd aidev
    ```

2.  **Build and run with Docker Compose:**
    This is the recommended way to run the entire application stack.
    ```bash
    docker-compose up --build -d
    ```

3.  **Access the application:**
    The web interface will be available at `http://localhost:3000`.

## Project Structure

- `front_end/jfrontend/`: Contains the Next.js frontend application.
- `python_back_end/`: The main Python backend, including the FastAPI server, AI logic, and automation scripts.
- `rest_api/`: A separate FastAPI service.
- `docker-compose.yaml`: Defines the services, networks, and volumes for the entire application.
- `nginx.conf`: Nginx configuration for routing traffic to the frontend and backend services.
- `.github/workflows/`: CI/CD pipeline definitions for automated testing and deployment.
