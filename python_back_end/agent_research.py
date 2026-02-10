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
    ollama_url=os.getenv("OLLAMA_URL", "http://ollama:11434"),
    default_model="mistral",
    max_search_results=5,
)

# Initialize the enhanced research agent for advanced features
enhanced_research_agent_instance = get_enhanced_research_agent(
    search_engine="duckduckgo",  # or "tavily" if API key is available
    ollama_url=os.getenv("OLLAMA_URL", "http://ollama:11434"),
    default_model="mistral",
    max_search_results=20,  # Increased for better results
    enable_advanced_features=True,  # Enable advanced pipeline
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
                    enhanced_research_agent_instance.advanced_research(
                        query, model, enable_verification=True
                    )
                )
                # Format for compatibility
                return {
                    "analysis": result,
                    "sources": [],  # Sources embedded in response
                    "model_used": model,
                    "sources_found": "embedded",
                    "advanced": True,
                }
            finally:
                loop.close()
        else:
            # Use backward compatible method
            result = research_agent_instance.research_topic(
                topic=query,
                model=model,
                research_depth="standard",
                include_sources=True,
            )

            # Format response for backwards compatibility
            return {
                "analysis": result["analysis"],
                "sources": result.get("sources", []),
                "model_used": result.get("model_used", model),
                "sources_found": result.get("sources_found", 0),
                "advanced": False,
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
                    "advanced": True,
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


def comparative_research_agent(
    topics: list,
    model: str = "mistral",
    use_advanced: bool = False,
    context: str = None,
):
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
                    enhanced_research_agent_instance.advanced_compare(
                        topics, context, model
                    )
                )
                return {
                    "topics": topics,
                    "analysis": result,
                    "model_used": model,
                    "context": context,
                    "advanced": True,
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
async def async_research_agent(
    query: str, model: str = "mistral", enable_streaming: bool = False
):
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
            enable_verification=True,
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


async def async_comparative_research_agent(
    topics: list, model: str = "mistral", context: str = None
):
    """Async comparative research agent"""
    try:
        return await enhanced_research_agent_instance.advanced_compare(
            topics, context, model
        )
    except Exception as e:
        logger.error(f"Async comparative research error: {e}")
        return f"Comparison failed: {str(e)}"


async def async_research_agent_streaming(
    query: str, model: str = "mistral", use_enhanced: bool = True
):
    """
    Async streaming research agent that yields progress events for real-time UI updates.
    Uses the enhanced research agent for better results (20 sources vs 5).

    Yields dictionaries with progress information:
    - {'type': 'search_query', 'query': 'search term'} - When starting a search
    - {'type': 'search_result', 'title': '...', 'url': '...', 'domain': '...'} - For each result
    - {'type': 'reading', 'domain': '...', 'url': '...'} - When extracting content
    - {'type': 'analysis', 'detail': '...'} - Analysis progress
    - {'type': 'complete', 'result': {...}} - Final result
    - {'type': 'error', 'error': '...'} - On error
    """
    try:
        logger.info(
            f"[Streaming Research] Starting research on: {query} (enhanced={use_enhanced})"
        )

        # Use enhanced agent for better search capabilities (20 results vs 5)
        agent = (
            enhanced_research_agent_instance
            if use_enhanced
            else research_agent_instance
        )
        max_results = 20 if use_enhanced else 5

        # Generate search queries using enhanced agent if available
        if use_enhanced and hasattr(agent, "advanced_agent") and agent.advanced_agent:
            # Use enhanced agent's query generation
            search_queries = [query]  # Start with the main query
            try:
                # Try to generate additional queries via the advanced agent
                additional_queries = await agent.advanced_agent._generate_queries(query)
                if additional_queries:
                    search_queries.extend(additional_queries[:2])  # Add up to 2 more
            except Exception as e:
                logger.warning(
                    f"[Streaming Research] Could not generate additional queries: {e}"
                )
        else:
            # Use async version for non-blocking query generation
            search_queries = (
                await research_agent_instance._async_generate_search_queries(
                    query, model
                )
            )

        logger.info(
            f"[Streaming Research] Generated {len(search_queries)} search queries: {search_queries}"
        )

        all_search_data = {"search_results": [], "extracted_content": [], "videos": []}

        # Perform searches and yield progress
        for search_query in search_queries:
            logger.info(f"[Streaming Research] Searching for: '{search_query}'")
            yield {"type": "search_query", "query": search_query}

            # Search the web using enhanced agent's web search (more results)
            if use_enhanced:
                search_results = agent.web_search.search_web(
                    search_query, num_results=max_results
                )
            else:
                search_results = research_agent_instance.search_agent.search_web(
                    search_query, num_results=max_results
                )
            logger.info(
                f"[Streaming Research] Found {len(search_results)} results for '{search_query}'"
            )

            # Yield each result as it's found
            for result in search_results:
                url = result.get("url") or ""
                title = result.get("title") or "Unknown"
                domain = ""
                try:
                    from urllib.parse import urlparse

                    parsed = urlparse(url)
                    if parsed.hostname:
                        domain = parsed.hostname.replace("www.", "")
                    else:
                        domain = url
                except:
                    domain = url

                yield {
                    "type": "search_result",
                    "title": title,
                    "url": url,
                    "domain": domain,
                }

                all_search_data["search_results"].append(result)

            # Extract content from top results (increased to 5 for enhanced mode)
            extract_limit = 5 if use_enhanced else 3
            for result in search_results[:extract_limit]:
                url = result.get("url", "")
                if url:
                    try:
                        domain = ""
                        try:
                            from urllib.parse import urlparse

                            domain = urlparse(url).hostname.replace("www.", "")
                        except:
                            domain = url

                        logger.info(
                            f"[Streaming Research] Reading content from: {domain}"
                        )
                        yield {"type": "reading", "domain": domain, "url": url}

                        if use_enhanced:
                            content = agent.web_search.extract_content_from_url(url)
                        else:
                            content = research_agent_instance.search_agent.extract_content_from_url(
                                url
                            )

                        if isinstance(content, dict) and content.get("success"):
                            all_search_data["extracted_content"].append(content)
                        elif isinstance(content, str) and content:
                            all_search_data["extracted_content"].append(
                                {"success": True, "content": content, "url": url}
                            )
                    except Exception as e:
                        logger.warning(
                            f"[Streaming Research] Failed to extract from {url}: {e}"
                        )

        # Yield analysis progress
        yield {
            "type": "analysis",
            "detail": "Analyzing search results with enhanced pipeline...",
        }

        # Use enhanced analysis with proper pipeline integration
        if use_enhanced and hasattr(agent, "advanced_agent") and agent.advanced_agent:
            try:
                logger.info(
                    "[Streaming Research] 🚀 USING ENHANCED PIPELINE with BM25 ranking and map/reduce synthesis"
                )

                # Convert search results to format expected by pipeline
                from research.core.types import DocChunk

                # Create DocChunks from extracted content for ranking
                chunks = []
                for content_data in all_search_data.get("extracted_content", []):
                    if isinstance(content_data, dict) and content_data.get("success"):
                        chunk = DocChunk(
                            url=content_data.get("url", ""),
                            title=content_data.get("title", "Unknown"),
                            text=content_data.get("content", "")[:8000],  # Limit size
                            start=0,
                            end=len(content_data.get("content", "")),
                            meta={"source": content_data.get("url", "")},
                        )
                        chunks.append(chunk)

                # If no extracted content, create chunks from search results
                if not chunks:
                    for result in all_search_data.get("search_results", [])[:10]:
                        chunk = DocChunk(
                            url=result.get("url", ""),
                            title=result.get("title", "Unknown"),
                            text=result.get("snippet", ""),
                            start=0,
                            end=len(result.get("snippet", "")),
                            meta={"source": result.get("url", "")},
                        )
                        chunks.append(chunk)

                # Use pipeline's ranking stage
                advanced_agent = agent.advanced_agent
                yield {"type": "analysis", "detail": "Ranking content relevance..."}

                try:
                    ranked_chunks = await advanced_agent._ranking_stage(query, chunks)
                    logger.info(
                        f"[Streaming Research] Ranked {len(ranked_chunks)} chunks"
                    )
                except Exception as e:
                    logger.warning(f"Ranking failed, using all chunks: {e}")
                    ranked_chunks = chunks[:15]  # Use top 15 without ranking

                # Use pipeline's synthesis stage with map/reduce
                yield {
                    "type": "analysis",
                    "detail": "Synthesizing comprehensive answer...",
                }

                try:
                    from research.synth.map_reduce import quick_map_reduce
                    from research.llm.model_policy import TaskType, get_model_for_task
                    from research.llm.ollama_client import OllamaClient

                    # Get synthesis model
                    synthesis_model = get_model_for_task(TaskType.SYNTHESIS)

                    # Run map/reduce synthesis
                    map_results, reduce_result = await quick_map_reduce(
                        query=query,
                        chunks=ranked_chunks[:15],  # Top 15 chunks
                        llm_client=OllamaClient(),
                        model=synthesis_model,
                        max_concurrent=3,
                    )

                    if reduce_result and reduce_result.success:
                        analysis = reduce_result.synthesis
                        logger.info(
                            f"[Streaming Research] ✅ Map/reduce synthesis successful - ANALYSIS GENERATED ({len(analysis)} chars)"
                        )
                        logger.info(
                            f"[Streaming Research] ✅ Using ENHANCED PIPELINE with BM25 ranking - synthesis complete"
                        )
                    else:
                        raise Exception("Map/reduce synthesis failed")

                except Exception as e:
                    logger.warning(
                        f"Map/reduce synthesis failed: {e}, using direct LLM"
                    )
                    # Fallback to direct LLM synthesis
                    synthesis_prompt = f"""Based on the following research findings, provide a comprehensive answer to the question.

Question: {query}

Research Findings:
"""
                    for i, chunk in enumerate(ranked_chunks[:10], 1):
                        synthesis_prompt += (
                            f"\n{i}. {chunk.title}\n{chunk.text[:1000]}\n"
                        )

                    synthesis_prompt += f"\n\nProvide a comprehensive, well-structured answer to: {query}"

                    # Use async version for non-blocking LLM call
                    analysis = await research_agent_instance.async_query_llm(
                        synthesis_prompt,
                        model,
                        "You are a research assistant. Synthesize information from multiple sources into a clear, comprehensive answer. Include specific details and cite sources where possible.",
                    )

                # Format sources for output
                quality_sources = all_search_data.get("search_results", [])
                quality_sources = quality_sources[:15]

                # Compile final result
                result = {
                    "type": "complete",
                    "result": {
                        "topic": query,
                        "analysis": analysis,
                        "research_depth": "enhanced",
                        "model_used": model,
                        "sources_found": len(all_search_data.get("search_results", [])),
                        "sources_used": len(quality_sources),
                        "sources": [
                            {
                                "title": s.get("title", "Unknown"),
                                "url": s.get("url", ""),
                                "snippet": s.get("snippet", "")[:200],
                            }
                            for s in quality_sources[:8]
                        ],
                        "timestamp": research_agent_instance._get_timestamp(),
                    },
                }
                logger.info(
                    f"[Streaming Research] Enhanced pipeline completed. Used {len(quality_sources)} sources"
                )
                yield result
                return
            except Exception as e:
                logger.warning(
                    f"[Streaming Research] Enhanced pipeline failed, falling back: {e}"
                )
                import traceback

                logger.warning(f"Pipeline error traceback: {traceback.format_exc()}")

        # Fallback to async standard analysis (non-blocking for K8s health checks)
        logger.info(
            "[Streaming Research] Using async_research_topic for fallback analysis"
        )
        yield {"type": "analysis", "detail": "Running async research analysis..."}

        try:
            # Use the new fully async research method
            research_result = await research_agent_instance.async_research_topic(
                topic=query,
                model=model,
                research_depth="standard",
                include_sources=True,
            )

            analysis = research_result.get("analysis", "")
            quality_sources = research_result.get("sources", [])
            raw_sources = research_result.get("raw_search_results", [])

            # Compile final result
            result = {
                "type": "complete",
                "result": {
                    "topic": query,
                    "analysis": analysis,
                    "research_depth": "standard",
                    "model_used": model,
                    "sources_found": len(raw_sources),
                    "sources_used": len(quality_sources),
                    "sources": quality_sources[:8],
                    "timestamp": research_agent_instance._get_timestamp(),
                },
            }

            logger.info(
                f"[Streaming Research] Async fallback completed. Used {len(quality_sources)}/{len(raw_sources)} sources"
            )
            yield result

        except Exception as e:
            logger.error(f"[Streaming Research] Async fallback failed: {e}")
            # Last resort: return what we have
            yield {
                "type": "complete",
                "result": {
                    "topic": query,
                    "analysis": f"Research completed but analysis generation failed: {str(e)}",
                    "research_depth": "standard",
                    "model_used": model,
                    "sources_found": len(all_search_data.get("search_results", [])),
                    "sources_used": 0,
                    "sources": [],
                    "timestamp": research_agent_instance._get_timestamp(),
                },
            }

    except Exception as e:
        logger.error(f"[Streaming Research] Error: {e}")
        yield {"type": "error", "error": str(e)}


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
