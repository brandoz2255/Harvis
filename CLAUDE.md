# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is the Harvis AI Project, a sophisticated AI voice assistant that combines Next.js frontend with Python backend services. The project features voice-first interaction, browser automation, AI-powered coding assistance, and authentication with PostgreSQL.


Remember the web app is ran through docker commands and the docker compose is just for the microservices that the web app runs on

## Docker Network URLs

**IMPORTANT**: Services communicate within Docker network using these URLs:
- **Backend URL**: `http://backend:8000` (Python FastAPI backend)
- **Frontend URL**: `http://frontend:3000` (Next.js frontend)
- **Ollama URL**: `http://ollama:11434` (Ollama AI models server)
- **Database URL**: `postgresql://pguser:pgpassword@pgsql:5432/database`

These are the correct URLs for inter-service communication within the Docker network.

### Architecture: Nginx Proxy + Backend Authentication

**IMPORTANT**: The application uses Nginx as a reverse proxy to handle all frontend-backend communication. All authentication logic is handled by the Python backend.

#### ❌ Incorrect (Direct backend calls):
```javascript
// This will fail due to CORS:
fetch("http://localhost:8000/api/auth/login")
```

#### ✅ Correct (Nginx Proxy Pattern):

**Nginx Configuration**: All API calls are proxied to the backend:
```nginx
location /api/ {
    proxy_pass http://backend:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

**Frontend Calls**: Use relative paths that Nginx proxies:
```javascript
// Browser calls are proxied by Nginx to backend:
fetch("/api/auth/login", {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password })
})
```

#### Communication Flow:
```
Browser → Nginx Proxy → Backend → Ollama/DB
   ↑         (Proxy)      ↑         ↑
   └──────────────────────┴─────────┴─ Docker Network
```

#### Authentication Architecture:
- **Backend-Only Authentication**: All auth logic in Python FastAPI backend
- **No Frontend API Routes**: Frontend only handles UI and calls backend via Nginx
- **CORS Configuration**: Backend properly configured for Nginx proxy
- **JWT Tokens**: Generated and validated entirely by backend
- **Database Access**: Only backend connects to PostgreSQL

#### **IMPORTANT: Access Pattern**
**✅ Correct Way to Access the Application:**
- Access via Nginx proxy: `http://localhost:9000`
- All API calls use relative paths: `/api/auth/login`, `/api/chat`, etc.
- Nginx handles all proxying and CORS headers

**❌ Incorrect (Will cause CORS errors):**
- Accessing backend directly: `http://localhost:8000` 
- Making direct backend API calls from browser

This pattern eliminates CORS issues and centralizes all logic in the backend.

## Database Safety and Management

**🚨 CRITICAL: Database data protection measures are now in place to prevent accidental data loss.**

### Database Safety Features

#### **Production-Safe Schema Script**
- **Location**: `front_end/jfrontend/db_setup.sql`
- **Safety**: Now uses `CREATE TABLE IF NOT EXISTS` (safe)
- **Previous Danger**: Contained `DROP TABLE CASCADE` (removed)
- **Purpose**: Safe table creation for production deployments

#### **Development Reset Script**
- **Location**: `dev-setup/db_reset_dev_only.sql` 
- **⚠️ DESTRUCTIVE**: Drops all tables and data
- **Use Case**: Development environment database reset only
- **Safety**: Clearly marked as development-only with warnings

### **Backup and Restore System**

#### **Automatic Backup Script**
```bash
./database-backup/backup.sh
```
- Creates timestamped backups: `harvis_backup_20250113_143022.sql`
- Automatic cleanup (keeps 10 most recent)
- Backup verification and size reporting

#### **Safe Restore Script**
```bash
# List available backups
./database-backup/restore.sh

# Restore latest backup  
./database-backup/restore.sh latest

# Restore specific backup
./database-backup/restore.sh harvis_backup_20250113_143022.sql
```
- **Safety backup**: Creates backup before restore
- **Confirmation prompts**: Prevents accidental restores
- **Verification**: Confirms restore completed successfully

### **Database Safety Workflow**

#### **Before Any Database Changes:**
1. **Always backup first**: `./database-backup/backup.sh`
2. **Make changes**: Schema updates, migrations, etc.
3. **If problems occur**: `./database-backup/restore.sh latest`

#### **Development Database Reset:**
```bash
# DEVELOPMENT ONLY - destroys all data
docker exec -i pgsql-db psql -U pguser -d database < dev-setup/db_reset_dev_only.sql

# Recreate tables safely
docker exec -i pgsql-db psql -U pguser -d database < front_end/jfrontend/db_setup.sql
```

#### **Production Database Updates:**
1. **Backup**: `./database-backup/backup.sh`
2. **Test on staging**: Never test on production first
3. **Apply changes**: Use migration scripts, not DROP commands
4. **Verify**: Check data integrity after changes

### **Database Security Considerations**

#### **Access Control**
- Database connection only from backend services
- No direct frontend database access
- Connection pooling with proper timeout settings
- Environment variables for sensitive credentials

#### **Data Protection**
- Password hashing with bcrypt
- JWT token expiration (configurable)
- No sensitive data in logs or error messages
- Database volume persistence with Docker

### **Common Issues Prevention**

#### **Data Loss Prevention**
- ✅ Removed dangerous `DROP TABLE CASCADE` from production scripts
- ✅ Separated development reset from production setup
- ✅ Added backup/restore system with safety measures
- ✅ Clear documentation of destructive vs safe operations

#### **Recovery Procedures**
- Regular automated backups (recommended: daily)
- Quick restore capability with verification
- Safety backups before any restore operation
- Clear documentation of backup/restore workflows

### Reasoning Model Integration

**IMPORTANT**: The application now fully supports reasoning models (DeepSeek R1, QwQ, O1, etc.) with proper separation of thinking process from final answers.

#### How It Works:

1. **Automatic Detection**: Backend detects `<think>...</think>` tags in model responses
2. **Content Separation**: Thinking process extracted from final answer server-side  
3. **Clean UI**: Main chat shows only final answers, AI insights shows reasoning
4. **TTS Optimization**: Chatterbox reads only final answers (not thinking process)

#### Backend Implementation:
```python
def separate_thinking_from_final_output(text: str) -> tuple[str, str]:
    """Extract reasoning content and return (reasoning, final_answer)"""
    # Processes <think>...</think> tags
    # Returns clean separation of content
```

#### API Response Format:
```json
{
  "history": [...],
  "audio_path": "/api/audio/...",
  "reasoning": "The thinking process...",     // Only if reasoning detected
  "final_answer": "The clean answer..."      // Clean answer for display/TTS
}
```

#### Frontend Handling:
- **Chat Bubble**: Displays only `final_answer` 
- **TTS/Chatterbox**: Reads only `final_answer`
- **AI Insights**: Shows `reasoning` with purple CPU icon
- **Zero Regression**: Non-reasoning models work exactly as before

#### Supported Models:
- Any model using `<think>...</think>` tag format
- DeepSeek R1 series, QwQ-32B, O1/O3 models
- Future: Can extend to support vLLM `reasoning_content` API format

#### Extensibility:
- Easy to modify `separate_thinking_from_final_output()` for other tag formats
- AI insights can be enhanced with reasoning analysis features
- Can add reasoning quality scoring or step-by-step breakdown display

## Documentation Requirements

**IMPORTANT for Claude Code**: Always document all changes and fixes in `front_end/jfrontend/changes.md` with:
- Timestamp of the change
- Problem description
- Root cause analysis  
- Solution applied
- Files modified
- Result/status

This helps track all modifications and provides debugging context for future development.

## Fixes and Troubleshooting

**IMPORTANT**: Before implementing solutions for common issues, check the `fixes/` directory for documented solutions:
- `fixes/` contains detailed documentation of resolved issues with complete step-by-step solutions
- Each fix document includes problem symptoms, root cause analysis, failed approaches, and working solutions
- When encountering authentication errors, API failures, or integration issues, search `fixes/` first
- Always reference existing fix documentation in new changes.md entries

Common fix categories:
- Authentication issues (n8n, database, JWT)
- API integration problems  
- Docker networking and configuration
- Frontend-backend communication errors 


## Key Commands

### Frontend Development (jfrontend)
- `cd front_end/jfrontend` - Navigate to the main frontend directory
- `npm run dev` - Start development server (runs on port 3000)
- `npm run build` - Build for production
- `npm run start` - Start production server
- `npm run lint` - Run ESLint
- `npm run type-check` - Run TypeScript type checking

### Docker Operations
- `docker-compose up --build -d` - Build and run the entire stack
- `docker-compose down` - Stop all services
- `docker-compose logs -f [service]` - View logs for specific service

### Database Operations
- Database setup script: `front_end/jfrontend/db_setup.sql`
- PostgreSQL runs on port 5432 in container
- Uses environment variables from `.env.local`

## Architecture Overview

### Frontend (Next.js)
- **Location**: `front_end/jfrontend/`
- **Framework**: Next.js 14 with App Router
- **Styling**: Tailwind CSS with Radix UI components
- **State Management**: Zustand for chat state
- **Authentication**: JWT-based with bcrypt password hashing

### Backend Services
- **Python Backend**: `python_back_end/` - Main AI processing, voice controls, browser automation
- **REST API**: `rest_api/` - Additional API services
- **Database**: PostgreSQL with connection pooling

### Key Frontend Directories
- `app/` - Next.js app router pages and API routes
- `components/` - Reusable React components including UI components
- `lib/` - Utility functions, database connection, and authentication services
- `stores/` - Zustand state management
- `rag_context/` - RAG context documentation

## Database Schema

### Users Table
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    avatar VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Authentication Architecture

### Recommended Approach: Backend-Centric Authentication (Most Secure)

**Current Status**: Authentication is currently handled by the Next.js frontend API routes. For maximum security, consider migrating to Python backend authentication.

### Option 1: Python Backend Authentication (RECOMMENDED - Most Secure)
- **Location**: Add auth endpoints to `python_back_end/main.py`
- **Database**: Direct PostgreSQL connection from Python using `psycopg2` or `asyncpg`
- **Security Benefits**:
  - Server-side password hashing with bcrypt
  - JWT token generation and validation on backend
  - Database queries isolated from frontend
  - Protection against client-side manipulation
  - Centralized auth logic for all AI services

### Option 2: Frontend API Routes (Current Implementation)
- **Location**: `front_end/jfrontend/app/api/auth/`
- **Database**: Uses `pg` library with connection pooling
- **Security**: Good but less secure than backend auth
- **Current Flow**:
  1. User signup/login through `/api/auth/login` or `/api/auth/signup`
  2. Passwords hashed with bcrypt
  3. JWT tokens generated with 1-hour expiration
  4. Token verification handled by `/api/me` endpoint

### Migration Path (Frontend → Backend Auth)
1. Create Python auth endpoints in `python_back_end/main.py`:
   - `POST /api/auth/login`
   - `POST /api/auth/signup`
   - `GET /api/auth/me`
2. Update frontend to call Python backend auth endpoints
3. Move database schema setup to Python backend
4. Update environment variables for backend database connection

## AI Integration

### Core AI Components
- **Voice Processing**: Whisper STT, Chatterbox TTS
- **LLM Integration**: Ollama for local model hosting
- **Browser Automation**: Selenium WebDriver
- **Screen Analysis**: Blip AI for visual understanding
- **Web Search**: LangChain-based web search with DuckDuckGo integration

### Key AI Features
- **Vibe Coding**: AI-powered development environment at `python_back_end/ollama_cli/vibe_agent.py`
- **Real-time Screen Analysis**: Context-aware assistance
- **Voice-First Interaction**: Natural language commands
- **Browser Automation**: Web navigation and interaction
- **Research & Web Search**: Comprehensive web search and research capabilities

### Web Search & Research API Endpoints

#### `/api/web-search` - Basic Web Search
**POST** - Perform web search using LangChain search agents

**Request Body:**
```json
{
  "query": "search query",
  "max_results": 5,
  "extract_content": false
}
```

**Response:**
```json
{
  "query": "search query",
  "search_results": [
    {
      "title": "Result Title",
      "url": "https://example.com",
      "snippet": "Result snippet",
      "source": "DuckDuckGo"
    }
  ],
  "extracted_content": []
}
```

#### `/api/research-chat` - Enhanced Research Chat
**POST** - Enhanced research with comprehensive web search and analysis

**Request Body:**
```json
{
  "message": "research question",
  "history": [],
  "model": "mistral",
  "enableWebSearch": true
}
```

#### `/api/fact-check` - Fact Checking
**POST** - Fact-check claims using web search

**Request Body:**
```json
{
  "claim": "claim to verify",
  "model": "mistral"
}
```

#### `/api/comparative-research` - Comparative Analysis
**POST** - Compare multiple topics using web research

**Request Body:**
```json
{
  "topics": ["topic1", "topic2"],
  "model": "mistral"
}
```

### Web Search Implementation Details

#### Search Agents
- **Location**: `python_back_end/research/`
- **Primary**: DuckDuckGo search via LangChain
- **Fallback**: Tavily API (requires `TAVILY_API_KEY`)
- **Content Extraction**: newspaper3k for full article content

#### Dependencies
Required packages in `requirements.txt`:
```
langchain
langchain-community
duckduckgo-search
beautifulsoup4
newspaper3k
tavily-python
```

### Troubleshooting Web Search

#### Common Issues with 0 Results

1. **Rate Limiting**: DuckDuckGo may throttle requests
   - **Solution**: Add delays between requests
   - **Check**: Look for rate limit errors in logs

2. **Network Issues in Docker**: Container connectivity problems
   - **Solution**: Verify Docker network configuration
   - **Check**: Test network connectivity from container

3. **User-Agent Blocking**: Search engines blocking requests
   - **Solution**: Set proper User-Agent (automatically configured)
   - **Environment**: `USER_AGENT` is set automatically if missing

4. **API Changes**: DuckDuckGo search library changes
   - **Warning**: Library suggests using `ddgs` instead of `duckduckgo_search`
   - **Solution**: Consider updating to newer library version

#### Debugging Steps

1. **Enable Debug Logging**: Set logging level to DEBUG
2. **Check Raw Results**: Verify DuckDuckGo returns data
3. **Network Tests**: Test connectivity from container
4. **Rate Limit Checks**: Monitor for rate limiting messages

#### Log Analysis
The web search endpoint provides detailed logging:
- Request parameters and query
- DuckDuckGo response count
- Formatted result details
- Error messages with full stack traces

Example log output:
```
INFO:main:Web search request: query='python', max_results=5, extract_content=False
INFO:research.web_search:Starting DuckDuckGo search for query: 'python' with max_results: 5
INFO:research.web_search:DuckDuckGo returned 5 raw results
INFO:main:Search completed: found 5 results
```

## Development Workflow

### Frontend Development
1. Navigate to `front_end/jfrontend/`
2. Install dependencies: `npm install`
3. Set up environment variables in `.env.local`
4. Run development server: `npm run dev`
5. Always run `npm run type-check` before committing

### Authentication Development

#### Current Frontend Implementation
- AuthService: `lib/auth/AuthService.ts` - Client-side auth functions
- UserProvider: `lib/auth/UserProvider.tsx` - Auth context provider
- Database connection: `lib/db.ts` - PostgreSQL connection pool

#### For Backend Authentication Migration
- Add auth dependencies to `python_back_end/requirements.txt`:
  ```
  python-jose[cryptography]
  passlib[bcrypt]
  python-multipart
  asyncpg
  ```
- Create auth middleware for protecting AI endpoints
- Update frontend AuthService to call backend endpoints
- Implement JWT token validation in Python backend

### Component Development
- UI components use Radix UI primitives
- Styling with Tailwind CSS
- Follow existing component patterns in `components/ui/`

## Docker Configuration

### Services
- **frontend**: Next.js app (port 3001 → 3000)
- **pgsql**: PostgreSQL database with health checks
- **Networks**: Uses external `ollama-n8n-network`

### Environment Variables
Required in `.env.local`:
- `DATABASE_URL` - PostgreSQL connection string
- `JWT_SECRET` - JWT signing secret
- `BACKEND_URL` - Backend service URL (default: http://backend:8000)

For backend authentication, also add to Python backend environment:
- `DATABASE_URL` - PostgreSQL connection for Python backend
- `JWT_SECRET` - Same secret for token validation consistency
- `JWT_ALGORITHM` - JWT algorithm (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES` - Token expiration (default: 60)

## Common Issues

### Database Connection
- Ensure PostgreSQL service is healthy before frontend starts
- Check `DATABASE_URL` environment variable
- Verify network connectivity between services

### Authentication
- JWT tokens expire after 1 hour (configurable)
- Password hashing uses bcrypt
- Check JWT_SECRET is properly set and consistent between frontend/backend
- For backend auth: Ensure Python backend can connect to PostgreSQL
- Token validation should be consistent across all services

### Type Checking
- Run `npm run type-check` regularly
- TypeScript errors are ignored in builds (not recommended for production)

## Git Branch Strategy
- Main branch: `main`
- Feature branches: Create from `main`
- Use conventional commits: `feat:`, `fix:`, `docs:`, etc.

## Testing
- No specific test framework configured
- Manual testing recommended for auth flows
- Test database operations with PostgreSQL running

## Security Considerations

### Current Security (Frontend Auth)
- Passwords are hashed with bcrypt
- JWT tokens for authentication
- Environment variables for sensitive data
- Database connection uses connection pooling
- Frontend runs in standalone mode for Docker deployment

### Enhanced Security (Backend Auth - Recommended)
- **Authentication Logic**: Move all auth logic to Python backend
- **Database Access**: Direct backend-to-database connection (no frontend DB access)
- **Token Validation**: Centralized JWT validation in Python backend
- **API Protection**: Protect all AI endpoints with auth middleware
- **CORS Configuration**: Properly configure CORS for frontend-backend communication
- **Input Validation**: Server-side validation of all auth inputs
- **Rate Limiting**: Implement rate limiting on auth endpoints
- **Audit Logging**: Log all authentication attempts and API access

### Security Benefits of Backend Auth
1. **Reduced Attack Surface**: Auth logic not exposed to client-side
2. **Centralized Security**: All AI services protected by same auth system
3. **Database Security**: Direct backend-to-database connection
4. **Token Security**: JWT secrets never exposed to frontend
5. **Consistent Validation**: Same auth validation across all endpoints