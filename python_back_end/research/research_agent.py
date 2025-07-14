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
        logger.info(f"Research model: {model}, depth: {research_depth}")
        
        # Adjust search parameters based on depth
        search_params = {
            "quick": {"max_results": 3, "extract_content": False},
            "standard": {"max_results": 5, "extract_content": True},
            "deep": {"max_results": 8, "extract_content": True}
        }
        
        params = search_params.get(research_depth, search_params["standard"])
        
        # First, let the LLM analyze and improve the search query
        search_queries = self._generate_search_queries(topic, model)
        logger.info(f"Generated search queries: {search_queries}")
        
        # Search the web with improved queries
        all_search_data = {"search_results": [], "extracted_content": []}
        
        for query in search_queries:
            logger.info(f"Searching for: '{query}'")
            if hasattr(self.search_agent, 'search_and_extract'):
                query_data = self.search_agent.search_and_extract(
                    query, 
                    extract_content=params["extract_content"]
                )
            else:
                query_data = {
                    "query": query,
                    "search_results": self.search_agent.search_web(query, params["max_results"]),
                    "extracted_content": []
                }
            
            # Combine results from all queries
            all_search_data["search_results"].extend(query_data.get("search_results", []))
            all_search_data["extracted_content"].extend(query_data.get("extracted_content", []))
        
        # Remove duplicates and limit results
        search_data = self._deduplicate_search_results(all_search_data, params["max_results"])
        
        # Prepare context for LLM
        context = self._prepare_research_context(search_data)
        
        # Debug: Log the context being sent to LLM
        logger.info(f"Context length: {len(context)} characters")
        logger.info(f"Context preview: {context[:500]}...")
        
        # Generate research analysis
        system_prompt = self._get_research_system_prompt(research_depth)
        
        research_prompt = f"""
You are analyzing search results for the user's question: "{topic}"

SEARCH RESULTS:
{context}

Your task:
1. First, assess if these search results actually address what the user is asking about "{topic}"
2. If the results are relevant, provide a comprehensive analysis WITH SPECIFIC SOURCE CITATIONS
3. If the results are largely irrelevant, clearly state this and explain what type of information would better answer their question

IMPORTANT: When referencing information, ALWAYS cite the specific source URL.

Provide your analysis in this format:

RELEVANCE ASSESSMENT:
[Are these results relevant to the user's question? If not, explain why and what would be more relevant]

ANALYSIS:
[Only if results are relevant - provide detailed analysis of the findings with citations like "According to [URL]: ..."]

SOURCES CITED:
[List all URLs you referenced in your analysis]

RECOMMENDATIONS:
[What the user should know based on the results, or what better searches might be needed]

Focus on being helpful and honest about whether the search results actually answer their question.
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
            result["raw_search_results"] = search_data.get("search_results", [])  # Include raw results for debugging
        
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
        base_prompt = """You are a research assistant that analyzes web search results to provide specific, accurate information about the requested topic. 

CRITICAL RULES:
- You must ONLY use information from the provided search results
- Do NOT provide general knowledge or generic information about search engines
- Focus specifically on the topic being researched
- Cite specific sources when making claims
- If the search results don't contain relevant information, say so explicitly"""
        
        depth_prompts = {
            "quick": f"{base_prompt} Provide concise, focused insights from the search results.",
            "standard": f"{base_prompt} Provide thorough analysis with balanced coverage of the search results.",
            "deep": f"{base_prompt} Provide in-depth, comprehensive analysis with detailed insights from the search results."
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
    
    def _generate_search_queries(self, topic: str, model: str = None) -> List[str]:
        """
        Use LLM to generate optimized search queries based on the user's topic
        """
        system_prompt = """You are an expert search strategist. Generate targeted search queries that will find the most relevant, authoritative information.

Focus Areas:
- AI/ML topics: Target research papers, official docs, and authoritative sources
- Technical topics: Target documentation, tutorials, and recent implementations
- Projects: Target repositories, demos, and case studies
- General topics: Target educational and authoritative sources

Output Format: Provide ONLY the search queries, one per line, no explanations."""

        # Analyze topic to determine search strategy
        topic_lower = topic.lower()
        if any(term in topic_lower for term in ['ai', 'agentic', 'machine learning', 'llm']):
            context = "This is an AI/ML research topic. Focus on recent research, implementations, and authoritative sources."
        elif any(term in topic_lower for term in ['project', 'implementation', 'build']):
            context = "This is about finding projects or implementations. Focus on repositories and working examples."
        else:
            context = "This is a general research topic. Focus on comprehensive, authoritative information."
        
        query_prompt = f"""
Topic: "{topic}"
Context: {context}

Generate 3 specific search queries that will find the most relevant information. Focus on:
1. The main concept/technology
2. Practical applications or examples
3. Recent developments or implementations

Queries:"""

        try:
            response = self.query_llm(query_prompt, model, system_prompt)
            
            # Parse the response to extract individual queries
            queries = []
            logger.info(f"LLM query generation response: {response[:200]}...")
            
            for line in response.strip().split('\n'):
                line = line.strip()
                # Skip empty lines and headers
                if line and not line.lower().startswith(('topic:', 'context:', 'queries:', 'generate')):
                    # Remove numbering and clean up
                    query = line.lstrip('0123456789.- ').strip()
                    # Remove quotes if present
                    query = query.strip('"\'')
                    
                    if query and len(query) > 5 and not query.lower().startswith(('example', 'user', 'think')):
                        queries.append(query)
                        logger.info(f"Extracted query: '{query}'")
            
            # Enhanced fallback with topic-specific optimization
            if not queries:
                logger.warning(f"No queries extracted, generating fallback queries for: '{topic}'")
                queries = self._generate_fallback_queries(topic)
            
            # Limit to 3 queries max
            final_queries = queries[:3]
            logger.info(f"Final search queries: {final_queries}")
            return final_queries
            
        except Exception as e:
            logger.error(f"Failed to generate search queries: {e}")
            return self._generate_fallback_queries(topic)
    
    def _deduplicate_search_results(self, search_data: Dict[str, Any], max_results: int) -> Dict[str, Any]:
        """
        Remove duplicate search results and limit to max_results
        """
        seen_urls = set()
        unique_results = []
        
        for result in search_data.get("search_results", []):
            url = result.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
                
                if len(unique_results) >= max_results:
                    break
        
        # Do the same for extracted content
        seen_content_urls = set()
        unique_content = []
        
        for content in search_data.get("extracted_content", []):
            url = content.get("url", "")
            if url and url not in seen_content_urls:
                seen_content_urls.add(url)
                unique_content.append(content)
        
        return {
            "search_results": unique_results,
            "extracted_content": unique_content
        }

    def _generate_fallback_queries(self, topic: str) -> List[str]:
        """
        Generate fallback queries when LLM fails
        """
        topic_lower = topic.lower()
        queries = []
        
        # Base query
        queries.append(topic)
        
        # Topic-specific fallbacks
        if any(term in topic_lower for term in ['ai', 'agentic', 'machine learning']):
            queries.extend([
                f"{topic} research paper arxiv",
                f"{topic} implementation github"
            ])
        elif 'project' in topic_lower:
            queries.extend([
                f"{topic} github repository",
                f"{topic} example demo"
            ])
        else:
            queries.extend([
                f"{topic} tutorial guide",
                f"{topic} documentation"
            ])
        
        return queries[:3]
    
    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()