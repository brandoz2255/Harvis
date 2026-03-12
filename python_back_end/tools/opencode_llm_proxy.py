"""
OpenCode LLM Proxy - Allows OpenCode to use Kimi K2.5 via Harvis backend.

This proxy exposes an OpenAI-compatible API that OpenCode can call.
OpenCode is configured to use:
  - Provider: @ai-sdk/openai-compatible
  - Base URL: http://backend:8000/api/opencode/chat
  - Model: kimi-k2.5

This proxy forwards requests to the Moonshot API and returns responses
in OpenAI-compatible format.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx

logger = logging.getLogger(__name__)

opencode_llm_router = APIRouter(prefix="/api/opencode", tags=["opencode-llm"])

# Moonshot API configuration
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")

# Default model for OpenCode
DEFAULT_MODEL = "kimi-k2.5"


# ─── Request/Response Models ────────────────────────────────────────────────


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = DEFAULT_MODEL
    messages: List[Message]
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False
    tools: Optional[List[Dict[str, Any]]] = None


class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = "stop"


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Usage


# ─── Helper Functions ────────────────────────────────────────────────────────


def _get_api_key() -> str:
    """Get Moonshot API key from environment or raise error."""
    if MOONSHOT_API_KEY:
        return MOONSHOT_API_KEY

    # Try to get from database or other sources
    # For now, require it to be set in environment
    raise HTTPException(
        status_code=503, detail="MOONSHOT_API_KEY not configured for OpenCode proxy"
    )


def _filter_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter empty messages before sending to Moonshot API."""
    filtered = []
    for msg in messages:
        role = msg.get("role", "")

        # Skip tool/function messages (Kimi called without tools)
        if role in ("tool", "function"):
            continue

        # Skip messages with no content
        content = msg.get("content", "")
        if isinstance(content, list):
            if not content:
                continue
        elif isinstance(content, str):
            if not content.strip():
                continue

        # Remove tool_calls from assistant messages
        if role == "assistant" and msg.get("tool_calls"):
            msg = {k: v for k, v in msg.items() if k != "tool_calls"}

        filtered.append(msg)
    return filtered


# ─── Endpoints ────────────────────────────────────────────────────────────────


@opencode_llm_router.post("/chat")
async def chat_completion(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """
    OpenAI-compatible chat completion endpoint for OpenCode.

    OpenCode calls this endpoint to use Kimi K2.5 for coding tasks.
    """
    api_key = _get_api_key()

    # Prepare payload for Moonshot
    filtered_messages = _filter_messages(
        [{"role": m.role, "content": m.content} for m in request.messages]
    )

    # Kimi K2.5 requires temperature=1.0
    payload = {
        "model": request.model if request.model else DEFAULT_MODEL,
        "messages": filtered_messages,
        "temperature": 1.0,
        "stream": False,
    }

    if request.max_tokens:
        payload["max_tokens"] = request.max_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{MOONSHOT_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            )

            if response.status_code != 200:
                logger.error(
                    f"Moonshot API error: {response.status_code} - {response.text}"
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Moonshot API error: {response.status_code}",
                )

            data = response.json()

            # Convert to OpenAI-compatible format
            choice = data["choices"][0]
            msg = choice["message"]

            return ChatCompletionResponse(
                id=data.get("id", f"chatcmpl-{hash(str(request))}"),
                created=data.get("created", 0),
                model=request.model,
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatMessage(
                            role=msg.get("role", "assistant"),
                            content=msg.get("content", ""),
                        ),
                        finish_reason=choice.get("finish_reason", "stop"),
                    )
                ],
                usage=Usage(
                    prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                    completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                    total_tokens=data.get("usage", {}).get("total_tokens", 0),
                ),
            )

    except httpx.TimeoutException:
        logger.error("Moonshot API request timed out")
        raise HTTPException(status_code=504, detail="Moonshot API request timed out")
    except Exception as e:
        logger.error(f"Error calling Moonshot API: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error calling Moonshot API: {str(e)}"
        )


@opencode_llm_router.post("/chat/stream")
async def chat_completion_stream(request: ChatCompletionRequest):
    """
    Streaming chat completion endpoint for OpenCode.

    OpenCode calls this endpoint for streaming responses.
    """
    api_key = _get_api_key()

    # Prepare payload for Moonshot
    filtered_messages = _filter_messages(
        [{"role": m.role, "content": m.content} for m in request.messages]
    )

    payload = {
        "model": request.model if request.model else DEFAULT_MODEL,
        "messages": filtered_messages,
        "temperature": 1.0,
        "stream": True,
    }

    if request.max_tokens:
        payload["max_tokens"] = request.max_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{MOONSHOT_BASE_URL}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'error': f'API error: {response.status_code}'})}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                yield "data: [DONE]\n\n"
                                break

                            try:
                                data = json.loads(data_str)
                                # Forward the data as-is in SSE format
                                yield f"data: {json.dumps(data)}\n\n"
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@opencode_llm_router.get("/models")
async def list_models():
    """
    List available models for OpenCode.
    """
    return {
        "object": "list",
        "data": [
            {
                "id": "kimi-k2.5",
                "object": "model",
                "created": 1700000000,
                "owned_by": "moonshot",
            }
        ],
    }


@opencode_llm_router.get("/health")
async def health_check():
    """Health check endpoint for OpenCode proxy."""
    return {"status": "ok", "service": "opencode-llm-proxy"}
