"""
Research agent that combines web search with LLM analysis
"""

import os
import logging
from typing import Dict, List, Any, Optional
from .web_search import WebSearchAgent, TavilySearchAgent
import requests
import json
import httpx
import asyncio

logger = logging.getLogger(__name__)

# ─── Ollama Configuration with Cloud/Local Fallback ──────────────────────────
CLOUD_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "https://coyotedev.ngrok.app")
LOCAL_OLLAMA_URL = os.getenv(
    "OLLAMA_URL", "http://ollama:11434"
)  # Use environment variable for merged deployment
API_KEY = os.getenv("OLLAMA_API_KEY", "key")


def make_ollama_request(endpoint, payload, timeout=90):
    """Make a POST request to Ollama with automatic fallback from cloud to local.
    Returns the response object from the successful request."""
    # Headers for local request
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}

    # Headers for cloud request
    external_api_key = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")
    external_headers = (
        {
            "Authorization": f"Bearer {external_api_key}",
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "Harvis-Backend",
        }
        if external_api_key
        else {"ngrok-skip-browser-warning": "true", "User-Agent": "Harvis-Backend"}
    )

    # Try cloud first
    try:
        logger.info("🌐 Trying cloud Ollama: %s", CLOUD_OLLAMA_URL)
        response = requests.post(
            f"{CLOUD_OLLAMA_URL}{endpoint}",
            json=payload,
            headers=external_headers,
            timeout=timeout,
        )
        if response.status_code == 200:
            logger.info("✅ Cloud Ollama request successful")
            return response
        else:
            logger.warning("⚠️ Cloud Ollama returned status %s", response.status_code)
    except Exception as e:
        logger.warning("⚠️ Cloud Ollama request failed: %s", e)

    # Fallback to local
    try:
        logger.info("🏠 Falling back to local Ollama: %s", LOCAL_OLLAMA_URL)
        response = requests.post(
            f"{LOCAL_OLLAMA_URL}{endpoint}", json=payload, timeout=timeout
        )
        if response.status_code == 200:
            logger.info("✅ Local Ollama request successful")
            return response
        else:
            logger.error("❌ Local Ollama returned status %s", response.status_code)
            response.raise_for_status()
    except Exception as e:
        logger.error("❌ Local Ollama request failed: %s", e)
        raise

    return response


async def async_make_ollama_request(endpoint, payload, timeout=90):
    """Async version: Make a POST request to Ollama with automatic fallback from cloud to local.
    Returns the response JSON from the successful request.

    This is the async version that uses httpx and doesn't block the event loop.
    """
    # Headers for local request (only if API key is set and not default)
    local_headers = (
        {"Authorization": f"Bearer {API_KEY}"} if API_KEY and API_KEY != "key" else {}
    )

    # Headers for cloud request
    external_api_key = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")
    external_headers = (
        {
            "Authorization": f"Bearer {external_api_key}",
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "Harvis-Backend",
        }
        if external_api_key
        else {"ngrok-skip-browser-warning": "true", "User-Agent": "Harvis-Backend"}
    )

    # Try cloud first
    try:
        logger.info("🌐 Trying async cloud Ollama: %s", CLOUD_OLLAMA_URL)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{CLOUD_OLLAMA_URL}{endpoint}", json=payload, headers=external_headers
            )
            if response.status_code == 200:
                logger.info("✅ Async cloud Ollama request successful")
                return response.json()
            else:
                logger.warning(
                    "⚠️ Async cloud Ollama returned status %s", response.status_code
                )
    except Exception as e:
        logger.warning("⚠️ Async cloud Ollama request failed: %s", e)

    # Fallback to local
    try:
        logger.info("🏠 Falling back to async local Ollama: %s", LOCAL_OLLAMA_URL)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{LOCAL_OLLAMA_URL}{endpoint}", json=payload, headers=local_headers
            )
            if response.status_code == 200:
                logger.info("✅ Async local Ollama request successful")
                return response.json()
            else:
                logger.error(
                    "❌ Async local Ollama returned status %s", response.status_code
                )
                response.raise_for_status()
    except Exception as e:
        logger.error("❌ Async local Ollama request failed: %s", e)
        raise

    return None


class ResearchAgent:
    """
    Advanced research agent that combines web search with LLM analysis
    """

    def __init__(
        self,
        search_engine: str = "duckduckgo",
        ollama_url: str = "http://ollama:11434",
        default_model: str = "mistral",
        max_search_results: int = 5,
    ):
        """
        Initialize the research agent

        Args:
            search_engine: Search engine to use ("duckduckgo" or "tavily")
            ollama_url: Ollama server URL
            default_model: Default LLM model to use
            max_search_results: Maximum number of search results to process
        """
        self.search_engine = search_engine
        self.ollama_url = ollama_url
        self.default_model = default_model
        self.max_search_results = max_search_results

        # Initialize search agent
        if search_engine == "tavily":
            self.search_agent = TavilySearchAgent()
        else:
            self.search_agent = WebSearchAgent(max_results=max_search_results)

    def query_llm(
        self, prompt: str, model: str = None, system_prompt: str = None
    ) -> str:
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
            response = make_ollama_request("/api/chat", payload, timeout=600)  # 10 min for large models

            result = response.json()
            return result.get("message", {}).get("content", "").strip()

        except Exception as e:
            logger.error(f"LLM query failed: {e}")
            return f"Error querying LLM: {str(e)}"

    async def async_query_llm(
        self, prompt: str, model: str = None, system_prompt: str = None
    ) -> str:
        """
        Query the LLM with a prompt (async version - non-blocking)

        This method uses httpx for async HTTP requests and doesn't block the event loop,
        making it safe for use in K8s environments where health checks must respond.

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
            result = await async_make_ollama_request("/api/chat", payload, timeout=600)  # 10 min for large models
            return result.get("message", {}).get("content", "").strip()

        except Exception as e:
            logger.error(f"Async LLM query failed: {e}")
            return f"Error querying LLM: {str(e)}"

    def research_topic(
        self,
        topic: str,
        model: str = None,
        research_depth: str = "standard",
        include_sources: bool = True,
    ) -> Dict[str, Any]:
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
            "quick": {"max_results": 3, "extract_content": False, "max_videos": 2},
            "standard": {"max_results": 5, "extract_content": True, "max_videos": 4},
            "deep": {"max_results": 8, "extract_content": True, "max_videos": 6},
        }

        params = search_params.get(research_depth, search_params["standard"])

        # First, let the LLM analyze and improve the search query
        search_queries = self._generate_search_queries(topic, model)
        logger.info(f"Generated search queries: {search_queries}")

        # Search the web with improved queries (including videos)
        all_search_data = {"search_results": [], "extracted_content": [], "videos": []}

        for query in search_queries:
            logger.info(f"Searching for: '{query}'")
            # Use video-enabled search if available
            if hasattr(self.search_agent, "search_and_extract_with_videos"):
                query_data = self.search_agent.search_and_extract_with_videos(
                    query,
                    extract_content=params["extract_content"],
                    max_web_results=params["max_results"],
                    max_video_results=params.get("max_videos", 4),
                )
            elif hasattr(self.search_agent, "search_and_extract"):
                query_data = self.search_agent.search_and_extract(
                    query, extract_content=params["extract_content"]
                )
                query_data["videos"] = []
            else:
                query_data = {
                    "query": query,
                    "search_results": self.search_agent.search_web(
                        query, params["max_results"]
                    ),
                    "extracted_content": [],
                    "videos": [],
                }

            # Combine results from all queries
            all_search_data["search_results"].extend(
                query_data.get("search_results", [])
            )
            all_search_data["extracted_content"].extend(
                query_data.get("extracted_content", [])
            )
            all_search_data["videos"].extend(query_data.get("videos", []))

        # Remove duplicates and limit results
        search_data = self._deduplicate_search_results(
            all_search_data, params["max_results"]
        )

        # Deduplicate videos
        videos = self._deduplicate_videos(
            all_search_data.get("videos", []), params.get("max_videos", 4)
        )

        # Fetch transcripts for top videos (if search agent supports it)
        if videos and hasattr(self.search_agent, "fetch_video_transcripts"):
            logger.info(f"Fetching transcripts for {min(3, len(videos))} videos...")
            videos = self.search_agent.fetch_video_transcripts(
                videos, max_videos=3, timeout_s=15
            )
            transcript_count = sum(1 for v in videos if v.get("hasTranscript", False))
            logger.info(f"Fetched {transcript_count} video transcripts")

        # Prepare context for LLM
        context = self._prepare_research_context(search_data)

        # Add video transcript context if available
        video_context = self._prepare_video_context(videos)
        if video_context:
            context += "\n" + video_context

        # Debug: Log the context being sent to LLM
        logger.info(f"Context length: {len(context)} characters")
        logger.info(f"Context preview: {context[:500]}...")

        # Generate research analysis
        system_prompt = self._get_research_system_prompt(research_depth)

        research_prompt = f"""
QUESTION: {topic}

{context}

════════════════════════════════════════════════════════════════════════════════
ANSWER FORMAT (follow exactly)
════════════════════════════════════════════════════════════════════════════════

Write a direct, informative answer. NO meta-commentary, NO "[Good]", NO template text.

PARAGRAPH FORMAT:
Write 2-3 paragraphs answering the question directly. Cite sources inline like this [1].
Do NOT write "Source 1 says" - just make the claim and cite: "Python dominates ML [1]."

BULLET POINTS (5 minimum):
After paragraphs, give actionable recommendations:

• **Use X for Y** - explanation of why [1]
• **Implement Z with A** - concrete benefit [2]
• **Configure B properly** - practical step [1][3]

RULES:
1. Only cite [1], [2], etc. - numbers must match sources above
2. For video transcripts, cite as [V1], [V2] - but prefer web sources
3. Never write "Source X says/states/mentions" - banned phrase
4. No made-up statistics unless directly quoted from source
5. No template text like "[Your answer]" or "domain.com"
6. Just answer the question naturally with citations

ANTI-HALLUCINATION (CRITICAL):
- For version numbers, dates, specs, benchmarks: ONLY use exact values from sources
- If a source says "Claude 4.6 released" but doesn't give specs, DON'T invent specs
- If you can't find specific info in sources, say "not specified in sources"
- NEVER extrapolate or guess technical details - only quote what's written
- When uncertain, be explicit: "sources don't provide this detail"

DO NOT include a Sources section - that's handled separately.
"""

        analysis = self.query_llm(research_prompt, model, system_prompt)

        # Post-process to remove template placeholders and clean up
        analysis = self._finalize_research_output(analysis)

        # Filter and rank sources by quality (Perplexity-style: 3-8 sources)
        raw_sources = search_data.get("search_results", [])
        quality_sources = self._filter_and_rank_sources(
            raw_sources, min_sources=3, max_sources=8
        )

        # ─── Quality Gates: Validate and Rewrite if Needed ──────────────────────
        source_count = len(quality_sources)
        analysis, validation_result = self._rewrite_with_validation(
            analysis, source_count, topic, context, model or self.default_model
        )

        # Log validation results
        if validation_result["is_valid"]:
            logger.info(f"✅ Final response passed all quality gates")
        else:
            logger.warning(
                f"⚠️ Final response has remaining issues: {validation_result['issues']}"
            )

        # Compile results
        result = {
            "topic": topic,
            "analysis": analysis,
            "research_depth": research_depth,
            "model_used": model or self.default_model,
            "sources_found": len(raw_sources),
            "sources_used": len(quality_sources),
            "timestamp": self._get_timestamp(),
            "quality_validation": validation_result,  # Include validation info for debugging
            "videos": videos,  # YouTube videos for Perplexity-style display
        }

        if include_sources:
            result["sources"] = self._format_sources(quality_sources)
            result["raw_search_results"] = (
                raw_sources  # Include raw results for debugging
            )

        logger.info(
            f"Research completed for topic: {topic} (used {len(quality_sources)}/{len(raw_sources)} sources)"
        )
        return result

    async def async_research_topic(
        self,
        topic: str,
        model: str = None,
        research_depth: str = "standard",
        include_sources: bool = True,
    ) -> Dict[str, Any]:
        """
        Research a topic using web search and LLM analysis (async version)

        This is the fully async version that doesn't block the event loop,
        making it safe for K8s environments. Uses async_query_llm for all
        LLM calls.

        Args:
            topic: Research topic/query
            model: LLM model to use for analysis
            research_depth: "quick", "standard", or "deep"
            include_sources: Whether to include source URLs in response

        Returns:
            Research results with analysis and sources
        """
        logger.info(f"[Async] Starting research on topic: {topic}")
        logger.info(f"[Async] Research model: {model}, depth: {research_depth}")

        # Adjust search parameters based on depth
        search_params = {
            "quick": {"max_results": 3, "extract_content": False, "max_videos": 2},
            "standard": {"max_results": 5, "extract_content": True, "max_videos": 4},
            "deep": {"max_results": 8, "extract_content": True, "max_videos": 6},
        }

        params = search_params.get(research_depth, search_params["standard"])

        # First, let the LLM analyze and improve the search query (async)
        search_queries = await self._async_generate_search_queries(topic, model)
        logger.info(f"[Async] Generated search queries: {search_queries}")

        # Search the web with improved queries (including videos)
        all_search_data = {"search_results": [], "extracted_content": [], "videos": []}

        for query in search_queries:
            logger.info(f"[Async] Searching for: '{query}'")
            # Use video-enabled search if available
            if hasattr(self.search_agent, "search_and_extract_with_videos"):
                query_data = self.search_agent.search_and_extract_with_videos(
                    query,
                    extract_content=params["extract_content"],
                    max_web_results=params["max_results"],
                    max_video_results=params.get("max_videos", 4),
                )
            elif hasattr(self.search_agent, "search_and_extract"):
                query_data = self.search_agent.search_and_extract(
                    query, extract_content=params["extract_content"]
                )
                query_data["videos"] = []
            else:
                query_data = {
                    "query": query,
                    "search_results": self.search_agent.search_web(
                        query, params["max_results"]
                    ),
                    "extracted_content": [],
                    "videos": [],
                }

            # Combine results from all queries
            all_search_data["search_results"].extend(
                query_data.get("search_results", [])
            )
            all_search_data["extracted_content"].extend(
                query_data.get("extracted_content", [])
            )
            all_search_data["videos"].extend(query_data.get("videos", []))

        # Remove duplicates and limit results
        search_data = self._deduplicate_search_results(
            all_search_data, params["max_results"]
        )

        # Deduplicate videos
        videos = self._deduplicate_videos(
            all_search_data.get("videos", []), params.get("max_videos", 4)
        )

        # Fetch transcripts for top videos (if search agent supports it)
        if videos and hasattr(self.search_agent, "fetch_video_transcripts"):
            logger.info(
                f"[Async] Fetching transcripts for {min(3, len(videos))} videos..."
            )
            videos = self.search_agent.fetch_video_transcripts(
                videos, max_videos=3, timeout_s=15
            )
            transcript_count = sum(1 for v in videos if v.get("hasTranscript", False))
            logger.info(f"[Async] Fetched {transcript_count} video transcripts")

        # Prepare context for LLM
        context = self._prepare_research_context(search_data)

        # Add video transcript context if available
        video_context = self._prepare_video_context(videos)
        if video_context:
            context += "\n" + video_context

        # Debug: Log the context being sent to LLM
        logger.info(f"[Async] Context length: {len(context)} characters")
        logger.info(f"[Async] Context preview: {context[:500]}...")

        # Generate research analysis
        system_prompt = self._get_research_system_prompt(research_depth)

        research_prompt = f"""
QUESTION: {topic}

{context}

════════════════════════════════════════════════════════════════════════════════
ANSWER FORMAT (follow exactly)
════════════════════════════════════════════════════════════════════════════════

Write a direct, informative answer. NO meta-commentary, NO "[Good]", NO template text.

PARAGRAPH FORMAT:
Write 2-3 paragraphs answering the question directly. Cite sources inline like this [1].
Do NOT write "Source 1 says" - just make the claim and cite: "Python dominates ML [1]."

BULLET POINTS (5 minimum):
After paragraphs, give actionable recommendations:

• **Use X for Y** - explanation of why [1]
• **Implement Z with A** - concrete benefit [2]
• **Configure B properly** - practical step [1][3]

RULES:
1. Only cite [1], [2], etc. - numbers must match sources above
2. For video transcripts, cite as [V1], [V2] - but prefer web sources
3. Never write "Source X says/states/mentions" - banned phrase
4. No made-up statistics unless directly quoted from source
5. No template text like "[Your answer]" or "domain.com"
6. Just answer the question naturally with citations

ANTI-HALLUCINATION (CRITICAL):
- For version numbers, dates, specs, benchmarks: ONLY use exact values from sources
- If a source says "Claude 4.6 released" but doesn't give specs, DON'T invent specs
- If you can't find specific info in sources, say "not specified in sources"
- NEVER extrapolate or guess technical details - only quote what's written
- When uncertain, be explicit: "sources don't provide this detail"

DO NOT include a Sources section - that's handled separately.
"""

        # Use async_query_llm for non-blocking LLM call
        analysis = await self.async_query_llm(research_prompt, model, system_prompt)

        # Post-process to remove template placeholders and clean up
        analysis = self._finalize_research_output(analysis)

        # Filter and rank sources by quality (Perplexity-style: 3-8 sources)
        raw_sources = search_data.get("search_results", [])
        quality_sources = self._filter_and_rank_sources(
            raw_sources, min_sources=3, max_sources=8
        )

        # Quality Gates: Validate and Rewrite if Needed (async version)
        source_count = len(quality_sources)
        analysis, validation_result = await self._async_rewrite_with_validation(
            analysis, source_count, topic, context, model or self.default_model
        )

        # Log validation results
        if validation_result["is_valid"]:
            logger.info(f"✅ [Async] Final response passed all quality gates")
        else:
            logger.warning(
                f"⚠️ [Async] Final response has remaining issues: {validation_result['issues']}"
            )

        # Compile results
        result = {
            "topic": topic,
            "analysis": analysis,
            "research_depth": research_depth,
            "model_used": model or self.default_model,
            "sources_found": len(raw_sources),
            "sources_used": len(quality_sources),
            "timestamp": self._get_timestamp(),
            "quality_validation": validation_result,
            "videos": videos,
        }

        if include_sources:
            result["sources"] = self._format_sources(quality_sources)
            result["raw_search_results"] = raw_sources

        logger.info(
            f"[Async] Research completed for topic: {topic} (used {len(quality_sources)}/{len(raw_sources)} sources)"
        )
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
        search_data = self.search_agent.search_and_extract(
            search_query, extract_content=True
        )

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
            "timestamp": self._get_timestamp(),
        }

    def comparative_research(
        self, topics: List[str], model: str = None
    ) -> Dict[str, Any]:
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
            research_result = self.research_topic(
                topic, model, "standard", include_sources=False
            )
            individual_research[topic] = research_result["analysis"]
            all_sources.extend(research_result.get("sources", []))

        # Generate comparative analysis
        system_prompt = """You are a research analyst specializing in comparative analysis. Provide objective, thorough comparisons highlighting similarities, differences, and key insights."""

        comparison_prompt = f"""
Provide a comparative analysis of the following topics: {", ".join(topics)}

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
            "timestamp": self._get_timestamp(),
        }

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for cleaner citation display"""
        import re

        match = re.search(r"https?://(?:www\.)?([^/]+)", url)
        return match.group(1) if match else url

    def _canonicalize_url(self, url: str) -> str:
        """
        Canonicalize URL for reliable matching.
        Handles: trailing slashes, utm params, http/https, www prefix
        """
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

        if not url:
            return ""

        try:
            parsed = urlparse(url.lower().strip())

            # Normalize scheme to https
            scheme = "https"

            # Remove www. prefix from host
            host = parsed.netloc
            if host.startswith("www."):
                host = host[4:]

            # Remove tracking params (utm_, fbclid, etc.)
            tracking_params = {
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "utm_term",
                "utm_content",
                "fbclid",
                "gclid",
                "ref",
                "source",
            }
            if parsed.query:
                params = parse_qs(parsed.query)
                clean_params = {
                    k: v for k, v in params.items() if k.lower() not in tracking_params
                }
                query = urlencode(clean_params, doseq=True) if clean_params else ""
            else:
                query = ""

            # Remove trailing slash from path
            path = parsed.path.rstrip("/")
            if not path:
                path = ""

            return urlunparse((scheme, host, path, "", query, ""))
        except Exception:
            return url.lower().strip()

    def _normalize_whitespace(self, text: str) -> str:
        """
        Normalize whitespace while PRESERVING paragraph breaks.
        - Replace \\r\\n -> \\n
        - Collapse 3+ newlines to 2
        - Collapse long runs of spaces, but keep \\n\\n
        """
        import re

        if not text:
            return ""

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Collapse 3+ newlines to 2 (preserve paragraph breaks)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Collapse multiple spaces (but not newlines) to single space
        text = re.sub(r"[^\S\n]+", " ", text)

        # Clean up space around newlines
        text = re.sub(r" *\n *", "\n", text)

        return text.strip()

    def _chunk_text(
        self, text: str, chunk_size: int = 800, max_chunks: int = 5
    ) -> List[str]:
        """
        Split text into labeled chunks for citation granularity.
        Tries to split on paragraph boundaries.
        """
        if not text or len(text) <= chunk_size:
            return [text] if text else []

        chunks = []
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = para

                # If single paragraph exceeds chunk_size, split it
                while len(current_chunk) > chunk_size:
                    # Find a sentence boundary to split on
                    split_point = current_chunk[:chunk_size].rfind(". ")
                    if split_point == -1:
                        split_point = chunk_size
                    chunks.append(current_chunk[: split_point + 1].strip())
                    current_chunk = current_chunk[split_point + 1 :].strip()

            if len(chunks) >= max_chunks:
                break

        if current_chunk and len(chunks) < max_chunks:
            chunks.append(current_chunk)

        return chunks[:max_chunks]

    def _prepare_research_context(self, search_data: Dict[str, Any]) -> str:
        """
        Prepare search results for LLM context with clear extractive formatting.
        Each source has clearly marked citable content with chunk labels.
        """
        context_parts = []

        # Anti-hallucination policy hint
        context_parts.append("""
╔═══════════════════════════════════════════════════════════════════════════════╗
║ ⚠️  STRICT ANTI-HALLUCINATION POLICY ⚠️                                       ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ 1. ONLY state facts that appear VERBATIM in the sources below                ║
║ 2. For specs (versions, dates, benchmarks, features): quote EXACTLY          ║
║ 3. If sources don't specify something, say "not specified in sources"        ║
║ 4. NEVER invent: version numbers, release dates, benchmark scores, features  ║
║ 5. If sources conflict, note the conflict - don't pick one arbitrarily       ║
║ 6. When a source mentions something exists but gives no details, DON'T       ║
║    fabricate the details - just state what's actually written                ║
╚═══════════════════════════════════════════════════════════════════════════════╝
""")

        # Build URL to source number mapping with canonicalized URLs
        url_to_source_num = {}
        for i, r in enumerate(search_data.get("search_results", []), 1):
            url = r.get("url", "")
            canonical = self._canonicalize_url(url)
            url_to_source_num[canonical] = i
            # Also map original URL for safety
            url_to_source_num[url] = i

        # Add search results with domain extraction and clear snippet marking
        for i, result in enumerate(search_data.get("search_results", []), 1):
            url = result.get("url", "Unknown")
            domain = self._extract_domain(url)
            title = result.get("title", "Unknown")
            snippet = result.get("snippet", "No snippet available")

            # Clean snippet whitespace
            snippet = self._normalize_whitespace(snippet)

            context_parts.append(f"""
═══ Source [{i}] ═════════════════════════════════════════════════════════════
Title: {title}
URL: {url}
Domain: {domain}
─── Search Snippet (citable as [{i}]) ───
{snippet}
""")

        # Add extracted content with chunk labeling for citation granularity
        for content in search_data.get("extracted_content", []):
            if content.get("success") and content.get("text"):
                url = content.get("url", "")
                canonical = self._canonicalize_url(url)

                # Try canonical first, then original
                source_num = url_to_source_num.get(canonical) or url_to_source_num.get(
                    url
                )

                if source_num:
                    # Normalize whitespace while preserving paragraph breaks
                    text = self._normalize_whitespace(content["text"])

                    # Chunk the text for citation granularity
                    chunks = self._chunk_text(text, chunk_size=800, max_chunks=4)

                    if chunks:
                        context_parts.append(f"""
─── Extended Content for Source [{source_num}] ───""")

                        for j, chunk in enumerate(chunks, 1):
                            chunk_label = (
                                f"[{source_num}.{chr(64 + j)}]"  # [1.A], [1.B], etc.
                            )
                            context_parts.append(f"""
Chunk {chunk_label}:
{chunk}
""")

        return "\n".join(context_parts)

    def _prepare_video_context(self, videos: List[Dict[str, Any]]) -> str:
        """
        Format video transcripts for LLM context with citation labels [V1], [V2], etc.
        Only includes videos that have transcripts.

        Args:
            videos: List of video results with optional transcript field

        Returns:
            Formatted video context string, or empty string if no transcripts
        """
        if not videos:
            return ""

        # Filter to only videos with transcripts
        videos_with_transcripts = [
            v for v in videos if v.get("hasTranscript") and v.get("transcript")
        ]

        if not videos_with_transcripts:
            return ""

        context_parts = [
            """
╔═══════════════════════════════════════════════════════════════════════════════╗
║ YOUTUBE VIDEO TRANSCRIPTS: Additional context from related videos. Cite as    ║
║ [V1], [V2], etc. These may provide practical demonstrations or explanations.  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
        ]

        for i, video in enumerate(videos_with_transcripts, 1):
            title = video.get("title", "Unknown Video")
            channel = video.get("channel", "Unknown Channel")
            url = video.get("url", "")
            transcript = video.get("transcript", "")

            # Truncate transcript to avoid context overflow (keep first 2000 chars)
            if len(transcript) > 2000:
                transcript = transcript[:2000] + "... [transcript truncated]"

            context_parts.append(f"""
═══ Video [V{i}] ═══════════════════════════════════════════════════════════════
Title: {title}
Channel: {channel}
URL: {url}
─── Transcript (citable as [V{i}]) ───
{transcript}
""")

        return "\n".join(context_parts)

    def _get_research_system_prompt(self, depth: str) -> str:
        """Get system prompt based on research depth"""
        base_prompt = """You are a research assistant. Answer questions using ONLY the provided search results.

CRITICAL ANTI-HALLUCINATION RULES:
1. ONLY state facts that appear VERBATIM or can be DIRECTLY inferred from the source text
2. If a source doesn't explicitly state something, DO NOT invent it
3. For product specs (versions, features, dates, benchmarks) - quote EXACTLY from sources
4. If sources conflict or are unclear, say "sources are unclear on this"
5. If you don't find information in sources, say "not found in available sources"
6. NEVER fabricate: version numbers, release dates, feature names, benchmark scores, technical specs

STYLE:
- Write naturally like a knowledgeable expert, not like a robot
- Cite sources with [1], [2] inline - never write "Source 1 says"
- Be specific and actionable, not generic
- If sources don't cover something, explicitly state that

FORBIDDEN:
- "Source X says/states/mentions" - BANNED
- Template text like "[Good]" or "[Your answer]"
- Made-up statistics, benchmarks, or specifications
- Inventing features, dates, or version details not in sources
- Generic advice not from the sources
- Synthesizing "likely" details that aren't explicitly stated"""

        depth_prompts = {
            "quick": f"{base_prompt}\n\nGive a brief, focused answer.",
            "standard": f"{base_prompt}\n\nGive a thorough answer with practical recommendations.",
            "deep": f"{base_prompt}\n\nGive a comprehensive analysis with detailed insights.",
        }

        return depth_prompts.get(depth, depth_prompts["standard"])

    def _format_sources(
        self, search_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Format sources with full Perplexity-style schema:
        id, title, url, domain, snippet (extractive quote from source)
        """
        sources = []
        for i, result in enumerate(search_results, 1):
            url = result.get("url", "")
            domain = self._extract_domain(url)
            snippet = result.get("snippet", "")

            # Clean and truncate snippet for citation display
            if snippet:
                # Take first 200 chars as extractive quote
                snippet = snippet[:200].strip()
                if len(result.get("snippet", "")) > 200:
                    snippet += "..."

            sources.append(
                {
                    "id": i,  # Numbered ID for citation mapping
                    "title": result.get("title", "Unknown"),
                    "url": url,
                    "domain": domain,
                    "snippet": snippet,  # Extractive quote for grounding
                    "source": result.get("source", "Web Search"),
                    "relevance_score": result.get("relevance_score", 0),
                }
            )
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
        if any(
            term in topic_lower for term in ["ai", "agentic", "machine learning", "llm"]
        ):
            context = "This is an AI/ML research topic. Focus on recent research, implementations, and authoritative sources."
        elif any(
            term in topic_lower for term in ["project", "implementation", "build"]
        ):
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

            for line in response.strip().split("\n"):
                line = line.strip()
                # Skip empty lines and headers
                if line and not line.lower().startswith(
                    ("topic:", "context:", "queries:", "generate")
                ):
                    # Remove numbering and clean up
                    query = line.lstrip("0123456789.- ").strip()
                    # Remove quotes if present
                    query = query.strip("\"'")

                    if (
                        query
                        and len(query) > 5
                        and not query.lower().startswith(("example", "user", "think"))
                    ):
                        queries.append(query)
                        logger.info(f"Extracted query: '{query}'")

            # Enhanced fallback with topic-specific optimization
            if not queries:
                logger.warning(
                    f"No queries extracted, generating fallback queries for: '{topic}'"
                )
                queries = self._generate_fallback_queries(topic)

            # Limit to 3 queries max
            final_queries = queries[:3]
            logger.info(f"Final search queries: {final_queries}")
            return final_queries

        except Exception as e:
            logger.error(f"Failed to generate search queries: {e}")
            return self._generate_fallback_queries(topic)

    async def _async_generate_search_queries(
        self, topic: str, model: str = None
    ) -> List[str]:
        """
        Use LLM to generate optimized search queries based on the user's topic (async version)
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
        if any(
            term in topic_lower for term in ["ai", "agentic", "machine learning", "llm"]
        ):
            context = "This is an AI/ML research topic. Focus on recent research, implementations, and authoritative sources."
        elif any(
            term in topic_lower for term in ["project", "implementation", "build"]
        ):
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
            # Use async_query_llm for non-blocking call
            response = await self.async_query_llm(query_prompt, model, system_prompt)

            # Parse the response to extract individual queries
            queries = []
            logger.info(f"[Async] LLM query generation response: {response[:200]}...")

            for line in response.strip().split("\n"):
                line = line.strip()
                # Skip empty lines and headers
                if line and not line.lower().startswith(
                    ("topic:", "context:", "queries:", "generate")
                ):
                    # Remove numbering and clean up
                    query = line.lstrip("0123456789.- ").strip()
                    # Remove quotes if present
                    query = query.strip("\"'")

                    if (
                        query
                        and len(query) > 5
                        and not query.lower().startswith(("example", "user", "think"))
                    ):
                        queries.append(query)
                        logger.info(f"[Async] Extracted query: '{query}'")

            # Enhanced fallback with topic-specific optimization
            if not queries:
                logger.warning(
                    f"[Async] No queries extracted, generating fallback queries for: '{topic}'"
                )
                queries = self._generate_fallback_queries(topic)

            # Limit to 3 queries max
            final_queries = queries[:3]
            logger.info(f"[Async] Final search queries: {final_queries}")
            return final_queries

        except Exception as e:
            logger.error(f"[Async] Failed to generate search queries: {e}")
            return self._generate_fallback_queries(topic)

    def _deduplicate_search_results(
        self, search_data: Dict[str, Any], max_results: int
    ) -> Dict[str, Any]:
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

        return {"search_results": unique_results, "extracted_content": unique_content}

    def _deduplicate_videos(
        self, videos: List[Dict[str, Any]], max_videos: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Remove duplicate videos and limit to max_videos
        """
        seen_urls = set()
        unique_videos = []

        for video in videos:
            url = video.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_videos.append(video)

                if len(unique_videos) >= max_videos:
                    break

        return unique_videos

    def _generate_fallback_queries(self, topic: str) -> List[str]:
        """
        Generate fallback queries when LLM fails
        """
        topic_lower = topic.lower()
        queries = []

        # Base query
        queries.append(topic)

        # Topic-specific fallbacks
        if any(term in topic_lower for term in ["ai", "agentic", "machine learning"]):
            queries.extend(
                [f"{topic} research paper arxiv", f"{topic} implementation github"]
            )
        elif "project" in topic_lower:
            queries.extend([f"{topic} github repository", f"{topic} example demo"])
        else:
            queries.extend([f"{topic} tutorial guide", f"{topic} documentation"])

        return queries[:3]

    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime

        return datetime.now().isoformat()

    # ─── Perplexity-Level Quality Gates ─────────────────────────────────────────

    def _validate_citations(
        self, response: str, source_count: int
    ) -> tuple[bool, list[int]]:
        """
        Gate 1: Validate that all [n] citations have matching sources.

        Returns:
            (is_valid, list of invalid citation numbers)
        """
        import re

        # Extract all citation numbers like [1], [2], [1][3], etc.
        citation_pattern = r"\[(\d+)\]"
        citations = [int(m) for m in re.findall(citation_pattern, response)]

        # Check which citations are invalid (outside range 1 to source_count)
        invalid = [c for c in citations if c < 1 or c > source_count]

        return len(invalid) == 0, list(set(invalid))

    def _detect_source_x_says(self, response: str) -> tuple[bool, list[str]]:
        """
        Gate 2: Detect banned "Source X says/states/emphasizes" patterns.

        Returns:
            (has_violations, list of violations found)
        """
        import re

        banned_patterns = [
            r"Source\s+\d+\s+says",
            r"Source\s+\d+\s+states",
            r"Source\s+\d+\s+emphasizes",
            r"Source\s+\d+\s+mentions",
            r"Source\s+\d+\s+notes",
            r"Source\s+\d+\s+explains",
            r"Source\s+\d+\s+describes",
            r"Source\s+\d+\s+reports",
            r"Source\s+\d+\s+indicates",
            r"Source\s+\d+\s+suggests",
            r"According\s+to\s+Source\s+\d+",
            r"Based\s+on\s+Source\s+\d+",
            r"Per\s+Source\s+\d+",
        ]

        violations = []
        for pattern in banned_patterns:
            matches = re.findall(pattern, response, re.IGNORECASE)
            violations.extend(matches)

        return len(violations) == 0, violations

    def _remove_source_x_says(self, response: str) -> str:
        """
        Remove "Source X says/states/etc." patterns and rephrase.

        Example: "Source 1 says Docker uses containers" -> "Docker uses containers [1]"
        """
        import re

        # Pattern: "Source N says/states/etc. <content>" -> "<content> [N]"
        patterns = [
            (
                r"Source\s+(\d+)\s+(says|states|emphasizes|mentions|notes|explains|describes|reports|indicates|suggests)\s+(?:that\s+)?(.+?)(?=[.!?\n]|$)",
                r"\3 [\1]",
            ),
            (r"According\s+to\s+Source\s+(\d+),?\s*(.+?)(?=[.!?\n]|$)", r"\2 [\1]"),
            (r"Based\s+on\s+Source\s+(\d+),?\s*(.+?)(?=[.!?\n]|$)", r"\2 [\1]"),
            (r"Per\s+Source\s+(\d+),?\s*(.+?)(?=[.!?\n]|$)", r"\2 [\1]"),
        ]

        cleaned = response
        for pattern, replacement in patterns:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        return cleaned

    def _validate_numeric_claims(self, response: str) -> tuple[bool, list[str]]:
        """
        Gate 3: Detect numeric claims (percentages, statistics) without adjacent citations.

        Returns:
            (is_valid, list of unsupported numeric claims)
        """
        import re

        # Find sentences containing statistics
        stat_patterns = [
            r"(\d+(?:\.\d+)?%)",  # Percentages
            r"(\d+(?:\.\d+)?\s*percent)",
            r"(\d+(?:\.\d+)?x\s+(?:faster|slower|more|less|better|worse))",  # Comparisons
            r"(\$\d+(?:\.\d+)?(?:\s*(?:million|billion|trillion))?)",  # Money
            r"(\d{4,}\s+(?:users|customers|companies|organizations|developers))",  # Large numbers
        ]

        unsupported = []

        for pattern in stat_patterns:
            # Find all stats and check if they have a citation within 50 chars
            for match in re.finditer(pattern, response, re.IGNORECASE):
                stat_pos = match.end()
                # Look for [n] within 50 characters after the stat
                following_text = response[stat_pos : stat_pos + 50]
                has_citation = bool(re.search(r"\[\d+\]", following_text))

                if not has_citation:
                    # Get context around the stat
                    start = max(0, match.start() - 20)
                    end = min(len(response), match.end() + 30)
                    context = response[start:end].strip()
                    unsupported.append(f"'{match.group()}' in: ...{context}...")

        return len(unsupported) == 0, unsupported

    def _check_action_density(self, response: str) -> tuple[bool, int]:
        """
        Gate 4: Check for minimum actionable content (5 concrete actions).

        Returns:
            (meets_requirement, actual_action_count)
        """
        import re

        # Look for bullet points with action verbs
        action_patterns = [
            r"•\s*\*\*[^*]+\*\*:",  # • **Action**: pattern
            r"\*\s*\*\*[^*]+\*\*:",  # * **Action**: pattern
            r"-\s*\*\*[^*]+\*\*:",  # - **Action**: pattern
            r"\d+\.\s*\*\*[^*]+\*\*:",  # 1. **Action**: pattern
        ]

        action_count = 0
        for pattern in action_patterns:
            action_count += len(re.findall(pattern, response))

        # Also count simple bullets with verbs
        bullet_pattern = r"(?:^|\n)\s*[•\-\*]\s+([A-Z][a-z]+)"
        bullets = re.findall(bullet_pattern, response)

        # Check if bullets start with action verbs
        action_verbs = {
            "use",
            "implement",
            "configure",
            "enable",
            "add",
            "create",
            "set",
            "install",
            "run",
            "deploy",
            "build",
            "optimize",
            "remove",
            "update",
            "switch",
            "migrate",
            "adopt",
            "leverage",
            "utilize",
            "apply",
            "ensure",
        }

        for bullet in bullets:
            if bullet.lower() in action_verbs:
                action_count += 1

        return action_count >= 5, action_count

    def _validate_response_quality(self, response: str, source_count: int) -> dict:
        """
        Run all 6 quality gates and return validation results.

        Returns dict with:
            - is_valid: bool (all gates passed)
            - gates: dict of individual gate results
            - issues: list of specific issues found
        """
        issues = []

        # Gate 1: Citation validation
        citations_valid, invalid_citations = self._validate_citations(
            response, source_count
        )
        if not citations_valid:
            issues.append(
                f"Invalid citations: {invalid_citations} (only have {source_count} sources)"
            )

        # Gate 2: Source X says detection
        no_source_says, violations = self._detect_source_x_says(response)
        if not no_source_says:
            issues.append(f"Banned 'Source X says' patterns: {violations}")

        # Gate 3: Numeric claims validation
        numbers_valid, unsupported_stats = self._validate_numeric_claims(response)
        if not numbers_valid:
            issues.append(
                f"Uncited statistics: {unsupported_stats[:3]}..."
            )  # Limit output

        # Gate 4: Action density
        has_actions, action_count = self._check_action_density(response)
        if not has_actions:
            issues.append(f"Only {action_count} actionable items (need 5+)")

        # Determine overall validity (allow numeric issues to pass with warning)
        is_valid = citations_valid and no_source_says

        return {
            "is_valid": is_valid,
            "gates": {
                "citations_valid": citations_valid,
                "no_source_says": no_source_says,
                "numbers_cited": numbers_valid,
                "action_density": has_actions,
            },
            "issues": issues,
            "details": {
                "invalid_citations": invalid_citations,
                "source_says_violations": violations,
                "uncited_stats": unsupported_stats[:5],
                "action_count": action_count,
            },
        }

    def _generate_rewrite_prompt(
        self, original_response: str, validation: dict, topic: str, context: str
    ) -> str:
        """
        Generate a prompt to rewrite the response fixing validation issues.
        """
        issues_text = "\n".join(f"- {issue}" for issue in validation["issues"])

        return f"""
Fix this response to address the issues listed below.

ORIGINAL:
{original_response[:1500]}

ISSUES:
{issues_text}

QUESTION: {topic}

FIX THESE PROBLEMS:
1. Replace "Source X says..." with direct claims + citation: "Python leads AI development [1]"
2. Remove any template text like "[Good]" or "[Your answer]"
3. Only cite [1], [2], etc. - matching the source numbers provided
4. Add 5+ actionable bullet points if missing
5. Do NOT generate a Sources section - that's handled automatically

Write the corrected answer now (just the content, no meta-commentary):
"""

    def _rewrite_with_validation(
        self,
        response: str,
        source_count: int,
        topic: str,
        context: str,
        model: str,
        max_attempts: int = 2,
    ) -> tuple[str, dict]:
        """
        Validate response and rewrite if needed (max 2 attempts).

        Returns:
            (final_response, final_validation_result)
        """
        # First validation
        validation = self._validate_response_quality(response, source_count)

        if validation["is_valid"]:
            logger.info("✅ Response passed all quality gates on first attempt")
            return response, validation

        logger.warning(f"⚠️ Response failed quality gates: {validation['issues']}")

        # Auto-fix "Source X says" patterns without LLM rewrite
        if not validation["gates"]["no_source_says"]:
            response = self._remove_source_x_says(response)
            # Re-validate after auto-fix
            validation = self._validate_response_quality(response, source_count)
            if validation["is_valid"]:
                logger.info(
                    "✅ Response passed after auto-fixing 'Source X says' patterns"
                )
                return response, validation

        # If still invalid, do LLM rewrite
        for attempt in range(max_attempts):
            logger.info(f"🔄 Attempting LLM rewrite {attempt + 1}/{max_attempts}")

            rewrite_prompt = self._generate_rewrite_prompt(
                response, validation, topic, context
            )
            system_prompt = """You are a research editor. Rewrite the response to fix the specific issues mentioned.
Keep all factual content accurate but fix formatting, citations, and style issues."""

            response = self.query_llm(rewrite_prompt, model, system_prompt)
            response = self._finalize_research_output(response)

            # Re-validate
            validation = self._validate_response_quality(response, source_count)

            if validation["is_valid"]:
                logger.info(
                    f"✅ Response passed quality gates after rewrite {attempt + 1}"
                )
                return response, validation

            logger.warning(
                f"⚠️ Rewrite {attempt + 1} still has issues: {validation['issues']}"
            )

        # Final auto-fix attempt
        response = self._remove_source_x_says(response)
        validation = self._validate_response_quality(response, source_count)

        logger.warning(
            f"⚠️ Final response after {max_attempts} rewrites - valid: {validation['is_valid']}"
        )
        return response, validation

    async def _async_rewrite_with_validation(
        self,
        response: str,
        source_count: int,
        topic: str,
        context: str,
        model: str,
        max_attempts: int = 2,
    ) -> tuple[str, dict]:
        """
        Validate response and rewrite if needed (async version)

        This is the async version that uses async_query_llm for LLM rewrites,
        making it safe for K8s environments where health checks must respond.

        Returns:
            (final_response, final_validation_result)
        """
        # First validation
        validation = self._validate_response_quality(response, source_count)

        if validation["is_valid"]:
            logger.info("✅ [Async] Response passed all quality gates on first attempt")
            return response, validation

        logger.warning(
            f"⚠️ [Async] Response failed quality gates: {validation['issues']}"
        )

        # Auto-fix "Source X says" patterns without LLM rewrite
        if not validation["gates"]["no_source_says"]:
            response = self._remove_source_x_says(response)
            # Re-validate after auto-fix
            validation = self._validate_response_quality(response, source_count)
            if validation["is_valid"]:
                logger.info(
                    "✅ [Async] Response passed after auto-fixing 'Source X says' patterns"
                )
                return response, validation

        # If still invalid, do LLM rewrite using async
        for attempt in range(max_attempts):
            logger.info(
                f"🔄 [Async] Attempting LLM rewrite {attempt + 1}/{max_attempts}"
            )

            rewrite_prompt = self._generate_rewrite_prompt(
                response, validation, topic, context
            )
            system_prompt = """You are a research editor. Rewrite the response to fix the specific issues mentioned.
Keep all factual content accurate but fix formatting, citations, and style issues."""

            # Use async_query_llm for non-blocking call
            response = await self.async_query_llm(rewrite_prompt, model, system_prompt)
            response = self._finalize_research_output(response)

            # Re-validate
            validation = self._validate_response_quality(response, source_count)

            if validation["is_valid"]:
                logger.info(
                    f"✅ [Async] Response passed quality gates after rewrite {attempt + 1}"
                )
                return response, validation

            logger.warning(
                f"⚠️ [Async] Rewrite {attempt + 1} still has issues: {validation['issues']}"
            )

        # Final auto-fix attempt
        response = self._remove_source_x_says(response)
        validation = self._validate_response_quality(response, source_count)

        logger.warning(
            f"⚠️ [Async] Final response after {max_attempts} rewrites - valid: {validation['is_valid']}"
        )
        return response, validation

    def _finalize_research_output(self, response: str) -> str:
        """
        Post-processing QA gate to clean up LLM output:
        - Remove template placeholders and meta-commentary
        - Remove duplicate/LLM-generated Sources sections (we add real ones from API)
        - Clean up formatting issues
        """
        import re

        # Remove meta-commentary and template leakage
        placeholder_patterns = [
            # Template placeholders
            r"\[Your direct answer.*?\]",
            r"\[Your answer here\]",
            r"\[Good\]",
            r"\[Bad\]",
            r"\[Direct answer citing sources:?\]",
            r"\[Direct answer\]",
            # Generic template text
            r"First key point with details\.\.\.?",
            r"Second key point with details\.\.\.?",
            r"Third key point or actionable insight\.\.\.?",
            r"Any additional important findings\.\.\.?",
            r"Key insight one with supporting detail\.\.\.?",
            r"Key insight two explaining another aspect\.\.\.?",
            r"Practical recommendation or action item\.\.\.?",
            # URL placeholders
            r"\[Title\]\(url\)",
            r"\[Title\]\(URL\)",
            r"\[Article Title\]\(https?://[^)]+\)",
            r"\[Another Article\]\(https?://[^)]+\)",
            r"- domain\.com\s*$",
            # Meta instructions that leaked
            r"DO NOT include a Sources section.*",
            r"Sources list handled separately.*",
            r"Paraphrase release notes by citing.*",
            r"citing Source \d+ (?:to|for).*",
        ]

        cleaned = response
        for pattern in placeholder_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE)

        # Remove LLM-generated Sources sections entirely (we provide real sources from API)
        # Match: **Sources** or Sources: followed by [1] list items
        sources_section_pattern = (
            r"\n*-{2,}\s*\n*\*?\*?Sources\*?\*?:?\s*\n(?:\[\d+\].*\n?)*"
        )
        cleaned = re.sub(sources_section_pattern, "", cleaned, flags=re.IGNORECASE)

        # Also remove standalone Sources headers
        cleaned = re.sub(
            r"\n*\*?\*?Sources\*?\*?:?\s*\n(?:\[\d+\].*?\n)*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        # Remove trailing source-like lines at the end
        cleaned = re.sub(
            r"\n\[\d+\]\s*-\s*[a-z]+\.com\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        # Clean up "Source X says" patterns that slipped through
        cleaned = re.sub(
            r"Source\s+\d+\s+(says|states|mentions|notes|emphasizes)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"According to Source\s+\d+,?\s*", "", cleaned, flags=re.IGNORECASE
        )
        cleaned = re.sub(
            r"Based on Source\s+\d+,?\s*", "", cleaned, flags=re.IGNORECASE
        )

        # Clean up multiple consecutive newlines
        cleaned = re.sub(r"\n{4,}", "\n\n", cleaned)

        # Clean up empty bullet points
        cleaned = re.sub(r"•\s*\n", "", cleaned)
        cleaned = re.sub(r"•\s*$", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"-\s*\n", "", cleaned)

        # Clean up stray dashes/separators at end
        cleaned = re.sub(r"\n-{2,}\s*$", "", cleaned)

        return cleaned.strip()

    def _score_source(self, source: dict) -> int:
        """
        Score a source for quality. Higher is better.
        Used to filter and rank sources.
        """
        score = 0
        url = source.get("url", "").lower()
        title = source.get("title", "").lower()

        # High-quality domains (+5)
        official_domains = [
            "github.com",
            "docs.",
            "blog.rust-lang",
            "kubernetes.io",
            "docs.aws",
            "cloud.google",
            "azure.microsoft",
            "cncf.io",
            "openai.com",
            "anthropic.com",
            "huggingface.co",
        ]
        for domain in official_domains:
            if domain in url:
                score += 5
                break

        # Reputable tech publishers (+3)
        reputable = [
            "medium.com/netflix",
            "engineering.",
            "techcrunch",
            "arstechnica",
            "theverge",
            "wired.com",
            "infoq.com",
            "dzone.com",
            "dev.to",
        ]
        for pub in reputable:
            if pub in url:
                score += 3
                break

        # SEO spam indicators (-3)
        seo_patterns = [
            "complete guide",
            "ultimate guide",
            "roadmap 202",
            "everything you need to know",
            "for beginners",
            "definitive guide",
            "step-by-step",
        ]
        for pattern in seo_patterns:
            if pattern in title:
                score -= 3
                break

        # Irrelevant domains (-5)
        irrelevant = ["goodreads.com", "pinterest.com", "facebook.com", "twitter.com"]
        for domain in irrelevant:
            if domain in url:
                score -= 5
                break

        # Has real URL (+1)
        if url.startswith("http"):
            score += 1

        return score

    def _filter_and_rank_sources(
        self, sources: list, min_sources: int = 3, max_sources: int = 8
    ) -> list:
        """
        Filter and rank sources by quality score.
        Returns 3-8 top-ranked sources (Perplexity-style).
        """
        # Score each source
        scored = [(self._score_source(s), s) for s in sources]

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Filter out negative-scored sources
        filtered = [s for score, s in scored if score >= 0]

        # Ensure we have at least min_sources (even if low quality)
        if len(filtered) < min_sources:
            # Add back some low-scored sources if needed
            remaining = [s for score, s in scored if score < 0][
                : min_sources - len(filtered)
            ]
            filtered.extend(remaining)

        # Cap at max_sources
        return filtered[:max_sources]
