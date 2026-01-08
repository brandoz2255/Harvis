"""
LangGraph Chat Workflow
Enhanced chat with context and citations
Adapted from Open Notebook for PostgreSQL backend
"""

import os
import logging
from typing import TypedDict, Optional, List, Dict, Any
import requests

from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
CLOUD_OLLAMA_URL = os.getenv("OLLAMA_CLOUD_URL", "https://coyotegpt.ngrok.app/ollama")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "mistral")

CHAT_SYSTEM_PROMPT = """You are a cognitive study assistant that helps users research and learn by engaging in focused discussions about documents in their workspace.

# CAPABILITIES
- Access to project information and selected documents (CONTEXT)
- Can engage in natural dialogue while maintaining academic rigor

# YOUR OPERATING METHOD
When a user asks you a question, identify the query context and user intent. The user might be continuing a previous conversation or asking a new question. Looking at the CONTEXT will give you hints about what the user is looking for. Formulate your answer accordingly, paying attention to the CITING INSTRUCTIONS below.

{notebook_info}

{context_info}

# CITING INSTRUCTIONS

If your answer is based on any item in the context, it's very important that your response contains references to the searched documents so the user can follow-up and read more about the topic. Add the id of the specific document in brackets like this: [document_id].

## EXAMPLE
User: Can you tell me more about the concept of "Deep Learning"?
Assistant: Deep learning is a subset of machine learning in artificial intelligence (AI) that enables networks to learn unsupervised from unstructured or unlabeled data. [source:abc123]. It can also be categorized into three main types: supervised, unsupervised, and reinforcement learning. [note:xyz789].

## IMPORTANT
- Do not make up documents or document ids
- Use document IDs exactly as provided, including their type prefix
- The ID format is "type:randomstring" (e.g., "source:abc123", "note:xyz789")
"""


class ChatState(TypedDict):
    """State for chat workflow"""
    message: str
    context: List[Dict[str, Any]]
    notebook_info: Optional[str]
    model: str
    response: str
    citations: List[str]
    error: Optional[str]


async def prepare_context(state: ChatState) -> ChatState:
    """Prepare context for the chat"""
    context = state.get("context", [])
    
    # Build context string from chunks
    context_parts = []
    for i, chunk in enumerate(context):
        source_title = chunk.get("source_title", "Unknown Source")
        content = chunk.get("content", "")
        source_id = chunk.get("source_id", f"source:{i}")
        
        context_parts.append(f"""
--- SOURCE [{source_id}]: {source_title} ---
{content}
---
""")
    
    state["_context_text"] = "\n".join(context_parts) if context_parts else "No sources available."
    
    return state


async def generate_response(state: ChatState) -> ChatState:
    """Generate chat response with citations"""
    if state.get("error"):
        return state
    
    message = state["message"]
    model = state.get("model", DEFAULT_MODEL)
    context_text = state.get("_context_text", "")
    notebook_info = state.get("notebook_info", "")
    
    # Build the full prompt
    notebook_section = f"# PROJECT INFORMATION\n{notebook_info}" if notebook_info else ""
    context_section = f"# CONTEXT\nThe user has selected this context to help you:\n{context_text}" if context_text else ""
    
    system_prompt = CHAT_SYSTEM_PROMPT.format(
        notebook_info=notebook_section,
        context_info=context_section
    )
    
    full_prompt = f"{system_prompt}\n\nUser: {message}\n\nAssistant:"
    
    # Call LLM
    try:
        response = await _call_llm(full_prompt, model)
        state["response"] = response
        
        # Extract citations from response
        import re
        citations = re.findall(r'\[(source|note|insight):[^\]]+\]', response)
        state["citations"] = [c.strip('[]') for c in citations]
        
    except Exception as e:
        logger.error(f"Chat generation failed: {e}")
        state["error"] = str(e)
        state["response"] = "I apologize, but I encountered an error. Please try again."
    
    return state


async def _call_llm(prompt: str, model: str) -> str:
    """Call Ollama LLM with fallback"""
    
    # Try local first
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                }
            },
            timeout=120
        )
        
        if response.status_code == 200:
            data = response.json()
            result = data.get("response", "")
            from ..utils import clean_thinking_content
            return clean_thinking_content(result)
    except Exception as e:
        logger.warning(f"Local Ollama failed: {e}")
    
    # Try cloud
    try:
        response = requests.post(
            f"{CLOUD_OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        
        if response.status_code == 200:
            data = response.json()
            result = data.get("response", "")
            from ..utils import clean_thinking_content
            return clean_thinking_content(result)
    except Exception as e:
        logger.error(f"Cloud Ollama also failed: {e}")
        raise
    
    raise Exception("All LLM providers failed")


def build_chat_graph() -> StateGraph:
    """Build and compile the chat LangGraph"""
    graph = StateGraph(ChatState)
    
    # Add nodes
    graph.add_node("prepare", prepare_context)
    graph.add_node("generate", generate_response)
    
    # Set entry point
    graph.set_entry_point("prepare")
    
    # Add edges
    graph.add_edge("prepare", "generate")
    graph.add_edge("generate", END)
    
    return graph.compile()

