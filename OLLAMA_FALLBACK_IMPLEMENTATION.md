# Ollama Cloud/Local Fallback Implementation

## Overview

This implementation provides automatic fallback between cloud and local Ollama instances for AI model requests. The system tries the cloud Ollama service first and automatically falls back to the local instance if the cloud service is unavailable.

## Configuration

### Environment Variables

- `OLLAMA_API_KEY`: API key for the cloud Ollama service (defaults to "key")
- Cloud URL: `https://coyotegpt.ngrok.app/ollama`
- Local URL: `http://ollama:11434`

### Default Model

- `DEFAULT_MODEL`: `llama3.2:3b`

## Implementation Details

### Core Functions

1. **`make_ollama_request(endpoint, payload, timeout=90)`**
   - Makes POST requests with automatic fallback
   - Tries cloud first, then local
   - Returns the successful response object

2. **`make_ollama_get_request(endpoint, timeout=10)`**
   - Makes GET requests with automatic fallback
   - Used for listing models and health checks

3. **`get_ollama_url()`**
   - Determines which Ollama instance is available
   - Returns the working URL for initialization

### Files Updated

1. **`python_back_end/main.py`**
   - ✅ Added fallback functions
   - ✅ Updated chat endpoint to use `make_ollama_request()`

2. **`python_back_end/ollama_cli/vibe_agent.py`**
   - ✅ Added fallback functions
   - ✅ Updated `_generate_plan()` method
   - ✅ Updated `_diagnose_and_fix()` method

3. **`python_back_end/n8n/automation_service.py`**
   - ✅ Added fallback functions
   - ✅ Updated `_analyze_user_prompt()` method

4. **`python_back_end/research/research_agent.py`**
   - ✅ Added fallback functions
   - ✅ Updated `query_llm()` method

## Features

### Automatic Fallback
- **Cloud First**: Always tries the cloud service first for better performance
- **Local Fallback**: Automatically switches to local if cloud fails
- **Transparent**: No changes needed in calling code

### Logging
- **Detailed Logging**: Each step is logged with emojis for easy identification
- **Status Tracking**: Clear indication of which service is being used
- **Error Reporting**: Detailed error messages for troubleshooting

### Authentication
- **API Key Support**: Automatic authentication for cloud service
- **Conditional Headers**: Only adds auth headers when API key is provided

## Usage Examples

### Basic Chat Request
```python
payload = {
    "model": "llama3.2:3b",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ],
    "stream": False
}

response = make_ollama_request("/api/chat", payload)
content = response.json().get("message", {}).get("content", "")
```

### List Available Models
```python
response = make_ollama_get_request("/api/tags")
models = response.json().get("models", [])
```

### Get Working URL
```python
working_url = get_ollama_url()
print(f"Using Ollama at: {working_url}")
```

## Testing

A test script is provided at `python_back_end/test_ollama_fallback.py` to verify the implementation:

```bash
cd python_back_end
python test_ollama_fallback.py
```

## Benefits

1. **High Availability**: Service continues even if one instance fails
2. **Performance**: Cloud service provides better performance when available
3. **Reliability**: Local fallback ensures service continuity
4. **Transparency**: Existing code works without modifications
5. **Monitoring**: Clear logging for operational visibility

## Error Handling

- **Connection Errors**: Automatically tries the fallback service
- **HTTP Errors**: Logs status codes and attempts fallback
- **Timeout Handling**: Configurable timeouts for each service
- **Authentication Errors**: Proper error reporting for auth issues

## Deployment Considerations

1. **Cloud Service**: Ensure the ngrok tunnel is stable and accessible
2. **Local Service**: Verify local Ollama container is running
3. **Network**: Check firewall rules for both services
4. **API Keys**: Ensure OLLAMA_API_KEY is properly set in production
5. **Monitoring**: Monitor logs for fallback frequency and errors

## Future Enhancements

- **Load Balancing**: Distribute requests across multiple instances
- **Health Checks**: Periodic health monitoring of services
- **Circuit Breaker**: Temporary disable failing services
- **Metrics**: Collect performance and availability metrics
- **Configuration**: Runtime configuration updates without restart