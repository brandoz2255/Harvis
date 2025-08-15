# Research System Troubleshooting Guide

## Quick Diagnostics

### 1. Check Search Results
```bash
cd python_back_end
python -c "
from research.web_search import WebSearchAgent
agent = WebSearchAgent()
results = agent.search_web('your query here', 5)
print(f'Found {len(results)} results')
for i, r in enumerate(results, 1):
    print(f'{i}. {r.get(\"title\", \"No title\")} (Score: {r.get(\"relevance_score\", \"N/A\")})')
"
```

### 2. Monitor Logs
Check these log entries in your application logs:
- `Starting DDGS search for original query`
- `Scored X relevant results from Y total`
- `Generated search queries`

## Common Issues & Solutions

### Issue 1: No Search Results (0 results found)

**Symptoms:**
- Log shows "Scored 0 relevant results from X total"
- Empty response from research endpoints

**Causes & Solutions:**

1. **Relevance threshold too high**
   ```python
   # In web_search.py line ~290
   if score > 0.15:  # Should be 0.15, not higher
   ```

2. **Network/API issues**
   ```bash
   # Test DuckDuckGo connectivity
   python -c "from ddgs import DDGS; print(list(DDGS().text('test', max_results=1)))"
   ```

3. **Query optimization too aggressive**
   - Check log for "Original query -> Improved query" 
   - Ensure improved query isn't over-filtered

**Fix:**
```python
# Temporary fix - lower threshold in _score_and_filter_results
if score > 0.05:  # Very permissive for testing
```

### Issue 2: Only Dictionary/Translation Results

**Symptoms:**
- Results from leo.org, dict.cc, translate.google.com
- RELEVANCE ASSESSMENT shows "not relevant"

**Causes & Solutions:**

1. **Topic detection not working**
   ```python
   # Check _optimize_search_query logic
   # Ensure AI/tech terms are detected properly
   ai_terms = ['ai', 'artificial intelligence', 'machine learning', 'agentic']
   ```

2. **Authority domains not prioritized**
   ```python
   # Verify authority_domains list includes relevant sources
   authority_domains = [
       'github.com', 'arxiv.org', 'openai.com', 'huggingface.co'
   ]
   ```

**Fix:**
- Add more specific terms to topic detection
- Update authority domains for your field

### Issue 3: Bing Redirects Instead of DuckDuckGo

**Symptoms:**
- Log shows "response: https://www.bing.com/search"
- Inconsistent search results

**Solution:**
```python
# In search_web method, ensure backend="api" is set
search_results = list(ddgs.text(
    query, 
    max_results=max_results * 2,
    backend="api",  # This is crucial
    region="us-en",
    safesearch="moderate"
))
```

### Issue 4: Missing Source URLs in Final Output

**Symptoms:**
- Research response lacks "sources" field
- LLM analysis doesn't cite URLs

**Causes & Solutions:**

1. **include_sources parameter**
   ```python
   # Ensure research_topic is called with include_sources=True
   result = agent.research_topic(topic, model, "standard", include_sources=True)
   ```

2. **URL extraction fails**
   ```python
   # Check formatted_result creation in search_web
   formatted_result = {
       "url": result.get("href", result.get("link", "")),  # Fallback to "link"
   }
   ```

3. **LLM not citing sources**
   - Verify research prompt includes "ALWAYS cite the specific source URL"
   - Check if LLM is following the required format

### Issue 5: Rate Limiting Errors

**Symptoms:**
- "Rate limited by DuckDuckGo" in logs
- Intermittent search failures

**Solutions:**

1. **Add delays**
   ```python
   # Increase delay in search_web
   time.sleep(1.0)  # Instead of 0.5
   ```

2. **Reduce request frequency**
   ```python
   # Use fewer search queries
   final_queries = queries[:2]  # Instead of [:3]
   ```

3. **Implement caching**
   ```python
   # Add simple cache for repeated queries
   @lru_cache(maxsize=100)
   def cached_search(query: str):
       return self.search_web(query)
   ```

## Performance Tuning

### Search Parameters

```python
# Adjust these based on your needs
search_params = {
    "quick": {"max_results": 3, "extract_content": False},
    "standard": {"max_results": 5, "extract_content": True}, 
    "deep": {"max_results": 8, "extract_content": True}
}
```

### Relevance Scoring Weights

```python
# In _calculate_relevance_score, adjust these weights:
score += (title_matches / max(len(query_words), 1)) * 0.5    # Title weight
score += (snippet_matches / max(len(query_words), 1)) * 0.3  # Snippet weight
if any(domain in url for domain in authority_domains):
    score += 0.4  # Authority boost
```

### Topic Detection

```python
# Customize topic detection for your domain
ai_terms = ['ai', 'machine learning', 'agentic', 'llm', 'neural']
tech_terms = ['programming', 'python', 'api', 'docker']
academic_terms = ['research', 'paper', 'study', 'analysis']
```

## Debug Mode

Enable detailed logging:

```python
import logging
logging.getLogger('research.web_search').setLevel(logging.DEBUG)
logging.getLogger('research.research_agent').setLevel(logging.DEBUG)
```

Key debug outputs:
- Query transformations
- Raw search results
- Relevance scores
- LLM prompt and response

## Configuration Checklist

### Environment
- [ ] ddgs library installed (`pip install ddgs`)
- [ ] Network connectivity to search engines
- [ ] No proxy blocking search requests

### Code Configuration
- [ ] Relevance threshold set to 0.15 or lower
- [ ] Authority domains updated for your field
- [ ] Topic detection includes relevant terms
- [ ] LLM prompt requires source citations

### Search Strategy
- [ ] Query optimization enabled
- [ ] Fallback queries configured
- [ ] Rate limiting delays in place
- [ ] Backend set to "api" not default

## Error Messages & Meanings

| Error | Meaning | Solution |
|-------|---------|----------|
| `ModuleNotFoundError: ddgs` | Missing dependency | `pip install ddgs` |
| `Rate limited by DuckDuckGo` | Too many requests | Add delays, reduce frequency |
| `Scored 0 relevant results` | Threshold too high | Lower relevance threshold |
| `No valid queries extracted` | LLM query generation failed | Check fallback queries |
| `Failed to extract content` | URL parsing issues | Check newspaper3k installation |

## Testing Commands

### Full Research Test
```bash
cd python_back_end
python -c "
from research.research_agent import ResearchAgent
agent = ResearchAgent()
result = agent.research_topic('agentic AI projects', 'mistral', 'standard', True)
print(f'Sources found: {result[\"sources_found\"]}')
print(f'Analysis: {result[\"analysis\"][:200]}...')
"
```

### Search Engine Test
```bash
python -c "
from ddgs import DDGS
with DDGS() as ddgs:
    results = list(ddgs.text('test query', max_results=1, backend='api'))
    print(f'Success: {len(results)} results')
"
```

### Relevance Scoring Test
```bash
python -c "
from research.web_search import WebSearchAgent
agent = WebSearchAgent()
score = agent._calculate_relevance_score(
    {'title': 'AI Projects on GitHub', 'body': 'Machine learning code', 'href': 'github.com/test'},
    {'ai', 'projects'},
    'ai projects'
)
print(f'Relevance score: {score}')
"
```

## When to Contact Support

Contact the development team if:
- Search consistently returns 0 results after trying all solutions
- Rate limiting persists despite delays
- LLM analysis quality is poor despite good search results
- Critical authority domains are blocked or inaccessible

Include in your report:
- Search query attempted
- Full error logs
- Configuration used
- Expected vs actual results