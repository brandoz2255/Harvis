# Design Document

## Overview

This design implements a comprehensive web-based IDE with secure code execution capabilities and AI assistant integration. The system consists of FastAPI backend endpoints for code execution and AI assistance, integrated with a Monaco editor frontend that provides a professional development environment with syntax highlighting, code completion, and multi-model AI support.

## Architecture

### High-Level Architecture

```mermaid
graph TB
    subgraph "Frontend (Next.js)"
        A[Monaco Editor Component]
        B[AI Assistant Interface]
        C[File Management UI]
        D[Model Selection Toggle]
    end
    
    subgraph "Backend (FastAPI)"
        E[/api/run Endpoint]
        F[/api/assistant Endpoint]
        G[Docker SDK Integration]
        H[Ollama CLI Integration]
    end
    
    subgraph "External Services"
        I[Docker Engine]
        J[Ollama Service]
        K[Multiple AI Models]
    end
    
    A --> E
    B --> F
    E --> G
    F --> H
    G --> I
    H --> J
    J --> K
    
    style A fill:#e1f5fe
    style E fill:#f3e5f5
    style I fill:#fff3e0
```

### System Components

1. **Frontend IDE Interface**: Monaco editor with file management and AI integration
2. **Code Execution Service**: Secure Docker-based code execution
3. **AI Assistant Service**: Multi-model AI assistance with streaming support
4. **Security Layer**: Container isolation and resource management
5. **File Management**: Temporary file handling and cleanup

## Components and Interfaces

### 1. Code Execution Component (/api/run)

**Purpose**: Execute Python code securely in isolated Docker containers

**Interface**:
```python
class RunCodeRequest(BaseModel):
    code: str
    timeout: Optional[int] = 30

class RunCodeResponse(BaseModel):
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time: float
    container_id: Optional[str] = None
```

**Implementation Details**:
- Uses Docker Python SDK for container management
- Creates temporary files with secure naming (UUID-based)
- Mounts code files as read-only into containers
- Implements resource limits (CPU, memory, timeout)
- Captures both stdout and stderr streams
- Automatic cleanup of containers and temporary files

**Security Features**:
- Container isolation with no network access
- Resource limits to prevent DoS attacks
- Temporary file cleanup after execution
- Read-only file system mounts
- Container auto-removal after execution

### 2. AI Assistant Component (/api/assistant)

**Purpose**: Provide AI-powered code assistance with multiple model support

**Interface**:
```python
class AssistantRequest(BaseModel):
    messages: List[Dict[str, str]]  # [{"role": "user|assistant", "content": "..."}]
    model: str = "llama3.2:3b"
    context: Optional[Dict[str, Any]] = None

class AssistantResponse(BaseModel):
    reply: str
    reasoning: Optional[str] = None
    model_used: str
```

**Implementation Details**:
- Uses subprocess to call Ollama CLI
- Supports streaming responses from AI models
- Handles conversation context and message history
- Implements fallback mechanisms for model availability
- Parses reasoning from response when available

**Model Support**:
- Primary: llama3.2:3b (default)
- Extensible to support additional Ollama models
- Model availability checking and fallback
- Dynamic model switching via frontend toggle

### 3. Monaco Editor Integration

**Purpose**: Provide professional IDE experience with AI-powered features

**Key Features**:
- Custom "vibe-dark" theme with syntax highlighting
- Multi-language support (Python, JavaScript, TypeScript, etc.)
- AI-powered code completion
- File management with tabs
- Real-time syntax validation
- Code formatting and auto-completion

**AI Integration**:
```typescript
interface MonacoCodeEditorProps {
  files: CodeFile[]
  activeFileId: string
  onFileChange: (fileId: string, content: string) => void
  onSaveFile?: (fileId: string) => void
  onRunFile?: (fileId: string) => void
  onRequestCompletion?: (fileId: string, position: any, context: string) => Promise<string[]>
  className?: string
}
```

**Code Completion Provider**:
- Triggers on specific characters (., space, (, [, {)
- Sends context (10 lines before cursor) to AI assistant
- Displays AI suggestions with proper ranking
- Integrates seamlessly with Monaco's completion system

### 4. Model Selection Interface

**Purpose**: Allow users to choose between different AI models

**Implementation**:
- Toggle/dropdown component in AI assistant interface
- Persists model selection in component state
- Updates all AI requests to use selected model
- Displays model availability status
- Fallback handling for unavailable models

## Data Models

### File Management
```typescript
interface CodeFile {
  id: string
  name: string
  content: string
  language: string
  isActive: boolean
  isModified: boolean
}
```

### Execution Context
```python
class ExecutionContext:
    container_id: str
    temp_file_path: str
    start_time: datetime
    timeout: int
    resource_limits: Dict[str, Any]
```

### AI Context
```python
class AIContext:
    conversation_history: List[Dict[str, str]]
    selected_model: str
    code_context: Optional[str]
    file_context: Optional[Dict[str, str]]
```

## Error Handling

### Code Execution Errors

1. **Docker Service Unavailable**:
   - Return 503 Service Unavailable
   - Log error details for debugging
   - Provide user-friendly error message

2. **Code Compilation/Runtime Errors**:
   - Capture stderr from container
   - Return structured error response
   - Include line numbers when available

3. **Timeout Errors**:
   - Force container termination
   - Return timeout-specific error message
   - Clean up resources properly

4. **Resource Exhaustion**:
   - Monitor container resource usage
   - Implement queue system for high load
   - Return appropriate HTTP status codes

### AI Assistant Errors

1. **Model Unavailable**:
   - Attempt fallback to default model
   - Return error if no models available
   - Cache model availability status

2. **Ollama Service Down**:
   - Return 503 Service Unavailable
   - Implement retry logic with exponential backoff
   - Provide offline mode message

3. **Invalid Input**:
   - Validate message format
   - Return 400 Bad Request for malformed requests
   - Sanitize input to prevent injection

### Frontend Error Handling

1. **Network Errors**:
   - Display connection status indicator
   - Implement retry mechanisms
   - Cache responses when possible

2. **Editor Errors**:
   - Graceful degradation for Monaco failures
   - Fallback to textarea for basic editing
   - Preserve user work during errors

## Testing Strategy

### Backend Testing

1. **Unit Tests**:
   - Test code execution with various Python scripts
   - Test AI assistant with mock Ollama responses
   - Test error handling scenarios
   - Test resource cleanup

2. **Integration Tests**:
   - Test Docker container lifecycle
   - Test Ollama CLI integration
   - Test file system operations
   - Test concurrent execution scenarios

3. **Security Tests**:
   - Test container escape attempts
   - Test resource limit enforcement
   - Test malicious code execution
   - Test file system access restrictions

### Frontend Testing

1. **Component Tests**:
   - Test Monaco editor initialization
   - Test file management operations
   - Test AI assistant interface
   - Test model selection functionality

2. **Integration Tests**:
   - Test code execution flow
   - Test AI completion integration
   - Test error state handling
   - Test responsive design

3. **E2E Tests**:
   - Test complete code writing and execution workflow
   - Test AI assistant conversation flow
   - Test multi-file project scenarios
   - Test error recovery scenarios

### Performance Testing

1. **Load Testing**:
   - Test concurrent code execution
   - Test AI assistant under load
   - Test resource cleanup efficiency
   - Test memory usage patterns

2. **Stress Testing**:
   - Test with large code files
   - Test with long-running code
   - Test with high AI request volume
   - Test container resource limits

## Security Considerations

### Container Security
- Use minimal base images (python:3.11-slim)
- No network access for execution containers
- Read-only file system where possible
- Resource limits (CPU, memory, disk)
- Automatic container cleanup

### Input Validation
- Sanitize all user input
- Validate file names and paths
- Limit code size and complexity
- Prevent path traversal attacks

### Authentication & Authorization
- Integrate with existing JWT authentication
- Rate limiting for API endpoints
- User-specific resource quotas
- Audit logging for security events

### Data Protection
- Secure temporary file handling
- No persistent storage of user code
- Encrypted communication channels
- Proper error message sanitization

## Deployment Considerations

### Docker Configuration
- Ensure Docker daemon is accessible
- Configure appropriate resource limits
- Set up container image caching
- Monitor container resource usage

### Ollama Setup
- Ensure Ollama service is running
- Configure model availability
- Set up model caching
- Monitor AI service health

### Monitoring & Logging
- Container execution metrics
- AI assistant usage statistics
- Error rate monitoring
- Resource utilization tracking

### Scalability
- Horizontal scaling for code execution
- Load balancing for AI requests
- Container orchestration considerations
- Database connection pooling