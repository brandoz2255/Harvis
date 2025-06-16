# LLM Integration

This document details the integration of the Ollama LLM (Large Language Model) in the AI Voice Assistant project.

## Overview

The LLM integration enables:
- Natural language understanding
- Context-aware responses
- Command interpretation
- Conversation management
- Dynamic response generation

## Implementation

### Core Components

```python
import requests
import logging

# Configuration
OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "mistral"

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_ollama_status():
    """Check if Ollama server is running."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags")
        return response.ok
    except requests.exceptions.RequestException:
        return False

def fetch_ollama_models():
    """Fetch available Ollama models."""
    if not check_ollama_status():
        logger.error("Ollama server is not running")
        return [], "⚠️ Ollama server is not running"

    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags")
        if not response.ok:
            return [], f"Error: {response.status_code} - {response.text}"
        
        models = [m["name"] for m in response.json().get("models", [])]
        return models, None
    except Exception as e:
        logger.error(f"Failed to fetch models: {e}")
        return [], str(e)
```

## Key Features

### 1. Model Management

```python
def load_model(model_name: str = DEFAULT_MODEL):
    """Load an Ollama model."""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": model_name}
        )
        if not response.ok:
            raise Exception(f"Failed to load model: {response.text}")
        return True
    except Exception as e:
        logger.error(f"Model loading error: {e}")
        raise
```

### 2. Response Generation

```python
def generate_response(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Generate a response using Ollama."""
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload
        )
        
        if not response.ok:
            raise Exception(f"Generation failed: {response.text}")
            
        return response.json()["response"]
    except Exception as e:
        logger.error(f"Response generation error: {e}")
        raise
```

### 3. Context Management

```python
class ConversationContext:
    def __init__(self, max_history: int = 10):
        self.history = []
        self.max_history = max_history
        
    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_history:
            self.history.pop(0)
            
    def get_context(self) -> str:
        """Get formatted conversation context."""
        return "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in self.history
        ])
```

## Error Handling

### Common Issues

1. **Server Connection**
   - Server not running
   - Network issues
   - Timeout errors
   - Authentication problems

2. **Model Operations**
   - Model not found
   - Loading failures
   - Memory issues
   - Version conflicts

3. **Response Generation**
   - Timeout errors
   - Invalid responses
   - Context issues
   - Memory constraints

### Error Recovery

```python
def handle_llm_error(error):
    """Handle LLM-related errors."""
    logger.error(f"LLM error: {error}")

    if "connection" in str(error).lower():
        return retry_connection()
    elif "model" in str(error).lower():
        return reload_model()
    elif "timeout" in str(error).lower():
        return retry_with_timeout()
    elif "cuda" in str(error).lower():
        # Fallback to CPU if CUDA error occurs
        return switch_to_cpu()
    else:
        return fallback_response()
```

## Performance Optimization

### 1. Response Caching

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_generate(prompt: str, model: str) -> str:
    """Cache generated responses."""
    return generate_response(prompt, model)
```

### 2. Context Optimization

```python
def optimize_context(context: str, max_length: int = 1000) -> str:
    """Optimize context length."""
    if len(context) <= max_length:
        return context
        
    # Truncate while preserving important information
    return context[-max_length:]
```

## Best Practices

### 1. Code Organization

- Separate LLM operations
- Clear interfaces
- Consistent error handling
- Resource management

### 2. Error Handling

- Comprehensive try-catch
- Detailed logging
- User feedback
- Recovery mechanisms

### 3. Performance

- Response caching
- Context optimization
- Memory management
- Timeout handling

## Testing

### 1. Unit Tests

```python
def test_llm_operations():
    """Test LLM operations."""
    # Test model loading
    assert load_model("mistral") is True
    
    # Test response generation
    response = generate_response("Hello, how are you?")
    assert isinstance(response, str)
    assert len(response) > 0
    
    # Test context management
    context = ConversationContext()
    context.add_message("user", "Hello")
    assert len(context.history) == 1
```

### 2. Integration Tests

- End-to-end testing
- Error scenario testing
- Performance testing
- Resource usage testing

## Interview Preparation

### Technical Questions

1. How is the LLM integrated?
2. What strategies handle errors?
3. How is performance optimized?
4. What are the security considerations?
5. How is the system tested?

### Implementation Questions

1. Why was Ollama chosen?
2. How is context managed?
3. What are the failure points?
4. How is the system scaled?
5. What are the alternatives?

### Architecture Questions

1. How is the LLM integrated?
2. What is the data flow?
3. How is state managed?
4. What are the security risks?
5. How is the system monitored?

## Common Use Cases

### 1. Basic Conversation

```python
# Simple conversation
response = generate_response("Hello, how are you?")
print(response)
```

### 2. Contextual Response

```python
# Contextual conversation
context = ConversationContext()
context.add_message("user", "What's the weather?")
context.add_message("assistant", "I don't have access to weather data.")
context.add_message("user", "Then what can you do?")

response = generate_response(context.get_context())
print(response)
```

### 3. Command Interpretation

```python
# Command interpretation
command = "open a new tab and search for python tutorials"
response = generate_response(f"Interpret this command: {command}")
print(response)
```

## Security Considerations

### 1. Input Validation

```python
def validate_prompt(prompt: str) -> bool:
    """Validate prompt content."""
    # Check for malicious content
    if len(prompt) > 10000:  # Max length
        return False
    if any(char in prompt for char in ["<", ">", "{", "}"]):
        return False
    return True
```

### 2. Response Sanitization

```python
def sanitize_response(response: str) -> str:
    """Sanitize LLM response."""
    # Remove potentially harmful content
    response = response.replace("<script>", "")
    response = response.replace("</script>", "")
    return response
```

### 3. Resource Management

```python
def manage_llm_resources():
    """Manage LLM resources."""
    # Clear response cache
    cached_generate.cache_clear()
    
    # Clear conversation history
    if 'context' in globals():
        context.history.clear()
```
