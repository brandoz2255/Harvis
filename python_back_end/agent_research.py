
"""
Enhanced research agent using the new research module
"""

import os
import logging
from research import ResearchAgent

logger = logging.getLogger(__name__)

# Initialize the research agent
research_agent_instance = ResearchAgent(
    search_engine="duckduckgo",  # or "tavily" if API key is available
    ollama_url="http://ollama:11434",
    default_model="mistral",
    max_search_results=5
)

def research_agent(query: str, model: str = "mistral"):
    """
    Enhanced research agent that performs comprehensive web research
    
    Args:
        query: Research query
        model: LLM model to use for analysis
        
    Returns:
        Research results with analysis and sources
    """
    try:
        # Use the new research agent for comprehensive research
        result = research_agent_instance.research_topic(
            topic=query,
            model=model,
            research_depth="standard",
            include_sources=True
        )
        
        # Format response for backwards compatibility
        return {
            "analysis": result["analysis"],
            "sources": result.get("sources", []),
            "model_used": result.get("model_used", model),
            "sources_found": result.get("sources_found", 0)
        }
        
    except Exception as e:
        logger.error(f"Research agent error: {e}")
        return {"error": f"Research failed: {str(e)}"}

def fact_check_agent(claim: str, model: str = "mistral"):
    """
    Fact-check a claim using web search
    
    Args:
        claim: Claim to fact-check
        model: LLM model to use
        
    Returns:
        Fact-check results
    """
    try:
        result = research_agent_instance.fact_check(claim, model)
        return result
        
    except Exception as e:
        logger.error(f"Fact-check agent error: {e}")
        return {"error": f"Fact-check failed: {str(e)}"}

def comparative_research_agent(topics: list, model: str = "mistral"):
    """
    Compare multiple topics
    
    Args:
        topics: List of topics to compare
        model: LLM model to use
        
    Returns:
        Comparative analysis results
    """
    try:
        result = research_agent_instance.comparative_research(topics, model)
        return result
        
    except Exception as e:
        logger.error(f"Comparative research agent error: {e}")
        return {"error": f"Comparative research failed: {str(e)}"}
