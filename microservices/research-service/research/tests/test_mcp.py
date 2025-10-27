"""
Tests for MCP integration.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import json

from ..mcp.tool import ResearchTool, ResearchEvent, ResearchEventType, StandaloneResearchTool


class TestResearchTool:
    """Test MCP research tool interface"""
    
    def test_tool_initialization(self):
        """Test research tool initialization"""
        tool = ResearchTool()
        
        assert tool.research_agent is not None
        assert tool.fact_checker is not None
        assert tool.comparative_analyzer is not None
        assert tool._tool_schemas is not None
    
    def test_tool_schemas(self):
        """Test MCP tool schema definitions"""
        tool = ResearchTool()
        tools = tool.get_tools()
        
        assert len(tools) == 3
        tool_names = [t["name"] for t in tools]
        assert "research" in tool_names
        assert "fact_check" in tool_names
        assert "compare" in tool_names
        
        # Check research tool schema
        research_tool = next(t for t in tools if t["name"] == "research")
        assert "description" in research_tool
        assert "inputSchema" in research_tool
        assert "properties" in research_tool["inputSchema"]
        assert "query" in research_tool["inputSchema"]["properties"]
        assert "required" in research_tool["inputSchema"]
        assert "query" in research_tool["inputSchema"]["required"]
    
    def test_research_event_creation(self):
        """Test research event creation"""
        event = ResearchEvent(
            type=ResearchEventType.STARTED,
            message="Starting research",
            stage="planning",
            progress=0.1
        )
        
        assert event.type == ResearchEventType.STARTED
        assert event.message == "Starting research"
        assert event.stage == "planning"
        assert event.progress == 0.1
        
        # Test serialization
        event_dict = event.to_dict()
        assert event_dict["type"] == "started"
        assert event_dict["message"] == "Starting research"
        assert event_dict["stage"] == "planning"
        assert event_dict["progress"] == 0.1
    
    @pytest.mark.asyncio
    async def test_emit_progress_event(self):
        """Test progress event emission"""
        tool = ResearchTool()
        
        event = await tool._emit_progress_event(
            ResearchEventType.PROGRESS,
            "Processing stage 1",
            stage="search",
            progress=0.5
        )
        
        assert event.type == ResearchEventType.PROGRESS
        assert event.message == "Processing stage 1"
        assert event.stage == "search"
        assert event.progress == 0.5
        assert event.timestamp is not None
    
    @pytest.mark.asyncio
    async def test_execute_research_no_streaming(self):
        """Test research execution without streaming"""
        tool = ResearchTool()
        
        with patch.object(tool.research_agent, 'research', new_callable=AsyncMock) as mock_research:
            mock_research.return_value = Mock(
                success=True,
                response="Research response about the query",
                sources_count=5,
                confidence_score=0.8,
                total_duration=2.5
            )
            
            result = await tool.execute_research(
                query="Test query",
                max_results=10,
                enable_verification=True,
                include_sources=True,
                stream_events=False
            )
            
            assert isinstance(result, str)
            assert result == "Research response about the query"
            mock_research.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_research_with_streaming(self):
        """Test research execution with streaming events"""
        tool = ResearchTool()
        
        with patch.object(tool.research_agent, 'research', new_callable=AsyncMock) as mock_research:
            mock_research.return_value = Mock(
                success=True,
                response="Streaming research response",
                sources_count=3,
                confidence_score=0.7,
                total_duration=1.8
            )
            
            result_generator = await tool.execute_research(
                query="Streaming test query",
                stream_events=True
            )
            
            # Collect all events and final response
            events = []
            response = None
            
            async for item in result_generator:
                if isinstance(item, ResearchEvent):
                    events.append(item)
                else:
                    response = item
            
            assert len(events) > 0
            assert any(event.type == ResearchEventType.STARTED for event in events)
            assert any(event.type == ResearchEventType.COMPLETED for event in events)
            assert response == "Streaming research response"
    
    @pytest.mark.asyncio
    async def test_execute_fact_check(self):
        """Test fact-check execution"""
        tool = ResearchTool()
        
        with patch.object(tool.fact_checker, 'fact_check', new_callable=AsyncMock) as mock_fact_check:
            from ..pipeline.fact_check import FactCheckResult, FactCheckVerdict
            mock_fact_check.return_value = FactCheckResult(
                claim="Test claim",
                verdict=FactCheckVerdict.SUPPORTED,
                confidence=0.9,
                evidence_count=5,
                contradicting_evidence=0,
                supporting_sources=[],
                contradicting_sources=[],
                authority_score=0.8,
                response="Fact-check response",
                processing_time=1.5,
                metadata={}
            )
            
            result = await tool.execute_fact_check(
                claim="Test claim to verify",
                strict_mode=True,
                stream_events=False
            )
            
            assert isinstance(result, str)
            assert result == "Fact-check response"
            mock_fact_check.assert_called_once_with("Test claim to verify")
    
    @pytest.mark.asyncio
    async def test_execute_compare(self):
        """Test comparison execution"""
        tool = ResearchTool()
        
        with patch.object(tool.comparative_analyzer, 'compare', new_callable=AsyncMock) as mock_compare:
            from ..pipeline.compare import ComparisonResult
            mock_compare.return_value = Mock(
                topics=["Topic A", "Topic B"],
                response="Comparison response",
                overall_confidence=0.8,
                similarities=["Similar feature 1"],
                differences=["Different feature 1"],
                processing_time=3.0
            )
            
            result = await tool.execute_compare(
                topics=["Topic A", "Topic B"],
                context="Test context",
                dimensions=["features", "advantages"],
                stream_events=False
            )
            
            assert isinstance(result, str)
            assert result == "Comparison response"
            mock_compare.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_streaming_with_errors(self):
        """Test streaming behavior with errors"""
        tool = ResearchTool()
        
        with patch.object(tool.research_agent, 'research', side_effect=Exception("Test error")):
            result_generator = await tool.execute_research(
                query="Error test",
                stream_events=True
            )
            
            events = []
            response = None
            
            async for item in result_generator:
                if isinstance(item, ResearchEvent):
                    events.append(item)
                else:
                    response = item
            
            # Should have error event
            assert any(event.type == ResearchEventType.ERROR for event in events)
            assert "Test error" in response


class TestStandaloneResearchTool:
    """Test standalone research tool (non-MCP)"""
    
    def test_standalone_tool_initialization(self):
        """Test standalone tool initialization"""
        tool = StandaloneResearchTool()
        assert tool.research_tool is not None
    
    @pytest.mark.asyncio
    async def test_standalone_research(self):
        """Test standalone research method"""
        tool = StandaloneResearchTool()
        
        with patch.object(tool.research_tool, 'execute_research', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = "Standalone research result"
            
            result = await tool.research(
                query="Test query",
                max_results=15,
                enable_verification=False,
                include_sources=True
            )
            
            assert result == "Standalone research result"
            mock_execute.assert_called_once_with(
                query="Test query",
                max_results=15,
                enable_verification=False,
                include_sources=True
            )
    
    @pytest.mark.asyncio
    async def test_standalone_fact_check(self):
        """Test standalone fact-check method"""
        tool = StandaloneResearchTool()
        
        with patch.object(tool.research_tool, 'execute_fact_check', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = "Fact-check result"
            
            result = await tool.fact_check("Test claim", strict_mode=False)
            
            assert result == "Fact-check result"
            mock_execute.assert_called_once_with(claim="Test claim", strict_mode=False)
    
    @pytest.mark.asyncio
    async def test_standalone_compare(self):
        """Test standalone compare method"""
        tool = StandaloneResearchTool()
        
        with patch.object(tool.research_tool, 'execute_compare', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = "Comparison result"
            
            result = await tool.compare(
                topics=["A", "B"],
                context="Test context",
                dimensions=["features"]
            )
            
            assert result == "Comparison result"
            mock_execute.assert_called_once_with(
                topics=["A", "B"],
                context="Test context",
                dimensions=["features"]
            )


class TestMCPServerIntegration:
    """Test MCP server integration (when MCP is available)"""
    
    @pytest.mark.skipif(True, reason="MCP integration tests require actual MCP library")
    def test_server_creation(self):
        """Test MCP server creation"""
        from ..mcp.tool import create_research_server
        server = create_research_server()
        
        # Would test actual server creation if MCP is available
        pass
    
    @pytest.mark.skipif(True, reason="MCP integration tests require actual MCP library") 
    @pytest.mark.asyncio
    async def test_tool_execution_via_mcp(self):
        """Test tool execution through MCP server"""
        # Would test actual MCP tool execution
        pass
    
    def test_mcp_unavailable_handling(self):
        """Test graceful handling when MCP is not available"""
        from ..mcp.tool import create_research_server
        
        with patch('research.mcp.tool.MCP_AVAILABLE', False):
            server = create_research_server()
            assert server is None


# Example usage tests
class TestExampleUsage:
    """Test example usage patterns"""
    
    @pytest.mark.asyncio
    async def test_example_research_workflow(self):
        """Test example research usage workflow"""
        tool = StandaloneResearchTool()
        
        with patch.object(tool.research_tool, 'execute_research', new_callable=AsyncMock) as mock_research, \
             patch.object(tool.research_tool, 'execute_fact_check', new_callable=AsyncMock) as mock_fact_check, \
             patch.object(tool.research_tool, 'execute_compare', new_callable=AsyncMock) as mock_compare:
            
            mock_research.return_value = "Research result"
            mock_fact_check.return_value = "Fact-check result"  
            mock_compare.return_value = "Comparison result"
            
            # Simulate example workflow
            research_result = await tool.research("What are the benefits of renewable energy?")
            assert research_result == "Research result"
            
            fact_result = await tool.fact_check("Solar panels last 25 years on average")
            assert fact_result == "Fact-check result"
            
            compare_result = await tool.compare(
                topics=["Solar power", "Wind power"],
                context="renewable energy comparison"
            )
            assert compare_result == "Comparison result"


# Error handling tests
class TestErrorHandling:
    """Test error handling in MCP integration"""
    
    @pytest.mark.asyncio
    async def test_invalid_tool_parameters(self):
        """Test handling of invalid parameters"""
        tool = ResearchTool()
        
        # Test empty query
        result = await tool.execute_research(
            query="",
            stream_events=False
        )
        
        # Should handle gracefully
        assert isinstance(result, str)
    
    @pytest.mark.asyncio
    async def test_comparison_insufficient_topics(self):
        """Test comparison with insufficient topics"""
        tool = ResearchTool()
        
        result = await tool.execute_compare(
            topics=["single_topic"],  # Need at least 2
            stream_events=False
        )
        
        # Should handle error gracefully
        assert isinstance(result, str)
        assert "error" in result.lower()
    
    @pytest.mark.asyncio
    async def test_network_timeout_handling(self):
        """Test handling of network timeouts"""
        tool = ResearchTool()
        
        with patch.object(tool.research_agent, 'research', side_effect=asyncio.TimeoutError("Timeout")):
            result = await tool.execute_research(
                query="Test timeout",
                stream_events=False
            )
            
            assert isinstance(result, str)
            assert "failed" in result.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])