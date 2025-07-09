"""
Integration tests for research API endpoints
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

class TestResearchAPIEndpoints:
    """Test cases for research API endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create a test client"""
        return TestClient(app)
    
    @patch('agent_research.research_agent')
    def test_research_chat_success(self, mock_research_agent, client):
        """Test successful research chat endpoint"""
        # Mock research agent response
        mock_research_agent.return_value = {
            "analysis": "This is a comprehensive analysis of the research topic.",
            "sources": [
                {"title": "Article 1", "url": "https://example.com/1", "source": "DuckDuckGo"},
                {"title": "Article 2", "url": "https://example.com/2", "source": "DuckDuckGo"}
            ],
            "sources_found": 2,
            "model_used": "mistral"
        }
        
        # Test request
        response = client.post("/api/research-chat", json={
            "message": "What is artificial intelligence?",
            "model": "mistral",
            "history": [],
            "enableWebSearch": True
        })
        
        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert "history" in data
        assert "response" in data
        assert "comprehensive analysis" in data["response"]
        assert "Sources (2 found)" in data["response"]
        assert len(data["history"]) == 1
        assert data["history"][0]["role"] == "assistant"
        
        # Verify research agent was called
        mock_research_agent.assert_called_once_with("What is artificial intelligence?", "mistral")
    
    @patch('agent_research.research_agent')
    def test_research_chat_error(self, mock_research_agent, client):
        """Test research chat endpoint error handling"""
        # Mock research agent to return error
        mock_research_agent.return_value = {
            "error": "Search engine unavailable"
        }
        
        # Test request
        response = client.post("/api/research-chat", json={
            "message": "Test query",
            "model": "mistral",
            "history": []
        })
        
        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert "Research Error" in data["response"]
        assert "Search engine unavailable" in data["response"]
    
    def test_research_chat_missing_message(self, client):
        """Test research chat endpoint with missing message"""
        # Test request with empty message
        response = client.post("/api/research-chat", json={
            "message": "",
            "model": "mistral",
            "history": []
        })
        
        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "Message is required" in data["error"]
    
    @patch('agent_research.fact_check_agent')
    def test_fact_check_success(self, mock_fact_check_agent, client):
        """Test successful fact check endpoint"""
        # Mock fact check agent response
        mock_fact_check_agent.return_value = {
            "claim": "The Earth is flat",
            "analysis": "This claim is FALSE. Multiple sources of evidence contradict this statement.",
            "sources": [
                {"title": "NASA Earth Facts", "url": "https://nasa.gov/earth", "source": "NASA"},
                {"title": "Scientific Evidence", "url": "https://science.com/earth", "source": "Science"}
            ],
            "model_used": "mistral",
            "timestamp": "2024-01-01T12:00:00"
        }
        
        # Test request
        response = client.post("/api/fact-check", json={
            "claim": "The Earth is flat",
            "model": "mistral"
        })
        
        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["claim"] == "The Earth is flat"
        assert "FALSE" in data["analysis"]
        assert len(data["sources"]) == 2
        assert data["model_used"] == "mistral"
        
        # Verify fact check agent was called
        mock_fact_check_agent.assert_called_once_with("The Earth is flat", "mistral")
    
    @patch('agent_research.fact_check_agent')
    def test_fact_check_error(self, mock_fact_check_agent, client):
        """Test fact check endpoint error handling"""
        # Mock fact check agent to raise exception
        mock_fact_check_agent.side_effect = Exception("Fact check service unavailable")
        
        # Test request
        response = client.post("/api/fact-check", json={
            "claim": "Test claim",
            "model": "mistral"
        })
        
        # Assertions
        assert response.status_code == 500
    
    @patch('agent_research.comparative_research_agent')
    def test_comparative_research_success(self, mock_comparative_agent, client):
        """Test successful comparative research endpoint"""
        # Mock comparative research agent response
        mock_comparative_agent.return_value = {
            "topics": ["Python", "JavaScript", "Rust"],
            "individual_research": {
                "Python": "Python is a high-level programming language...",
                "JavaScript": "JavaScript is a dynamic programming language...",
                "Rust": "Rust is a systems programming language..."
            },
            "comparative_analysis": "These languages differ significantly in their design philosophy...",
            "model_used": "mistral",
            "timestamp": "2024-01-01T12:00:00"
        }
        
        # Test request
        response = client.post("/api/comparative-research", json={
            "topics": ["Python", "JavaScript", "Rust"],
            "model": "mistral"
        })
        
        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["topics"] == ["Python", "JavaScript", "Rust"]
        assert "Python" in data["individual_research"]
        assert "JavaScript" in data["individual_research"]
        assert "Rust" in data["individual_research"]
        assert "design philosophy" in data["comparative_analysis"]
        
        # Verify comparative agent was called
        mock_comparative_agent.assert_called_once_with(["Python", "JavaScript", "Rust"], "mistral")
    
    def test_comparative_research_insufficient_topics(self, client):
        """Test comparative research endpoint with insufficient topics"""
        # Test request with only one topic
        response = client.post("/api/comparative-research", json={
            "topics": ["Python"],
            "model": "mistral"
        })
        
        # Assertions
        assert response.status_code == 400
        data = response.json()
        assert "At least 2 topics are required" in data["detail"]
    
    @patch('agent_research.comparative_research_agent')
    def test_comparative_research_error(self, mock_comparative_agent, client):
        """Test comparative research endpoint error handling"""
        # Mock comparative agent to raise exception
        mock_comparative_agent.side_effect = Exception("Comparative research service unavailable")
        
        # Test request
        response = client.post("/api/comparative-research", json={
            "topics": ["Python", "JavaScript"],
            "model": "mistral"
        })
        
        # Assertions
        assert response.status_code == 500

class TestResearchAPIModels:
    """Test Pydantic models for research endpoints"""
    
    def test_research_chat_request_model(self):
        """Test ResearchChatRequest model validation"""
        from main import ResearchChatRequest
        
        # Valid request
        request = ResearchChatRequest(
            message="Test message",
            model="mistral",
            history=[],
            enableWebSearch=True
        )
        
        assert request.message == "Test message"
        assert request.model == "mistral"
        assert request.history == []
        assert request.enableWebSearch == True
    
    def test_fact_check_request_model(self):
        """Test FactCheckRequest model validation"""
        from main import FactCheckRequest
        
        # Valid request
        request = FactCheckRequest(
            claim="Test claim",
            model="mistral"
        )
        
        assert request.claim == "Test claim"
        assert request.model == "mistral"
    
    def test_comparative_research_request_model(self):
        """Test ComparativeResearchRequest model validation"""
        from main import ComparativeResearchRequest
        
        # Valid request
        request = ComparativeResearchRequest(
            topics=["Topic A", "Topic B"],
            model="mistral"
        )
        
        assert request.topics == ["Topic A", "Topic B"]
        assert request.model == "mistral"