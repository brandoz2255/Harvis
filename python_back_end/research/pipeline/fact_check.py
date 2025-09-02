"""
Specialized fact-checking pipeline using stricter verification standards.

Provides focused fact-checking capabilities with enhanced verification,
source authority assessment, and confidence scoring.
"""

import asyncio
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

from .research_agent import ResearchAgent, ResearchConfig, ResearchResult
from ..synth.prompts import get_fact_check_map_prompt
from ..synth.verify import VerificationStatus
from ..llm.model_policy import get_model_for_task, TaskType

logger = logging.getLogger(__name__)


class FactCheckVerdict(Enum):
    """Fact check verdicts"""
    SUPPORTED = "supported"         # Claim is well-supported by evidence
    PARTIALLY_SUPPORTED = "partially_supported"  # Some support but incomplete
    UNSUPPORTED = "unsupported"     # No credible evidence found
    CONTRADICTED = "contradicted"   # Evidence contradicts the claim
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # Not enough reliable sources


@dataclass
class FactCheckResult:
    """Result of fact-checking analysis"""
    claim: str
    verdict: FactCheckVerdict
    confidence: float  # 0-1 confidence in verdict
    evidence_count: int
    contradicting_evidence: int
    supporting_sources: List[str]
    contradicting_sources: List[str]
    authority_score: float  # 0-1 score of source authority
    response: str  # Detailed explanation
    processing_time: float
    metadata: Dict[str, Any]


class FactChecker:
    """
    Specialized fact-checking agent with enhanced verification.
    
    Uses stricter standards than general research, with emphasis on:
    - Source authority and credibility
    - Evidence strength assessment
    - Contradiction detection
    - Confidence quantification
    """
    
    def __init__(self, config: Optional[ResearchConfig] = None):
        # Configure for fact-checking with stricter standards
        if config is None:
            config = ResearchConfig()
        
        # Override config for fact-checking
        config.max_search_results = 25  # More sources for verification
        config.enable_verification = True  # Always verify
        config.rerank_strategy = "cross_encoder"  # Better semantic matching
        config.max_chunks_for_synthesis = 20  # More evidence
        
        self.config = config
        self.research_agent = ResearchAgent(config)
        
        # Fact-checking specific settings
        self.authority_weights = {
            "gov": 1.0,           # Government sources
            "edu": 0.9,           # Educational institutions
            "org": 0.7,           # Organizations
            "com": 0.5,           # Commercial sites
            "wikipedia.org": 0.8, # Wikipedia (with caveats)
            "arxiv.org": 0.9,     # Academic papers
            "reuters.com": 0.8,   # News agencies
            "bbc.com": 0.8,
            "cnn.com": 0.6,
            "reddit.com": 0.3,    # Lower authority
            "twitter.com": 0.2,   # Very low authority
        }
    
    def _assess_source_authority(self, sources: List[str]) -> float:
        """Assess overall authority of source list"""
        if not sources:
            return 0.0
        
        total_authority = 0.0
        for source in sources:
            domain = source.lower()
            authority = 0.5  # Default
            
            # Check against authority weights
            for pattern, weight in self.authority_weights.items():
                if pattern in domain:
                    authority = weight
                    break
            
            total_authority += authority
        
        return total_authority / len(sources)
    
    def _analyze_claim_support(
        self,
        verification_result: Any,
        research_result: ResearchResult
    ) -> Dict[str, Any]:
        """Analyze level of support for the claim"""
        if not verification_result:
            return {
                "supporting_evidence": 0,
                "contradicting_evidence": 0,
                "supporting_sources": [],
                "contradicting_sources": [],
                "confidence": 0.0
            }
        
        # Count verified vs questionable evidence
        verified_items = 0
        questionable_items = 0
        unsupported_items = 0
        
        # Analyze quote verifications
        for qv in verification_result.quote_verifications:
            if qv.status == VerificationStatus.VERIFIED:
                verified_items += 1
            elif qv.status == VerificationStatus.QUESTIONABLE:
                questionable_items += 1
            else:
                unsupported_items += 1
        
        # Analyze claim verifications
        for cv in verification_result.claim_verifications:
            if cv.status == VerificationStatus.VERIFIED:
                verified_items += 1
            elif cv.status == VerificationStatus.QUESTIONABLE:
                questionable_items += 1
            else:
                unsupported_items += 1
        
        total_items = verified_items + questionable_items + unsupported_items
        
        # Calculate support metrics
        if total_items == 0:
            support_ratio = 0.0
        else:
            support_ratio = verified_items / total_items
        
        # Extract sources from research result
        sources = []
        if research_result.success:
            ranking_stage = research_result.get_stage_result(research_result.stage_results[3].stage)
            if ranking_stage and ranking_stage.data:
                sources = [chunk.chunk.url for chunk in ranking_stage.data[:10]]
        
        return {
            "supporting_evidence": verified_items,
            "contradicting_evidence": unsupported_items,
            "questionable_evidence": questionable_items,
            "support_ratio": support_ratio,
            "supporting_sources": sources,  # Simplified - in practice would classify
            "contradicting_sources": [],   # Would need contradiction detection
            "confidence": support_ratio
        }
    
    def _determine_verdict(
        self,
        support_analysis: Dict[str, Any],
        authority_score: float,
        verification_accuracy: float
    ) -> FactCheckVerdict:
        """Determine fact-check verdict based on evidence analysis"""
        support_ratio = support_analysis["support_ratio"]
        evidence_count = support_analysis["supporting_evidence"]
        contradicting_count = support_analysis["contradicting_evidence"]
        
        # Apply stricter thresholds for fact-checking
        if contradicting_count > evidence_count and authority_score > 0.6:
            return FactCheckVerdict.CONTRADICTED
        
        if support_ratio >= 0.8 and evidence_count >= 3 and authority_score > 0.6:
            return FactCheckVerdict.SUPPORTED
        
        if support_ratio >= 0.6 and evidence_count >= 2:
            return FactCheckVerdict.PARTIALLY_SUPPORTED
        
        if evidence_count < 2 or authority_score < 0.4:
            return FactCheckVerdict.INSUFFICIENT_EVIDENCE
        
        return FactCheckVerdict.UNSUPPORTED
    
    async def fact_check(self, claim: str) -> FactCheckResult:
        """
        Perform comprehensive fact-checking of a claim.
        
        Args:
            claim: The claim to fact-check
            
        Returns:
            Detailed fact-check result with verdict and evidence
        """
        import time
        start_time = time.time()
        
        logger.info(f"Starting fact-check for claim: '{claim}'")
        
        try:
            # Use research pipeline to gather evidence
            research_result = await self.research_agent.research(claim)
            
            if not research_result.success:
                return FactCheckResult(
                    claim=claim,
                    verdict=FactCheckVerdict.INSUFFICIENT_EVIDENCE,
                    confidence=0.0,
                    evidence_count=0,
                    contradicting_evidence=0,
                    supporting_sources=[],
                    contradicting_sources=[],
                    authority_score=0.0,
                    response="Unable to gather sufficient evidence for fact-checking.",
                    processing_time=time.time() - start_time,
                    metadata={"error": research_result.error}
                )
            
            # Get verification results
            verification_stage = research_result.get_stage_result(research_result.stage_results[-2].stage)
            verification_result = verification_stage.data if verification_stage else None
            
            # Analyze claim support
            support_analysis = self._analyze_claim_support(verification_result, research_result)
            
            # Assess source authority
            authority_score = self._assess_source_authority(support_analysis["supporting_sources"])
            
            # Get verification accuracy
            verification_accuracy = verification_result.accuracy_score if verification_result else 0.0
            
            # Determine verdict
            verdict = self._determine_verdict(support_analysis, authority_score, verification_accuracy)
            
            # Calculate overall confidence
            confidence = min(1.0, (
                support_analysis["confidence"] * 0.4 +
                authority_score * 0.3 +
                verification_accuracy * 0.3
            ))
            
            # Create detailed response
            response = self._format_fact_check_response(
                claim=claim,
                verdict=verdict,
                support_analysis=support_analysis,
                authority_score=authority_score,
                confidence=confidence,
                research_response=research_result.response
            )
            
            processing_time = time.time() - start_time
            
            result = FactCheckResult(
                claim=claim,
                verdict=verdict,
                confidence=confidence,
                evidence_count=support_analysis["supporting_evidence"],
                contradicting_evidence=support_analysis["contradicting_evidence"],
                supporting_sources=support_analysis["supporting_sources"],
                contradicting_sources=support_analysis["contradicting_sources"],
                authority_score=authority_score,
                response=response,
                processing_time=processing_time,
                metadata={
                    "research_duration": research_result.total_duration,
                    "sources_analyzed": research_result.sources_count,
                    "verification_accuracy": verification_accuracy,
                    "support_ratio": support_analysis["support_ratio"]
                }
            )
            
            logger.info(f"Fact-check completed in {processing_time:.2f}s - Verdict: {verdict.value}")
            
            return result
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Fact-checking failed: {str(e)}")
            
            return FactCheckResult(
                claim=claim,
                verdict=FactCheckVerdict.INSUFFICIENT_EVIDENCE,
                confidence=0.0,
                evidence_count=0,
                contradicting_evidence=0,
                supporting_sources=[],
                contradicting_sources=[],
                authority_score=0.0,
                response=f"Fact-checking failed due to error: {str(e)}",
                processing_time=processing_time,
                metadata={"error": str(e)}
            )
    
    def _format_fact_check_response(
        self,
        claim: str,
        verdict: FactCheckVerdict,
        support_analysis: Dict[str, Any],
        authority_score: float,
        confidence: float,
        research_response: Optional[str]
    ) -> str:
        """Format detailed fact-check response"""
        
        # Verdict formatting
        verdict_indicators = {
            FactCheckVerdict.SUPPORTED: "✅ SUPPORTED",
            FactCheckVerdict.PARTIALLY_SUPPORTED: "⚠️ PARTIALLY SUPPORTED", 
            FactCheckVerdict.UNSUPPORTED: "❌ UNSUPPORTED",
            FactCheckVerdict.CONTRADICTED: "🚫 CONTRADICTED",
            FactCheckVerdict.INSUFFICIENT_EVIDENCE: "❓ INSUFFICIENT EVIDENCE"
        }
        
        verdict_indicator = verdict_indicators.get(verdict, "❓ UNKNOWN")
        
        # Build response
        response_parts = [
            f"# Fact Check: {claim}",
            "",
            f"## Verdict: {verdict_indicator}",
            "",
            f"**Confidence:** {confidence:.1%}",
            f"**Evidence Quality:** {support_analysis['supporting_evidence']} supporting, {support_analysis['contradicting_evidence']} contradicting",
            f"**Source Authority:** {authority_score:.1%}",
            "",
            "## Analysis"
        ]
        
        # Add detailed research if available
        if research_response:
            # Extract key sections from research response
            research_parts = research_response.split("##")
            for part in research_parts[1:3]:  # Take first 2 sections
                if part.strip():
                    response_parts.append(f"##{part}")
        
        # Add verdict explanation
        response_parts.extend([
            "",
            "## Verdict Explanation"
        ])
        
        if verdict == FactCheckVerdict.SUPPORTED:
            response_parts.append("The claim is well-supported by credible evidence from multiple reliable sources.")
        elif verdict == FactCheckVerdict.PARTIALLY_SUPPORTED:
            response_parts.append("The claim has some supporting evidence but lacks complete verification or has notable limitations.")
        elif verdict == FactCheckVerdict.UNSUPPORTED:
            response_parts.append("No credible evidence was found to support this claim.")
        elif verdict == FactCheckVerdict.CONTRADICTED:
            response_parts.append("Credible evidence contradicts this claim.")
        else:
            response_parts.append("Insufficient reliable evidence is available to make a determination.")
        
        return "\n".join(response_parts)
    
    async def batch_fact_check(self, claims: List[str]) -> List[FactCheckResult]:
        """Fact-check multiple claims concurrently"""
        logger.info(f"Starting batch fact-check for {len(claims)} claims")
        
        # Limit concurrency to avoid overwhelming resources
        semaphore = asyncio.Semaphore(3)
        
        async def bounded_fact_check(claim: str) -> FactCheckResult:
            async with semaphore:
                return await self.fact_check(claim)
        
        results = await asyncio.gather(
            *[bounded_fact_check(claim) for claim in claims],
            return_exceptions=True
        )
        
        # Handle any exceptions
        fact_check_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Create error result
                fact_check_results.append(FactCheckResult(
                    claim=claims[i],
                    verdict=FactCheckVerdict.INSUFFICIENT_EVIDENCE,
                    confidence=0.0,
                    evidence_count=0,
                    contradicting_evidence=0,
                    supporting_sources=[],
                    contradicting_sources=[],
                    authority_score=0.0,
                    response=f"Error during fact-checking: {str(result)}",
                    processing_time=0.0,
                    metadata={"error": str(result)}
                ))
            else:
                fact_check_results.append(result)
        
        return fact_check_results


# Convenience functions
async def quick_fact_check(claim: str) -> str:
    """Quick fact-checking with minimal setup"""
    checker = FactChecker()
    result = await checker.fact_check(claim)
    return result.response


async def fact_check_with_verdict(claim: str) -> tuple[FactCheckVerdict, float]:
    """Get just verdict and confidence for a claim"""
    checker = FactChecker()
    result = await checker.fact_check(claim)
    return result.verdict, result.confidence