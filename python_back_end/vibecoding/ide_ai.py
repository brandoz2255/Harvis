"""IDE AI Assistant Router

This module provides AI capabilities for the IDE:
- Copilot-style inline code suggestions
- AI Assistant chat (separate from home chat)
- Code change proposals with diff generation
- Diff application to workspace files
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
import logging
import os
import json
import re
import asyncio
import httpx
from uuid import UUID, uuid4
import difflib
import time
import hashlib
from collections import defaultdict

# Import auth dependencies
from auth_optimized import get_current_user_optimized

# Import container and file operations
from vibecoding.containers import container_manager
from vibecoding import file_operations

# Import Ollama compatibility layer
from vibecoding.llm.ollama_compat import collect_text, stream_sse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ide", tags=["ide-ai"])

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Model configuration for Copilot features
# Use fast, code-optimized models for inline completions
COMPLETION_MODEL = os.getenv("IDE_COPILOT_MODEL", "deepseek-coder:6.7b")
# Use more capable models for chat/proposals
CHAT_MODEL = os.getenv("IDE_CHAT_MODEL", "gpt-oss")

# Optimized parameters for fast inline completions
COMPLETION_PARAMS = {
    "temperature": 0.2,
    "top_p": 0.95,
    "top_k": 50,
    "stop": ["\n\n", "```", "###", "# "],
    "num_predict": 150  # max tokens for inline completions
}

IDE_INLINE_MAX_CHARS = int(os.getenv("IDE_INLINE_MAX_CHARS", "240"))
IDE_INLINE_MAX_TOKENS = int(os.getenv("IDE_INLINE_MAX_TOKENS", "160"))

SYSTEM_INLINE = (
    "You are a code completion engine for an IDE.\n"
    "TASK: Predict only the next code the user is likely to type.\n"
    "HARD RULES:\n"
    "  - OUTPUT CODE ONLY. No prose. No markdown fences. No apologies.\n"
    "  - Do not repeat existing text in the suffix.\n"
    "  - Respect the language and indentation exactly.\n"
    "  - Prefer short, incremental continuations for inline suggestions.\n"
    "  - If there is not enough signal to continue safely, return nothing.\n"
)

CODEISH_PAT = re.compile(r"[;{}\[\]()=]|^\s*(def|class|return|if|for|while|try|catch|import|from|const|let|var)\b", re.I)
APOLOGY_PAT = re.compile(r"\b(sorry|apolog|as an ai|i can[’']?t|i cannot|i'm unable)\b", re.I)
FENCE_PAT = re.compile(r"^```[\w-]*\s*|\s*```$", re.M)
BACKTICK_PAT = re.compile(r"`{1,3}")

# Rate limiting storage (in-memory, per user)
_copilot_rate_limits: Dict[str, List[float]] = defaultdict(list)
# Allow much more generous rate for inline ghost suggestions (per-keystroke)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 120  # max requests per window (2 per second on average)

# Ollama compatibility detection (cached)
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
            # - If route doesn't exist: 404 with HTML error page (old Ollama)
            # - If route exists but model not found: 404 with JSON error (new Ollama)
            # - Any other response: endpoint exists
            
            if response.status_code == 404:
                # Try to parse as JSON - if it works, endpoint exists but model missing
                try:
                    error_data = response.json()
                    if "error" in error_data and "model" in error_data["error"].lower():
                        # Model not found error means endpoint exists
                        _ollama_has_chat_endpoint = True
                        logger.info(f"Ollama /api/chat detection: True (endpoint exists, test model not found)")
                    else:
                        # Other 404 means route doesn't exist
                        _ollama_has_chat_endpoint = False
                        logger.info(f"Ollama /api/chat detection: False (404, legacy mode)")
                except:
                    # Can't parse JSON, likely HTML 404 from old Ollama
                    _ollama_has_chat_endpoint = False
                    logger.info(f"Ollama /api/chat detection: False (404 HTML, legacy mode)")
            else:
                # Any other status means endpoint exists
                _ollama_has_chat_endpoint = True
                logger.info(f"Ollama /api/chat detection: True (status {response.status_code})")
                
    except Exception as e:
        logger.warning(f"Failed to detect Ollama /api/chat support: {e}, assuming legacy /api/generate")
        _ollama_has_chat_endpoint = False
    
    return _ollama_has_chat_endpoint

async def stream_chat_sse(model: str, messages: List[Dict[str, str]]):
    """
    Unified SSE streaming for Ollama chat
    Uses ollama_compat.stream_sse() for robust streaming with fallback
    Yields SSE-formatted chunks: data: {"token": "..."}\n\n
    """
    try:
        async for chunk in stream_sse(model, messages, options={"temperature": 0.7, "top_p": 0.9}):
            yield chunk
    except Exception as e:
        logger.error(f"Ollama streaming error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

# ─── Pydantic Models ───────────────────────────────────────────────────────────

class ProviderInfo(BaseModel):
    """Provider/model information"""
    id: str = Field(..., description="Model identifier")
    label: str = Field(..., description="Display name")
    type: str = Field(..., description="Provider type: 'ollama' or 'cloud'")
    capabilities: List[str] = Field(default_factory=lambda: ["chat", "completion"], description="Model capabilities")

class ProvidersResponse(BaseModel):
    """Response with available providers/models"""
    providers: List[ProviderInfo] = Field(..., description="List of available models")

def build_copilot_context(
    content: str,
    cursor_pos: int,
    before_lines: int = 40,
    after_lines: int = 15,
    local_radius: int = 3,
) -> Dict[str, Any]:
    """
    Extract contextual slices around the cursor so the completion model
    can reason about the surrounding code (not just the active line).
    """
    lines_before = content[:cursor_pos].split('\n')
    lines_after = content[cursor_pos:].split('\n')

    context_before_lines = lines_before[-before_lines:] if before_lines > 0 else lines_before
    context_after_lines = lines_after[:after_lines] if after_lines > 0 else lines_after

    current_line = lines_before[-1] if lines_before else ""
    prev_local = lines_before[-local_radius:] if local_radius > 0 else []
    next_local = lines_after[:local_radius] if local_radius > 0 else []
    surrounding_snippet = '\n'.join(prev_local + [current_line] + next_local)

    indentation = len(current_line) - len(current_line.lstrip()) if current_line else 0

    return {
        "before": '\n'.join(context_before_lines),
        "after": '\n'.join(context_after_lines),
        "current_line": current_line,
        "surrounding_snippet": surrounding_snippet,
        "indentation": indentation,
        "before_line_count": len(context_before_lines),
        "after_line_count": len(context_after_lines),
    }

def stops_for(language: str, suffix: str) -> List[str]:
    """Build dynamic stop sequences that prevent rambling or suffix repetition."""
    base = ["```", "\n\n\n"]
    suffix_hint = suffix[:24].strip()
    if suffix_hint:
        base.append(suffix_hint)

    lang_stops = {
        "python": ["\n\n", "# ", '"""', "'''"],
        "javascript": ["\n\n", "/*", "//"],
        "typescript": ["\n\n", "/*", "//"],
        "go": ["\n\n", "/*", "//"],
        "java": ["\n\n", "/*", "//"],
        "c": ["\n\n", "/*", "//"],
        "cpp": ["\n\n", "/*", "//"],
        "csharp": ["\n\n", "/*", "//"],
        "rust": ["\n\n", "/*", "//"],
        "php": ["\n\n", "/*", "//", "?>"],
        "ruby": ["\n\n", "# "],
        "shell": ["\n\n", "# "],
        "sql": ["\n\n", "-- "],
        "html": ["\n\n", "<!--"],
        "css": ["\n\n"],
        "json": ["\n\n", "}"],
        "yaml": ["\n\n", "- "],
        "markdown": ["\n\n"],
        "plaintext": ["\n\n"],
    }
    stops = base + lang_stops.get(language.lower(), ["\n\n"])
    # Deduplicate while preserving order
    seen = set()
    ordered: List[str] = []
    for item in stops:
        if item not in seen and item:
            ordered.append(item)
            seen.add(item)
    return ordered

def inline_generation_options(language: str, suffix: str) -> Dict[str, Any]:
    """Merge base completion params with dynamic stop sequences and token limits."""
    options = dict(COMPLETION_PARAMS)
    options["stop"] = stops_for(language, suffix)
    options["temperature"] = float(os.getenv("IDE_INLINE_TEMPERATURE", options.get("temperature", 0.15)))
    options["top_p"] = float(os.getenv("IDE_INLINE_TOP_P", options.get("top_p", 0.85)))
    options["top_k"] = int(os.getenv("IDE_INLINE_TOP_K", options.get("top_k", 40)))
    options["num_predict"] = IDE_INLINE_MAX_TOKENS
    return options

def summarize_neighbor_files(
    neighbor_files: Optional[List[Dict[str, str]]],
    max_files: int = 2,
    snippet_lines: int = 80,
    max_chars: int = 1500,
) -> str:
    """
    Build a compact summary of nearby files so the model understands
    cross-file context without exceeding prompt limits.
    """
    if not neighbor_files:
        return ""

    summaries: List[str] = []
    remaining = max_chars

    for file_data in neighbor_files[:max_files]:
        path = file_data.get("path", "unknown")
        content = file_data.get("content", "")
        if not content or remaining <= 0:
            continue

        lines = content.splitlines()
        snippet = '\n'.join(lines[:snippet_lines])
        snippet = snippet[:remaining]

        section = f"File: {path}\n```\n{snippet}\n```"
        summaries.append(section)
        remaining -= len(section)

        if remaining <= 0:
            break

    return '\n\n'.join(summaries)

def build_copilot_messages(
    language: str,
    safe_path: str,
    context_window: Dict[str, Any],
    neighbor_summary: str,
) -> List[Dict[str, str]]:
    """Construct system/user prompts following the strict masterprompt contract."""
    before_slice = context_window["before"][-2000:]
    after_slice = context_window["after"][:400]

    payload = {
        "file": safe_path,
        "language": language,
        "indentation": context_window["indentation"],
        "before_lines": context_window["before_line_count"],
        "after_lines": context_window["after_line_count"],
        "prefix": before_slice,
        "suffix": after_slice,
        "surrounding": context_window["surrounding_snippet"],
        "neighbors": neighbor_summary or "",
        "instruction": (
            "Return ONLY the characters to insert at the cursor.\n"
            "No backticks or markdown. No commentary. No apologies.\n"
            "If unsure, return empty string."
        ),
    }

    return [
        {"role": "system", "content": SYSTEM_INLINE},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

def clean_copilot_suggestion(raw: str, language: str = "", indentation: int = 0) -> str:
    """
    Normalize raw model output so Monaco receives the exact text to insert.
    Removes markdown fences, apologies, chatter, and enforces indentation.
    """
    if not raw:
        return ""

    text = raw.strip()
    text = FENCE_PAT.sub("", text)
    text = BACKTICK_PAT.sub("", text)

    if APOLOGY_PAT.search(text):
        return ""

    parts = [p.strip("\n") for p in text.split("\n\n") if p.strip()]
    if parts:
        chosen = ""
        for fragment in parts:
            if CODEISH_PAT.search(fragment):
                chosen = fragment
                break
        text = chosen or parts[0]

    text = text.replace("\r\n", "\n")
    lines = text.split('\n')
    if len(lines) > 1:
        indent = " " * max(indentation, 0)
        normalized_lines = [lines[0]]
        for line in lines[1:]:
            normalized_lines.append(indent + line.lstrip())
        text = '\n'.join(normalized_lines)

    max_chars = IDE_INLINE_MAX_CHARS
    text = text[:max_chars].rstrip()

    return text

def truncate_safely(text: str) -> str:
    """Stop output at safe boundaries to avoid trailing prose or half tokens."""
    if not text:
        return ""

    for marker in ["\n\n", "\n# ", "\n// ", "\n/*"]:
        idx = text.find(marker)
        if idx != -1:
            return text[:idx].rstrip()
    return text

class CopilotSuggestRequest(BaseModel):
    """Request for inline code suggestion"""
    session_id: str = Field(..., description="Vibecode session ID")
    filepath: str = Field(..., description="Current file path")
    language: str = Field(..., description="Programming language")
    content: str = Field(..., description="Full buffer content")
    cursor_offset: int = Field(..., description="Cursor position as character offset")
    neighbor_files: Optional[List[Dict[str, str]]] = Field(None, description="Neighboring files for context")
    prefix: Optional[str] = Field(None, description="Recent text before cursor (frontend hint)")
    suffix: Optional[str] = Field(None, description="Upcoming text after cursor (frontend hint)")
    model: Optional[str] = Field(None, description="Model to use (defaults to COMPLETION_MODEL)")

class CopilotSuggestResponse(BaseModel):
    """Response with code suggestion"""
    suggestion: str = Field(..., description="Suggested code completion")
    range: Dict[str, int] = Field(..., description="Range where suggestion applies {start, end}")

class ChatMessage(BaseModel):
    """Chat message structure"""
    role: str = Field(..., description="user, assistant, or system")
    content: str = Field(..., description="Message content")

class ChatAttachment(BaseModel):
    """File attachment for chat"""
    path: str = Field(..., description="File path in workspace")
    content: Optional[str] = Field(None, description="File content (optional)")

class IDEChatSendRequest(BaseModel):
    """Request to send chat message"""
    session_id: str = Field(..., description="Vibecode session ID")
    message: str = Field(..., min_length=1, description="User message")
    history: List[ChatMessage] = Field(default_factory=list, description="Chat history")
    attachments: Optional[List[ChatAttachment]] = Field(None, description="File attachments")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    model: str = Field("mistral", description="Model to use")

class ProposeDiffRequest(BaseModel):
    """Request to propose code changes"""
    session_id: str = Field(..., description="Vibecode session ID")
    filepath: str = Field(..., description="File to modify")
    base_content: Optional[str] = Field(None, description="Current file content (if not provided, read from disk)")
    instructions: str = Field(..., description="What changes to make")
    model: str = Field("gpt-oss", description="Model to use for code generation")
    selection: Optional[Dict[str, Any]] = Field(None, description="Selected text range {start_line, end_line, text}")
    mode: Optional[str] = Field("draft", description="Return mode: 'draft' (full content) or 'unified_diff' (diff only)")

class ProposeDiffResponse(BaseModel):
    """Response with proposed changes"""
    draft_content: Optional[str] = Field(None, description="Modified file content (if mode='draft')")
    diff: Optional[str] = Field(None, description="Unified diff format")
    stats: Dict[str, int] = Field(..., description="Change statistics: {lines_added, lines_removed, hunks}")
    base_etag: str = Field(..., description="SHA256 hash of original content for optimistic concurrency")

class ApplyDiffRequest(BaseModel):
    """Request to apply changes to file"""
    session_id: str = Field(..., description="Vibecode session ID")
    filepath: str = Field(..., description="File to modify")
    draft_content: str = Field(..., description="New file content")
    base_etag: Optional[str] = Field(None, description="ETag of original content for conflict detection")

class ApplyDiffResponse(BaseModel):
    """Response after applying changes"""
    saved: bool = Field(..., description="Whether save was successful")
    bytes: int = Field(..., description="Bytes written")
    updated_at: str = Field(..., description="Update timestamp")
    new_etag: str = Field(..., description="SHA256 hash of new content")

# ─── Utility Functions ─────────────────────────────────────────────────────────

def compute_etag(content: str) -> str:
    """Compute SHA256 hash of content for ETag (optimistic concurrency)"""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def sanitize_path(path: str) -> str:
    """Sanitize file path to prevent directory traversal
    Returns path that can be passed to file_operations functions
    Handles both /workspace/file.py and file.py formats
    """
    # Remove leading slash if present
    if path.startswith('/'):
        path = path[1:]
    
    # Remove /workspace/ prefix if present (normalize to relative)
    if path.startswith('workspace/'):
        path = path[len('workspace/'):]
    
    # Reject absolute paths, .., and other dangerous patterns
    if path.startswith('/') or '..' in path or path.startswith('~'):
        raise ValueError("Invalid path: absolute paths and '..' not allowed")
    
    # Ensure path is relative to workspace (file_operations will handle /workspace prefix)
    return path

def check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit for copilot suggestions"""
    now = time.time()
    user_requests = _copilot_rate_limits[user_id]
    
    # Remove old requests outside window
    user_requests[:] = [ts for ts in user_requests if now - ts < RATE_LIMIT_WINDOW]
    
    # Check limit
    if len(user_requests) >= RATE_LIMIT_MAX:
        return False
    
    # Add new request
    user_requests.append(now)
    return True

async def query_ollama_generate(prompt: str, model: str = "mistral", options: Optional[Dict[str, Any]] = None):
    """Query Ollama for code completion using /api/generate (non-streaming)"""
    try:
        # Default options if none provided
        if options is None:
            options = {
                "temperature": 0.7,
                "top_p": 0.9,
            }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": options
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
    except Exception as e:
        logger.error(f"Ollama generate query failed: {e}")
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {str(e)}")

async def query_ollama_chat(messages: list, model: str = "mistral", stream: bool = False, allow_retry: bool = True):
    """
    Query Ollama for chat (non-streaming)
    Uses ollama_compat.collect_text() for robust text collection with fallback
    Optimized for faster responses
    """
    try:
        options = {
            "temperature": 0.3,  # Lower for more deterministic/focused output
            "top_p": 0.8,        # Reduced for faster generation
            "num_predict": 2000,  # Limit tokens for speed
            "stop": ["```\n\n", "\n\n\n"],  # Stop on code block end
        }
        return await collect_text(model, messages, options, allow_retry)
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"Ollama value error: {error_msg}")
        raise HTTPException(status_code=503, detail=f"AI service error: {error_msg}")
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        logger.error(f"Ollama HTTP error: {error_msg}")
        raise HTTPException(status_code=503, detail=f"AI service error: {error_msg}")
    except httpx.TimeoutException as e:
        error_msg = "Request timed out (>60s)"
        logger.error(f"Ollama timeout: {error_msg}")
        raise HTTPException(status_code=504, detail=f"AI service timeout: {error_msg}")
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Ollama chat query failed: {error_msg}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {error_msg}")

def generate_diff(original: str, modified: str, filepath: str) -> tuple[str, Dict[str, int]]:
    """Generate unified diff and statistics"""
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        lineterm=''
    )
    
    diff_text = '\n'.join(diff)
    
    # Calculate stats
    added = len([line for line in modified_lines if line not in original_lines])
    removed = len([line for line in original_lines if line not in modified_lines])
    
    stats = {
        "lines_added": added,
        "lines_removed": removed,
        "hunks": diff_text.count("@@") // 2 if diff_text else 0
    }
    
    return diff_text, stats

# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/providers", response_model=ProvidersResponse)
async def get_providers(
    user: Dict = Depends(get_current_user_optimized)
):
    """
    Get list of available AI providers/models
    Queries Ollama for available models and optionally includes cloud models from env vars
    """
    try:
        providers: List[ProviderInfo] = []
        
        # Query Ollama for available models
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{OLLAMA_URL}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("models", [])
                    
                    # Filter for code-capable models (heuristic: check name)
                    code_keywords = ["code", "coder", "llama", "mistral", "gpt", "deepseek", "phi", "qwen"]
                    for model in models:
                        model_name = model.get("name", "")
                        # Include all models for now (user can choose)
                        # But prioritize code-focused ones
                        is_code_focused = any(kw in model_name.lower() for kw in code_keywords)
                        
                        providers.append(ProviderInfo(
                            id=model_name,
                            label=model_name.replace(":", " ").title(),
                            type="ollama",
                            capabilities=["chat", "completion", "code"] if is_code_focused else ["chat", "completion"]
                        ))
        except Exception as e:
            logger.warning(f"Failed to query Ollama models: {e}")
            # Fallback: return default models
            providers.append(ProviderInfo(
                id="gpt-oss",
                label="GPT-OSS",
                type="ollama",
                capabilities=["chat", "completion", "code"]
            ))
            providers.append(ProviderInfo(
                id="mistral",
                label="Mistral",
                type="ollama",
                capabilities=["chat", "completion"]
            ))
        
        # Optionally add cloud models if API keys exist (but don't force them)
        if OPENAI_API_KEY:
            providers.append(ProviderInfo(
                id="gpt-4",
                label="GPT-4 (OpenAI)",
                type="cloud",
                capabilities=["chat", "completion", "code"]
            ))
        
        if ANTHROPIC_API_KEY:
            providers.append(ProviderInfo(
                id="claude-3",
                label="Claude 3 (Anthropic)",
                type="cloud",
                capabilities=["chat", "completion", "code"]
            ))
        
        # If no providers found, add at least one default
        if not providers:
            providers.append(ProviderInfo(
                id="gpt-oss",
                label="GPT-OSS (Default)",
                type="ollama",
                capabilities=["chat", "completion", "code"]
            ))
        
        return ProvidersResponse(providers=providers)
        
    except Exception as e:
        logger.error(f"Get providers failed: {e}")
        # Return at least default model on error
        return ProvidersResponse(providers=[
            ProviderInfo(
                id="gpt-oss",
                label="GPT-OSS (Default)",
                type="ollama",
                capabilities=["chat", "completion", "code"]
            )
        ])

@router.post("/copilot/suggest", response_model=CopilotSuggestResponse)
async def copilot_suggest(
    request: CopilotSuggestRequest,
    user: Dict = Depends(get_current_user_optimized)
):
    """
    Generate inline code suggestion based on cursor context
    Uses dedicated Ollama compatibility layer with robust empty response handling
    Decoupled from assistant/propose - this is ONLY for ghost suggestions
    """
    try:
        user_id = str(user.get('id'))
        
        # Check rate limit
        if not check_rate_limit(user_id):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Max 10 suggestions per minute."
            )
        
        # Sanitize filepath
        safe_path = sanitize_path(request.filepath)
        
        # Extract context around cursor
        content = request.content
        cursor_pos = request.cursor_offset
        
        context_window = build_copilot_context(
            content=content,
            cursor_pos=cursor_pos,
            before_lines=40,
            after_lines=15,
            local_radius=3,
        )
        neighbor_summary = summarize_neighbor_files(request.neighbor_files)
        messages = build_copilot_messages(
            language=request.language,
            safe_path=safe_path,
            context_window=context_window,
            neighbor_summary=neighbor_summary,
        )
        suffix_hint = request.suffix if request.suffix is not None else context_window["after"][:400]
        options = inline_generation_options(request.language, suffix_hint)
        
        # Use specified model or default to COMPLETION_MODEL
        model_to_use = request.model or COMPLETION_MODEL
        
        logger.info(f"🤖 Querying Ollama for code suggestion with model: {model_to_use}")
        
        # Use ollama_compat.collect_text() which handles empty responses and fallback
        # Per masterprompt3: never return 503 for empty outputs; return suggestion: "" instead
        try:
            suggestion = await collect_text(
                model=model_to_use,
                messages=messages,
                options=options,
                allow_retry=True
            )
            logger.info(f"✅ Ollama returned suggestion: {len(suggestion)} chars")
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"❌ Ollama HTTP error: {error_msg}")
            # Return empty suggestion instead of 503
            suggestion = ""
        except httpx.TimeoutException:
            logger.error("❌ Ollama timeout")
            # Return empty suggestion instead of 504
            suggestion = ""
        except Exception as e:
            logger.error(f"❌ Ollama query failed: {e}")
            # Return empty suggestion instead of 503
            suggestion = ""
        
        cleaned = truncate_safely(
            clean_copilot_suggestion(
                suggestion,
                language=request.language,
                indentation=context_window["indentation"],
            )
        )
        logger.info(f"📝 Raw suggestion before cleanup: {suggestion[:200]}")
        logger.info(f"✨ Final suggestion to return: {cleaned}")
        
        return CopilotSuggestResponse(
            suggestion=cleaned,
            range={"start": cursor_pos, "end": cursor_pos}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Copilot suggestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/send")
async def chat_send(
    request: IDEChatSendRequest,
    user: Dict = Depends(get_current_user_optimized)
):
    """
    Send message to IDE Assistant and stream response
    Uses SSE for streaming
    """
    try:
        # Build conversation context
        messages = []
        
        # Add system message
        system_msg = "You are an expert programming assistant integrated into a code editor. Help the user with coding tasks, explain code, suggest improvements, and answer questions. Be concise and practical."
        messages.append({"role": "system", "content": system_msg})
        
        # Add file attachments to context
        if request.attachments:
            attachment_context = "Files attached to this conversation:\n\n"
            for attachment in request.attachments:
                safe_path = sanitize_path(attachment.path)
                attachment_context += f"File: {safe_path}\n"
                if attachment.content:
                    # Limit content size
                    content = attachment.content[:10000]
                    attachment_context += f"```\n{content}\n```\n\n"
            messages.append({"role": "system", "content": attachment_context})
        
        # Add history
        for msg in request.history[-10:]:  # Last 10 messages for context
            messages.append({"role": msg.role, "content": msg.content})
        
        # Add current message
        messages.append({"role": "user", "content": request.message})
        
        # Stream response using compatibility layer (auto-detects /api/chat vs /api/generate)
        return StreamingResponse(
            stream_chat_sse(request.model, messages),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
        
    except Exception as e:
        logger.error(f"IDE chat send failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/propose-diff", response_model=ProposeDiffResponse)
async def propose_diff(
    request: ProposeDiffRequest,
    user: Dict = Depends(get_current_user_optimized)
):
    """
    Propose code changes based on instructions
    Returns draft content and diff
    """
    try:
        # Sanitize filepath
        safe_path = sanitize_path(request.filepath)
        
        # Get base content (either provided or read from container)
        if request.base_content:
            original_content = request.base_content
        else:
            # Read from container filesystem
            container = await container_manager.get_container(request.session_id)
            
            if not container:
                raise HTTPException(
                    status_code=404,
                    detail=f"Container not found for session {request.session_id}"
                )
            
            try:
                original_content = await file_operations.read_file(container, safe_path)
                logger.debug(f"Read file {safe_path} from container for propose-diff")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to read file {safe_path} from container: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read file from container: {str(e)}"
                )
        
        # Build prompt for code modification
        # If selection provided, focus on that region
        if request.selection and request.selection.get('text'):
            selection_info = f"""

SELECTED REGION (lines {request.selection.get('start_line', '?')}-{request.selection.get('end_line', '?')}):
{request.selection['text']}

Focus your changes on this selection, but return the COMPLETE file with modifications."""
        else:
            selection_info = ""
        
        prompt = f"""You are an expert programmer. Modify the following code according to the instructions. Return ONLY the complete modified code, without explanations or markdown formatting.

File: {safe_path}
Instructions: {request.instructions}{selection_info}

Original code:
{original_content}

Modified code (complete file):"""
        
        # Query Ollama for modified code using chat endpoint
        messages = [
            {"role": "system", "content": "You are an expert programmer. Modify code according to instructions and return ONLY the complete modified code without explanations."},
            {"role": "user", "content": prompt}
        ]
        modified_content = await query_ollama_chat(messages, model=request.model, stream=False)
        
        # Clean up response
        modified_content = modified_content.strip()
        if modified_content.startswith("```"):
            lines = modified_content.split('\n')
            # Remove first and last line (markdown code block markers)
            if len(lines) > 2:
                modified_content = '\n'.join(lines[1:-1])
        
        # Generate diff
        diff_text, stats = generate_diff(original_content, modified_content, safe_path)
        
        # Compute base ETag for optimistic concurrency
        base_etag = compute_etag(original_content)
        
        return ProposeDiffResponse(
            draft_content=modified_content,
            diff=diff_text,
            stats=stats,
            base_etag=base_etag
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Propose diff failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/diff/propose", response_model=ProposeDiffResponse)
async def propose_diff_new(
    request: ProposeDiffRequest,
    user: Dict = Depends(get_current_user_optimized)
):
    """
    Propose code changes for a file (new endpoint per masterprompt2.md spec)
    Supports mode parameter: 'draft' (full content) or 'unified_diff' (diff only)
    Returns base_etag for optimistic concurrency
    """
    try:
        # Sanitize filepath
        safe_path = sanitize_path(request.filepath)
        
        # Get base content (either provided or read from container)
        if request.base_content:
            original_content = request.base_content
        else:
            # Read from container filesystem
            container = await container_manager.get_container(request.session_id)
            
            if not container:
                raise HTTPException(
                    status_code=404,
                    detail=f"Container not found for session {request.session_id}"
                )
            
            try:
                original_content = await file_operations.read_file(container, safe_path)
                logger.debug(f"Read file {safe_path} from container for propose-diff")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to read file {safe_path} from container: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read file from container: {str(e)}"
                )
        
        # Compute base ETag
        base_etag = compute_etag(original_content)
        
        # Build prompt for code modification
        # If selection provided, focus on that region
        if request.selection and request.selection.get('text'):
            selection_info = f"""

SELECTED REGION (lines {request.selection.get('start_line', '?')}-{request.selection.get('end_line', '?')}):
{request.selection['text']}

Focus your changes on this selection, but return the COMPLETE file with modifications."""
        else:
            selection_info = ""
        
        prompt = f"""You are an expert programmer. Modify the following code according to the instructions. Return ONLY the complete modified code, without explanations or markdown formatting.

File: {safe_path}
Instructions: {request.instructions}{selection_info}

Original code:
{original_content}

Modified code (complete file):"""
        
        # Query Ollama for modified code using chat endpoint
        messages = [
            {"role": "system", "content": "You are an expert programmer. Modify code according to instructions and return ONLY the complete modified code without explanations."},
            {"role": "user", "content": prompt}
        ]
        modified_content = await query_ollama_chat(messages, model=request.model, stream=False)
        
        # Clean up response
        modified_content = modified_content.strip()
        if modified_content.startswith("```"):
            lines = modified_content.split('\n')
            # Remove first and last line (markdown code block markers)
            if len(lines) > 2:
                modified_content = '\n'.join(lines[1:-1])
        
        # Generate diff and stats
        diff_text, stats = generate_diff(original_content, modified_content, safe_path)
        
        # Handle mode parameter
        mode = request.mode or "draft"
        
        if mode == "unified_diff":
            # Return only diff, no draft content
            return ProposeDiffResponse(
                draft_content=None,
                diff=diff_text,
                stats=stats,
                base_etag=base_etag
            )
        else:
            # Default: return full draft content
            return ProposeDiffResponse(
                draft_content=modified_content,
                diff=diff_text,
                stats=stats,
                base_etag=base_etag
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Propose diff failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/diff/apply", response_model=ApplyDiffResponse)
async def apply_diff(
    request: ApplyDiffRequest,
    user: Dict = Depends(get_current_user_optimized)
):
    """
    Apply proposed changes to file in workspace
    Writes to container filesystem
    Supports ETag-based optimistic concurrency: if base_etag provided and doesn't match current file, returns 409 conflict
    """
    try:
        # Sanitize filepath
        safe_path = sanitize_path(request.filepath)
        
        # Validate content size (max 10MB)
        content_bytes = request.draft_content.encode('utf-8')
        if len(content_bytes) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="File content too large (max 10MB)"
            )
        
        # Get the container for this session
        container = await container_manager.get_container(request.session_id)
        
        if not container:
            raise HTTPException(
                status_code=404,
                detail=f"Container not found for session {request.session_id}"
            )
        
        # Check for conflicts if base_etag provided
        if request.base_etag:
            try:
                current_content = await file_operations.read_file(container, safe_path)
                current_etag = compute_etag(current_content)
                
                if current_etag != request.base_etag:
                    # Conflict detected - file changed since proposal
                    logger.warning(f"Conflict detected for {safe_path}: expected {request.base_etag}, got {current_etag}")
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "conflict": True,
                            "current_etag": current_etag,
                            "current_content": current_content
                        }
                    )
            except HTTPException:
                # Re-raise HTTP exceptions (including 409)
                raise
            except Exception as e:
                # File might not exist yet, that's okay - proceed with save
                logger.debug(f"Could not read file for ETag check (may not exist): {e}")
        
        # Write to container filesystem
        success = await file_operations.save_file(
            container,
            safe_path,
            request.draft_content
        )
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to save file to container"
            )
        
        # Compute new ETag after save
        new_etag = compute_etag(request.draft_content)
        
        logger.info(f"✅ Applied diff to {safe_path} ({len(content_bytes)} bytes) in session {request.session_id}")
        
        return ApplyDiffResponse(
            saved=True,
            bytes=len(content_bytes),
            updated_at=datetime.utcnow().isoformat(),
            new_etag=new_etag
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Apply diff failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Export router
__all__ = ["router"]


