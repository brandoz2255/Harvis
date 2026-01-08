"""
LangGraph Transformation Workflow
Handles AI transformations like summarization, key points extraction, etc.
Adapted from Open Notebook for PostgreSQL backend
"""

import os
import logging
from typing import TypedDict, Optional, Any
import requests

from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
CLOUD_OLLAMA_URL = os.getenv("OLLAMA_CLOUD_URL", "https://coyotegpt.ngrok.app/ollama")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "mistral")

# Available transformation types
TRANSFORMATION_TYPES = {
    "summarize": {
        "name": "Summarize",
        "description": "Create a concise summary of the content",
        "prompt": """Create a comprehensive but concise summary of the following content.
Focus on the main ideas, key arguments, and important details.
Structure your summary with clear sections if the content covers multiple topics.

CONTENT:
{content}

SUMMARY:"""
    },
    "key_points": {
        "name": "Key Points",
        "description": "Extract the main takeaways and key points",
        "prompt": """Extract the key points and main takeaways from the following content.
Present them as a numbered list, ordered by importance.
Each point should be concise but informative.

CONTENT:
{content}

KEY POINTS:"""
    },
    "questions": {
        "name": "Study Questions",
        "description": "Generate study questions based on the content",
        "prompt": """Generate thoughtful study questions based on the following content.
Include a mix of:
- Factual questions (testing recall)
- Conceptual questions (testing understanding)
- Application questions (testing ability to apply concepts)
- Analysis questions (testing critical thinking)

CONTENT:
{content}

STUDY QUESTIONS:"""
    },
    "outline": {
        "name": "Outline",
        "description": "Create a structured outline of the content",
        "prompt": """Create a detailed hierarchical outline of the following content.
Use Roman numerals for main sections, capital letters for subsections, and numbers for details.
Capture the structure and organization of the material.

CONTENT:
{content}

OUTLINE:"""
    },
    "simplify": {
        "name": "Simplify",
        "description": "Explain the content in simpler terms",
        "prompt": """Explain the following content in simpler terms that anyone can understand.
Avoid jargon and technical language where possible.
Use analogies and examples to make complex concepts clearer.

CONTENT:
{content}

SIMPLIFIED EXPLANATION:"""
    },
    "critique": {
        "name": "Critical Analysis",
        "description": "Provide a critical analysis of the content",
        "prompt": """Provide a critical analysis of the following content.
Consider:
- Strengths and weaknesses of the arguments
- Potential biases or assumptions
- Missing perspectives or information
- Overall validity and reliability

CONTENT:
{content}

CRITICAL ANALYSIS:"""
    },
    "action_items": {
        "name": "Action Items",
        "description": "Extract actionable items and next steps",
        "prompt": """Extract actionable items and next steps from the following content.
Organize them by priority (High/Medium/Low).
Include any deadlines or timeframes mentioned.

CONTENT:
{content}

ACTION ITEMS:"""
    }
}


class TransformState(TypedDict):
    """State for transformation workflow"""
    content: str
    transformation: str
    model: str
    result: str
    custom_prompt: Optional[str]
    error: Optional[str]


async def analyze_content(state: TransformState) -> TransformState:
    """Analyze the content before transformation"""
    content = state.get("content", "")
    
    # Basic validation
    if not content or len(content.strip()) < 10:
        state["error"] = "Content is too short for transformation"
        return state
    
    # Log content size
    word_count = len(content.split())
    logger.info(f"Transforming content with {word_count} words using {state.get('transformation')}")
    
    return state


async def apply_transformation(state: TransformState) -> TransformState:
    """Apply the transformation using LLM"""
    if state.get("error"):
        return state
    
    content = state["content"]
    transformation = state["transformation"]
    model = state.get("model", DEFAULT_MODEL)
    custom_prompt = state.get("custom_prompt")
    
    # Get the prompt template
    if custom_prompt:
        prompt = custom_prompt.replace("{content}", content)
    elif transformation in TRANSFORMATION_TYPES:
        prompt = TRANSFORMATION_TYPES[transformation]["prompt"].format(content=content)
    else:
        state["error"] = f"Unknown transformation type: {transformation}"
        return state
    
    # Call LLM
    try:
        result = await _call_llm(prompt, model)
        state["result"] = result
    except Exception as e:
        logger.error(f"Transformation failed: {e}")
        state["error"] = str(e)
    
    return state


async def _call_llm(prompt: str, model: str) -> str:
    """Call Ollama LLM with fallback to cloud"""
    
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
            
            # Clean thinking content
            from ..utils import clean_thinking_content
            return clean_thinking_content(result)
    except Exception as e:
        logger.warning(f"Local Ollama failed: {e}, trying cloud...")
    
    # Try cloud fallback
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


def build_transform_graph() -> StateGraph:
    """Build and compile the transformation LangGraph"""
    graph = StateGraph(TransformState)
    
    # Add nodes
    graph.add_node("analyze", analyze_content)
    graph.add_node("transform", apply_transformation)
    
    # Set entry point
    graph.set_entry_point("analyze")
    
    # Add edges
    graph.add_edge("analyze", "transform")
    graph.add_edge("transform", END)
    
    return graph.compile()


def get_available_transformations() -> list:
    """Get list of available transformation types"""
    return [
        {
            "id": key,
            "name": val["name"],
            "description": val["description"]
        }
        for key, val in TRANSFORMATION_TYPES.items()
    ]

