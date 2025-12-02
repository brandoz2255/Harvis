"""
Ollama Compatibility Layer
Provides robust streaming and text collection with fallback handling
"""

import json
import logging
import os
from typing import AsyncGenerator, List, Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

# Cache for chat endpoint detection
_ollama_has_chat_endpoint: Optional[bool] = None


async def detect_ollama_chat_support() -> bool:
    """
    Detect if Ollama supports /api/chat endpoint (v0.1.0+)
    Falls back to /api/generate for older versions
    Caches result to avoid repeated checks
    """
    global _ollama_has_chat_endpoint
    
    if _ollama_has_chat_endpoint is not None:
        return _ollama_has_chat_endpoint
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try a minimal chat request
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": "test", "messages": [{"role": "user", "content": "test"}]}
            )
            
            # Check if endpoint exists
            if response.status_code == 404:
                try:
                    error_data = response.json()
                    if "error" in error_data and "model" in error_data["error"].lower():
                        _ollama_has_chat_endpoint = True
                        logger.info("Ollama /api/chat detection: True (endpoint exists, test model not found)")
                    else:
                        _ollama_has_chat_endpoint = False
                        logger.info("Ollama /api/chat detection: False (404, legacy mode)")
                except:
                    _ollama_has_chat_endpoint = False
                    logger.info("Ollama /api/chat detection: False (404 HTML, legacy mode)")
            else:
                _ollama_has_chat_endpoint = True
                logger.info(f"Ollama /api/chat detection: True (status {response.status_code})")
                
    except Exception as e:
        logger.warning(f"Failed to detect Ollama /api/chat support: {e}, assuming legacy /api/generate")
        _ollama_has_chat_endpoint = False
    
    return _ollama_has_chat_endpoint


async def stream_sse(
    model: str,
    messages: List[Dict[str, str]],
    options: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[str, None]:
    """
    Stream tokens from Ollama as Server-Sent Events
    Automatically uses /api/chat (newer) or /api/generate (older) based on detection
    Yields SSE-formatted chunks: data: {"token": "..."}\n\n
    
    Args:
        model: Model name to use
        messages: List of message dicts with 'role' and 'content'
        options: Optional generation options (temperature, top_p, etc.)
    
    Yields:
        SSE-formatted strings: data: {"token": "..."}\n\n
    """
    has_chat_api = await detect_ollama_chat_support()
    default_options = {"temperature": 0.7, "top_p": 0.9}
    if options:
        default_options.update(options)
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if has_chat_api:
                # Use /api/chat (newer Ollama)
                logger.debug(f"Streaming via /api/chat for model {model}")
                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": True,
                        "options": default_options
                    }
                ) as response:
                    if response.status_code >= 400:
                        logger.warning(f"/api/chat returned {response.status_code}, falling back to /api/generate")
                    else:
                        async for line in response.aiter_lines():
                            if line.strip():
                                try:
                                    data = json.loads(line)
                                    if "message" in data and "content" in data["message"]:
                                        token = data["message"]["content"]
                                        if token:
                                            yield f"data: {json.dumps({'token': token})}\n\n"
                                    if data.get("done", False):
                                        break
                                except json.JSONDecodeError:
                                    continue
                    
                    # If chat failed, fall back to generate
                    if response.status_code >= 400:
                        logger.debug(f"Falling back to /api/generate for model {model}")
                        # Convert messages to prompt
                        prompt_parts = []
                        for msg in messages:
                            role = msg.get("role", "user")
                            content = msg.get("content", "")
                            if role == "system":
                                prompt_parts.append(f"System: {content}")
                            elif role == "user":
                                prompt_parts.append(f"User: {content}")
                            elif role == "assistant":
                                prompt_parts.append(f"Assistant: {content}")
                        prompt = "\n\n".join(prompt_parts) + "\n\nAssistant:"
                        
                        async with client.stream(
                            "POST",
                            f"{OLLAMA_URL}/api/generate",
                            json={
                                "model": model,
                                "prompt": prompt,
                                "stream": True,
                                "options": default_options
                            }
                        ) as gen_response:
                            gen_response.raise_for_status()
                            async for line in gen_response.aiter_lines():
                                if line.strip():
                                    try:
                                        data = json.loads(line)
                                        if "response" in data:
                                            token = data["response"]
                                            if token:
                                                yield f"data: {json.dumps({'token': token})}\n\n"
                                        if data.get("done", False):
                                            break
                                    except json.JSONDecodeError:
                                        continue
            else:
                # Use /api/generate (older Ollama)
                logger.debug(f"Streaming via /api/generate for model {model} (legacy mode)")
                prompt_parts = []
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "system":
                        prompt_parts.append(f"System: {content}")
                    elif role == "user":
                        prompt_parts.append(f"User: {content}")
                    elif role == "assistant":
                        prompt_parts.append(f"Assistant: {content}")
                prompt = "\n\n".join(prompt_parts) + "\n\nAssistant:"
                
                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": True,
                        "options": default_options
                    }
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                if "response" in data:
                                    token = data["response"]
                                    if token:
                                        yield f"data: {json.dumps({'token': token})}\n\n"
                                if data.get("done", False):
                                    break
                            except json.JSONDecodeError:
                                continue
        
        yield f"data: {json.dumps({'done': True})}\n\n"
        
    except Exception as e:
        logger.error(f"Ollama streaming error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


async def collect_text(
    model: str,
    messages: List[Dict[str, str]],
    options: Optional[Dict[str, Any]] = None,
    allow_retry: bool = True
) -> str:
    """
    Collect complete text from Ollama (non-streaming)
    Handles empty responses by retrying with minimal "code-only" prompt
    Automatically uses /api/chat (newer) or /api/generate (older) based on detection
    
    Args:
        model: Model name to use
        messages: List of message dicts with 'role' and 'content'
        options: Optional generation options
        allow_retry: If True, retry with minimal prompt if response is empty
    
    Returns:
        Complete text response from Ollama
    
    Raises:
        ValueError: If response is empty and retry failed
        httpx.HTTPStatusError: If HTTP error occurs
        httpx.TimeoutException: If request times out
    """
    has_chat_api = await detect_ollama_chat_support()
    default_options = {
        "temperature": 0.3,
        "top_p": 0.8,
        "num_predict": 2000,
        "stop": ["```\n\n", "\n\n\n"],
    }
    if options:
        default_options.update(options)
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if has_chat_api:
                # Use /api/chat (newer Ollama)
                logger.info(f"Collecting text via /api/chat with model: {model}")
                response = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": default_options
                    }
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("message", {}).get("content", "")
                
                if not content or not content.strip():
                    logger.warning(f"Ollama returned empty content. Response: {data}")
                    if allow_retry:
                        logger.info("Retrying with minimal code-only prompt...")
                        # Retry with minimal prompt that forces code output
                        minimal_messages = [
                            {"role": "system", "content": "You are a code completion assistant. Return ONLY code, no explanations."},
                            {"role": "user", "content": "Complete the code. Return ONLY the code continuation, nothing else."}
                        ]
                        retry_content = await collect_text(model, minimal_messages, options, allow_retry=False)
                        if retry_content and retry_content.strip():
                            return retry_content
                    # Return empty string instead of raising error (per masterprompt3)
                    logger.warning("Ollama returned empty response after retry, returning empty string")
                    return ""
                
                logger.info(f"Ollama response received: {len(content)} chars")
                return content
                
            else:
                # Use /api/generate (older Ollama)
                logger.info(f"Collecting text via /api/generate with model: {model}")
                prompt_parts = []
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "system":
                        prompt_parts.append(f"System: {content}")
                    elif role == "user":
                        prompt_parts.append(f"User: {content}")
                    elif role == "assistant":
                        prompt_parts.append(f"Assistant: {content}")
                prompt = "\n\n".join(prompt_parts) + "\n\nAssistant:"
                
                response = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": default_options
                    }
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("response", "")
                
                if not content or not content.strip():
                    logger.warning(f"Ollama returned empty content. Response: {data}")
                    if allow_retry:
                        logger.info("Retrying with minimal code-only prompt...")
                        minimal_prompt = "Complete the code. Return ONLY the code continuation, nothing else."
                        retry_content = await collect_text(
                            model,
                            [{"role": "user", "content": minimal_prompt}],
                            options,
                            allow_retry=False
                        )
                        if retry_content and retry_content.strip():
                            return retry_content
                    # Return empty string instead of raising error (per masterprompt3)
                    logger.warning("Ollama returned empty response after retry, returning empty string")
                    return ""
                
                logger.info(f"Ollama response received: {len(content)} chars")
                return content
                
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        logger.error(f"Ollama HTTP error: {error_msg}")
        raise
    except httpx.TimeoutException as e:
        error_msg = "Request timed out (>60s)"
        logger.error(f"Ollama timeout: {error_msg}")
        raise
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"Ollama value error: {error_msg}")
        raise
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Ollama text collection failed: {error_msg}", exc_info=True)
        raise

