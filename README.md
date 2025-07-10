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
- **Database:** PostgreSQL with connection pooling
- **Authentication:** JWT-based with bcrypt password hashing
- **AI/LLM:** 
  - Ollama for local language model hosting
  - Qwen2-VL for visual understanding
  - **VibeAgent:** Located in `python_back_end/ollama_cli/vibe_agent.py`, this module orchestrates the AI-powered coding experience.
  - **Web Search:** LangChain-based with DuckDuckGo integration
  - **Research API:** Comprehensive web search and analysis capabilities
- **Speech-to-Text (STT):** Whisper
- **Text-to-Speech (TTS):** Chatterbox TTS
- **Browser Automation:** Selenium WebDriver

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

2.  **Set up environment variables:**
    Create `.env.local` in `front_end/jfrontend/` with:
    ```bash
    DATABASE_URL=postgresql://user:password@localhost:5432/jarvis
    JWT_SECRET=your-jwt-secret-key
    BACKEND_URL=http://backend:8000
    ```

3.  **Build and run with Docker Compose:**
    This is the recommended way to run the entire application stack.
    ```bash
    docker-compose up --build -d
    ```

4.  **Access the application:**
    The web interface will be available at `http://localhost:3000`.

## Web Search & Research API

Jarvis includes comprehensive web search and research capabilities powered by LangChain and DuckDuckGo:

### API Endpoints

- **`/api/web-search`** - Basic web search with configurable result limits and content extraction
- **`/api/research-chat`** - Enhanced research chat with comprehensive web search and analysis
- **`/api/fact-check`** - Fact-checking claims using web search verification
- **`/api/comparative-research`** - Compare multiple topics using web research

### Features

- **Multi-source Search:** Primary DuckDuckGo search with Tavily API fallback
- **Content Extraction:** Full article content using newspaper3k
- **Research Analysis:** AI-powered analysis and synthesis of search results
- **Rate Limiting Protection:** Built-in handling for search engine rate limits

## Authentication & Database

### Database Schema
- **PostgreSQL** with connection pooling
- **Users table** with JWT authentication
- **Environment-based configuration** for secure connections

### Authentication Options
- **Current:** Frontend API routes (`/app/api/auth/`)
- **Recommended:** Backend-centric authentication for enhanced security
- **JWT tokens** with configurable expiration (default: 1 hour)
- **bcrypt password hashing** for secure credential storage

## Project Structure

- `front_end/jfrontend/`: Contains the Next.js frontend application.
  - `app/`: Next.js app router pages and API routes
  - `components/`: Reusable React components including UI components
  - `lib/`: Utility functions, database connection, and authentication services
  - `stores/`: Zustand state management for chat functionality
- `python_back_end/`: The main Python backend, including the FastAPI server, AI logic, and automation scripts.
  - `research/`: Web search and research functionality
  - `ollama_cli/vibe_agent.py`: AI-powered development environment
- `rest_api/`: A separate FastAPI service.
- `docker-compose.yaml`: Defines the services, networks, and volumes for the entire application.
- `nginx.conf`: Nginx configuration for routing traffic to the frontend and backend services.
- `.github/workflows/`: CI/CD pipeline definitions for automated testing and deployment.

## Development Workflow

### Frontend Development
```bash
cd front_end/jfrontend
npm install
npm run dev          # Start development server
npm run build        # Build for production
npm run lint         # Run ESLint
npm run type-check   # Run TypeScript checking
```

### Docker Operations
```bash
docker-compose up --build -d    # Build and run entire stack
docker-compose down             # Stop all services
docker-compose logs -f [service] # View service logs
```

### Key Development Commands
- **Database setup:** `front_end/jfrontend/db_setup.sql`
- **Type checking:** Always run before committing
- **Git strategy:** Feature branches from `main` with conventional commits

## Security Considerations

### Current Security Features
- **Password Security:** bcrypt hashing with salt
- **Token Management:** JWT with 1-hour expiration
- **Database Security:** Connection pooling and parameterized queries
- **Environment Variables:** Secure configuration management

### Recommended Enhancements
- **Backend Authentication:** Migrate auth logic to Python backend for enhanced security
- **Rate Limiting:** Implement on auth and API endpoints
- **CORS Configuration:** Proper frontend-backend communication
- **Audit Logging:** Track authentication attempts and API access
- **Input Validation:** Server-side validation for all endpoints

## Troubleshooting

### Common Issues
- **Database Connection:** Ensure PostgreSQL service health before frontend starts
- **Authentication:** Check JWT_SECRET consistency across services
- **Web Search 0 Results:** May indicate rate limiting or network issues in Docker
- **Type Errors:** Run `npm run type-check` regularly during development
