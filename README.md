# The Harvis AI Project
### Quick Start (Local Development)

The fastest way to get started locally:

Run the following command to uninstall all conflicting packages:

```bash
sudo apt remove $(dpkg --get-selections docker.io docker-compose docker-compose-v2 docker-doc podman-docker co
```
To install Docker :

```bash
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Installation & Usage

## 1.  **Clone the repository:**
```bash
    git clone <repository_url>
    cd Harvis
```
<img width="760" height="163" alt="clone" src="https://github.com/user-attachments/assets/f0ddf838-296e-4ecd-bb91-e34414f0b930" />
    
## 2.  **Set up environment variables:**
Copy the example env files, then create a top-level `.env` for the values `docker-compose.yaml` reads:

```bash
    cp python_back_end/.env.example python_back_end/.env
    # top-level .env (docker-compose reads these):
    JWT_SECRET=<a-long-random-secret>       # REQUIRED — compose fails to start without it
    MOONSHOT_API_KEY=<kimi-key>             # optional — cloud planner/writer (Kimi K2.5)
    OPENCLAW_GATEWAY_TOKEN=<token>          # optional — OpenClaw agent runtime
```
See `docker-compose.yaml` for the full list of variables.

## 3.  **Run — `./install.sh`:**
There is nothing to choose. Harvis ships the workspace — UI, API, routing, auth, ONNX speech,
embeddings — and needs **no GPU of its own**, so the old nvidia/amd/cpu question is gone. The
installer looks for a model server you already run, generates the secrets `.env` needs, creates the
docker network, and launches the stack:

```bash
    ./install.sh          # detects a local model server, then installs
    ./install.sh --yes    # same, non-interactive
```

It probes this machine for an OpenAI-compatible server and uses the first one it finds:

| Port | Server |
|---|---|
| 11434 | Ollama |
| 1234 | LM Studio |
| 8080 | llama.cpp |
| 8000 | vLLM |

Point it somewhere else with `./install.sh --llm-url http://host.docker.internal:11434` — note that
`localhost` inside a container means *the container*, so use `host.docker.internal` or a LAN IP for a
server on your own machine. Found or not, the stack starts either way: with no server running, Harvis
comes up and reports that no model provider is connected, and you can attach one from Settings later.

**Apple Silicon (M-series):** Docker on macOS can't reach the Mac GPU, so run **Ollama natively** for
Metal acceleration — the installer will find it on 11434 like any other host server.

<details><summary>Manual / advanced (skip the installer)</summary>

```bash
    docker network create ollama-n8n-network    # once (external network)
    docker compose up --build -d
```
`JWT_SECRET` must be set in `.env` for this to start. Set `HARVIS_LLM_BASE_URL` to your model
server; every service resolves against it, falling back to `OLLAMA_URL` and then to
`http://host.docker.internal:11434`.
</details>

## 4.  **Access the application:**
Open **`http://localhost:9000`** — Nginx serves the web UI and proxies all `/api/*` calls to the
backend. Do **not** call the backend on `:8000` directly from the browser (CORS). The live UI is
the Svelte app built from `front_end/owui/`.



The Harvis AI Project is a sophisticated, voice-activated AI assistant designed to be a proactive and interactive partner on your computer. It combines the power of large language models, voice synthesis, and system automation to provide a seamless interface for controlling your digital environment, retrieving information, and assisting with various tasks.

## Core Features

- **Voice-First Interaction:** Control Harvis AI and receive responses primarily through natural voice commands.
- **Vibe Coding (AI-Powered Development):** A dedicated, voice-first, AI-powered development environment. It allows users to write, execute, and debug code through conversational voice and text commands. It operates in two modes:
    - **Assistant Mode:** Turn-by-turn interaction for collaborative, step-by-step coding.
    - **Vibe Mode:** Continuous execution for automating larger tasks with verbal updates and explicit user confirmation for critical actions.
- **n8n Workflow Automation:** AI-powered natural language to n8n workflow creation system that interprets user requests and automatically generates sophisticated automation workflows.
- **Desktop Automation:** Harvis AI can interact with your operating system, open applications, and manage files.
- **Browser Automation:** Perform web searches, navigate to websites, and interact with web pages using simple voice commands.
- **Real-time Screen Analysis:** Harvis AI can "see" your screen, understand the context of your current task, and provide relevant assistance, powered by Qwen2-VL AI for visual understanding.
- **AI-Powered Chat:** Engage in contextual conversations, ask questions, and get intelligent responses from a powerful language model such as Mistral.
- **Reasoning Model Support:** Full integration with reasoning models (DeepSeek R1, QwQ, O1) with automatic separation of thinking process from final answers.
- **Extensible and Modular:** Built with a modern tech stack that allows for easy expansion and customization.

## Tech Stack

<img width="1653" height="1392" alt="image" src="https://github.com/user-attachments/assets/36dd9d2d-9313-41bb-9491-313838ed5e97" />

### Frontend
- **Live UI:** `front_end/owui/` — a forked **OpenWebUI (SvelteKit)** app, built to a static
  bundle and served by Nginx at `/`. This is the current, canonical frontend.
- **Language / Styling:** TypeScript · Tailwind CSS
- *Legacy:* `front_end/newjfrontend/` (Next.js) is vestigial (see Deployment notes); the old
  `front_end/jfrontend/` was removed.

### Backend
- **API:** Python (FastAPI) & Node.js (Next.js API Routes)
- **Database:** PostgreSQL with connection pooling
- **Authentication:** JWT-based with bcrypt password hashing
- **AI/LLM:** 
  - Ollama for local language model hosting
  - **External Model Support:** Ability to route specific large models (e.g., `qwen3:235b`) to external Ollama endpoints, with automatic API key authentication.
  - Qwen2-VL for visual understanding
  - **VibeAgent:** Located in `python_back_end/ollama_cli/vibe_agent.py`, this module orchestrates the AI-powered coding experience.
  - **Web Search:** LangChain-based with DuckDuckGo integration
  - **Research API:** Comprehensive web search and analysis capabilities
  - **n8n Automation:** AI-powered workflow automation with natural language processing
- **Speech-to-Text (STT):** Whisper
- **Text-to-Speech (TTS):** Chatterbox TTS
- **Browser Automation:** Selenium WebDriver
- **Workflow Automation:** n8n integration with AI-powered workflow generation

### Infrastructure & Deployment
- **Containerization:** Docker & Docker Compose
- **Web Server:** Nginx
- **CI/CD:** GitHub Actions

## Getting Started

### Prerequisites

- Docker and Docker Compose (v2 / the `docker compose` plugin).
- A GPU is **optional** — `./install.sh` supports **nvidia**, **amd** (ROCm), or **cpu**. Only the
  `nvidia` backend needs an NVIDIA GPU + nvidia-container-toolkit; `cpu` runs anywhere. See the
  "Choose your backend" section above.
- `ffmpeg` for audio (voice) features.


## n8n Workflow Automation API

Harvis AI includes a sophisticated AI-powered n8n workflow automation system that interprets natural language requests and automatically generates corresponding n8n workflows.

### Architecture Overview

The n8n automation system consists of several interconnected components:

1. **AI Analysis Engine** - Uses Ollama/Mistral to parse natural language requests
2. **Workflow Builder** - Constructs n8n-compatible workflow configurations
3. **n8n Client** - Manages communication with n8n REST API
4. **Database Storage** - Tracks created workflows and automation history
5. **Template System** - Provides pre-built workflow templates for common tasks

### API Endpoints

#### Core Automation Endpoints

- **`POST /api/n8n/automate`** - Create workflow from natural language prompt
- **`POST /api/n8n/workflow`** - Create workflow from predefined template
- **`GET /api/n8n/workflows`** - List user's created workflows
- **`GET /api/n8n/templates`** - List available workflow templates
- **`POST /api/n8n/workflow/{id}/execute`** - Execute workflow manually
- **`GET /api/n8n/workflow/{id}/executions`** - Get workflow execution history
- **`GET /api/n8n/history`** - Get user's automation request history
- **`GET /api/n8n/health`** - Check system health and connectivity

#### Frontend Proxy Endpoints

- **`POST /api/n8n-automation`** - Next.js proxy route for browser access

### Key Libraries and Dependencies

#### Backend (Python)
- **`requests`** - HTTP client for n8n API communication
- **`pydantic`** - Data validation and serialization
- **`asyncpg`** - PostgreSQL async database driver
- **`fastapi`** - API framework
- **`ollama`** - AI model integration

#### Frontend (TypeScript)
- **`next.js`** - React framework for API routes
- **`react`** - UI components and state management

### How It Works

#### 1. Natural Language Processing
```python
# User input: "Every 5 minutes, check if google.com is up. If not, send Discord message"
async def _analyze_user_prompt(prompt: str, model: str = "mistral"):
    # AI analyzes request and returns structured workflow requirements
    return {
        "feasible": True,
        "workflow_type": "schedule",
        "nodes_required": ["scheduleTrigger", "httpRequest", "if", "discord"],
        "schedule": {"interval": "5 minutes"},
        "parameters": {"url": "https://google.com", "discord_webhook": "..."}
    }
```

#### 2. Workflow Generation
```python
# Converts AI analysis into n8n workflow configuration
def build_ai_workflow(name: str, description: str, requirements: Dict):
    config = WorkflowConfig(name=name, nodes=[], connections={})
    
    # Add trigger node
    if requirements["trigger"] == "schedule":
        config.nodes.append(create_schedule_trigger(requirements["schedule"]))
    
    # Add action nodes based on requirements
    for action in requirements["actions"]:
        config.nodes.append(create_action_node(action))
    
    return config
```

#### 3. n8n Integration
```python
# Creates workflow in n8n via REST API
def create_workflow(workflow_config: Dict) -> Dict:
    response = requests.post(
        f"{self.base_url}/api/v1/workflows",
        json=workflow_config,
        auth=HTTPBasicAuth(self.username, self.password)
    )
    return response.json()
```

### Workflow Templates

The system includes predefined templates for common automation scenarios:

- **`weather_monitor`** - Scheduled weather data fetching with notifications
- **`web_scraper`** - Periodic website data extraction
- **`slack_notification`** - Slack message automation
- **`email_automation`** - Email sending workflows  
- **`http_api`** - HTTP API integration workflows
- **`webhook_receiver`** - Webhook handling workflows

### Design Decisions

#### Why We Built It This Way

1. **Microservices Architecture**: Separates concerns between AI processing, workflow building, and n8n communication
2. **Template-Based Approach**: Provides reliable, tested workflow patterns while allowing custom generation
3. **AI-Powered Analysis**: Enables natural language input without rigid syntax requirements
4. **Database Tracking**: Maintains audit trail and allows workflow management
5. **Docker Network Integration**: Seamless communication between services in containerized environment

#### Browser-to-Docker Network Pattern
Since browsers cannot access Docker internal networks, we use a proxy pattern:
```
Browser → Next.js Route → Python Backend → n8n Service
```

### Database Schema

The system uses PostgreSQL to track workflows and automation history:

```sql
-- Workflow records
CREATE TABLE n8n_workflows (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR(255) UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    prompt TEXT,
    template_id VARCHAR(100),
    config JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'created',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Automation history
CREATE TABLE n8n_automation_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    prompt TEXT NOT NULL,
    response TEXT NOT NULL,
    workflow_id VARCHAR(255),
    success BOOLEAN NOT NULL,
    error_message TEXT,
    execution_time FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Future Possibilities

#### Short-term Enhancements
- **Visual Workflow Preview**: Generate workflow diagrams before creation
- **Advanced Templates**: More sophisticated workflow templates for complex scenarios
- **Workflow Versioning**: Track changes and allow rollbacks
- **Real-time Monitoring**: Live workflow execution monitoring dashboard

#### Long-term Vision
- **Multi-Platform Support**: Integration with Zapier, Microsoft Power Automate, etc.
- **AI Workflow Optimization**: Suggest improvements based on execution patterns
- **Natural Language Debugging**: "My workflow isn't working" → AI diagnosis and fixes
- **Collaborative Workflows**: Team-based workflow creation and sharing
- **Integration Marketplace**: Community-contributed workflow templates

#### Technical Improvements
- **Caching Layer**: Redis for workflow templates and AI analysis results
- **Rate Limiting**: Prevent abuse of AI analysis endpoints
- **Webhook Management**: Dynamic webhook URL generation and routing
- **Error Recovery**: Automatic workflow repair and retry mechanisms

## Web Search & Research API

Harvis AI includes comprehensive web search and research capabilities powered by LangChain and DuckDuckGo:

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

- `front_end/owui/`: **The live frontend** — a forked OpenWebUI (SvelteKit) app. Built to a static
  bundle and served by Nginx at `/`. Most UI work happens here (`src/lib/`, `src/routes/`).
- `front_end/newjfrontend/`: Legacy Next.js frontend — vestigial (Nginx only proxies `/api/ai-chat`
  to it, and the live UI never calls that route). Slated for removal.
- `front_end/open-notebook/`: Vendored NotebookLM-style Next.js UI, served at `/onb`.
- `python_back_end/`: The main Python backend — FastAPI server, AI logic, orchestration, automation.
  - `research/`: Web search and research functionality
  - `ollama_cli/vibe_agent.py`: AI-powered development environment
- `rest_api/`: A separate FastAPI service.
- `docker-compose.yaml`: Defines the services, networks, and volumes for the entire application.
- `nginx.conf`: Nginx configuration for routing traffic to the frontend and backend services.
- `.github/workflows/`: CI/CD pipeline definitions for automated testing and deployment.

## Development Workflow

### Frontend Development (owui — the live UI)
> First-time deploy needs none of this — `docker compose up --build` builds the owui
> bundle inside Docker (the `owui-builder` service) and Nginx waits for it. The steps
> below are only for a fast **local** edit loop, where a host build beats a container rebuild.
```bash
cd front_end/owui
npm install
npm run build        # produce the static bundle Nginx serves at /
```
After a build, reload Nginx to serve it: `docker restart nginx-proxy`.
(The `owui-builder` step is idempotent — it skips when `front_end/owui/build` already
exists, so your host build is never clobbered. Clear that dir to force a Docker rebuild.)

### Docker Operations
```bash
docker compose up --build -d     # Build and run the entire stack (Nginx at :9000)
docker compose down              # Stop all services
docker compose logs -f [service] # View service logs
docker restart harvis-backend    # Backend is bind-mounted — restart to pick up Python changes
```

### Key Development Commands
- **Type checking:** `npm run type-check` in `front_end/owui` before committing UI changes.
- **Backend tests:** `docker exec harvis-backend python -m pytest tests/ -q`.
- **Git strategy:** Feature branches from `main` with conventional commits.

## Recent Improvements & Changes


### Latest Updates (2026-01-26)

#### Core Improvements
- ✅ **Research Agent**: Significantly improved output quality for deep research tasks, utilizing the new "Cards" UI.
- ✅ **UI Redesign**: Complete visual overhaul with a new "Cards" layout for better information density and aesthetics.
- ✅ **Streaming Responses**: Implemented true Server-Sent Events (SSE) streaming for chat and voice, resolving Nginx 499 timeouts.
- ✅ **User Experience**: Fixed independent scrolling issues for the sidebar and main chat area.

### Latest Updates (2025-01-17)

#### Security Enhancements
- ✅ **XSS Vulnerability Fix**: Resolved unescaped entities in React components
- ✅ **React Hook Dependencies**: Fixed useEffect dependency warnings
- ✅ **Performance Optimization**: Added useCallback to prevent unnecessary re-renders
- ✅ **Code Quality**: All ESLint warnings and errors resolved

#### Reasoning Model Integration
- ✅ **Full Reasoning Support**: Automatic detection of reasoning models (DeepSeek R1, QwQ, O1)
- ✅ **Content Separation**: Thinking process separated from final answers server-side
- ✅ **Clean UI**: Main chat shows only final answers, AI insights shows reasoning
- ✅ **TTS Optimization**: Chatterbox reads only final answers (not thinking process)

#### Chat Interface Improvements
- ✅ **Infinite Loop Fixes**: Resolved infinite render loops in chat components
- ✅ **Model Selection**: Ollama models properly populate in dropdown
- ✅ **Session Management**: Fixed chat history infinite fetching issues
- ✅ **Database Integration**: Proper UUID handling for chat sessions

### Development Notes

#### Change Tracking
Design/architecture decisions and session handoffs are tracked in `docs/handoffs/` and the
project's Obsidian vault; per-fix notes live alongside the code. (The former
`front_end/jfrontend/changes.md` was removed with that directory.)

#### Quality Assurance
- All changes pass `npm run lint` and `npm run type-check`
- Security vulnerabilities proactively identified and resolved
- Performance optimizations implemented for better user experience

## Security Considerations

### Current Security Features
- **Password Security:** bcrypt hashing with salt
- **Token Management:** JWT with 1-hour expiration
- **Database Security:** Connection pooling and parameterized queries
- **Environment Variables:** Secure configuration management

### Recent Security Improvements (2025-01-17)
- **XSS Protection:** Fixed unescaped entities in React components
- **React Hook Security:** Resolved useEffect dependency warnings preventing stale closures
- **Performance Optimization:** Wrapped functions in useCallback to prevent unnecessary re-renders
- **Code Quality:** All ESLint security warnings resolved
- **Memory Leak Prevention:** Proper cleanup of event listeners and timeouts

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
