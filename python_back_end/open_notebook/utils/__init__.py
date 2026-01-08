"""
Open Notebook Utilities
"""

import re
import os
from typing import Optional


def clean_thinking_content(content: str) -> str:
    """
    Clean thinking/reasoning content from LLM responses.
    Removes <think></think> tags and their content.
    """
    if not content:
        return content
    
    # Remove <think>...</think> blocks
    cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    
    # Clean up extra whitespace
    cleaned = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned)
    
    return cleaned.strip()


def token_count(text: str) -> int:
    """
    Estimate token count for text.
    Uses rough approximation of 4 characters per token.
    """
    if not text:
        return 0
    return len(text) // 4


def extract_json_from_response(response: str) -> Optional[str]:
    """
    Extract JSON from LLM response that may contain thinking tags or markdown.
    """
    import json
    
    # Remove thinking tags first
    cleaned = clean_thinking_content(response)
    
    # Try to find JSON in code blocks
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
    if json_match:
        return json_match.group(1)
    
    # Try to find raw JSON object
    json_match = re.search(r'(\{[^{}]*\})', cleaned, re.DOTALL)
    if json_match:
        try:
            json.loads(json_match.group(1))
            return json_match.group(1)
        except json.JSONDecodeError:
            pass
    
    return None


def get_prompts_dir() -> str:
    """Get the path to the prompts directory"""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'prompts')


__all__ = [
    'clean_thinking_content',
    'token_count', 
    'extract_json_from_response',
    'get_prompts_dir'
]

