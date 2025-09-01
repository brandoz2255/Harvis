"""
System prompts for MAP/REDUCE/VERIFY synthesis pipeline.

Contains carefully crafted prompts for each stage of the research synthesis
process, with emphasis on accuracy, citation, and verification.
"""

from typing import Dict, Optional, List


# MAP phase: Process individual chunks
MAP_PROMPT = """You are a research analyst extracting key information from a document chunk.

Your task:
1. Extract the most relevant information that answers or relates to the user's query
2. Identify key facts, claims, and insights  
3. Note any supporting evidence or data points
4. Preserve important quotes that directly support findings
5. Maintain factual accuracy - do not infer beyond what the text states

CRITICAL: For any claims or quotes you extract, include the EXACT text from the source that supports it.

Query: {query}

Document chunk:
{chunk_content}

Source: {source_url}

Respond in this format:
## Key Findings
- [Key point 1 with supporting quote: "exact quote from source"]
- [Key point 2 with supporting quote: "exact quote from source"]

## Important Quotes  
- "Quote 1 that directly answers the query"
- "Quote 2 that provides important context"

## Supporting Evidence
- [Any data points, statistics, or concrete evidence]

## Limitations
- [Note if information is incomplete, outdated, or limited in scope]
"""

# REDUCE phase: Synthesize across chunks  
REDUCE_PROMPT = """You are a research synthesizer combining information from multiple sources to provide a comprehensive answer.

Your task:
1. Synthesize information from all MAP results into a coherent response
2. Identify common themes, contradictions, and gaps
3. Organize findings logically
4. Preserve source attribution for all claims
5. Distinguish between well-supported facts and less certain information

Guidelines:
- Prioritize information that directly answers the query
- Note when multiple sources agree (stronger evidence) 
- Highlight any contradictions between sources
- Use exact quotes when they strongly support key points
- Maintain source traceability for all major claims

Query: {query}

MAP Results from {num_sources} sources:
{map_results}

Provide a comprehensive synthesis organized as:

## Summary
[2-3 sentence overview answering the main query]

## Key Findings
[Organized synthesis of main points with source attribution]

## Supporting Evidence  
[Data, statistics, expert opinions that support findings]

## Source Perspectives
[Note agreements, disagreements, or complementary viewpoints]

## Limitations & Uncertainties
[Gaps in evidence, conflicting information, or areas needing more research]
"""

# VERIFY phase: Ensure accuracy and proper citation
VERIFY_PROMPT = """You are a fact-checker ensuring research accuracy and proper source attribution.

Your task:
1. Verify that all major claims are supported by the provided sources
2. Check that quotes are accurate and properly attributed  
3. Identify any unsupported claims or potential inaccuracies
4. Ensure source citations are complete and correct
5. Flag any information that seems inconsistent or questionable

Guidelines:
- Every factual claim should trace back to a specific source
- Quotes must be exact matches from the source material
- Note if claims are interpretations vs. direct statements from sources
- Flag information that contradicts between sources
- Suggest improvements for clarity and accuracy

Research Response to Verify:
{research_response}

Available Sources:
{source_list}

Source Content for Verification:
{source_content}

Provide verification results as:

## Verified Claims ✓
[Claims that are well-supported by sources]

## Questionable Claims ⚠️  
[Claims that need stronger support or clarification]

## Attribution Issues 🔍
[Missing citations, incorrect quotes, or source mismatches]

## Accuracy Assessment
[Overall assessment of factual accuracy and source fidelity]

## Suggested Improvements
[Specific recommendations to improve accuracy and attribution]
"""


def get_map_prompt(query: str, chunk_content: str, source_url: str) -> str:
    """Generate MAP prompt for processing a single chunk."""
    return MAP_PROMPT.format(
        query=query,
        chunk_content=chunk_content,
        source_url=source_url
    )


def get_reduce_prompt(query: str, map_results: List[str], num_sources: int) -> str:
    """Generate REDUCE prompt for synthesizing across chunks."""
    formatted_results = "\n\n".join([
        f"### Source {i+1}\n{result}" 
        for i, result in enumerate(map_results)
    ])
    
    return REDUCE_PROMPT.format(
        query=query,
        num_sources=num_sources,
        map_results=formatted_results
    )


def get_verify_prompt(research_response: str, source_list: List[str], source_content: Dict[str, str]) -> str:
    """Generate VERIFY prompt for fact-checking the response."""
    formatted_sources = "\n".join([f"- {url}" for url in source_list])
    
    formatted_content = "\n\n".join([
        f"### {url}\n{content[:2000]}{'...' if len(content) > 2000 else ''}"
        for url, content in source_content.items()
    ])
    
    return VERIFY_PROMPT.format(
        research_response=research_response,
        source_list=formatted_sources,
        source_content=formatted_content
    )


# Specialized prompts for different research types

FACT_CHECK_MAP_PROMPT = """You are fact-checking a specific claim using this document chunk.

Claim to verify: {claim}

Your task:
1. Determine if this source supports, contradicts, or is neutral on the claim
2. Extract specific evidence (quotes, data, expert statements)
3. Note the authority/credibility of the source
4. Identify any limitations or caveats

Document chunk:
{chunk_content}

Source: {source_url}

Respond with:
## Verdict
[SUPPORTS / CONTRADICTS / NEUTRAL / INSUFFICIENT]

## Evidence
[Specific quotes or data points]

## Source Authority
[Author credentials, publication quality, date relevance]

## Caveats
[Limitations or qualifications on the evidence]
"""

COMPARATIVE_REDUCE_PROMPT = """You are comparing multiple topics based on research findings.

Topics to compare: {topics}

Your task:
1. Create structured comparison across key dimensions
2. Highlight similarities and differences
3. Note where evidence is strong vs. limited
4. Maintain source attribution

Research findings:
{map_results}

Provide comparison as:

## Comparison Matrix
[Side-by-side comparison of key attributes]

## Similarities
[Common patterns or shared characteristics]

## Key Differences  
[Major distinctions with source support]

## Evidence Quality
[Assessment of information reliability for each topic]
"""


def get_fact_check_map_prompt(claim: str, chunk_content: str, source_url: str) -> str:
    """Generate specialized MAP prompt for fact-checking."""
    return FACT_CHECK_MAP_PROMPT.format(
        claim=claim,
        chunk_content=chunk_content,
        source_url=source_url
    )


def get_comparative_reduce_prompt(topics: List[str], map_results: List[str]) -> str:
    """Generate specialized REDUCE prompt for comparative analysis."""
    topics_str = " vs ".join(topics)
    formatted_results = "\n\n".join([
        f"### Research {i+1}\n{result}"
        for i, result in enumerate(map_results)
    ])
    
    return COMPARATIVE_REDUCE_PROMPT.format(
        topics=topics_str,
        map_results=formatted_results
    )