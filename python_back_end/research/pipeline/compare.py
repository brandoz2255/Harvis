"""
Comparative analysis pipeline for multi-topic research.

Provides structured comparison capabilities with side-by-side analysis,
similarity/difference identification, and balanced perspective synthesis.
"""

import asyncio
import logging
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from .research_agent import ResearchAgent, ResearchConfig, ResearchResult
from ..synth.prompts import get_comparative_reduce_prompt
from ..synth.render import ResponseType
from ..llm.model_policy import get_model_for_task, TaskType

logger = logging.getLogger(__name__)


class ComparisonDimension(Enum):
    """Dimensions for comparative analysis"""
    DEFINITION = "definition"
    FEATURES = "features"
    ADVANTAGES = "advantages"
    DISADVANTAGES = "disadvantages"
    USE_CASES = "use_cases"
    PERFORMANCE = "performance"
    COST = "cost"
    POPULARITY = "popularity"
    HISTORY = "history"
    FUTURE_OUTLOOK = "future_outlook"


@dataclass
class TopicAnalysis:
    """Analysis result for a single topic"""
    topic: str
    research_result: ResearchResult
    key_points: Dict[ComparisonDimension, str]
    confidence: float
    source_count: int
    processing_time: float


@dataclass
class ComparisonResult:
    """Result of comparative analysis between topics"""
    topics: List[str]
    topic_analyses: List[TopicAnalysis]
    comparison_matrix: Dict[ComparisonDimension, Dict[str, str]]
    similarities: List[str]
    differences: List[str]
    recommendations: List[str]
    overall_confidence: float
    response: str
    processing_time: float
    metadata: Dict[str, Any]


class ComparativeAnalyzer:
    """
    Specialized analyzer for comparative research between multiple topics.
    
    Performs parallel research on each topic then synthesizes structured
    comparisons highlighting similarities, differences, and trade-offs.
    """
    
    def __init__(self, config: Optional[ResearchConfig] = None):
        # Configure for comparative analysis
        if config is None:
            config = ResearchConfig()
        
        # Optimize for comparison
        config.max_search_results = 15  # Balanced for multiple topics
        config.enable_verification = True
        config.max_chunks_for_synthesis = 12  # Efficient synthesis
        
        self.config = config
        self.research_agent = ResearchAgent(config)
        
        # Comparison-specific settings
        self.default_dimensions = [
            ComparisonDimension.DEFINITION,
            ComparisonDimension.FEATURES,
            ComparisonDimension.ADVANTAGES,
            ComparisonDimension.DISADVANTAGES,
            ComparisonDimension.USE_CASES
        ]
    
    async def _analyze_single_topic(
        self,
        topic: str,
        comparison_context: Optional[str] = None
    ) -> TopicAnalysis:
        """Analyze a single topic in comparative context"""
        import time
        start_time = time.time()
        
        # Enhance query with comparison context if provided
        query = topic
        if comparison_context:
            query = f"{topic} {comparison_context}"
        
        logger.info(f"Analyzing topic: {topic}")
        
        # Perform research
        research_result = await self.research_agent.research(query)
        
        # Extract key points (placeholder - would use structured extraction)
        key_points = {}
        if research_result.success:
            # Simple extraction based on response content
            response = research_result.response or ""
            
            # Extract information for each dimension
            for dimension in self.default_dimensions:
                # Placeholder extraction - would use more sophisticated methods
                key_points[dimension] = f"Key {dimension.value} for {topic}"
        
        processing_time = time.time() - start_time
        
        return TopicAnalysis(
            topic=topic,
            research_result=research_result,
            key_points=key_points,
            confidence=research_result.confidence_score,
            source_count=research_result.sources_count,
            processing_time=processing_time
        )
    
    def _extract_comparison_dimensions(
        self,
        topic_analyses: List[TopicAnalysis]
    ) -> Dict[ComparisonDimension, Dict[str, str]]:
        """Extract structured comparison matrix"""
        comparison_matrix = {}
        
        for dimension in self.default_dimensions:
            dimension_data = {}
            
            for analysis in topic_analyses:
                if dimension in analysis.key_points:
                    dimension_data[analysis.topic] = analysis.key_points[dimension]
                else:
                    dimension_data[analysis.topic] = f"No specific information about {dimension.value}"
            
            comparison_matrix[dimension] = dimension_data
        
        return comparison_matrix
    
    def _identify_similarities_differences(
        self,
        topic_analyses: List[TopicAnalysis],
        comparison_matrix: Dict[ComparisonDimension, Dict[str, str]]
    ) -> Tuple[List[str], List[str]]:
        """Identify similarities and differences between topics"""
        
        similarities = []
        differences = []
        
        # Analyze each dimension
        for dimension, data in comparison_matrix.items():
            topics = list(data.keys())
            values = list(data.values())
            
            # Simple similarity/difference detection (placeholder)
            # In practice, would use semantic similarity
            
            # Check for common patterns
            if len(set(values)) == 1:
                similarities.append(f"All topics share similar {dimension.value}")
            elif len(set(values)) == len(values):
                differences.append(f"Topics differ significantly in {dimension.value}")
            else:
                # Mixed - some similar, some different
                similarities.append(f"Some overlap in {dimension.value} across topics")
        
        return similarities, differences
    
    def _generate_recommendations(
        self,
        topic_analyses: List[TopicAnalysis],
        similarities: List[str],
        differences: List[str]
    ) -> List[str]:
        """Generate recommendations based on comparison"""
        recommendations = []
        
        # Based on confidence levels
        high_confidence_topics = [
            analysis.topic for analysis in topic_analyses 
            if analysis.confidence > 0.7
        ]
        
        if high_confidence_topics:
            recommendations.append(
                f"Highest confidence analysis available for: {', '.join(high_confidence_topics)}"
            )
        
        # Based on source availability
        well_researched_topics = [
            analysis.topic for analysis in topic_analyses
            if analysis.source_count > 5
        ]
        
        if well_researched_topics:
            recommendations.append(
                f"Most comprehensive information available for: {', '.join(well_researched_topics)}"
            )
        
        # Based on similarities/differences
        if len(similarities) > len(differences):
            recommendations.append("Topics show strong similarities - consider focusing on subtle distinctions")
        elif len(differences) > len(similarities):
            recommendations.append("Topics are quite distinct - each serves different use cases")
        
        return recommendations
    
    async def _synthesize_comparison(
        self,
        topics: List[str],
        topic_analyses: List[TopicAnalysis],
        comparison_matrix: Dict[ComparisonDimension, Dict[str, str]],
        similarities: List[str],
        differences: List[str]
    ) -> str:
        """Synthesize final comparative response"""
        
        # Prepare data for LLM synthesis
        research_summaries = []
        for analysis in topic_analyses:
            if analysis.research_result.success:
                summary = f"## {analysis.topic}\n{analysis.research_result.response[:1000]}..."
                research_summaries.append(summary)
        
        # Use comparative prompt
        model = get_model_for_task(TaskType.COMPARISON)
        
        prompt = get_comparative_reduce_prompt(
            topics=topics,
            map_results=research_summaries
        )
        
        # Generate synthesis (placeholder - would use actual LLM)
        synthesis = f"""# Comparative Analysis: {' vs '.join(topics)}

## Overview
This analysis compares {len(topics)} topics across multiple dimensions based on comprehensive research.

## Comparison Matrix

### Key Features
{self._format_matrix_section(comparison_matrix.get(ComparisonDimension.FEATURES, {}))}

### Advantages
{self._format_matrix_section(comparison_matrix.get(ComparisonDimension.ADVANTAGES, {}))}

### Use Cases
{self._format_matrix_section(comparison_matrix.get(ComparisonDimension.USE_CASES, {}))}

## Similarities
{self._format_list(similarities)}

## Key Differences  
{self._format_list(differences)}

## Analysis Summary
Based on the research, each topic has distinct characteristics and optimal use cases. The comparison reveals both shared concepts and important differentiators that should guide selection decisions.
"""
        
        return synthesis
    
    def _format_matrix_section(self, section_data: Dict[str, str]) -> str:
        """Format a section of the comparison matrix"""
        if not section_data:
            return "- No data available"
        
        lines = []
        for topic, info in section_data.items():
            lines.append(f"- **{topic}**: {info}")
        
        return "\n".join(lines)
    
    def _format_list(self, items: List[str]) -> str:
        """Format a list of items"""
        if not items:
            return "- None identified"
        
        return "\n".join([f"- {item}" for item in items])
    
    async def compare(
        self,
        topics: List[str],
        comparison_context: Optional[str] = None,
        dimensions: Optional[List[ComparisonDimension]] = None
    ) -> ComparisonResult:
        """
        Perform comprehensive comparative analysis of topics.
        
        Args:
            topics: List of topics to compare
            comparison_context: Optional context to guide comparison
            dimensions: Specific dimensions to focus on
            
        Returns:
            Detailed comparison result
        """
        import time
        start_time = time.time()
        
        if len(topics) < 2:
            raise ValueError("Need at least 2 topics for comparison")
        
        logger.info(f"Starting comparative analysis of {len(topics)} topics: {topics}")
        
        # Use specified dimensions or defaults
        if dimensions:
            self.default_dimensions = dimensions
        
        try:
            # Step 1: Analyze each topic individually (in parallel)
            logger.info("Analyzing individual topics...")
            
            topic_analyses = await asyncio.gather(
                *[self._analyze_single_topic(topic, comparison_context) for topic in topics],
                return_exceptions=True
            )
            
            # Handle any exceptions
            valid_analyses = []
            for i, analysis in enumerate(topic_analyses):
                if isinstance(analysis, Exception):
                    logger.error(f"Analysis failed for topic '{topics[i]}': {str(analysis)}")
                    # Create placeholder analysis
                    valid_analyses.append(TopicAnalysis(
                        topic=topics[i],
                        research_result=ResearchResult(query=topics[i], success=False, error=str(analysis)),
                        key_points={},
                        confidence=0.0,
                        source_count=0,
                        processing_time=0.0
                    ))
                else:
                    valid_analyses.append(analysis)
            
            # Step 2: Extract comparison dimensions
            logger.info("Extracting comparison dimensions...")
            comparison_matrix = self._extract_comparison_dimensions(valid_analyses)
            
            # Step 3: Identify similarities and differences
            logger.info("Identifying similarities and differences...")
            similarities, differences = self._identify_similarities_differences(valid_analyses, comparison_matrix)
            
            # Step 4: Generate recommendations
            recommendations = self._generate_recommendations(valid_analyses, similarities, differences)
            
            # Step 5: Synthesize final comparison
            logger.info("Synthesizing comparative response...")
            response = await self._synthesize_comparison(
                topics, valid_analyses, comparison_matrix, similarities, differences
            )
            
            # Calculate overall confidence
            confidences = [analysis.confidence for analysis in valid_analyses if analysis.confidence > 0]
            overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            processing_time = time.time() - start_time
            
            result = ComparisonResult(
                topics=topics,
                topic_analyses=valid_analyses,
                comparison_matrix=comparison_matrix,
                similarities=similarities,
                differences=differences,
                recommendations=recommendations,
                overall_confidence=overall_confidence,
                response=response,
                processing_time=processing_time,
                metadata={
                    "comparison_context": comparison_context,
                    "dimensions_analyzed": len(self.default_dimensions),
                    "successful_analyses": sum(1 for a in valid_analyses if a.research_result.success),
                    "total_sources": sum(a.source_count for a in valid_analyses)
                }
            )
            
            logger.info(f"Comparative analysis completed in {processing_time:.2f}s")
            return result
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Comparative analysis failed: {str(e)}")
            
            return ComparisonResult(
                topics=topics,
                topic_analyses=[],
                comparison_matrix={},
                similarities=[],
                differences=[],
                recommendations=[],
                overall_confidence=0.0,
                response=f"Comparative analysis failed: {str(e)}",
                processing_time=processing_time,
                metadata={"error": str(e)}
            )
    
    async def compare_with_template(
        self,
        topics: List[str],
        template: str = "features_and_use_cases"
    ) -> ComparisonResult:
        """Compare topics using predefined templates"""
        
        templates = {
            "features_and_use_cases": [
                ComparisonDimension.DEFINITION,
                ComparisonDimension.FEATURES,
                ComparisonDimension.USE_CASES,
                ComparisonDimension.ADVANTAGES
            ],
            "comprehensive": [
                ComparisonDimension.DEFINITION,
                ComparisonDimension.FEATURES,
                ComparisonDimension.ADVANTAGES,
                ComparisonDimension.DISADVANTAGES,
                ComparisonDimension.USE_CASES,
                ComparisonDimension.PERFORMANCE,
                ComparisonDimension.COST
            ],
            "business_analysis": [
                ComparisonDimension.ADVANTAGES,
                ComparisonDimension.DISADVANTAGES,
                ComparisonDimension.COST,
                ComparisonDimension.PERFORMANCE,
                ComparisonDimension.POPULARITY
            ]
        }
        
        dimensions = templates.get(template, self.default_dimensions)
        return await self.compare(topics, dimensions=dimensions)


# Convenience functions
async def quick_compare(topic1: str, topic2: str) -> str:
    """Quick comparison between two topics"""
    analyzer = ComparativeAnalyzer()
    result = await analyzer.compare([topic1, topic2])
    return result.response


async def compare_multiple(topics: List[str], context: str = None) -> ComparisonResult:
    """Compare multiple topics with optional context"""
    analyzer = ComparativeAnalyzer()
    return await analyzer.compare(topics, comparison_context=context)