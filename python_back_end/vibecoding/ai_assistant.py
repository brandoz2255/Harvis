"""Vibe Coding AI Assistant

This module handles AI assistant functionality including:
- AI provider detection (Ollama, OpenAI, Anthropic)
- Context-aware chat responses
- Session context building
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import os
import httpx
from pydantic import BaseModel, Field

# Import auth dependencies
from auth_utils import get_current_user
from vibecoding.sessions import SessionManager, get_session_manager
from vibecoding.containers import ContainerManager, get_container_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibecode/ai", tags=["vibecode-ai"])

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ─── Pydantic Models ───────────────────────────────────────────────────────────

class AIProvider(BaseModel):
    """AI provider information"""
    name: str
    type: str  # "local" or "cloud"
    status: str  # "online", "offline", "configured"
    models: List[str] = []

class ChatMessage(BaseModel):
    """Chat message structure"""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: Optional[datetime] = None

class ChatRequest(BaseModel):
    """Request model for AI chat"""
    message: str = Field(..., min_length=1, description="User message")
    session_id: str = Field(..., description="Session ID for context")
    model: str = Field("mistral", description="Model to use")
    history: Optional[List[ChatMessage]] = Field(None, description="Chat history")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")

class AIResponse(BaseModel):
    """Response model for AI chat"""
    content: str
    model: str
    reasoning: Optional[str] = None
    timestamp: datetime

class ProvidersResponse(BaseModel):
    """Response model for available providers"""
    providers: List[AIProvider]

class ModelsResponse(BaseModel):
    """Response model for available models"""
    models: List[Dict[str, str]]

# ─── AI Provider Detection ─────────────────────────────────────────────────────

async def detect_ai_providers() -> List[AIProvider]:
    """Detect available AI providers
    
    Checks:
    - Ollama availability at http://ollama:11434
    - OpenAI API key in environment
    - Anthropic API key in environment
    
    Returns list of available providers with their status and models.
    """
    providers = []
    
    # Check Ollama (local)
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            
            if response.status_code == 200:
                data = response.json()
                models = [model['name'] for model in data.get('models', [])]
                
                providers.append(AIProvider(
                    name="ollama",
                    type="local",
                    status="online",
                    models=models
                ))
                logger.info(f"✅ Ollama detected with {len(models)} models")
            else:
                providers.append(AIProvider(
                    name="ollama",
                    type="local",
                    status="offline",
                    models=[]
                ))
                logger.warning(f"⚠️ Ollama returned status {response.status_code}")
                
    except Exception as e:
        providers.append(AIProvider(
            name="ollama",
            type="local",
            status="offline",
            models=[]
        ))
        logger.warning(f"⚠️ Ollama not available: {e}")
    
    # Check OpenAI
    if OPENAI_API_KEY:
        providers.append(AIProvider(
            name="openai",
            type="cloud",
            status="configured",
            models=["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]
        ))
        logger.info("✅ OpenAI API key configured")
    
    # Check Anthropic
    if ANTHROPIC_API_KEY:
        providers.append(AIProvider(
            name="anthropic",
            type="cloud",
            status="configured",
            models=["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"]
        ))
        logger.info("✅ Anthropic API key configured")
    
    return providers

# ─── Session Context Building ──────────────────────────────────────────────────

async def build_session_context(
    session_id: str,
    user_id: int,
    session_manager: SessionManager,
    container_manager: ContainerManager,
    additional_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Build context about current session for AI
    
    Includes:
    - Session name and description
    - Container status
    - Selected file (from additional_context)
    - File count (optional)
    """
    try:
        # Get session info
        session = await session_manager.get_session(session_id, user_id)
        
        # Get container status
        container_status = "stopped"
        try:
            container = await container_manager.get_container(session_id)
            if container:
                container_status = container.status
        except Exception as e:
            logger.warning(f"Could not get container status: {e}")
        
        context = {
            "session_name": session.name,
            "session_description": session.description,
            "container_status": container_status,
            "selected_file": None,
            "working_directory": "/workspace"
        }
        
        # Add additional context from frontend
        if additional_context:
            context.update(additional_context)
        
        return context
        
    except Exception as e:
        logger.error(f"❌ Failed to build session context: {e}")
        # Return minimal context on error
        return {
            "session_name": "Unknown",
            "container_status": "unknown",
            "selected_file": None,
            "working_directory": "/workspace"
        }

# ─── AI Chat Handler ───────────────────────────────────────────────────────────

async def get_ai_response(
    message: str,
    session_id: str,
    user_id: int,
    model: str,
    session_manager: SessionManager,
    container_manager: ContainerManager,
    history: Optional[List[ChatMessage]] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> AIResponse:
    """Get AI response with session context
    
    Builds context about the current session and sends it along with
    the user's message to the AI model.
    """
    
    # Build session context
    context = await build_session_context(
        session_id,
        user_id,
        session_manager,
        container_manager,
        additional_context
    )
    
    # Prepare system prompt with context
    system_prompt = f"""You are a coding assistant for VibeCode IDE.

Session: {context['session_name']}
Container Status: {context['container_status']}
Current File: {context.get('selected_file') or 'None'}
Working Directory: {context['working_directory']}

Help the user with coding tasks, debugging, and explanations. Be concise and practical."""
    
    # Prepare messages
    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]
    
    # Add history (last 10 messages)
    if history:
        for msg in history[-10:]:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })
    
    # Add current message
    messages.append({
        "role": "user",
        "content": message
    })
    
    # Call AI provider based on model
    try:
        # For now, we'll use Ollama as the primary provider
        response_content = await call_ollama(model, messages)
        
        return AIResponse(
            content=response_content,
            model=model,
            reasoning=None,  # Ollama doesn't provide reasoning separately
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to get AI response: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get AI response: {str(e)}"
        )

async def call_ollama(model: str, messages: List[Dict[str, str]]) -> str:
    """Call Ollama API for chat completion"""
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Ollama API error: {response.text}"
                )
            
            data = response.json()
            return data.get("message", {}).get("content", "")
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="AI request timed out"
        )
    except Exception as e:
        logger.error(f"❌ Ollama API call failed: {e}")
        raise

# ─── API Endpoints ─────────────────────────────────────────────────────────────

@router.get("/providers", response_model=ProvidersResponse)
async def get_providers():
    """Get list of available AI providers
    
    Returns information about available AI providers including:
    - Ollama (local)
    - OpenAI (if API key configured)
    - Anthropic (if API key configured)
    """
    providers = await detect_ai_providers()
    
    return ProvidersResponse(providers=providers)

@router.get("/models", response_model=ModelsResponse)
async def get_models():
    """Get list of available AI models from all providers
    
    Returns a combined list of models from all configured providers.
    """
    providers = await detect_ai_providers()
    
    models = []
    for provider in providers:
        if provider.status in ["online", "configured"]:
            for model_name in provider.models:
                models.append({
                    "name": model_name,
                    "provider": provider.name,
                    "type": provider.type
                })
    
    return ModelsResponse(models=models)

@router.post("/chat", response_model=AIResponse)
async def chat(
    request: ChatRequest,
    user: Dict = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
    container_manager: ContainerManager = Depends(get_container_manager)
):
    """Send a message to the AI assistant
    
    The AI assistant has context about your current session including:
    - Session name and status
    - Container status
    - Currently selected file
    - Chat history
    
    This allows the AI to provide relevant, context-aware assistance.
    """
    user_id = user.get("id")
    
    # Verify user has access to this session
    await session_manager.get_session(request.session_id, user_id)
    
    # Get AI response
    response = await get_ai_response(
        message=request.message,
        session_id=request.session_id,
        user_id=user_id,
        model=request.model,
        session_manager=session_manager,
        container_manager=container_manager,
        history=request.history,
        additional_context=request.context
    )
    
    return response
