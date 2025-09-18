
"""
Enhanced research agent using the advanced research pipeline
"""

import os
import logging
import asyncio
from research import ResearchAgent
from research.enhanced_research_agent import get_enhanced_research_agent

logger = logging.getLogger(__name__)

# Initialize the research agent
research_agent_instance = ResearchAgent(
    search_engine="duckduckgo",  # or "tavily" if API key is available
    ollama_url="http://ollama:11434",
    default_model="mistral",
    max_search_results=5
)

# Initialize the enhanced research agent for advanced features
enhanced_research_agent_instance = get_enhanced_research_agent(
    search_engine="duckduckgo",  # or "tavily" if API key is available
    ollama_url="http://ollama:11434",
    default_model="mistral",
    max_search_results=20,  # Increased for better results
    enable_advanced_features=True  # Enable advanced pipeline
)

def research_agent(query: str, model: str = "mistral", use_advanced: bool = False):
    """
    Enhanced research agent that performs comprehensive web research
    
    Args:
        query: Research query
        model: LLM model to use for analysis
        use_advanced: Whether to use advanced pipeline (async)
        
    Returns:
        Research results with analysis and sources
    """
    try:
        if use_advanced:
            # Use enhanced research agent for advanced features
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    enhanced_research_agent_instance.advanced_research(query, model, enable_verification=True)
                )
                # Format for compatibility
                return {
                    "analysis": result,
                    "sources": [],  # Sources embedded in response
                    "model_used": model,
                    "sources_found": "embedded",
                    "advanced": True
                }
            finally:
                loop.close()
        else:
            # Use backward compatible method
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
                "sources_found": result.get("sources_found", 0),
                "advanced": False
            }
        
    except Exception as e:
        logger.error(f"Research agent error: {e}")
        return {"error": f"Research failed: {str(e)}"}

def fact_check_agent(claim: str, model: str = "mistral", use_advanced: bool = False):
    """
    Fact-check a claim using web search
    
    Args:
        claim: Claim to fact-check
        model: LLM model to use
        use_advanced: Whether to use advanced fact-checking pipeline
        
    Returns:
        Fact-check results
    """
    try:
        if use_advanced:
            # Use enhanced research agent for advanced fact-checking
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    enhanced_research_agent_instance.advanced_fact_check(claim, model)
                )
                return {
                    "claim": claim,
                    "analysis": result,
                    "model_used": model,
                    "advanced": True
                }
            finally:
                loop.close()
        else:
            # Use backward compatible method
            result = research_agent_instance.fact_check(claim, model)
            result["advanced"] = False
            return result
        
    except Exception as e:
        logger.error(f"Fact-check agent error: {e}")
        return {"error": f"Fact-check failed: {str(e)}"}

def comparative_research_agent(topics: list, model: str = "mistral", use_advanced: bool = False, context: str = None):
    """
    Compare multiple topics
    
    Args:
        topics: List of topics to compare
        model: LLM model to use
        use_advanced: Whether to use advanced comparison pipeline
        context: Optional context to guide comparison
        
    Returns:
        Comparative analysis results
    """
    try:
        if use_advanced:
            # Use enhanced research agent for advanced comparison
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    enhanced_research_agent_instance.advanced_compare(topics, context, model)
                )
                return {
                    "topics": topics,
                    "analysis": result,
                    "model_used": model,
                    "context": context,
                    "advanced": True
                }
            finally:
                loop.close()
        else:
            # Use backward compatible method
            result = research_agent_instance.comparative_research(topics, model)
            result["advanced"] = False
            return result
        
    except Exception as e:
        logger.error(f"Comparative research agent error: {e}")
        return {"error": f"Comparative research failed: {str(e)}"}

# New advanced functions
async def async_research_agent(query: str, model: str = "mistral", enable_streaming: bool = False):
    """
    Async research agent for use in FastAPI endpoints
    
    Args:
        query: Research query
        model: LLM model to use
        enable_streaming: Enable streaming progress
        
    Returns:
        Research results or async generator for streaming
    """
    try:
        return await enhanced_research_agent_instance.advanced_research(
            query=query,
            model=model,
            enable_streaming=enable_streaming,
            enable_verification=True
        )
    except Exception as e:
        logger.error(f"Async research agent error: {e}")
        return f"Research failed: {str(e)}"


async def async_fact_check_agent(claim: str, model: str = "mistral"):
    """Async fact-check agent"""
    try:
        return await enhanced_research_agent_instance.advanced_fact_check(claim, model)
    except Exception as e:
        logger.error(f"Async fact-check error: {e}")
        return f"Fact-check failed: {str(e)}"


async def async_comparative_research_agent(topics: list, model: str = "mistral", context: str = None):
    """Async comparative research agent"""
    try:
        return await enhanced_research_agent_instance.advanced_compare(topics, context, model)
    except Exception as e:
        logger.error(f"Async comparative research error: {e}")
        return f"Comparison failed: {str(e)}"


def get_research_agent_stats():
    """Get research agent statistics"""
    try:
        # Try both research agents and combine stats
        stats = {}
        try:
            basic_stats = research_agent_instance.get_statistics()
            stats.update(basic_stats)
        except:
            pass
        try:
            enhanced_stats = enhanced_research_agent_instance.get_statistics()
            stats.update(enhanced_stats)
        except:
            pass
        return stats if stats else {"error": "No stats available"}
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {"error": f"Could not get stats: {str(e)}"}


def get_mcp_tool():
    """Get MCP tool interface"""
    try:
        # Try enhanced first, then basic
        try:
            return enhanced_research_agent_instance.get_mcp_tool()
        except:
            return research_agent_instance.get_mcp_tool()
    except Exception as e:
        logger.error(f"MCP tool error: {e}")
        return None
