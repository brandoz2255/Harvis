"""
MCP tool interface for research system.

Exposes research capabilities as MCP tools with proper schema definition,
streaming events, and integration with the complete research pipeline.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator, Union
from dataclasses import dataclass, asdict
from enum import Enum

try:
    from mcp import Server, Request, Response
    from mcp.types import Tool, TextContent, ImageContent, CallToolRequest
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    # Placeholder types for when MCP is not available
    class Server: pass
    class Tool: pass
    class TextContent: pass

from ..pipeline.research_agent import ResearchAgent, ResearchConfig
from ..pipeline.fact_check import FactChecker
from ..pipeline.compare import ComparativeAnalyzer

logger = logging.getLogger(__name__)


class ResearchEventType(Enum):
    """Types of research progress events"""
    STARTED = "started"
    STAGE_BEGIN = "stage_begin"
    STAGE_COMPLETE = "stage_complete"
    PROGRESS = "progress"
    WARNING = "warning"
    ERROR = "error"
    COMPLETED = "completed"


@dataclass
class ResearchEvent:
    """Research progress event for streaming"""
    type: ResearchEventType
    message: str
    stage: Optional[str] = None
    progress: Optional[float] = None  # 0-1 completion percentage
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {k: v for k, v in asdict(self).items() if v is not None}


class ResearchTool:
    """
    MCP tool wrapper for research system.
    
    Provides structured interface for research operations with proper
    schema definitions and streaming progress events.
    """
    
    def __init__(self):
        self.research_agent = ResearchAgent()
        self.fact_checker = FactChecker()
        self.comparative_analyzer = ComparativeAnalyzer()
        
        # Tool schemas
        self._tool_schemas = self._create_tool_schemas()
    
    def _create_tool_schemas(self) -> Dict[str, Dict]:
        """Create MCP tool schemas for all research functions"""
        
        schemas = {
            "research": {
                "name": "research",
                "description": "Perform comprehensive research on a query using web search, content extraction, and synthesis",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The research query or question to investigate"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of search results to process (default: 20)",
                            "minimum": 1,
                            "maximum": 50,
                            "default": 20
                        },
                        "enable_verification": {
                            "type": "boolean",
                            "description": "Enable fact verification of the response (default: true)",
                            "default": True
                        },
                        "include_sources": {
                            "type": "boolean",
                            "description": "Include source list in response (default: true)",
                            "default": True
                        }
                    },
                    "required": ["query"]
                }
            },
            
            "fact_check": {
                "name": "fact_check",
                "description": "Fact-check a specific claim using comprehensive source verification",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "claim": {
                            "type": "string",
                            "description": "The claim to fact-check"
                        },
                        "strict_mode": {
                            "type": "boolean",
                            "description": "Use stricter verification standards (default: true)",
                            "default": True
                        }
                    },
                    "required": ["claim"]
                }
            },
            
            "compare": {
                "name": "compare",
                "description": "Compare multiple topics with structured analysis of similarities and differences",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of topics to compare (minimum 2)",
                            "minItems": 2,
                            "maxItems": 5
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional context to guide the comparison"
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["definition", "features", "advantages", "disadvantages", "use_cases", "performance", "cost"]
                            },
                            "description": "Specific dimensions to focus the comparison on"
                        }
                    },
                    "required": ["topics"]
                }
            }
        }
        
        return schemas
    
    def get_tools(self) -> List[Dict]:
        """Get list of available MCP tools"""
        return list(self._tool_schemas.values())
    
    async def _emit_progress_event(
        self,
        event_type: ResearchEventType,
        message: str,
        **kwargs
    ) -> ResearchEvent:
        """Emit a progress event (for streaming)"""
        import datetime
        
        event = ResearchEvent(
            type=event_type,
            message=message,
            timestamp=datetime.datetime.now().isoformat(),
            **kwargs
        )
        
        # Log the event
        logger.info(f"Research event: {event_type.value} - {message}")
        
        return event
    
    async def execute_research(
        self,
        query: str,
        max_results: int = 20,
        enable_verification: bool = True,
        include_sources: bool = True,
        stream_events: bool = False
    ) -> Union[str, AsyncGenerator[Union[str, ResearchEvent], None]]:
        """
        Execute comprehensive research.
        
        Args:
            query: Research query
            max_results: Maximum search results
            enable_verification: Enable verification
            include_sources: Include sources in response
            stream_events: Whether to stream progress events
            
        Returns:
            Research response string or async generator of events/response
        """
        
        async def _research_with_events():
            """Internal function that yields events and final response"""
            try:
                # Start event
                yield await self._emit_progress_event(
                    ResearchEventType.STARTED,
                    f"Starting research for: {query}",
                    progress=0.0
                )
                
                # Configure research
                config = ResearchConfig(
                    max_search_results=max_results,
                    enable_verification=enable_verification,
                    include_metadata=include_sources
                )
                
                research_agent = ResearchAgent(config)
                
                # Execute research with progress tracking
                yield await self._emit_progress_event(
                    ResearchEventType.STAGE_BEGIN,
                    "Planning research queries",
                    stage="planning",
                    progress=0.1
                )
                
                result = await research_agent.research(query)
                
                yield await self._emit_progress_event(
                    ResearchEventType.STAGE_COMPLETE,
                    "Research pipeline completed",
                    stage="completed",
                    progress=1.0
                )
                
                if result.success:
                    yield await self._emit_progress_event(
                        ResearchEventType.COMPLETED,
                        f"Research completed successfully with {result.sources_count} sources",
                        data={
                            "confidence": result.confidence_score,
                            "duration": result.total_duration,
                            "sources_count": result.sources_count
                        }
                    )
                    
                    # Final response
                    yield result.response
                else:
                    yield await self._emit_progress_event(
                        ResearchEventType.ERROR,
                        f"Research failed: {result.error}"
                    )
                    
                    yield f"Research failed: {result.error}"
                    
            except Exception as e:
                logger.error(f"Research execution failed: {str(e)}")
                yield await self._emit_progress_event(
                    ResearchEventType.ERROR,
                    f"Research execution failed: {str(e)}"
                )
                yield f"Research execution failed: {str(e)}"
        
        if stream_events:
            return _research_with_events()
        else:
            # Execute without streaming
            config = ResearchConfig(
                max_search_results=max_results,
                enable_verification=enable_verification,
                include_metadata=include_sources
            )
            
            research_agent = ResearchAgent(config)
            result = await research_agent.research(query)
            
            if result.success:
                return result.response
            else:
                return f"Research failed: {result.error}"
    
    async def execute_fact_check(
        self,
        claim: str,
        strict_mode: bool = True,
        stream_events: bool = False
    ) -> Union[str, AsyncGenerator[Union[str, ResearchEvent], None]]:
        """Execute fact-checking with optional streaming"""
        
        async def _fact_check_with_events():
            try:
                yield await self._emit_progress_event(
                    ResearchEventType.STARTED,
                    f"Starting fact-check for claim: {claim}",
                    progress=0.0
                )
                
                result = await self.fact_checker.fact_check(claim)
                
                yield await self._emit_progress_event(
                    ResearchEventType.COMPLETED,
                    f"Fact-check completed - Verdict: {result.verdict.value}",
                    data={
                        "verdict": result.verdict.value,
                        "confidence": result.confidence,
                        "evidence_count": result.evidence_count
                    }
                )
                
                yield result.response
                
            except Exception as e:
                logger.error(f"Fact-check failed: {str(e)}")
                yield await self._emit_progress_event(
                    ResearchEventType.ERROR,
                    f"Fact-check failed: {str(e)}"
                )
                yield f"Fact-check failed: {str(e)}"
        
        if stream_events:
            return _fact_check_with_events()
        else:
            result = await self.fact_checker.fact_check(claim)
            return result.response
    
    async def execute_compare(
        self,
        topics: List[str],
        context: Optional[str] = None,
        dimensions: Optional[List[str]] = None,
        stream_events: bool = False
    ) -> Union[str, AsyncGenerator[Union[str, ResearchEvent], None]]:
        """Execute comparison with optional streaming"""
        
        async def _compare_with_events():
            try:
                yield await self._emit_progress_event(
                    ResearchEventType.STARTED,
                    f"Starting comparison of {len(topics)} topics",
                    progress=0.0
                )
                
                # Convert dimension strings to enums if provided
                dimension_enums = None
                if dimensions:
                    from ..pipeline.compare import ComparisonDimension
                    dimension_enums = [
                        ComparisonDimension(dim) for dim in dimensions 
                        if dim in [d.value for d in ComparisonDimension]
                    ]
                
                result = await self.comparative_analyzer.compare(
                    topics=topics,
                    comparison_context=context,
                    dimensions=dimension_enums
                )
                
                yield await self._emit_progress_event(
                    ResearchEventType.COMPLETED,
                    f"Comparison completed with confidence {result.overall_confidence:.1%}",
                    data={
                        "topics": topics,
                        "confidence": result.overall_confidence,
                        "similarities_count": len(result.similarities),
                        "differences_count": len(result.differences)
                    }
                )
                
                yield result.response
                
            except Exception as e:
                logger.error(f"Comparison failed: {str(e)}")
                yield await self._emit_progress_event(
                    ResearchEventType.ERROR,
                    f"Comparison failed: {str(e)}"
                )
                yield f"Comparison failed: {str(e)}"
        
        if stream_events:
            return _compare_with_events()
        else:
            result = await self.comparative_analyzer.compare(
                topics=topics,
                comparison_context=context
            )
            return result.response


def create_research_server() -> Optional[Server]:
    """Create MCP server with research tools"""
    if not MCP_AVAILABLE:
        logger.warning("MCP not available, cannot create server")
        return None
    
    server = Server("research-agent")
    research_tool = ResearchTool()
    
    @server.list_tools()
    async def handle_list_tools() -> List[Tool]:
        """List available research tools"""
        tools = []
        for tool_schema in research_tool.get_tools():
            tools.append(Tool(
                name=tool_schema["name"],
                description=tool_schema["description"],
                inputSchema=tool_schema["inputSchema"]
            ))
        return tools
    
    @server.call_tool()
    async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle tool execution"""
        try:
            if name == "research":
                query = arguments.get("query")
                if not query:
                    raise ValueError("Query is required")
                
                response = await research_tool.execute_research(
                    query=query,
                    max_results=arguments.get("max_results", 20),
                    enable_verification=arguments.get("enable_verification", True),
                    include_sources=arguments.get("include_sources", True)
                )
                
                return [TextContent(type="text", text=response)]
            
            elif name == "fact_check":
                claim = arguments.get("claim")
                if not claim:
                    raise ValueError("Claim is required")
                
                response = await research_tool.execute_fact_check(
                    claim=claim,
                    strict_mode=arguments.get("strict_mode", True)
                )
                
                return [TextContent(type="text", text=response)]
            
            elif name == "compare":
                topics = arguments.get("topics")
                if not topics or len(topics) < 2:
                    raise ValueError("At least 2 topics are required")
                
                response = await research_tool.execute_compare(
                    topics=topics,
                    context=arguments.get("context"),
                    dimensions=arguments.get("dimensions")
                )
                
                return [TextContent(type="text", text=response)]
            
            else:
                raise ValueError(f"Unknown tool: {name}")
                
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            logger.error(error_msg)
            return [TextContent(type="text", text=error_msg)]
    
    return server


async def run_research_server(host: str = "localhost", port: int = 3001):
    """Run the research MCP server"""
    if not MCP_AVAILABLE:
        logger.error("MCP not available, cannot run server")
        return
    
    server = create_research_server()
    if not server:
        logger.error("Failed to create research server")
        return
    
    logger.info(f"Starting research MCP server on {host}:{port}")
    
    try:
        # This would use the actual MCP server runner
        # await server.run(host=host, port=port)
        
        # Placeholder for server running
        logger.info("Research MCP server is running...")
        
        # Keep server running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Research MCP server stopped")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")


# Standalone tool interface (for non-MCP usage)
class StandaloneResearchTool:
    """Standalone research tool interface without MCP dependency"""
    
    def __init__(self):
        self.research_tool = ResearchTool()
    
    async def research(
        self,
        query: str,
        max_results: int = 20,
        enable_verification: bool = True,
        include_sources: bool = True
    ) -> str:
        """Perform research query"""
        return await self.research_tool.execute_research(
            query=query,
            max_results=max_results,
            enable_verification=enable_verification,
            include_sources=include_sources
        )
    
    async def fact_check(self, claim: str, strict_mode: bool = True) -> str:
        """Fact-check a claim"""
        return await self.research_tool.execute_fact_check(
            claim=claim,
            strict_mode=strict_mode
        )
    
    async def compare(
        self,
        topics: List[str],
        context: Optional[str] = None,
        dimensions: Optional[List[str]] = None
    ) -> str:
        """Compare topics"""
        return await self.research_tool.execute_compare(
            topics=topics,
            context=context,
            dimensions=dimensions
        )


# Example usage functions
async def example_research_usage():
    """Example of using the research tool"""
    tool = StandaloneResearchTool()
    
    # Basic research
    result = await tool.research("What are the benefits of renewable energy?")
    print("Research Result:")
    print(result)
    
    # Fact checking
    fact_result = await tool.fact_check("Solar panels last 25 years on average")
    print("\nFact Check Result:")
    print(fact_result)
    
    # Comparison
    compare_result = await tool.compare(
        topics=["Solar power", "Wind power"],
        context="renewable energy comparison"
    )
    print("\nComparison Result:")
    print(compare_result)


if __name__ == "__main__":
    # Run example usage
    asyncio.run(example_research_usage())