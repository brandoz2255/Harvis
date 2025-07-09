"""
Research module for Jarvis AI
Provides web search and research capabilities using LangChain
"""

from .web_search import WebSearchAgent
from .research_agent import ResearchAgent

__all__ = ["WebSearchAgent", "ResearchAgent"]