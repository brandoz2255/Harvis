# Research API Endpoints

Complete API reference for the Enhanced Research System endpoints.

## Overview

The Enhanced Research System provides both backward-compatible endpoints and advanced research capabilities through a unified FastAPI interface. All endpoints support both simple research (using existing pipeline) and advanced research (using enhanced pipeline with ranking, synthesis, and verification).

## Base URL

```
http://localhost:8000/api
```

## Authentication

All research endpoints require authentication. Include the JWT token in the Authorization header:

```http
Authorization: Bearer <your_jwt_token>
```

## Endpoint Categories

- **Core Research** - Primary research functionality
- **Specialized Research** - Fact-checking and comparative analysis  
- **Advanced Features** - Streaming, statistics, and health monitoring
- **Content Processing** - Web search and content extraction

---

## Core Research Endpoints

### 1. Research Chat

**Endpoint:** `POST /research-chat`

Enhanced research chat with comprehensive web search and analysis.

#### Request

```json
{
  "message": "What are the latest developments in quantum computing?",
  "history": [],
  "model": "mistral",
  "use_advanced": false,
  "enableWebSearch": true
}
```

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `message` | string | Yes | - | Research question or query |
| `history` | array | No | `[]` | Chat history for context |
| `model` | string | No | `"mistral"` | LLM model to use |
| `use_advanced` | boolean | No | `false` | Enable advanced pipeline |
| `enableWebSearch` | boolean | No | `true` | Enable web search |

#### Response

```json
{
  "message": "Based on recent research, quantum computing has made significant breakthroughs...",
  "history": [...],
  "audio_path": "/api/audio/response_1234567890.wav",
  "model_used": "mistral",
  "sources_found": 15,
  "advanced": false,
  "search_results": [
    {
      "title": "Quantum Computing Breakthrough 2024",
      "url": "https://example.com/quantum-news",
      "snippet": "Recent advances in quantum error correction...",
      "relevance_score": 0.95
    }
  ]
}
```

#### Example Usage

```javascript
// Simple research
const response = await fetch('/api/research-chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    message: "Explain machine learning algorithms",
    model: "mistral"
  })
});

// Advanced research with streaming
const response = await fetch('/api/research-chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    message: "Compare different renewable energy sources",
    model: "mistral",
    use_advanced: true,
    enableWebSearch: true
  })
});
```

---

### 2. Advanced Research (Streaming)

**Endpoint:** `POST /research-advanced`

Advanced research with streaming progress updates and enhanced verification.

#### Request

```json
{
  "message": "Analyze the impact of AI on healthcare",
  "model": "mistral",
  "use_advanced": true,
  "enable_streaming": true
}
```

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `message` | string | Yes | - | Research query |
| `model` | string | No | `"mistral"` | LLM model |
| `use_advanced` | boolean | No | `true` | Force advanced pipeline |
| `enable_streaming` | boolean | No | `false` | Enable streaming |

#### Response (Non-streaming)

```json
{
  "response": "AI in healthcare has shown remarkable progress in diagnostic imaging, drug discovery, and personalized treatment plans. Recent studies indicate...",
  "sources_count": 23,
  "confidence_score": 0.87,
  "total_duration": 12.4,
  "verification_status": "high_confidence",
  "model_used": "mistral"
}
```

#### Response (Streaming)

Server-Sent Events stream:

```
data: {"event": "search_started", "query": "AI impact healthcare"}

data: {"event": "sources_found", "count": 15}

data: {"event": "ranking_complete", "top_sources": 8}

data: {"event": "synthesis_progress", "chunks_processed": 5, "total_chunks": 8}

data: {"event": "verification_complete", "confidence": 0.87}

data: {"event": "response_chunk", "content": "AI in healthcare has shown..."}

data: {"event": "complete", "total_duration": 12.4}
```

---

## Specialized Research Endpoints

### 3. Fact Check

**Endpoint:** `POST /fact-check`

Comprehensive fact-checking with evidence analysis and authority scoring.

#### Request

```json
{
  "claim": "Solar panels are 95% efficient",
  "model": "mistral",
  "use_advanced": false
}
```

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `claim` | string | Yes | - | Claim to fact-check |
| `model` | string | No | `"mistral"` | LLM model |
| `use_advanced` | boolean | No | `false` | Enable advanced fact-checking |

#### Response

```json
{
  "claim": "Solar panels are 95% efficient",
  "verdict": "FALSE",
  "confidence": 0.92,
  "analysis": "Current commercial solar panels typically achieve 15-22% efficiency, with the most advanced laboratory cells reaching about 47%. The claim of 95% efficiency is not supported by current technology.",
  "evidence": [
    {
      "source": "NREL Solar Cell Efficiency Records",
      "url": "https://www.nrel.gov/pv/cell-efficiency.html",
      "authority_score": 0.95,
      "relevance": 0.98,
      "quote": "The highest confirmed conversion efficiency for any photovoltaic device is 47.6%"
    }
  ],
  "authority_analysis": {
    "high_authority_sources": 8,
    "peer_reviewed_sources": 5,
    "government_sources": 3
  },
  "model_used": "mistral",
  "advanced": false
}
```

---

### 4. Comparative Research

**Endpoint:** `POST /comparative-research`

Multi-dimensional comparison analysis of different topics or concepts.

#### Request

```json
{
  "topics": ["Solar Power", "Wind Power", "Nuclear Power"],
  "context": "renewable energy comparison for large-scale deployment",
  "model": "mistral",
  "use_advanced": false
}
```

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `topics` | array | Yes | - | List of topics to compare |
| `context` | string | No | `null` | Comparison context |
| `model` | string | No | `"mistral"` | LLM model |
| `use_advanced` | boolean | No | `false` | Enable advanced comparison |

#### Response

```json
{
  "topics": ["Solar Power", "Wind Power", "Nuclear Power"],
  "context": "renewable energy comparison for large-scale deployment",
  "comparison": {
    "overview": "This analysis compares three major energy sources for large-scale deployment...",
    "dimensions": [
      {
        "name": "Cost Effectiveness",
        "solar_power": {
          "score": 8.5,
          "analysis": "Solar costs have dropped 90% since 2010...",
          "evidence": ["LCOE data", "Installation trends"]
        },
        "wind_power": {
          "score": 8.0,
          "analysis": "Wind power remains cost-competitive...",
          "evidence": ["Capacity factor data", "Grid integration"]
        },
        "nuclear_power": {
          "score": 6.5,
          "analysis": "High upfront costs but stable long-term...",
          "evidence": ["Construction costs", "Operating expenses"]
        }
      }
    ],
    "recommendations": {
      "best_overall": "Solar Power",
      "best_for_baseload": "Nuclear Power",
      "best_for_scalability": "Wind Power"
    }
  },
  "sources_per_topic": {
    "Solar Power": 12,
    "Wind Power": 10,
    "Nuclear Power": 8
  },
  "model_used": "mistral",
  "advanced": false
}
```

---

## Advanced Features Endpoints

### 5. Research Statistics

**Endpoint:** `GET /research-stats`

Get detailed statistics about research system performance and usage.

#### Response

```json
{
  "search_engine": "duckduckgo",
  "default_model": "mistral",
  "max_search_results": 20,
  "advanced_features_enabled": true,
  "cache_stats": {
    "total_requests": 1205,
    "cache_hits": 823,
    "cache_hit_rate": 0.683,
    "cache_size_mb": 45.2,
    "expired_entries": 12
  },
  "pipeline_stats": {
    "total_research_requests": 89,
    "advanced_requests": 34,
    "average_response_time": 8.7,
    "success_rate": 0.955,
    "top_models": {
      "mistral": 45,
      "llama2": 32,
      "codellama": 12
    }
  },
  "search_stats": {
    "total_searches": 156,
    "average_results_per_search": 18.3,
    "sources_extracted": 2847,
    "extraction_success_rate": 0.892
  }
}
```

---

### 6. Health Check

**Endpoint:** `GET /research-health`

System health status for monitoring and debugging.

#### Response

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:45Z",
  "components": {
    "ollama_client": {
      "status": "healthy",
      "url": "http://ollama:11434",
      "response_time_ms": 45,
      "available_models": ["mistral", "llama2", "codellama"]
    },
    "search_engine": {
      "status": "healthy",
      "type": "duckduckgo",
      "last_search_success": true,
      "response_time_ms": 320
    },
    "cache_system": {
      "status": "healthy",
      "cache_size": 1024,
      "free_space_mb": 2048,
      "last_cleanup": "2024-01-15T10:15:22Z"
    },
    "advanced_pipeline": {
      "status": "healthy",
      "ranker": "ready",
      "synthesizer": "ready",
      "verifier": "ready"
    }
  },
  "system_info": {
    "python_version": "3.11.5",
    "dependencies_status": "all_satisfied",
    "memory_usage_mb": 256,
    "uptime_seconds": 86400
  }
}
```

---

## Content Processing Endpoints

### 7. Web Search

**Endpoint:** `POST /web-search`

Basic web search functionality without AI analysis.

#### Request

```json
{
  "query": "quantum computing applications",
  "max_results": 10,
  "extract_content": true
}
```

#### Response

```json
{
  "query": "quantum computing applications",
  "search_results": [
    {
      "title": "Quantum Computing Applications in Finance",
      "url": "https://example.com/quantum-finance",
      "snippet": "Quantum algorithms can optimize portfolio management...",
      "source": "DuckDuckGo",
      "relevance_score": 0.92
    }
  ],
  "extracted_content": [
    {
      "url": "https://example.com/quantum-finance",
      "title": "Full Article Title",
      "content": "Complete article text content...",
      "word_count": 1247,
      "extraction_success": true
    }
  ],
  "total_results": 10,
  "extraction_success_rate": 0.8
}
```

---

## Error Handling

All endpoints return consistent error responses:

### Error Response Format

```json
{
  "error": "Error message",
  "error_code": "RESEARCH_ERROR",
  "details": {
    "component": "search_engine",
    "reason": "Rate limit exceeded",
    "retry_after": 60
  },
  "timestamp": "2024-01-15T10:30:45Z"
}
```

### Common Error Codes

| Error Code | Description | HTTP Status |
|------------|-------------|-------------|
| `AUTHENTICATION_REQUIRED` | Missing or invalid JWT token | 401 |
| `INVALID_REQUEST` | Malformed request body | 400 |
| `RESEARCH_ERROR` | General research pipeline failure | 500 |
| `SEARCH_UNAVAILABLE` | Web search service unavailable | 503 |
| `MODEL_UNAVAILABLE` | Requested LLM model not available | 503 |
| `RATE_LIMIT_EXCEEDED` | Too many requests | 429 |
| `CONTENT_EXTRACTION_FAILED` | Unable to extract web content | 502 |

---

## Rate Limiting

The API implements rate limiting to prevent abuse:

- **General endpoints**: 100 requests per minute per user
- **Research endpoints**: 20 requests per minute per user  
- **Streaming endpoints**: 5 concurrent streams per user

Rate limit headers are included in responses:

```http
X-RateLimit-Limit: 20
X-RateLimit-Remaining: 17
X-RateLimit-Reset: 1705315845
```

---

## SDK Examples

### Python SDK Usage

```python
import httpx
import asyncio
from typing import Dict, Any

class ResearchClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {token}"}
    
    async def research(self, query: str, use_advanced: bool = False) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/research-chat",
                json={
                    "message": query,
                    "use_advanced": use_advanced
                },
                headers=self.headers
            )
            return response.json()
    
    async def fact_check(self, claim: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/fact-check",
                json={"claim": claim, "use_advanced": True},
                headers=self.headers
            )
            return response.json()

# Usage
client = ResearchClient("http://localhost:8000/api", "your_jwt_token")
result = await client.research("Explain quantum entanglement")
```

### JavaScript/TypeScript SDK

```typescript
interface ResearchClient {
  baseUrl: string;
  token: string;
}

class EnhancedResearchAPI {
  constructor(private config: ResearchClient) {}
  
  async research(query: string, options: {
    useAdvanced?: boolean;
    model?: string;
    enableStreaming?: boolean;
  } = {}) {
    const response = await fetch(`${this.config.baseUrl}/research-chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.token}`
      },
      body: JSON.stringify({
        message: query,
        use_advanced: options.useAdvanced || false,
        model: options.model || 'mistral',
        enable_streaming: options.enableStreaming || false
      })
    });
    
    return response.json();
  }
  
  async factCheck(claim: string): Promise<any> {
    const response = await fetch(`${this.config.baseUrl}/fact-check`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.token}`
      },
      body: JSON.stringify({ claim, use_advanced: true })
    });
    
    return response.json();
  }
  
  async streamResearch(query: string): Promise<ReadableStream> {
    const response = await fetch(`${this.config.baseUrl}/research-advanced`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.token}`
      },
      body: JSON.stringify({
        message: query,
        enable_streaming: true
      })
    });
    
    return response.body;
  }
}

// Usage
const api = new EnhancedResearchAPI({
  baseUrl: 'http://localhost:8000/api',
  token: 'your_jwt_token'
});

const result = await api.research('Machine learning trends 2024');
const factCheck = await api.factCheck('The Earth is flat');
```

---

## Testing Examples

### Integration Test Examples

```python
import pytest
import httpx
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_research_chat():
    response = client.post(
        "/api/research-chat",
        json={
            "message": "What is artificial intelligence?",
            "model": "mistral"
        },
        headers={"Authorization": "Bearer test_token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "sources_found" in data
    assert data["model_used"] == "mistral"

def test_fact_check_advanced():
    response = client.post(
        "/api/fact-check",
        json={
            "claim": "Water boils at 100°C",
            "use_advanced": True
        },
        headers={"Authorization": "Bearer test_token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "verdict" in data
    assert "confidence" in data
    assert "evidence" in data

def test_comparative_research():
    response = client.post(
        "/api/comparative-research",
        json={
            "topics": ["Python", "JavaScript"],
            "context": "programming languages for web development"
        },
        headers={"Authorization": "Bearer test_token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "comparison" in data
    assert "dimensions" in data["comparison"]
```

---

## Performance Considerations

### Optimization Tips

1. **Caching**: Use `use_advanced=true` to leverage HTTP caching
2. **Streaming**: Use streaming for long-running research queries
3. **Batch Requests**: Group multiple fact-checks into comparative research
4. **Model Selection**: Use appropriate models for task complexity
5. **Result Limits**: Adjust `max_search_results` based on quality needs

### Response Time Expectations

| Operation | Simple Mode | Advanced Mode |
|-----------|-------------|---------------|
| Basic Research | 3-8 seconds | 8-15 seconds |
| Fact Checking | 2-5 seconds | 5-12 seconds |
| Comparative Analysis | 5-12 seconds | 12-25 seconds |
| Web Search Only | 1-3 seconds | N/A |

### Resource Usage

- **Memory**: ~50-200MB per concurrent request
- **CPU**: Moderate usage during ranking/synthesis
- **Network**: Heavy during initial search, cached afterward
- **Storage**: Cache grows ~1-5MB per research session

---

## Changelog

### v1.0.0 (Current)
- Initial release of Enhanced Research System
- Backward compatible with existing research endpoints
- Advanced pipeline with ranking, synthesis, verification
- Streaming support and comprehensive error handling
- MCP server integration and statistics endpoints

### Planned Features
- Multi-modal research (image/video content analysis)
- Custom model fine-tuning for domain-specific research
- Collaborative research with shared contexts
- API versioning and migration tools
- Enhanced visualization and reporting