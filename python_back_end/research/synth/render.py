"""
Markdown rendering for research responses with proper source attribution.

Creates well-formatted, citation-rich research responses with source lists,
confidence indicators, and verification status.
"""

import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .map_reduce import ReduceResult
from .verify import VerificationResult, VerificationStatus


class ResponseType(Enum):
    """Types of research responses"""
    STANDARD = "standard"
    FACT_CHECK = "fact_check"  
    COMPARATIVE = "comparative"
    SUMMARY = "summary"


@dataclass
class SourceInfo:
    """Information about a source used in the response"""
    url: str
    title: Optional[str] = None
    domain: Optional[str] = None
    last_accessed: Optional[datetime] = None
    relevance_score: Optional[float] = None
    excerpt: Optional[str] = None


@dataclass 
class ResearchResponse:
    """Complete research response with metadata"""
    query: str
    content: str  # Main markdown content
    response_type: ResponseType
    sources: List[SourceInfo]
    confidence_score: float
    verification_status: Optional[VerificationStatus] = None
    processing_time: float = 0.0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MarkdownRenderer:
    """
    Renders research responses as well-formatted Markdown with citations.
    
    Features:
    - Clean, readable formatting
    - Proper source attribution 
    - Confidence and verification indicators
    - Responsive to different response types
    """
    
    def __init__(
        self,
        include_metadata: bool = True,
        include_verification: bool = True,
        max_sources: int = 20,
        excerpt_length: int = 150
    ):
        self.include_metadata = include_metadata
        self.include_verification = include_verification
        self.max_sources = max_sources
        self.excerpt_length = excerpt_length
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain name from URL"""
        import re
        match = re.search(r'https?://([^/]+)', url)
        if match:
            domain = match.group(1)
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        return url
    
    def _format_confidence_indicator(self, confidence: float) -> str:
        """Generate confidence indicator emoji and text"""
        if confidence >= 0.9:
            return "🟢 High confidence"
        elif confidence >= 0.7:
            return "🟡 Medium confidence"
        elif confidence >= 0.5:
            return "🟠 Low confidence"
        else:
            return "🔴 Very low confidence"
    
    def _format_verification_indicator(self, status: VerificationStatus) -> str:
        """Generate verification status indicator"""
        indicators = {
            VerificationStatus.VERIFIED: "✅ Verified",
            VerificationStatus.QUESTIONABLE: "⚠️ Needs review", 
            VerificationStatus.UNSUPPORTED: "❌ Unsupported",
            VerificationStatus.ATTRIBUTION_ISSUE: "🔍 Attribution issues"
        }
        return indicators.get(status, "❓ Unknown")
    
    def _render_source_list(self, sources: List[SourceInfo]) -> str:
        """Render the sources section"""
        if not sources:
            return ""
        
        # Limit number of sources shown
        display_sources = sources[:self.max_sources]
        
        lines = ["## Sources"]
        
        for i, source in enumerate(display_sources, 1):
            domain = source.domain or self._extract_domain(source.url)
            title = source.title or f"Source {i}"
            
            # Basic source entry
            source_line = f"{i}. **{title}** - [{domain}]({source.url})"
            
            # Add relevance score if available
            if source.relevance_score is not None:
                source_line += f" (Relevance: {source.relevance_score:.1f})"
            
            lines.append(source_line)
            
            # Add excerpt if available
            if source.excerpt:
                excerpt = source.excerpt[:self.excerpt_length]
                if len(source.excerpt) > self.excerpt_length:
                    excerpt += "..."
                lines.append(f"   > {excerpt}")
                lines.append("")  # Extra spacing
        
        # Note if sources were truncated
        if len(sources) > self.max_sources:
            lines.append(f"*... and {len(sources) - self.max_sources} more sources*")
        
        return "\n".join(lines)
    
    def _render_metadata_section(
        self,
        response: ResearchResponse,
        verification_result: Optional[VerificationResult] = None
    ) -> str:
        """Render metadata and verification section"""
        if not self.include_metadata:
            return ""
        
        lines = ["## Research Metadata"]
        
        # Query info
        lines.append(f"**Query:** {response.query}")
        lines.append(f"**Response Type:** {response.response_type.value.title()}")
        
        # Confidence and verification
        confidence_indicator = self._format_confidence_indicator(response.confidence_score)
        lines.append(f"**Confidence:** {confidence_indicator} ({response.confidence_score:.1%})")
        
        if response.verification_status and self.include_verification:
            verification_indicator = self._format_verification_indicator(response.verification_status)
            lines.append(f"**Verification:** {verification_indicator}")
        
        # Processing stats
        if response.processing_time > 0:
            lines.append(f"**Processing Time:** {response.processing_time:.1f}s")
        
        lines.append(f"**Sources Used:** {len(response.sources)}")
        
        # Verification details if available
        if verification_result and self.include_verification:
            lines.append("")
            lines.append("### Verification Details")
            
            if verification_result.quote_verifications:
                verified_quotes = sum(1 for qv in verification_result.quote_verifications 
                                    if qv.status == VerificationStatus.VERIFIED)
                lines.append(f"- **Quotes:** {verified_quotes}/{len(verification_result.quote_verifications)} verified")
            
            if verification_result.claim_verifications:
                verified_claims = sum(1 for cv in verification_result.claim_verifications
                                    if cv.status == VerificationStatus.VERIFIED)
                lines.append(f"- **Claims:** {verified_claims}/{len(verification_result.claim_verifications)} verified")
            
            lines.append(f"- **Overall Accuracy:** {verification_result.accuracy_score:.1%}")
        
        return "\n".join(lines)
    
    def render_standard_response(
        self,
        reduce_result: ReduceResult,
        query: str,
        sources: List[SourceInfo],
        verification_result: Optional[VerificationResult] = None
    ) -> ResearchResponse:
        """Render a standard research response"""
        
        # Main content (from REDUCE phase)
        content_lines = [reduce_result.synthesis]
        
        # Add source list
        source_section = self._render_source_list(sources)
        if source_section:
            content_lines.extend(["", source_section])
        
        # Add metadata section
        response = ResearchResponse(
            query=query,
            content="",  # Will be set below
            response_type=ResponseType.STANDARD,
            sources=sources,
            confidence_score=reduce_result.confidence_score or 0.5,
            verification_status=verification_result.overall_status if verification_result else None,
            processing_time=reduce_result.processing_time,
            metadata={
                "reduce_token_count": reduce_result.token_count,
                "sources_count": len(sources)
            }
        )
        
        metadata_section = self._render_metadata_section(response, verification_result)
        if metadata_section:
            content_lines.extend(["", "---", "", metadata_section])
        
        response.content = "\n".join(content_lines)
        return response
    
    def render_fact_check_response(
        self,
        claim: str,
        reduce_result: ReduceResult,
        sources: List[SourceInfo],
        verification_result: Optional[VerificationResult] = None
    ) -> ResearchResponse:
        """Render a fact-checking response"""
        
        content_lines = [f"# Fact Check: {claim}", ""]
        
        # Add verdict section based on verification
        if verification_result:
            status = verification_result.overall_status
            if status == VerificationStatus.VERIFIED:
                content_lines.extend(["## Verdict: ✅ SUPPORTED", ""])
            elif status == VerificationStatus.QUESTIONABLE:
                content_lines.extend(["## Verdict: ⚠️ PARTIALLY SUPPORTED", ""])
            else:
                content_lines.extend(["## Verdict: ❌ UNSUPPORTED", ""])
        
        # Add main analysis
        content_lines.append(reduce_result.synthesis)
        
        # Add source list
        source_section = self._render_source_list(sources)
        if source_section:
            content_lines.extend(["", source_section])
        
        response = ResearchResponse(
            query=f"Fact check: {claim}",
            content="",
            response_type=ResponseType.FACT_CHECK,
            sources=sources,
            confidence_score=reduce_result.confidence_score or 0.5,
            verification_status=verification_result.overall_status if verification_result else None,
            processing_time=reduce_result.processing_time
        )
        
        # Add metadata
        metadata_section = self._render_metadata_section(response, verification_result)
        if metadata_section:
            content_lines.extend(["", "---", "", metadata_section])
        
        response.content = "\n".join(content_lines)
        return response
    
    def render_comparative_response(
        self,
        topics: List[str],
        reduce_result: ReduceResult,
        sources: List[SourceInfo],
        verification_result: Optional[VerificationResult] = None
    ) -> ResearchResponse:
        """Render a comparative analysis response"""
        
        topics_str = " vs ".join(topics)
        content_lines = [f"# Comparative Analysis: {topics_str}", ""]
        
        # Add main comparison
        content_lines.append(reduce_result.synthesis)
        
        # Add source list
        source_section = self._render_source_list(sources)
        if source_section:
            content_lines.extend(["", source_section])
        
        response = ResearchResponse(
            query=f"Compare: {topics_str}",
            content="",
            response_type=ResponseType.COMPARATIVE,
            sources=sources,
            confidence_score=reduce_result.confidence_score or 0.5,
            verification_status=verification_result.overall_status if verification_result else None,
            processing_time=reduce_result.processing_time,
            metadata={"topics": topics}
        )
        
        # Add metadata
        metadata_section = self._render_metadata_section(response, verification_result)
        if metadata_section:
            content_lines.extend(["", "---", "", metadata_section])
        
        response.content = "\n".join(content_lines)
        return response
    
    def add_citation_numbers(self, content: str, sources: List[SourceInfo]) -> str:
        """
        Add citation numbers to content based on URL mentions.
        
        Finds URLs in content and replaces them with [1], [2], etc.
        """
        if not sources:
            return content
        
        # Create URL to number mapping
        url_to_number = {source.url: i + 1 for i, source in enumerate(sources)}
        
        # Replace URLs with citation numbers
        def replace_url(match):
            url = match.group(0)
            if url in url_to_number:
                return f"[{url_to_number[url]}]"
            return url
        
        # Pattern to match URLs
        url_pattern = r'https?://[^\s\)]+(?:\([^\)]*\))?[^\s\.,;]*'
        
        return re.sub(url_pattern, replace_url, content)


def create_source_info(url: str, title: str = None, relevance_score: float = None) -> SourceInfo:
    """Convenience function to create SourceInfo objects"""
    return SourceInfo(
        url=url,
        title=title,
        domain=MarkdownRenderer()._extract_domain(url),
        last_accessed=datetime.now(),
        relevance_score=relevance_score
    )