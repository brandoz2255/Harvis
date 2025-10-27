"""
MAP/REDUCE orchestration for research synthesis.

Implements the MAP phase (process individual chunks) and REDUCE phase
(synthesize across chunks) with proper error handling and parallelization.
"""

import asyncio
import logging
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import time

# Will import from your modules once ready
from ..rank.rerank import RerankedChunk
from .prompts import get_map_prompt, get_reduce_prompt

logger = logging.getLogger(__name__)


@dataclass
class MapResult:
    """Result from processing a single chunk in MAP phase"""
    chunk_id: str
    source_url: str
    content: str  # Extracted key information
    success: bool
    error: Optional[str] = None
    processing_time: float = 0.0
    token_count: Optional[int] = None


@dataclass 
class ReduceResult:
    """Result from synthesizing across chunks in REDUCE phase"""
    synthesis: str  # Combined response
    sources_used: List[str]  # URLs of sources incorporated
    success: bool
    error: Optional[str] = None
    processing_time: float = 0.0
    token_count: Optional[int] = None
    confidence_score: Optional[float] = None


class MapReduceProcessor:
    """
    Orchestrates MAP/REDUCE processing for research synthesis.
    
    Handles parallel processing of chunks, error recovery, and
    progressive synthesis with source tracking.
    """
    
    def __init__(
        self,
        max_concurrent: int = 5,
        timeout_seconds: int = 30,
        min_successful_maps: int = 1,
        enable_fallback: bool = True
    ):
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds
        self.min_successful_maps = min_successful_maps
        self.enable_fallback = enable_fallback
    
    async def _process_single_chunk(
        self, 
        query: str, 
        chunk: RerankedChunk,
        llm_client: Any,  # Will be your LLM client
        model: str = "mistral"
    ) -> MapResult:
        """Process a single chunk in MAP phase"""
        start_time = time.time()
        chunk_id = chunk.chunk.chunk_id
        source_url = chunk.chunk.url
        
        try:
            # Generate MAP prompt
            prompt = get_map_prompt(
                query=query,
                chunk_content=chunk.chunk.content[:4000],  # Limit chunk size
                source_url=source_url
            )
            
            # Call LLM (placeholder - will use your LLM client)
            # response = await llm_client.generate(prompt, model=model)
            
            # Placeholder response for now
            response = f"""## Key Findings
- This chunk from {source_url} contains relevant information about: {query}
- Supporting quote: "{chunk.chunk.content[:200]}..."

## Important Quotes
- "{chunk.chunk.content[:100]}..."

## Supporting Evidence  
- Lexical relevance score: {chunk.lexical_score:.3f}
- Semantic relevance score: {chunk.semantic_score:.3f}

## Limitations
- Chunk is truncated for processing efficiency
"""
            
            processing_time = time.time() - start_time
            
            return MapResult(
                chunk_id=chunk_id,
                source_url=source_url,
                content=response,
                success=True,
                processing_time=processing_time,
                token_count=len(response.split())  # Rough estimate
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"MAP phase failed for chunk {chunk_id}: {str(e)}")
            
            return MapResult(
                chunk_id=chunk_id,
                source_url=source_url,
                content="",
                success=False,
                error=str(e),
                processing_time=processing_time
            )
    
    async def map_phase(
        self,
        query: str,
        chunks: List[RerankedChunk],
        llm_client: Any,
        model: str = "mistral"
    ) -> List[MapResult]:
        """
        Execute MAP phase: process all chunks in parallel.
        
        Args:
            query: Research query
            chunks: Ranked and reranked document chunks
            llm_client: LLM client for processing
            model: Model name to use
            
        Returns:
            List of MapResult objects
        """
        logger.info(f"Starting MAP phase with {len(chunks)} chunks")
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def bounded_process(chunk: RerankedChunk) -> MapResult:
            async with semaphore:
                return await self._process_single_chunk(query, chunk, llm_client, model)
        
        # Process chunks with timeout
        try:
            map_results = await asyncio.wait_for(
                asyncio.gather(*[bounded_process(chunk) for chunk in chunks]),
                timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning(f"MAP phase timed out after {self.timeout_seconds}s")
            # Return partial results if available
            map_results = []
        
        # Filter successful results
        successful_results = [r for r in map_results if r.success]
        failed_results = [r for r in map_results if not r.success]
        
        if failed_results:
            logger.warning(f"MAP phase: {len(failed_results)} chunks failed processing")
        
        if len(successful_results) < self.min_successful_maps:
            logger.error(f"Insufficient successful MAP results: {len(successful_results)} < {self.min_successful_maps}")
        
        logger.info(f"MAP phase completed: {len(successful_results)} successful, {len(failed_results)} failed")
        return map_results
    
    async def reduce_phase(
        self,
        query: str,
        map_results: List[MapResult],
        llm_client: Any,
        model: str = "mistral"
    ) -> ReduceResult:
        """
        Execute REDUCE phase: synthesize MAP results into final response.
        
        Args:
            query: Original research query
            map_results: Results from MAP phase
            llm_client: LLM client for synthesis
            model: Model name to use
            
        Returns:
            ReduceResult with synthesized response
        """
        start_time = time.time()
        
        # Filter successful MAP results
        successful_maps = [r for r in map_results if r.success]
        
        if not successful_maps:
            return ReduceResult(
                synthesis="No successful MAP results to synthesize.",
                sources_used=[],
                success=False,
                error="No successful MAP results available",
                processing_time=time.time() - start_time
            )
        
        logger.info(f"Starting REDUCE phase with {len(successful_maps)} successful MAP results")
        
        try:
            # Prepare MAP results for synthesis
            map_contents = [r.content for r in successful_maps]
            sources_used = list(set(r.source_url for r in successful_maps))
            
            # Generate REDUCE prompt
            prompt = get_reduce_prompt(
                query=query,
                map_results=map_contents,
                num_sources=len(sources_used)
            )
            
            # Call LLM for synthesis (placeholder)
            # synthesis = await llm_client.generate(prompt, model=model)
            
            # Placeholder synthesis
            synthesis = f"""## Summary
Based on analysis of {len(successful_maps)} sources, here's a comprehensive response to: {query}

## Key Findings
The research reveals multiple perspectives on this topic, with the following key insights:
- Finding 1: Supported by {len(sources_used)} sources
- Finding 2: Consistent across multiple sources
- Finding 3: Emerging trend noted in recent sources

## Supporting Evidence
- Statistical data from {sources_used[0] if sources_used else 'multiple sources'}
- Expert opinions cited across {len(sources_used)} sources
- Case studies and examples from various contexts

## Source Perspectives
The sources generally agree on core concepts while offering different perspectives on implementation and implications.

## Limitations & Uncertainties  
Some aspects require additional research, particularly around recent developments and long-term implications.
"""
            
            processing_time = time.time() - start_time
            
            # Calculate confidence based on source count and success rate
            success_rate = len(successful_maps) / len(map_results) if map_results else 0
            source_diversity = min(1.0, len(sources_used) / 5)  # Normalize to max of 5 sources
            confidence_score = (success_rate * 0.6) + (source_diversity * 0.4)
            
            return ReduceResult(
                synthesis=synthesis,
                sources_used=sources_used,
                success=True,
                processing_time=processing_time,
                token_count=len(synthesis.split()),
                confidence_score=confidence_score
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"REDUCE phase failed: {str(e)}")
            
            return ReduceResult(
                synthesis="",
                sources_used=[],
                success=False,
                error=str(e),
                processing_time=processing_time
            )
    
    async def process(
        self,
        query: str,
        chunks: List[RerankedChunk],
        llm_client: Any,
        model: str = "mistral"
    ) -> Tuple[List[MapResult], ReduceResult]:
        """
        Execute full MAP/REDUCE pipeline.
        
        Args:
            query: Research query
            chunks: Ranked document chunks
            llm_client: LLM client
            model: Model name
            
        Returns:
            Tuple of (map_results, reduce_result)
        """
        start_time = time.time()
        logger.info(f"Starting MAP/REDUCE pipeline for query: {query}")
        
        # Execute MAP phase
        map_results = await self.map_phase(query, chunks, llm_client, model)
        
        # Execute REDUCE phase
        reduce_result = await self.reduce_phase(query, map_results, llm_client, model)
        
        total_time = time.time() - start_time
        logger.info(f"MAP/REDUCE pipeline completed in {total_time:.2f}s")
        
        return map_results, reduce_result
    
    def get_statistics(self, map_results: List[MapResult], reduce_result: ReduceResult) -> Dict[str, Any]:
        """Get processing statistics for debugging and monitoring"""
        successful_maps = [r for r in map_results if r.success]
        failed_maps = [r for r in map_results if not r.success]
        
        return {
            "map_phase": {
                "total_chunks": len(map_results),
                "successful": len(successful_maps),
                "failed": len(failed_maps),
                "success_rate": len(successful_maps) / len(map_results) if map_results else 0,
                "avg_processing_time": sum(r.processing_time for r in successful_maps) / len(successful_maps) if successful_maps else 0,
                "total_tokens": sum(r.token_count or 0 for r in successful_maps)
            },
            "reduce_phase": {
                "success": reduce_result.success,
                "processing_time": reduce_result.processing_time,
                "sources_used": len(reduce_result.sources_used),
                "token_count": reduce_result.token_count,
                "confidence_score": reduce_result.confidence_score
            }
        }


# Convenience functions
async def quick_map_reduce(
    query: str,
    chunks: List[RerankedChunk],
    llm_client: Any,
    model: str = "mistral",
    max_concurrent: int = 3
) -> Tuple[List[MapResult], ReduceResult]:
    """Convenience function for quick MAP/REDUCE processing"""
    processor = MapReduceProcessor(max_concurrent=max_concurrent)
    return await processor.process(query, chunks, llm_client, model)