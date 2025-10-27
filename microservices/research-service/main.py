"""
Research Service - Web Search, Research Agents, Fact-Checking
Handles all research-related functionality
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import logging
from typing import List, Dict, Optional, Union
from datetime import datetime

# Import research modules
from research.pipeline.research_agent import async_research_agent, research_agent
from research.pipeline.fact_check import fact_check_agent, async_fact_check_agent
from research.pipeline.compare import comparative_research_agent, async_comparative_research_agent
from research.search.aggregator import WebSearchAgent

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI App
app = FastAPI(
    title="Harvis Research Service",
    description="Web Search and Research Agents",
    version="1.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models
class ResearchChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    model: str = "mistral"
    enableWebSearch: bool = True

class AdvancedResearchRequest(BaseModel):
    message: str
    model: str = "mistral"
    max_sources: int = 10
    history: List[Dict[str, str]] = []
    use_advanced: bool = Field(default=False, description="Use advanced research pipeline")
    enable_streaming: bool = Field(default=False, description="Enable streaming progress")
    enable_verification: bool = Field(default=True, description="Enable response verification")

class FactCheckRequest(BaseModel):
    claim: str
    model: str = "mistral"

class ComparativeResearchRequest(BaseModel):
    topics: List[str]
    model: str = "mistral"

class WebSearchRequest(BaseModel):
    query: str
    max_results: int = 5
    extract_content: bool = False

# Health Check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "research-service"}

# Research Chat Endpoint
@app.post("/api/research-chat", tags=["research"])
async def research_chat(req: Union[ResearchChatRequest, AdvancedResearchRequest]):
    """
    Enhanced research chat endpoint with advanced pipeline support
    """
    try:
        if not req.message:
            raise HTTPException(status_code=400, detail="Message is required")

        # Check if using advanced features
        use_advanced = getattr(req, 'use_advanced', False)
        enable_streaming = getattr(req, 'enable_streaming', False)
        enable_verification = getattr(req, 'enable_verification', True)

        logger.info(f"🔍 Starting research (advanced: {use_advanced})")

        # Call the appropriate research agent
        if use_advanced:
            # Use advanced async research agent
            logger.info("Using advanced async research agent")
            max_sources = getattr(req, 'max_sources', 10)
            result = await async_research_agent(
                query=req.message,
                model=req.model,
                max_sources=max_sources,
                enable_verification=enable_verification
            )
        else:
            # Use standard research agent
            logger.info("Using standard research agent")
            result = research_agent(
                query=req.message,
                model=req.model,
                history=req.history,
                enable_web_search=getattr(req, 'enableWebSearch', True)
            )

        return {
            "response": result,
            "model_used": req.model,
            "advanced": use_advanced,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.exception("Research chat endpoint crashed")
        raise HTTPException(status_code=500, detail=str(e))

# Fact Check Endpoint
@app.post("/api/fact-check", tags=["research"])
async def fact_check(req: FactCheckRequest):
    """
    Fact-check a claim using web search and analysis
    """
    try:
        logger.info(f"🔍 Fact-checking: {req.claim}")
        result = fact_check_agent(req.claim, req.model)
        return {
            "claim": req.claim,
            "analysis": result,
            "model_used": req.model,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.exception("Fact-check endpoint crashed")
        raise HTTPException(status_code=500, detail=str(e))

# Advanced Fact Check Endpoint
@app.post("/api/research/advanced-fact-check", tags=["research"])
async def advanced_fact_check(claim: str, model: str = "mistral"):
    """
    Advanced fact-checking with authority scoring and evidence analysis
    """
    try:
        logger.info(f"🔍 Advanced fact-check for: {claim}")
        result = await async_fact_check_agent(claim, model)
        return {
            "claim": claim,
            "analysis": result,
            "model_used": model,
            "advanced": True,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Advanced fact-check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Comparative Research Endpoint
@app.post("/api/comparative-research", tags=["research"])
async def comparative_research(req: ComparativeResearchRequest):
    """
    Compare multiple topics using web research
    """
    try:
        if len(req.topics) < 2:
            raise HTTPException(status_code=400, detail="At least 2 topics are required for comparison")

        logger.info(f"🔄 Comparing topics: {req.topics}")
        result = comparative_research_agent(req.topics, req.model)
        return {
            "topics": req.topics,
            "analysis": result,
            "model_used": req.model,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.exception("Comparative research endpoint crashed")
        raise HTTPException(status_code=500, detail=str(e))

# Advanced Comparative Research Endpoint
@app.post("/api/research/advanced-compare", tags=["research"])
async def advanced_compare(topics: List[str], context: str = None, model: str = "mistral"):
    """
    Advanced comparison with structured analysis
    """
    try:
        if len(topics) < 2:
            raise HTTPException(status_code=400, detail="At least 2 topics required for comparison")

        logger.info(f"🔄 Advanced comparison of: {topics}")
        result = await async_comparative_research_agent(topics, model, context)
        return {
            "topics": topics,
            "context": context,
            "analysis": result,
            "model_used": model,
            "advanced": True,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Advanced comparison error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Web Search Endpoint
@app.post("/api/web-search", tags=["research"])
async def web_search(req: WebSearchRequest):
    """
    Perform web search using LangChain search agents
    """
    try:
        logger.info(f"Web search request: query='{req.query}', max_results={req.max_results}, extract_content={req.extract_content}")

        # Initialize the web search agent
        search_agent = WebSearchAgent(max_results=req.max_results)

        if req.extract_content:
            # Search and extract content from URLs
            logger.info("Performing search with content extraction...")
            result = search_agent.search_and_extract(req.query, extract_content=True)
        else:
            # Just search without content extraction
            logger.info("Performing basic search...")
            search_results = search_agent.search_web(req.query, req.max_results)
            result = {
                "query": req.query,
                "search_results": search_results,
                "extracted_content": []
            }

        logger.info(f"Search completed: found {len(result.get('search_results', []))} results")
        return result

    except Exception as e:
        logger.exception("Web search endpoint crashed")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
