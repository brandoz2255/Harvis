"""
Synthesis and verification module for research pipeline.

Provides MAP/REDUCE orchestration, quote verification, and markdown rendering
for generating comprehensive research responses with proper source attribution.
"""

from .prompts import MAP_PROMPT, REDUCE_PROMPT, VERIFY_PROMPT, get_map_prompt, get_reduce_prompt, get_verify_prompt
from .map_reduce import MapReduceProcessor, MapResult, ReduceResult
from .verify import QuoteVerifier, VerificationResult
from .render import MarkdownRenderer, ResearchResponse

__all__ = [
    "MAP_PROMPT",
    "REDUCE_PROMPT", 
    "VERIFY_PROMPT",
    "get_map_prompt",
    "get_reduce_prompt",
    "get_verify_prompt",
    "MapReduceProcessor",
    "MapResult",
    "ReduceResult",
    "QuoteVerifier",
    "VerificationResult",
    "MarkdownRenderer",
    "ResearchResponse",
]