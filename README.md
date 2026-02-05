# The Harvis AI Project

<img width="1653" height="1392" alt="image" src="https://github.com/user-attachments/assets/36dd9d2d-9313-41bb-9491-313838ed5e97" />


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

- Docker and Docker Compose
- An NVIDIA GPU with CUDA drivers is recommended for optimal performance, but not strictly required.
- `ffmpeg` for audio processing.

### Quick Start (Local Development)

The fastest way to get started locally:

```bash
docker-compose build
docker-compose up
```

That's it! The application will be available at `http://localhost:3000`.

### Installation & Usage

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd aidev
    ```

2.  **Set up environment variables:**
    Create `.env.local` in `front_end/jfrontend/` with:
    ```bash
    DATABASE_URL=postgresql://user:password@localhost:5432/harvis
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
All modifications are documented in `/front_end/jfrontend/changes.md` with:
- Timestamp and problem description
- Root cause analysis
- Solution implementation details
- Files modified and results

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
