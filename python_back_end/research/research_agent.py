"""
Research agent that combines web search with LLM analysis
"""

import os
import logging
from typing import Dict, List, Any, Optional
from .web_search import WebSearchAgent, TavilySearchAgent
import requests
import json

logger = logging.getLogger(__name__)

class ResearchAgent:
    """
    Advanced research agent that combines web search with LLM analysis
    """
    
    def __init__(self, 
                 search_engine: str = "duckduckgo",
                 ollama_url: str = "http://ollama:11434",
                 default_model: str = "mistral",
                 max_search_results: int = 5):
        """
        Initialize the research agent
        
        Args:
            search_engine: Search engine to use ("duckduckgo" or "tavily")
            ollama_url: Ollama server URL
            default_model: Default LLM model to use
            max_search_results: Maximum number of search results to process
        """
        self.ollama_url = ollama_url
        self.default_model = default_model
        self.max_search_results = max_search_results
        
        # Initialize search agent
        if search_engine == "tavily":
            self.search_agent = TavilySearchAgent()
        else:
            self.search_agent = WebSearchAgent(max_results=max_search_results)
    
    def query_llm(self, prompt: str, model: str = None, system_prompt: str = None) -> str:
        """
        Query the LLM with a prompt
        
        Args:
            prompt: User prompt
            model: LLM model to use
            system_prompt: System prompt for the LLM
            
        Returns:
            LLM response
        """
        model = model or self.default_model
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        
        try:
            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            
            result = response.json()
            return result.get("message", {}).get("content", "").strip()
            
        except Exception as e:
            logger.error(f"LLM query failed: {e}")
            return f"Error querying LLM: {str(e)}"
    
    def research_topic(self, 
                      topic: str, 
                      model: str = None,
                      research_depth: str = "standard",
                      include_sources: bool = True) -> Dict[str, Any]:
        """
        Research a topic using web search and LLM analysis
        
        Args:
            topic: Research topic/query
            model: LLM model to use for analysis
            research_depth: "quick", "standard", or "deep"
            include_sources: Whether to include source URLs in response
            
        Returns:
            Research results with analysis and sources
        """
        logger.info(f"Starting research on topic: {topic}")
        
        # Adjust search parameters based on depth
        search_params = {
            "quick": {"max_results": 3, "extract_content": False},
            "standard": {"max_results": 5, "extract_content": True},
            "deep": {"max_results": 8, "extract_content": True}
        }
        
        params = search_params.get(research_depth, search_params["standard"])
        
        # Search the web
        if hasattr(self.search_agent, 'search_and_extract'):
            search_data = self.search_agent.search_and_extract(
                topic, 
                extract_content=params["extract_content"]
            )
        else:
            search_data = {
                "query": topic,
                "search_results": self.search_agent.search_web(topic, params["max_results"]),
                "extracted_content": []
            }
        
        # Prepare context for LLM
        context = self._prepare_research_context(search_data)
        
        # Generate research analysis
        system_prompt = self._get_research_system_prompt(research_depth)
        
        research_prompt = f"""
Research Topic: {topic}

Based on the following web search results and content, provide a comprehensive analysis:

{context}

Please provide:
1. A summary of key findings
2. Main insights and conclusions
3. Different perspectives or viewpoints found
4. Potential implications or applications
5. Areas that might need further research

Be thorough but concise, and cite sources when referencing specific information.
"""
        
        analysis = self.query_llm(research_prompt, model, system_prompt)
        
        # Compile results
        result = {
            "topic": topic,
            "analysis": analysis,
            "research_depth": research_depth,
            "model_used": model or self.default_model,
            "sources_found": len(search_data.get("search_results", [])),
            "timestamp": self._get_timestamp()
        }
        
        if include_sources:
            result["sources"] = self._format_sources(search_data.get("search_results", []))
        
        logger.info(f"Research completed for topic: {topic}")
        return result
    
    def fact_check(self, claim: str, model: str = None) -> Dict[str, Any]:
        """
        Fact-check a claim using web search
        
        Args:
            claim: Claim to fact-check
            model: LLM model to use
            
        Returns:
            Fact-check results
        """
        logger.info(f"Fact-checking claim: {claim}")
        
        # Search for information about the claim
        search_query = f"fact check: {claim}"
        search_data = self.search_agent.search_and_extract(search_query, extract_content=True)
        
        # Prepare context
        context = self._prepare_research_context(search_data)
        
        # Generate fact-check analysis
        system_prompt = """You are a fact-checking assistant. Analyze the provided information carefully and provide an objective assessment of the claim's accuracy. Be thorough and cite sources."""
        
        fact_check_prompt = f"""
Claim to verify: "{claim}"

Based on the following search results and content:

{context}

Please provide:
1. Verification status (True/False/Partially True/Insufficient Information)
2. Detailed explanation of your assessment
3. Key evidence supporting or contradicting the claim
4. Source reliability assessment
5. Any important context or nuances

Be objective and cite specific sources for your conclusions.
"""
        
        analysis = self.query_llm(fact_check_prompt, model, system_prompt)
        
        return {
            "claim": claim,
            "analysis": analysis,
            "sources": self._format_sources(search_data.get("search_results", [])),
            "model_used": model or self.default_model,
            "timestamp": self._get_timestamp()
        }
    
    def comparative_research(self, 
                           topics: List[str], 
                           model: str = None) -> Dict[str, Any]:
        """
        Compare multiple topics or concepts
        
        Args:
            topics: List of topics to compare
            model: LLM model to use
            
        Returns:
            Comparative analysis results
        """
        logger.info(f"Starting comparative research on: {topics}")
        
        # Research each topic
        individual_research = {}
        all_sources = []
        
        for topic in topics:
            research_result = self.research_topic(topic, model, "standard", include_sources=False)
            individual_research[topic] = research_result["analysis"]
            all_sources.extend(research_result.get("sources", []))
        
        # Generate comparative analysis
        system_prompt = """You are a research analyst specializing in comparative analysis. Provide objective, thorough comparisons highlighting similarities, differences, and key insights."""
        
        comparison_prompt = f"""
Provide a comparative analysis of the following topics: {', '.join(topics)}

Individual research findings:
{json.dumps(individual_research, indent=2)}

Please provide:
1. Key similarities between the topics
2. Major differences and contrasts
3. Strengths and weaknesses of each
4. Practical implications of these differences
5. Summary recommendations or conclusions

Be thorough and objective in your analysis.
"""
        
        analysis = self.query_llm(comparison_prompt, model, system_prompt)
        
        return {
            "topics": topics,
            "individual_research": individual_research,
            "comparative_analysis": analysis,
            "model_used": model or self.default_model,
            "timestamp": self._get_timestamp()
        }
    
    def _prepare_research_context(self, search_data: Dict[str, Any]) -> str:
        """Prepare search results for LLM context"""
        context_parts = []
        
        # Add search results
        for i, result in enumerate(search_data.get("search_results", []), 1):
            context_parts.append(f"""
Source {i}: {result.get('title', 'Unknown')}
URL: {result.get('url', 'Unknown')}
Snippet: {result.get('snippet', 'No snippet available')}
""")
        
        # Add extracted content if available
        for i, content in enumerate(search_data.get("extracted_content", []), 1):
            if content.get("success") and content.get("text"):
                # Truncate very long content
                text = content["text"][:2000] if len(content["text"]) > 2000 else content["text"]
                context_parts.append(f"""
Full Content {i}: {content.get('title', 'Unknown')}
URL: {content.get('url', 'Unknown')}
Content: {text}
""")
        
        return "\n".join(context_parts)
    
    def _get_research_system_prompt(self, depth: str) -> str:
        """Get system prompt based on research depth"""
        base_prompt = "You are a research assistant providing comprehensive, accurate analysis based on web search results."
        
        depth_prompts = {
            "quick": f"{base_prompt} Provide concise, focused insights.",
            "standard": f"{base_prompt} Provide thorough analysis with balanced coverage.",
            "deep": f"{base_prompt} Provide in-depth, comprehensive analysis with detailed insights and implications."
        }
        
        return depth_prompts.get(depth, depth_prompts["standard"])
    
    def _format_sources(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Format sources for output"""
        sources = []
        for result in search_results:
            sources.append({
                "title": result.get("title", "Unknown"),
                "url": result.get("url", "Unknown"),
                "source": result.get("source", "Web Search")
            })
        return sources
    
    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()