"""
Main research agent orchestrating the complete research pipeline.

Coordinates query planning, search, extraction, ranking, synthesis, and verification
to produce comprehensive research responses with proper source attribution.
"""

import asyncio
import logging
import time
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

# Import from your modules (will be available once integrated)
# from ..planners.query_planner import QueryPlanner
# from ..search.aggregator import SearchAggregator  
# from ..extract.router import ExtractionRouter
from ..rank.bm25 import BM25Ranker, quick_bm25_rank
from ..rank.rerank import ReRanker, quick_rerank
from ..synth.map_reduce import MapReduceProcessor, quick_map_reduce
from ..synth.verify import QuoteVerifier, quick_verify
from ..synth.render import MarkdownRenderer, ResponseType, create_source_info
from ..llm.ollama_client import OllamaClient
from ..llm.model_policy import get_model_for_task, TaskType
from ..cache.http_cache import get_cache

logger = logging.getLogger(__name__)


class ResearchStage(Enum):
    """Stages of the research pipeline"""
    PLANNING = "planning"
    SEARCH = "search"
    EXTRACTION = "extraction"
    RANKING = "ranking"
    SYNTHESIS = "synthesis"
    VERIFICATION = "verification"
    RENDERING = "rendering"


@dataclass
class ResearchConfig:
    """Configuration for research pipeline"""
    # Query processing
    enable_query_expansion: bool = True
    max_queries: int = 3
    
    # Search parameters
    max_search_results: int = 20
    search_timeout: int = 30
    
    # Content extraction
    max_content_length: int = 50000
    extract_timeout: int = 60
    
    # Ranking and filtering
    min_relevance_score: float = 0.1
    max_chunks_for_synthesis: int = 15
    enable_reranking: bool = True
    rerank_strategy: str = "cross_encoder"
    
    # Synthesis
    max_concurrent_maps: int = 5
    enable_verification: bool = True
    
    # Models
    planning_model: Optional[str] = None
    extraction_model: Optional[str] = None
    synthesis_model: Optional[str] = None
    verification_model: Optional[str] = None
    
    # Output
    include_metadata: bool = True
    max_sources_in_response: int = 10


@dataclass
class StageResult:
    """Result from a single research stage"""
    stage: ResearchStage
    success: bool
    duration: float
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchResult:
    """Complete research result with all stages and metadata"""
    query: str
    success: bool
    response: Optional[str] = None
    stage_results: List[StageResult] = field(default_factory=list)
    total_duration: float = 0.0
    sources_count: int = 0
    confidence_score: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_stage_result(self, stage: ResearchStage) -> Optional[StageResult]:
        """Get result for a specific stage"""
        for result in self.stage_results:
            if result.stage == stage:
                return result
        return None
    
    def was_stage_successful(self, stage: ResearchStage) -> bool:
        """Check if a stage was successful"""
        result = self.get_stage_result(stage)
        return result is not None and result.success


class ResearchAgent:
    """
    Main research agent coordinating the complete pipeline.
    
    Orchestrates all research stages from query planning through final
    response generation with comprehensive error handling and monitoring.
    """
    
    def __init__(self, config: Optional[ResearchConfig] = None):
        self.config = config or ResearchConfig()
        
        # Initialize components
        self.llm_client = OllamaClient()
        self.cache = get_cache()
        self.ranker = BM25Ranker()
        self.reranker = ReRanker(strategy=self.config.rerank_strategy)
        self.map_reduce = MapReduceProcessor(max_concurrent=self.config.max_concurrent_maps)
        self.verifier = QuoteVerifier(enable_llm_verification=self.config.enable_verification)
        self.renderer = MarkdownRenderer(
            include_metadata=self.config.include_metadata,
            max_sources=self.config.max_sources_in_response
        )
        
        # Pipeline stats
        self._pipeline_count = 0
        self._total_duration = 0.0
        self._stage_stats = {}
    
    async def _run_stage(
        self,
        stage: ResearchStage,
        stage_func: callable,
        *args,
        **kwargs
    ) -> StageResult:
        """Run a single pipeline stage with timing and error handling"""
        start_time = time.time()
        logger.info(f"Starting stage: {stage.value}")
        
        try:
            result_data = await stage_func(*args, **kwargs)
            duration = time.time() - start_time
            
            # Update stats
            if stage.value not in self._stage_stats:
                self._stage_stats[stage.value] = {"total_time": 0.0, "count": 0, "errors": 0}
            
            self._stage_stats[stage.value]["total_time"] += duration
            self._stage_stats[stage.value]["count"] += 1
            
            logger.info(f"Completed stage {stage.value} in {duration:.2f}s")
            
            return StageResult(
                stage=stage,
                success=True,
                duration=duration,
                data=result_data
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = str(e)
            
            # Update error stats
            if stage.value in self._stage_stats:
                self._stage_stats[stage.value]["errors"] += 1
            
            logger.error(f"Stage {stage.value} failed after {duration:.2f}s: {error_msg}")
            
            return StageResult(
                stage=stage,
                success=False,
                duration=duration,
                error=error_msg
            )
    
    async def _planning_stage(self, query: str) -> List[str]:
        """Plan research queries (placeholder for your query planner)"""
        # This will integrate with your QueryPlanner once ready
        
        if not self.config.enable_query_expansion:
            return [query]
        
        # Placeholder: simple query expansion
        expanded_queries = [query]
        
        # Add some basic expansions
        if len(query.split()) > 1:
            # Add more specific variations
            expanded_queries.append(f"{query} explanation")
            expanded_queries.append(f"{query} examples")
        
        return expanded_queries[:self.config.max_queries]
    
    async def _search_stage(self, queries: List[str]) -> List[Dict]:
        """Search for content using queries (placeholder for your search aggregator)"""
        # This will integrate with your SearchAggregator once ready
        
        # Placeholder search results
        all_results = []
        for query in queries:
            # Simulate search results
            results = [
                {
                    "url": f"https://example.com/article-{i}",
                    "title": f"Article about {query} - {i}",
                    "snippet": f"This article discusses {query} in detail with examples and explanations.",
                    "relevance_score": 0.8 - (i * 0.1)
                }
                for i in range(min(5, self.config.max_search_results // len(queries)))
            ]
            all_results.extend(results)
        
        return all_results[:self.config.max_search_results]
    
    async def _extraction_stage(self, search_results: List[Dict]) -> List[Dict]:
        """Extract content from search results (placeholder for your extraction router)"""
        # This will integrate with your ExtractionRouter once ready
        
        extracted_content = []
        for result in search_results:
            # Simulate content extraction
            content = f"""
            Title: {result['title']}
            
            This is the extracted content for {result['title']}.
            It contains detailed information about the topic with multiple paragraphs
            of relevant content that would be useful for research synthesis.
            
            The content includes facts, examples, and explanations that directly
            relate to the search query and provide valuable insights.
            
            URL: {result['url']}
            Relevance: {result['relevance_score']:.2f}
            """
            
            extracted_content.append({
                "url": result["url"],
                "title": result["title"],
                "content": content.strip(),
                "length": len(content),
                "extraction_success": True
            })
        
        return extracted_content
    
    async def _ranking_stage(self, query: str, extracted_content: List[Dict]) -> List[Any]:
        """Rank and filter content chunks"""
        # Convert extracted content to DocChunk format 
        from ..core.types import DocChunk
        
        chunks = []
        for i, content in enumerate(extracted_content):
            chunk = DocChunk(
                url=content["url"],
                title=content["title"],
                text=content["content"],
                start=0,
                end=len(content["content"]),
                meta={"extraction_success": str(content.get("extraction_success", True))}
            )
            chunks.append(chunk)
        
        # BM25 ranking
        ranked_chunks = quick_bm25_rank(
            query=query,
            chunks=chunks,
            top_k=self.config.max_chunks_for_synthesis
        )
        
        # Optional reranking
        if self.config.enable_reranking and ranked_chunks:
            reranked_chunks = await quick_rerank(
                query=query,
                ranked_chunks=ranked_chunks,
                strategy=self.config.rerank_strategy,
                top_k=self.config.max_chunks_for_synthesis
            )
            return reranked_chunks
        
        return ranked_chunks
    
    async def _synthesis_stage(self, query: str, ranked_chunks: List[Any]) -> Tuple[Any, Any]:
        """Synthesize ranked chunks into coherent response"""
        model = get_model_for_task(TaskType.SYNTHESIS)
        
        # Run MAP/REDUCE synthesis
        map_results, reduce_result = await quick_map_reduce(
            query=query,
            chunks=ranked_chunks,
            llm_client=self.llm_client,
            model=model,
            max_concurrent=self.config.max_concurrent_maps
        )
        
        return map_results, reduce_result
    
    async def _verification_stage(
        self,
        reduce_result: Any,
        ranked_chunks: List[Any]
    ) -> Optional[Any]:
        """Verify response against source material"""
        if not self.config.enable_verification:
            return None
        
        # Prepare source content for verification
        source_content = {}
        for chunk in ranked_chunks[:10]:  # Limit for performance
            source_content[chunk.chunk.url] = chunk.chunk.text
        
        # Verify response
        verification_result = await quick_verify(
            research_response=reduce_result.synthesis,
            source_content=source_content,
            llm_client=self.llm_client
        )
        
        return verification_result
    
    async def _rendering_stage(
        self,
        query: str,
        reduce_result: Any,
        ranked_chunks: List[Any],
        verification_result: Optional[Any] = None
    ) -> str:
        """Render final response with sources and metadata"""
        
        # Create source info
        sources = []
        for chunk in ranked_chunks[:self.config.max_sources_in_response]:
            source_info = create_source_info(
                url=chunk.chunk.url,
                title=chunk.chunk.title,
                relevance_score=chunk.combined_score
            )
            sources.append(source_info)
        
        # Render response
        research_response = self.renderer.render_standard_response(
            reduce_result=reduce_result,
            query=query,
            sources=sources,
            verification_result=verification_result
        )
        
        return research_response.content
    
    async def research(self, query: str) -> ResearchResult:
        """
        Execute complete research pipeline.
        
        Args:
            query: Research query to investigate
            
        Returns:
            Complete research result with response and metadata
        """
        pipeline_start = time.time()
        self._pipeline_count += 1
        
        logger.info(f"Starting research pipeline for query: '{query}'")
        
        result = ResearchResult(query=query, success=False)
        
        try:
            # Stage 1: Planning
            planning_result = await self._run_stage(
                ResearchStage.PLANNING,
                self._planning_stage,
                query
            )
            result.stage_results.append(planning_result)
            
            if not planning_result.success:
                result.error = "Query planning failed"
                return result
            
            queries = planning_result.data
            
            # Stage 2: Search
            search_result = await self._run_stage(
                ResearchStage.SEARCH,
                self._search_stage,
                queries
            )
            result.stage_results.append(search_result)
            
            if not search_result.success or not search_result.data:
                result.error = "Search failed or no results found"
                return result
            
            search_results = search_result.data
            
            # Stage 3: Extraction
            extraction_result = await self._run_stage(
                ResearchStage.EXTRACTION,
                self._extraction_stage,
                search_results
            )
            result.stage_results.append(extraction_result)
            
            if not extraction_result.success or not extraction_result.data:
                result.error = "Content extraction failed"
                return result
            
            extracted_content = extraction_result.data
            
            # Stage 4: Ranking
            ranking_result = await self._run_stage(
                ResearchStage.RANKING,
                self._ranking_stage,
                query,
                extracted_content
            )
            result.stage_results.append(ranking_result)
            
            if not ranking_result.success or not ranking_result.data:
                result.error = "Content ranking failed"
                return result
            
            ranked_chunks = ranking_result.data
            
            # Stage 5: Synthesis
            synthesis_result = await self._run_stage(
                ResearchStage.SYNTHESIS,
                self._synthesis_stage,
                query,
                ranked_chunks
            )
            result.stage_results.append(synthesis_result)
            
            if not synthesis_result.success:
                result.error = "Content synthesis failed"
                return result
            
            map_results, reduce_result = synthesis_result.data
            
            if not reduce_result.success:
                result.error = "Synthesis reduce phase failed"
                return result
            
            # Stage 6: Verification (optional)
            verification_result = None
            if self.config.enable_verification:
                verify_result = await self._run_stage(
                    ResearchStage.VERIFICATION,
                    self._verification_stage,
                    reduce_result,
                    ranked_chunks
                )
                result.stage_results.append(verify_result)
                
                if verify_result.success:
                    verification_result = verify_result.data
            
            # Stage 7: Rendering
            rendering_result = await self._run_stage(
                ResearchStage.RENDERING,
                self._rendering_stage,
                query,
                reduce_result,
                ranked_chunks,
                verification_result
            )
            result.stage_results.append(rendering_result)
            
            if not rendering_result.success:
                result.error = "Response rendering failed"
                return result
            
            # Success!
            result.success = True
            result.response = rendering_result.data
            result.sources_count = len(ranked_chunks)
            result.confidence_score = reduce_result.confidence_score or 0.5
            
            # Add metadata
            result.metadata = {
                "queries_used": len(queries),
                "search_results": len(search_results),
                "content_extracted": len(extracted_content),
                "chunks_ranked": len(ranked_chunks),
                "map_results": len(map_results) if map_results else 0,
                "verification_enabled": self.config.enable_verification,
                "reranking_enabled": self.config.enable_reranking
            }
            
        except Exception as e:
            result.error = f"Pipeline error: {str(e)}"
            logger.error(f"Research pipeline failed: {str(e)}")
        
        finally:
            result.total_duration = time.time() - pipeline_start
            self._total_duration += result.total_duration
            
            logger.info(f"Research pipeline completed in {result.total_duration:.2f}s (success: {result.success})")
        
        return result
    
    def get_pipeline_stats(self) -> Dict[str, Any]:
        """Get pipeline usage statistics"""
        return {
            "total_pipelines": self._pipeline_count,
            "total_duration": self._total_duration,
            "avg_duration": self._total_duration / max(1, self._pipeline_count),
            "stage_stats": dict(self._stage_stats),
            "config": {
                "max_search_results": self.config.max_search_results,
                "max_chunks_for_synthesis": self.config.max_chunks_for_synthesis,
                "enable_reranking": self.config.enable_reranking,
                "enable_verification": self.config.enable_verification
            }
        }


# Convenience functions
async def quick_research(query: str, **config_overrides) -> str:
    """Quick research with minimal setup"""
    config = ResearchConfig(**config_overrides)
    agent = ResearchAgent(config)
    
    result = await agent.research(query)
    
    if result.success:
        return result.response
    else:
        raise Exception(f"Research failed: {result.error}")


async def research_with_custom_config(
    query: str,
    max_results: int = 15,
    enable_verification: bool = True,
    rerank_strategy: str = "cross_encoder"
) -> ResearchResult:
    """Research with custom configuration"""
    config = ResearchConfig(
        max_search_results=max_results,
        enable_verification=enable_verification,
        rerank_strategy=rerank_strategy
    )
    
    agent = ResearchAgent(config)
    return await agent.research(query)