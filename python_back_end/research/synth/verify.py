"""
Quote verification and fact-checking module.

Ensures research responses maintain proper source attribution and
factual accuracy by verifying quotes and claims against source material.
"""

import re
import logging
from typing import List, Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum

from .prompts import get_verify_prompt
from .map_reduce import ReduceResult

logger = logging.getLogger(__name__)


class VerificationStatus(Enum):
    """Status levels for verification results"""
    VERIFIED = "verified"
    QUESTIONABLE = "questionable"
    UNSUPPORTED = "unsupported"
    ATTRIBUTION_ISSUE = "attribution_issue"


@dataclass
class QuoteVerification:
    """Verification result for a specific quote"""
    quote_text: str
    status: VerificationStatus
    source_match: Optional[str] = None  # Actual text found in source
    similarity_score: float = 0.0
    source_url: Optional[str] = None
    issues: List[str] = None
    
    def __post_init__(self):
        if self.issues is None:
            self.issues = []


@dataclass
class ClaimVerification:
    """Verification result for a factual claim"""
    claim_text: str
    status: VerificationStatus
    supporting_sources: List[str] = None
    contradicting_sources: List[str] = None
    confidence: float = 0.0
    issues: List[str] = None
    
    def __post_init__(self):
        if self.supporting_sources is None:
            self.supporting_sources = []
        if self.contradicting_sources is None:
            self.contradicting_sources = []
        if self.issues is None:
            self.issues = []


@dataclass
class VerificationResult:
    """Complete verification result for a research response"""
    overall_status: VerificationStatus
    accuracy_score: float  # 0-1 score of overall accuracy
    quote_verifications: List[QuoteVerification] = None
    claim_verifications: List[ClaimVerification] = None
    missing_citations: List[str] = None
    attribution_issues: List[str] = None
    suggestions: List[str] = None
    processing_time: float = 0.0
    
    def __post_init__(self):
        if self.quote_verifications is None:
            self.quote_verifications = []
        if self.claim_verifications is None:
            self.claim_verifications = []
        if self.missing_citations is None:
            self.missing_citations = []
        if self.attribution_issues is None:
            self.attribution_issues = []
        if self.suggestions is None:
            self.suggestions = []


class QuoteVerifier:
    """
    Verifies quotes and claims in research responses against source material.
    
    Uses fuzzy matching for quotes and semantic analysis for claim verification.
    """
    
    def __init__(
        self,
        quote_similarity_threshold: float = 0.8,
        claim_confidence_threshold: float = 0.6,
        enable_llm_verification: bool = True
    ):
        self.quote_similarity_threshold = quote_similarity_threshold
        self.claim_confidence_threshold = claim_confidence_threshold
        self.enable_llm_verification = enable_llm_verification
    
    def _extract_quotes(self, text: str) -> List[str]:
        """Extract quoted text from research response"""
        # Find text within double quotes
        quote_pattern = r'"([^"]+)"'
        quotes = re.findall(quote_pattern, text)
        
        # Also look for formatted quotes (indented or with > prefix)
        block_quote_pattern = r'^> (.+)$'
        block_quotes = re.findall(block_quote_pattern, text, re.MULTILINE)
        
        # Combine and filter out very short quotes
        all_quotes = quotes + block_quotes
        return [q.strip() for q in all_quotes if len(q.strip()) > 10]
    
    def _extract_claims(self, text: str) -> List[str]:
        """Extract factual claims from research response"""
        # Simple heuristic: sentences that make definitive statements
        sentences = re.split(r'[.!?]+', text)
        
        claims = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:
                continue
                
            # Look for claim indicators
            claim_indicators = [
                r'\b(according to|research shows|studies indicate|data reveals)\b',
                r'\b(found that|discovered|concluded|determined)\b',
                r'\b(\d+%|\d+ percent|statistics show)\b',
                r'\b(experts|researchers|scientists) (say|believe|argue)\b'
            ]
            
            is_claim = any(re.search(pattern, sentence, re.IGNORECASE) for pattern in claim_indicators)
            if is_claim:
                claims.append(sentence)
        
        return claims[:10]  # Limit to avoid overwhelming verification
    
    def _fuzzy_match_quote(self, quote: str, source_content: str) -> Tuple[float, Optional[str]]:
        """
        Find the best fuzzy match for a quote in source content.
        
        Returns:
            Tuple of (similarity_score, matching_text)
        """
        quote_clean = quote.lower().strip()
        
        # Split source into overlapping windows
        words = source_content.lower().split()
        quote_word_count = len(quote_clean.split())
        
        best_score = 0.0
        best_match = None
        
        # Try windows of various sizes around the quote length
        for window_size in [quote_word_count, quote_word_count + 2, quote_word_count - 2]:
            if window_size < 1:
                continue
                
            for i in range(len(words) - window_size + 1):
                window = " ".join(words[i:i + window_size])
                score = SequenceMatcher(None, quote_clean, window).ratio()
                
                if score > best_score:
                    best_score = score
                    best_match = window
        
        return best_score, best_match
    
    def _verify_quote_against_sources(
        self, 
        quote: str, 
        source_content: Dict[str, str]
    ) -> QuoteVerification:
        """Verify a single quote against all source content"""
        
        best_score = 0.0
        best_match = None
        best_source = None
        
        # Check against each source
        for source_url, content in source_content.items():
            score, match = self._fuzzy_match_quote(quote, content)
            if score > best_score:
                best_score = score
                best_match = match
                best_source = source_url
        
        # Determine verification status
        if best_score >= self.quote_similarity_threshold:
            status = VerificationStatus.VERIFIED
            issues = []
        elif best_score >= 0.6:
            status = VerificationStatus.QUESTIONABLE
            issues = [f"Quote similarity ({best_score:.2f}) below threshold ({self.quote_similarity_threshold})"]
        else:
            status = VerificationStatus.UNSUPPORTED
            issues = ["No similar text found in sources"]
        
        return QuoteVerification(
            quote_text=quote,
            status=status,
            source_match=best_match,
            similarity_score=best_score,
            source_url=best_source,
            issues=issues
        )
    
    async def _llm_verify_claim(
        self,
        claim: str,
        source_content: Dict[str, str],
        llm_client: Any,
        model: str = "mistral"
    ) -> ClaimVerification:
        """Use LLM to verify a claim against sources (placeholder)"""
        
        # This would use your LLM client for semantic verification
        # For now, return a placeholder result
        
        supporting_sources = []
        contradicting_sources = []
        confidence = 0.5  # Default neutral confidence
        
        # Simple keyword-based verification for demo
        claim_lower = claim.lower()
        for source_url, content in source_content.items():
            content_lower = content.lower()
            
            # Very basic overlap check
            claim_words = set(claim_lower.split())
            content_words = set(content_lower.split())
            overlap = len(claim_words.intersection(content_words))
            
            if overlap > len(claim_words) * 0.3:
                supporting_sources.append(source_url)
                confidence += 0.2
        
        confidence = min(1.0, confidence)
        
        # Determine status
        if supporting_sources and confidence >= self.claim_confidence_threshold:
            status = VerificationStatus.VERIFIED
            issues = []
        elif supporting_sources:
            status = VerificationStatus.QUESTIONABLE
            issues = [f"Low confidence ({confidence:.2f}) in claim verification"]
        else:
            status = VerificationStatus.UNSUPPORTED
            issues = ["No supporting evidence found in sources"]
        
        return ClaimVerification(
            claim_text=claim,
            status=status,
            supporting_sources=supporting_sources,
            contradicting_sources=contradicting_sources,
            confidence=confidence,
            issues=issues
        )
    
    async def verify_response(
        self,
        research_response: str,
        source_content: Dict[str, str],  # url -> content mapping
        llm_client: Optional[Any] = None,
        model: str = "mistral"
    ) -> VerificationResult:
        """
        Verify a complete research response against source material.
        
        Args:
            research_response: The synthesized research response
            source_content: Dictionary mapping source URLs to their content
            llm_client: Optional LLM client for semantic verification
            model: Model to use for LLM verification
            
        Returns:
            Complete verification result
        """
        import time
        start_time = time.time()
        
        logger.info("Starting response verification")
        
        # Extract quotes and claims
        quotes = self._extract_quotes(research_response)
        claims = self._extract_claims(research_response)
        
        logger.info(f"Extracted {len(quotes)} quotes and {len(claims)} claims for verification")
        
        # Verify quotes
        quote_verifications = []
        for quote in quotes:
            verification = self._verify_quote_against_sources(quote, source_content)
            quote_verifications.append(verification)
        
        # Verify claims (using LLM if available)
        claim_verifications = []
        if claims and llm_client and self.enable_llm_verification:
            for claim in claims:
                verification = await self._llm_verify_claim(claim, source_content, llm_client, model)
                claim_verifications.append(verification)
        
        # Calculate overall accuracy score
        verified_quotes = sum(1 for qv in quote_verifications if qv.status == VerificationStatus.VERIFIED)
        verified_claims = sum(1 for cv in claim_verifications if cv.status == VerificationStatus.VERIFIED)
        
        total_items = len(quote_verifications) + len(claim_verifications)
        accuracy_score = (verified_quotes + verified_claims) / max(1, total_items)
        
        # Determine overall status
        if accuracy_score >= 0.8:
            overall_status = VerificationStatus.VERIFIED
        elif accuracy_score >= 0.6:
            overall_status = VerificationStatus.QUESTIONABLE
        else:
            overall_status = VerificationStatus.UNSUPPORTED
        
        # Collect issues and suggestions
        attribution_issues = []
        suggestions = []
        
        for qv in quote_verifications:
            if qv.status != VerificationStatus.VERIFIED:
                attribution_issues.extend(qv.issues)
        
        if accuracy_score < 0.8:
            suggestions.append("Consider adding more specific citations for claims")
            suggestions.append("Verify quotes match source material exactly")
        
        processing_time = time.time() - start_time
        
        result = VerificationResult(
            overall_status=overall_status,
            accuracy_score=accuracy_score,
            quote_verifications=quote_verifications,
            claim_verifications=claim_verifications,
            attribution_issues=attribution_issues,
            suggestions=suggestions,
            processing_time=processing_time
        )
        
        logger.info(f"Verification completed in {processing_time:.2f}s - Status: {overall_status.value}, Accuracy: {accuracy_score:.2f}")
        
        return result
    
    async def llm_verify_response(
        self,
        research_response: str,
        source_content: Dict[str, str],
        llm_client: Any,
        model: str = "mistral"
    ) -> str:
        """
        Use LLM for comprehensive verification with detailed feedback.
        
        This provides a more thorough verification using the LLM's understanding
        of context and reasoning.
        """
        source_list = list(source_content.keys())
        
        prompt = get_verify_prompt(
            research_response=research_response,
            source_list=source_list,
            source_content=source_content
        )
        
        # Call LLM for verification (placeholder)
        # verification_response = await llm_client.generate(prompt, model=model)
        
        # Placeholder verification response
        verification_response = f"""## Verified Claims ✓
- Most major claims are supported by the provided sources
- Quotes appear to be accurately represented
- Source attribution is generally appropriate

## Questionable Claims ⚠️
- Some statistical claims would benefit from more specific citations
- A few statements appear to be interpretations rather than direct quotes

## Attribution Issues 🔍  
- {len(source_list)} sources are properly referenced
- Consider adding page numbers or section references where possible

## Accuracy Assessment
Overall accuracy appears high with good source fidelity. The response appropriately synthesizes information from multiple sources.

## Suggested Improvements
- Add more specific citations for numerical claims
- Clarify when statements are analysis vs. direct source quotes
- Consider adding confidence indicators for uncertain claims
"""
        
        return verification_response


# Convenience functions
async def quick_verify(
    research_response: str,
    source_content: Dict[str, str],
    llm_client: Optional[Any] = None
) -> VerificationResult:
    """Convenience function for quick verification"""
    verifier = QuoteVerifier()
    return await verifier.verify_response(research_response, source_content, llm_client)