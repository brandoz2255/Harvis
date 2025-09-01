"""
Enhanced research agent that bridges the existing system with the advanced pipeline.

This module provides a bridge between:
- Your existing make_ollama_request function and web_search capabilities
- My advanced pipeline with ranking, synthesis, verification, and caching

Maintains backward compatibility while adding advanced features.
"""

import os
import logging
from typing import Dict, List, Any, Optional, Union, AsyncGenerator
import asyncio

# Import your existing components
from .web_search import WebSearchAgent, TavilySearchAgent
from .research_agent import make_ollama_request

# Import core types and advanced pipeline
from .core.types import Hit, DocChunk, Quote
from .pipeline.research_agent import ResearchAgent as AdvancedResearchAgent, ResearchConfig
from .pipeline.fact_check import FactChecker
from .pipeline.compare import ComparativeAnalyzer
from .llm.ollama_client import OllamaClient
from .cache.http_cache import setup_cache, CacheConfig
from .mcp.tool import StandaloneResearchTool

logger = logging.getLogger(__name__)


class EnhancedResearchAgent:
    """
    Enhanced research agent that bridges existing functionality with advanced pipeline.
    
    Provides both simple research (backward compatible) and advanced research
    with streaming, verification, and structured analysis.
    """
    
    def __init__(
        self,
        search_engine: str = "duckduckgo",
        ollama_url: str = "http://ollama:11434", 
        default_model: str = "mistral",
        max_search_results: int = 20,
        enable_advanced_features: bool = True
    ):
        self.search_engine = search_engine
        self.ollama_url = ollama_url
        self.default_model = default_model
        self.max_search_results = max_search_results
        self.enable_advanced_features = enable_advanced_features
        
        # Initialize your existing web search
        self.web_search = WebSearchAgent(max_results=max_search_results)
        
        # Initialize Tavily if available
        if search_engine == "tavily" and os.getenv("TAVILY_API_KEY"):
            self.tavily_search = TavilySearchAgent(max_results=max_search_results)
        else:
            self.tavily_search = None
        
        # Initialize advanced pipeline if enabled
        if enable_advanced_features:
            # Setup caching
            cache_config = CacheConfig(
                cache_dir="research_cache",
                expire_after=3600,  # 1 hour default
                max_cache_size=1000
            )
            setup_cache(cache_config)
            
            # Configure advanced research
            research_config = ResearchConfig(
                max_search_results=max_search_results,
                enable_verification=True,
                enable_reranking=True,
                max_chunks_for_synthesis=15
            )
            
            self.advanced_agent = AdvancedResearchAgent(research_config)
            self.fact_checker = FactChecker()
            self.comparative_analyzer = ComparativeAnalyzer()
            self.standalone_tool = StandaloneResearchTool()
        else:
            self.advanced_agent = None
            self.fact_checker = None
            self.comparative_analyzer = None
            self.standalone_tool = None
    
    def _convert_search_results_to_hits(self, results: List[Dict]) -> List[Hit]:
        """Convert web search results to Hit objects"""
        hits = []
        for result in results:
            hit = Hit(
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("snippet", ""),
                score=result.get("relevance_score", 0.5),
                source=self.search_engine
            )
            hits.append(hit)
        return hits
    
    def _create_simple_response(self, analysis: str, sources: List[Dict], model: str) -> Dict[str, Any]:
        """Create backward-compatible response format"""
        return {
            "analysis": analysis,
            "sources": sources,
            "model_used": model,
            "sources_found": len(sources)
        }
    
    async def _make_ollama_request_async(self, prompt: str, model: str) -> str:
        """Async wrapper for your existing make_ollama_request function"""
        import asyncio
        loop = asyncio.get_event_loop()
        
        # Run your existing function in executor to avoid blocking
        try:
            response = await loop.run_in_executor(None, lambda: make_ollama_request("/api/generate", {
                "model": model,
                "prompt": prompt,
                "stream": False
            }))
            
            if response and response.status_code == 200:
                data = response.json()
                return data.get("response", "No response generated")
            else:
                return "Error: Could not generate response"
                
        except Exception as e:
            logger.error(f"Ollama request failed: {e}")
            return f"Error: {str(e)}"
    
    # Backward compatible methods (maintain your existing API)
    def research_topic(
        self,
        topic: str,
        model: str = None,
        research_depth: str = "standard",
        include_sources: bool = True
    ) -> Dict[str, Any]:
        """
        Backward compatible research method.
        
        Uses simple web search + LLM analysis for compatibility.
        """
        model = model or self.default_model
        
        try:
            # Use your existing web search
            search_results = self.web_search.search_web(topic)
            
            if not search_results:
                return {
                    "analysis": "No search results found for the topic.",
                    "sources": [],
                    "model_used": model,
                    "sources_found": 0
                }
            
            # Create analysis prompt
            sources_text = "\n\n".join([
                f"Source: {result['title']}\nURL: {result['url']}\nContent: {result['snippet']}"
                for result in search_results
            ])
            
            prompt = f"""Analyze the following topic based on the provided sources: {topic}

Sources:
{sources_text}

Please provide a comprehensive analysis including:
1. Key findings and insights
2. Important facts and data
3. Different perspectives if any
4. Conclusion and summary

Analysis:"""
            
            # Use your existing Ollama request
            response = make_ollama_request("/api/generate", {
                "model": model,
                "prompt": prompt,
                "stream": False
            })
            
            if response and response.status_code == 200:
                data = response.json()
                analysis = data.get("response", "No analysis generated")
            else:
                analysis = "Error: Could not generate analysis"
            
            return self._create_simple_response(analysis, search_results, model)
            
        except Exception as e:
            logger.error(f"Research topic error: {e}")
            return {"error": f"Research failed: {str(e)}"}
    
    def fact_check(self, claim: str, model: str = None) -> Dict[str, Any]:
        """Backward compatible fact-check method"""
        model = model or self.default_model
        
        try:
            # Simple fact-checking using web search
            search_query = f"fact check {claim}"
            search_results = self.web_search.search_web(search_query)
            
            sources_text = "\n\n".join([
                f"Source: {result['title']}\nContent: {result['snippet']}"
                for result in search_results
            ])
            
            prompt = f"""Fact-check the following claim based on the provided sources:

Claim: {claim}

Sources:
{sources_text}

Please analyze whether the claim is:
1. TRUE - well supported by evidence
2. FALSE - contradicted by evidence  
3. MIXED - partially true with qualifications
4. UNKNOWN - insufficient evidence

Provide your analysis and reasoning.

Fact-check result:"""
            
            response = make_ollama_request("/api/generate", {
                "model": model,
                "prompt": prompt,
                "stream": False
            })
            
            if response and response.status_code == 200:
                data = response.json()
                analysis = data.get("response", "No analysis generated")
            else:
                analysis = "Error: Could not generate fact-check"
            
            return {
                "claim": claim,
                "analysis": analysis,
                "sources": search_results,
                "model_used": model
            }
            
        except Exception as e:
            logger.error(f"Fact-check error: {e}")
            return {"error": f"Fact-check failed: {str(e)}"}
    
    def comparative_research(self, topics: List[str], model: str = None) -> Dict[str, Any]:
        """Backward compatible comparative research method"""
        model = model or self.default_model
        
        try:
            # Search for each topic
            all_results = []
            for topic in topics:
                results = self.web_search.search_web(topic, num_results=3)
                all_results.extend(results)
            
            # Create comparison prompt
            topics_text = " vs ".join(topics)
            sources_text = "\n\n".join([
                f"Source: {result['title']}\nContent: {result['snippet']}"
                for result in all_results
            ])
            
            prompt = f"""Compare and contrast the following topics: {topics_text}

Based on the provided sources:
{sources_text}

Please provide a structured comparison including:
1. Key similarities between the topics
2. Important differences
3. Strengths and weaknesses of each
4. Use cases or applications
5. Overall conclusion

Comparative analysis:"""
            
            response = make_ollama_request("/api/generate", {
                "model": model,
                "prompt": prompt,
                "stream": False
            })
            
            if response and response.status_code == 200:
                data = response.json()
                analysis = data.get("response", "No analysis generated")
            else:
                analysis = "Error: Could not generate comparison"
            
            return {
                "topics": topics,
                "analysis": analysis,
                "sources": all_results,
                "model_used": model
            }
            
        except Exception as e:
            logger.error(f"Comparative research error: {e}")
            return {"error": f"Comparative research failed: {str(e)}"}
    
    # Advanced methods (new functionality)
    async def advanced_research(
        self,
        query: str,
        model: str = None,
        enable_streaming: bool = False,
        enable_verification: bool = True
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        Advanced research using the full pipeline.
        
        Args:
            query: Research query
            model: Model to use (optional)
            enable_streaming: Whether to stream progress events
            enable_verification: Enable response verification
            
        Returns:
            Research response or stream of events
        """
        if not self.enable_advanced_features or not self.advanced_agent:
            # Fallback to simple research
            result = self.research_topic(query, model)
            return result.get("analysis", "Research failed")
        
        try:
            if enable_streaming:
                # Stream research progress
                result = await self.advanced_agent.research(query)
                
                async def stream_progress():
                    yield f"🔍 Starting research for: {query}\n\n"
                    yield f"📊 Found {result.sources_count} sources\n"
                    yield f"🎯 Confidence: {result.confidence_score:.1%}\n"
                    yield f"⏱️ Processing time: {result.total_duration:.1f}s\n\n"
                    if result.success:
                        yield result.response
                    else:
                        yield f"❌ Research failed: {result.error}"
                
                return stream_progress()
            else:
                # Non-streaming research
                result = await self.advanced_agent.research(query)
                return result.response if result.success else f"Research failed: {result.error}"
                
        except Exception as e:
            logger.error(f"Advanced research failed: {e}")
            return f"Advanced research failed: {str(e)}"
    
    async def advanced_fact_check(self, claim: str, model: str = None) -> str:
        """Advanced fact-checking with authority scoring and evidence analysis"""
        if not self.enable_advanced_features or not self.fact_checker:
            # Fallback to simple fact-check
            result = self.fact_check(claim, model)
            return result.get("analysis", "Fact-check failed")
        
        try:
            result = await self.fact_checker.fact_check(claim)
            return result.response
        except Exception as e:
            logger.error(f"Advanced fact-check failed: {e}")
            return f"Advanced fact-check failed: {str(e)}"
    
    async def advanced_compare(
        self,
        topics: List[str],
        context: str = None,
        model: str = None
    ) -> str:
        """Advanced comparison with structured analysis"""
        if not self.enable_advanced_features or not self.comparative_analyzer:
            # Fallback to simple comparison
            result = self.comparative_research(topics, model)
            return result.get("analysis", "Comparison failed")
        
        try:
            result = await self.comparative_analyzer.compare(topics, comparison_context=context)
            return result.response
        except Exception as e:
            logger.error(f"Advanced comparison failed: {e}")
            return f"Advanced comparison failed: {str(e)}"
    
    def get_mcp_tool(self) -> Optional[StandaloneResearchTool]:
        """Get MCP standalone tool interface"""
        return self.standalone_tool if self.enable_advanced_features else None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get research agent statistics"""
        stats = {
            "search_engine": self.search_engine,
            "default_model": self.default_model,
            "max_search_results": self.max_search_results,
            "advanced_features_enabled": self.enable_advanced_features
        }
        
        if self.enable_advanced_features and self.advanced_agent:
            stats["advanced_pipeline_stats"] = self.advanced_agent.get_pipeline_stats()
        
        return stats


# Convenience functions for backward compatibility
def create_enhanced_research_agent(**kwargs) -> EnhancedResearchAgent:
    """Create enhanced research agent with configuration"""
    return EnhancedResearchAgent(**kwargs)


# Global instance (for compatibility with your existing code)
_global_enhanced_agent = None


def get_enhanced_research_agent(**kwargs) -> EnhancedResearchAgent:
    """Get or create global enhanced research agent"""
    global _global_enhanced_agent
    if _global_enhanced_agent is None:
        _global_enhanced_agent = EnhancedResearchAgent(**kwargs)
    return _global_enhanced_agent