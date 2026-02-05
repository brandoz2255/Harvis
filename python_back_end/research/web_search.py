"""
Web search functionality using LangChain and multiple search engines
"""

import os
import logging
from typing import List, Dict, Any
from ddgs import DDGS
from langchain.text_splitter import RecursiveCharacterTextSplitter
import requests
from newspaper import Article
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Import YouTube transcript extraction
from research.extract.youtube import extract_youtube

logger = logging.getLogger(__name__)

class WebSearchAgent:
    """
    Web search agent that can search the web and extract content from URLs
    """
    
    def __init__(self, max_results: int = 5, max_workers: int = 3):
        self.max_results = max_results
        self.max_workers = max_workers
        
        # Set a default User-Agent if not set
        if not os.getenv("USER_AGENT"):
            os.environ["USER_AGENT"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        
        # Initialize LangChain text splitter for content processing
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        
    def search_web(self, query: str, num_results: int = None) -> List[Dict[str, Any]]:
        """
        Search the web for a given query using ddgs (modern DuckDuckGo search)
        
        Args:
            query: Search query
            num_results: Number of results to return (default: self.max_results)
            
        Returns:
            List of search results with title, url, and snippet
        """
        max_results = num_results or self.max_results
        
        try:
            # Smart query optimization based on topic analysis
            improved_query = self._optimize_search_query(query)
            
            # Log the actual query being used
            logger.info(f"Original query: '{query}' -> Improved query: '{improved_query}'")
            
            logger.info(f"Starting DDGS search for original query: '{query}', improved query: '{improved_query}' with max_results: {max_results}")
            
            # Use ddgs (modern DuckDuckGo search) as primary method
            with DDGS() as ddgs:
                # Add a small delay to avoid rate limiting
                time.sleep(0.5)
                
                # Try original query first, then improved if no results
                search_results = []
                
                # First try with original query to get basic results
                try:
                    original_results = list(ddgs.text(
                        query, 
                        max_results=max_results * 2,
                        backend="api",  # Force API backend to avoid redirects
                        region="us-en",
                        safesearch="moderate"
                    ))
                    search_results.extend(original_results)
                except Exception as e:
                    logger.warning(f"Original query failed: {e}")
                
                # If we don't have enough results, try improved query
                if len(search_results) < max_results:
                    try:
                        improved_results = list(ddgs.text(
                            improved_query, 
                            max_results=max_results * 2,
                            backend="api",
                            region="us-en", 
                            safesearch="moderate"
                        ))
                        # Add unique results only
                        existing_urls = {r.get('href', '') for r in search_results}
                        for result in improved_results:
                            if result.get('href', '') not in existing_urls:
                                search_results.append(result)
                    except Exception as e:
                        logger.warning(f"Improved query failed: {e}")
            
            logger.info(f"DDGS returned {len(search_results)} raw results")
            
            # Debug: Log first few raw results to see what we're getting
            for i, result in enumerate(search_results[:3]):
                logger.info(f"Raw result {i+1}: Title='{result.get('title', 'N/A')}', URL='{result.get('href', 'N/A')}'")
            
            # Intelligent result filtering and ranking
            scored_results = self._score_and_filter_results(search_results, query)
            
            # Format and limit results
            formatted_results = []
            for result_data in scored_results[:max_results]:
                result = result_data['result']
                formatted_result = {
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "snippet": result.get("body", ""),
                    "source": "DuckDuckGo",
                    "relevance_score": result_data['score']
                }
                
                # Ensure we always have URL in the result
                if not formatted_result["url"] and result.get("link"):
                    formatted_result["url"] = result.get("link")
                formatted_results.append(formatted_result)
                logger.debug(f"Added result (score: {result_data['score']:.2f}): {formatted_result['title'][:50]}...")
            
            logger.info(f"Found {len(formatted_results)} relevant search results for query: '{query}'")
            
            # If we still have no results, lower the threshold even more
            if not formatted_results and scored_results:
                logger.warning("No results passed initial filtering, including lower-scored results")
                for result_data in scored_results[:max_results]:
                    result = result_data['result']
                    formatted_result = {
                        "title": result.get("title", ""),
                        "url": result.get("href", result.get("link", "")),
                        "snippet": result.get("body", ""),
                        "source": "DuckDuckGo",
                        "relevance_score": result_data['score']
                    }
                    formatted_results.append(formatted_result)
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"DDGS search failed for query '{query}': {e}")
            logger.exception("Full traceback:")
            
            # Log more details about the error
            if "rate limit" in str(e).lower():
                logger.error("Rate limited by DuckDuckGo. Consider adding delays between requests.")
            elif "network" in str(e).lower():
                logger.error("Network error occurred during search.")
            
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
            # Quick URL validation first
            response = requests.head(url, timeout=5, allow_redirects=True)
            if response.status_code >= 400:
                logger.warning(f"URL returned {response.status_code}: {url}")
                return {
                    "title": "",
                    "text": "",
                    "authors": [],
                    "publish_date": None,
                    "url": url,
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }
            
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
    
    def _optimize_search_query(self, query: str) -> str:
        """
        Intelligently optimize search queries based on topic detection
        """
        query_lower = query.lower()
        
        # Detect AI/tech topics and add authoritative source preferences
        ai_terms = ['ai', 'artificial intelligence', 'machine learning', 'llm', 'gpt', 'neural network', 'deep learning', 'agentic']
        tech_terms = ['programming', 'python', 'javascript', 'react', 'docker', 'kubernetes', 'api', 'database']
        academic_terms = ['research', 'study', 'analysis', 'paper', 'thesis', 'academic']
        
        # Build optimized query
        if any(term in query_lower for term in ai_terms):
            # For AI topics, target authoritative sources and recent content
            return f'{query} site:arxiv.org OR site:openai.com OR site:huggingface.co OR site:anthropic.com OR site:github.com OR "2024" OR "2023"'
        
        elif any(term in query_lower for term in tech_terms):
            # For tech topics, prioritize documentation and recent tutorials
            return f'{query} site:docs.python.org OR site:github.com OR site:stackoverflow.com OR "documentation" OR "tutorial" 2024 OR 2023'
        
        elif any(term in query_lower for term in academic_terms):
            # For academic content, target scholarly sources
            return f'{query} site:scholar.google.com OR site:arxiv.org OR site:ieee.org OR filetype:pdf'
        
        elif 'project' in query_lower:
            # For projects, target repositories and showcases
            return f'{query} site:github.com OR "open source" OR "repository" OR "demo"'
        
        else:
            # Generic optimization - exclude low-quality sources
            return f'{query} -site:pinterest.com -site:facebook.com -site:twitter.com -"search engine"'
    
    def _score_and_filter_results(self, search_results: List[Dict], original_query: str) -> List[Dict]:
        """
        Score and filter search results based on relevance and quality
        """
        scored_results = []
        query_words = set(original_query.lower().split())
        
        for result in search_results:
            score = self._calculate_relevance_score(result, query_words, original_query)
            
            # Lower threshold to include more results
            if score > 0.15:
                scored_results.append({
                    'result': result,
                    'score': score
                })
        
        # Sort by score (highest first)
        scored_results.sort(key=lambda x: x['score'], reverse=True)
        
        logger.info(f"Scored {len(scored_results)} relevant results from {len(search_results)} total")
        return scored_results
    
    def _calculate_relevance_score(self, result: Dict, query_words: set, _: str) -> float:
        """
        Calculate relevance score for a search result
        """
        score = 0.0
        
        title = result.get('title', '').lower()
        snippet = result.get('body', '').lower()
        url = result.get('href', '').lower()
        
        # Check for search engine homepages (major penalty)
        search_domains = ['google.com', 'bing.com', 'yahoo.com', 'duckduckgo.com', 'search.brave.com']
        if any(domain in url for domain in search_domains):
            return 0.0
        
        # Check for dictionary/translation sites (often irrelevant for technical queries)
        dict_domains = ['leo.org', 'dict.cc', 'linguee.com', 'translate.google.com']
        if any(domain in url for domain in dict_domains):
            return 0.05  # Lower but not zero in case it's relevant
        
        # Keyword matching in title (highest weight)
        title_matches = sum(1 for word in query_words if word in title)
        score += (title_matches / max(len(query_words), 1)) * 0.5
        
        # Keyword matching in snippet
        snippet_matches = sum(1 for word in query_words if word in snippet)
        score += (snippet_matches / max(len(query_words), 1)) * 0.3
        
        # Authority boost for high-quality domains
        authority_domains = [
            'github.com', 'stackoverflow.com', 'docs.python.org', 'arxiv.org',
            'openai.com', 'anthropic.com', 'huggingface.co', 'tensorflow.org',
            'pytorch.org', 'scikit-learn.org', 'nvidia.com', 'microsoft.com/en-us/research',
            'research.google.com', 'ai.facebook.com', 'deepmind.com'
        ]
        
        if any(domain in url for domain in authority_domains):
            score += 0.4
        
        # Recent content boost (if year mentioned in title/snippet)
        if any(year in title + snippet for year in ['2024', '2023']):
            score += 0.2
        
        # Technical content indicators
        tech_indicators = ['tutorial', 'guide', 'documentation', 'api', 'example', 'implementation']
        if any(indicator in title + snippet for indicator in tech_indicators):
            score += 0.15
        
        # Penalize generic or off-topic content (but less aggressively)
        irrelevant_terms = ['definition', 'meaning', 'translate', 'dictionary', 'search engine', 'homepage']
        penalty = sum(0.1 for term in irrelevant_terms if term in title + snippet)
        score = max(0.1, score - penalty)  # Don't go below 0.1
        
        return min(1.0, score)

    def search_youtube_videos(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search for YouTube videos related to the query using DuckDuckGo video search.

        Args:
            query: Search query
            max_results: Maximum number of video results

        Returns:
            List of video results with title, url, thumbnail, channel, duration, views
        """
        try:
            # Add "youtube" to query to bias results toward YouTube
            video_query = f"{query} site:youtube.com"

            logger.info(f"Searching for YouTube videos: '{video_query}'")

            with DDGS() as ddgs:
                time.sleep(0.3)  # Small delay to avoid rate limiting

                # Use video search
                video_results = list(ddgs.videos(
                    video_query,
                    max_results=max_results * 2,  # Get extra to filter
                    region="us-en",
                    safesearch="moderate"
                ))

            logger.info(f"DDGS video search returned {len(video_results)} raw results")

            # Filter for YouTube videos and format results
            formatted_videos = []
            seen_urls = set()

            for video in video_results:
                url = video.get('content', video.get('href', ''))

                # Only include YouTube videos
                if 'youtube.com' not in url and 'youtu.be' not in url:
                    continue

                # Skip duplicates
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Extract video ID for thumbnail
                video_id = self._extract_youtube_video_id(url)
                thumbnail = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg" if video_id else video.get('thumbnail', '')

                formatted_video = {
                    "title": video.get('title', ''),
                    "url": url,
                    "thumbnail": thumbnail,
                    "channel": video.get('uploader', video.get('publisher', '')),
                    "duration": video.get('duration', ''),
                    "views": video.get('views', ''),
                    "description": video.get('description', video.get('body', ''))[:200],
                    "published": video.get('published', ''),
                    "source": "YouTube",
                    "videoId": video_id,  # Include video ID for embedding
                    "transcript": "",  # Will be populated by fetch_video_transcripts
                    "hasTranscript": False  # Will be set by fetch_video_transcripts
                }

                formatted_videos.append(formatted_video)

                if len(formatted_videos) >= max_results:
                    break

            logger.info(f"Found {len(formatted_videos)} YouTube videos for query: '{query}'")
            return formatted_videos

        except Exception as e:
            logger.error(f"YouTube video search failed for query '{query}': {e}")
            logger.exception("Full traceback:")
            return []

    def _extract_youtube_video_id(self, url: str) -> str:
        """Extract YouTube video ID from various URL formats"""
        import re

        # Handle youtu.be short links
        short_match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
        if short_match:
            return short_match.group(1)

        # Handle youtube.com/watch?v= links
        watch_match = re.search(r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})', url)
        if watch_match:
            return watch_match.group(1)

        # Handle youtube.com/embed/ links
        embed_match = re.search(r'youtube\.com/embed/([a-zA-Z0-9_-]{11})', url)
        if embed_match:
            return embed_match.group(1)

        # Handle youtube.com/v/ links
        v_match = re.search(r'youtube\.com/v/([a-zA-Z0-9_-]{11})', url)
        if v_match:
            return v_match.group(1)

        return ''

    def search_with_videos(self, query: str, max_web_results: int = 5, max_video_results: int = 4) -> Dict[str, Any]:
        """
        Combined search for both web results and YouTube videos.

        Args:
            query: Search query
            max_web_results: Maximum number of web results
            max_video_results: Maximum number of video results

        Returns:
            Dictionary with search_results, videos, and extracted_content
        """
        # Run web search and video search
        web_results = self.search_web(query, max_web_results)
        video_results = self.search_youtube_videos(query, max_video_results)

        return {
            "query": query,
            "search_results": web_results,
            "videos": video_results,
            "extracted_content": []
        }

    def search_and_extract_with_videos(self, query: str, extract_content: bool = True,
                                       max_web_results: int = 5, max_video_results: int = 4) -> Dict[str, Any]:
        """
        Search with video support and optional content extraction.

        Args:
            query: Search query
            extract_content: Whether to extract full content from URLs
            max_web_results: Maximum number of web results
            max_video_results: Maximum number of video results

        Returns:
            Dictionary with search results, videos, and extracted content
        """
        # Get web results
        search_results = self.search_web(query, max_web_results)

        # Get video results
        video_results = self.search_youtube_videos(query, max_video_results)

        result = {
            "query": query,
            "search_results": search_results,
            "videos": video_results,
            "extracted_content": []
        }

        if extract_content and search_results:
            # Extract URLs from search results (exclude YouTube)
            urls = [r["url"] for r in search_results
                    if r.get("url") and 'youtube.com' not in r["url"] and 'youtu.be' not in r["url"]]

            # Extract content from URLs
            if urls:
                extracted_content = self.extract_content_from_urls(urls)
                result["extracted_content"] = extracted_content

        return result

    def fetch_video_transcripts(self, videos: List[Dict[str, Any]], max_videos: int = 3, timeout_s: int = 15) -> List[Dict[str, Any]]:
        """
        Fetch transcripts for top N videos in parallel.

        Args:
            videos: List of video results from search_youtube_videos()
            max_videos: Maximum videos to fetch transcripts for (default 3)
            timeout_s: Timeout per transcript fetch in seconds

        Returns:
            Same list of videos with transcript, hasTranscript fields populated
        """
        if not videos:
            return videos

        videos_to_process = videos[:max_videos]
        logger.info(f"Fetching transcripts for {len(videos_to_process)} videos")

        def fetch_single_transcript(video: Dict[str, Any]) -> Dict[str, Any]:
            """Fetch transcript for a single video"""
            url = video.get('url', '')
            video_id = video.get('videoId', '')

            if not url and not video_id:
                return video

            try:
                # Use the existing extract_youtube function
                transcript_url = url if url else f"https://youtube.com/watch?v={video_id}"
                transcript_data = extract_youtube(transcript_url, timeout_s=timeout_s)

                if transcript_data.get('success') and transcript_data.get('text'):
                    # Limit transcript length to avoid context overflow
                    video['transcript'] = transcript_data['text'][:4000]
                    video['hasTranscript'] = True
                    logger.info(f"Successfully fetched transcript for: {video.get('title', 'Unknown')[:50]}")
                else:
                    video['transcript'] = ''
                    video['hasTranscript'] = False
                    logger.debug(f"No transcript available for: {video.get('title', 'Unknown')[:50]}")

            except Exception as e:
                logger.warning(f"Transcript fetch failed for {url}: {e}")
                video['transcript'] = ''
                video['hasTranscript'] = False

            return video

        # Fetch transcripts in parallel with timeout
        with ThreadPoolExecutor(max_workers=min(3, len(videos_to_process))) as executor:
            future_to_video = {
                executor.submit(fetch_single_transcript, video): video
                for video in videos_to_process
            }

            try:
                for future in as_completed(future_to_video, timeout=timeout_s + 5):
                    # Results are already updated in-place in the video dict
                    pass
            except TimeoutError:
                logger.warning("Transcript fetching timed out, returning partial results")

        # Count successful transcripts
        success_count = sum(1 for v in videos_to_process if v.get('hasTranscript', False))
        logger.info(f"Fetched {success_count}/{len(videos_to_process)} video transcripts")

        return videos


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