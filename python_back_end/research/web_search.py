"""
Web search functionality using LangChain and multiple search engines
"""

import os
import logging
from typing import List, Dict, Any, Optional
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_community.document_loaders import WebBaseLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from bs4 import BeautifulSoup
import requests
from newspaper import Article
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

class WebSearchAgent:
    """
    Web search agent that can search the web and extract content from URLs
    """
    
    def __init__(self, max_results: int = 5, max_workers: int = 3):
        self.max_results = max_results
        self.max_workers = max_workers
        self.search_wrapper = DuckDuckGoSearchAPIWrapper(
            region="us-en",
            time="y",  # Past year
            max_results=max_results
        )
        self.search_tool = DuckDuckGoSearchRun(api_wrapper=self.search_wrapper)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        
    def search_web(self, query: str, num_results: int = None) -> List[Dict[str, Any]]:
        """
        Search the web for a given query
        
        Args:
            query: Search query
            num_results: Number of results to return (default: self.max_results)
            
        Returns:
            List of search results with title, url, and snippet
        """
        try:
            if num_results:
                self.search_wrapper.max_results = num_results
            
            # Use DuckDuckGo search
            results = self.search_wrapper.results(query, max_results=num_results or self.max_results)
            
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("link", ""),
                    "snippet": result.get("snippet", ""),
                    "source": "DuckDuckGo"
                })
            
            logger.info(f"Found {len(formatted_results)} search results for query: {query}")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return []
    
    def extract_content_from_url(self, url: str) -> Dict[str, Any]:
        """
        Extract content from a URL using newspaper3k
        
        Args:
            url: URL to extract content from
            
        Returns:
            Dictionary with title, text, authors, and publish_date
        """
        try:
            article = Article(url)
            article.download()
            article.parse()
            
            return {
                "title": article.title,
                "text": article.text,
                "authors": article.authors,
                "publish_date": article.publish_date,
                "url": url,
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Failed to extract content from {url}: {e}")
            return {
                "title": "",
                "text": "",
                "authors": [],
                "publish_date": None,
                "url": url,
                "success": False,
                "error": str(e)
            }
    
    def extract_content_from_urls(self, urls: List[str]) -> List[Dict[str, Any]]:
        """
        Extract content from multiple URLs in parallel
        
        Args:
            urls: List of URLs to extract content from
            
        Returns:
            List of content dictionaries
        """
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = list(executor.map(self.extract_content_from_url, urls))
        
        successful_results = [r for r in results if r.get("success", False)]
        logger.info(f"Successfully extracted content from {len(successful_results)} out of {len(urls)} URLs")
        
        return results
    
    def search_and_extract(self, query: str, extract_content: bool = True) -> Dict[str, Any]:
        """
        Search the web and optionally extract content from the results
        
        Args:
            query: Search query
            extract_content: Whether to extract full content from URLs
            
        Returns:
            Dictionary with search results and extracted content
        """
        # Search the web
        search_results = self.search_web(query)
        
        result = {
            "query": query,
            "search_results": search_results,
            "extracted_content": []
        }
        
        if extract_content and search_results:
            # Extract URLs from search results
            urls = [result["url"] for result in search_results if result.get("url")]
            
            # Extract content from URLs
            extracted_content = self.extract_content_from_urls(urls)
            result["extracted_content"] = extracted_content
        
        return result
    
    def get_summarized_content(self, query: str, max_content_length: int = 3000) -> str:
        """
        Get summarized content from web search results
        
        Args:
            query: Search query
            max_content_length: Maximum length of combined content
            
        Returns:
            Summarized content string
        """
        search_data = self.search_and_extract(query, extract_content=True)
        
        # Combine snippets and extracted content
        combined_content = []
        
        # Add search result snippets
        for result in search_data["search_results"]:
            if result.get("snippet"):
                combined_content.append(f"**{result['title']}**\n{result['snippet']}\nSource: {result['url']}\n")
        
        # Add extracted content (truncated)
        for content in search_data["extracted_content"]:
            if content.get("success") and content.get("text"):
                text = content["text"][:1000]  # Truncate long content
                combined_content.append(f"**{content['title']}**\n{text}...\nSource: {content['url']}\n")
        
        # Combine and truncate to max length
        full_content = "\n---\n".join(combined_content)
        if len(full_content) > max_content_length:
            full_content = full_content[:max_content_length] + "...\n\n[Content truncated for length]"
        
        return full_content

class TavilySearchAgent:
    """
    Alternative search agent using Tavily API for more comprehensive results
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.base_url = "https://api.tavily.com"
        
    def search_web(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search using Tavily API
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            List of search results
        """
        if not self.api_key:
            logger.warning("Tavily API key not found, falling back to DuckDuckGo")
            fallback_agent = WebSearchAgent(max_results=max_results)
            return fallback_agent.search_web(query, max_results)
        
        try:
            import tavily
            
            client = tavily.TavilyClient(api_key=self.api_key)
            response = client.search(query, max_results=max_results)
            
            results = []
            for result in response.get("results", []):
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("content", ""),
                    "source": "Tavily"
                })
            
            logger.info(f"Found {len(results)} Tavily search results for query: {query}")
            return results
            
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            # Fallback to DuckDuckGo
            fallback_agent = WebSearchAgent(max_results=max_results)
            return fallback_agent.search_web(query, max_results)