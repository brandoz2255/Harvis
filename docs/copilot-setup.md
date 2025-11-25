# Copilot Setup Guide

This guide explains how to set up and configure the AI Copilot features in the Harvis AI IDE.

## Overview

The IDE includes several Copilot-style AI features:

1. **Inline Completions**: Ghost text suggestions that appear as you type (600ms debounce)
2. **TODO Comment Detection**: Automatically proposes code changes when you write `// TODO: instruction`
3. **Quick Propose Shortcut**: Press `Ctrl+Shift+I` (or `Cmd+Shift+I` on Mac) to quickly propose changes
4. **AI Assistant Auto-Propose**: Automatically proposes diff when AI provides code in chat
5. **Model Selection**: Choose between different models for completions vs. chat

## Fast Code Completion Models

For optimal inline completion performance, we recommend using specialized code models:

### DeepSeek Coder (Recommended)

DeepSeek Coder is optimized for fast, accurate code completions:

```bash
# Pull the 6.7B model (recommended)
docker exec ollama ollama pull deepseek-coder:6.7b

# Or pull the 1.3B model (faster, less accurate)
docker exec ollama ollama pull deepseek-coder:1.3b

# Or pull the 33B model (slower, more accurate)
docker exec ollama ollama pull deepseek-coder:33b
```

### CodeLlama (Alternative)

CodeLlama is Meta's code-specialized model:

```bash
# Pull the 7B model (recommended)
docker exec ollama ollama pull codellama:7b

# Or pull the 13B model
docker exec ollama ollama pull codellama:13b
```

### Model Comparison

| Model | Size | Speed | Accuracy | Use Case |
|-------|------|-------|----------|----------|
| deepseek-coder:1.3b | 1.3B | ⚡⚡⚡ | ⭐⭐ | Very fast completions |
| deepseek-coder:6.7b | 6.7B | ⚡⚡ | ⭐⭐⭐⭐ | **Recommended** balanced |
| codellama:7b | 7B | ⚡⚡ | ⭐⭐⭐ | Alternative balanced |
| deepseek-coder:33b | 33B | ⚡ | ⭐⭐⭐⭐⭐ | Highest accuracy, slower |

## Configuration

### Backend Configuration (Optional)

You can configure default models via environment variables:

```bash
# In docker-compose.yaml or .env
COPILOT_MODEL=deepseek-coder:6.7b  # Fast model for inline completions
IDE_CHAT_MODEL=gpt-oss              # Comprehensive model for chat/proposals
```

### Frontend Model Selection

In the IDE, you can select the Copilot model:

1. Open a file in the editor
2. Look for the "Copilot" selector in the top-right corner
3. Choose from:
   - **DeepSeek Coder 6.7B** (recommended for completions)
   - **Code Llama 7B** (alternative for completions)
   - **gpt-oss** (general purpose)
   - **mistral** (general purpose)
4. Your selection is saved automatically

## Features Configuration

### Inline Completions

- **Trigger**: Automatically after 600ms pause while typing
- **Accept**: Press `Tab`
- **Dismiss**: Press `Esc` or continue typing
- **Enable/Disable**: Use the ON/OFF toggle in the Copilot selector

### TODO Comment Detection

Automatically proposes changes when you write special comments:

```javascript
// TODO: add error handling for network requests
// FIXME: optimize this loop for better performance
// AI: refactor this function to use async/await
```

Supported formats:
- `// TODO:` (JavaScript, TypeScript, C++, etc.)
- `# TODO:` (Python, Ruby, Shell, etc.)
- `/* TODO: */` (Multi-line comments)

The detection triggers 1 second after you finish typing the comment.

**To disable**: Uncheck "Auto-propose" in the AI Assistant panel.

### Quick Propose Keyboard Shortcut

Press `Ctrl+Shift+I` (or `Cmd+Shift+I` on Mac) to:

1. Open a prompt dialog
2. Enter your instructions (e.g., "Add TypeScript types")
3. View the proposed changes in a diff viewer
4. Accept, reject, or merge the changes

Also available via Command Palette: `Ctrl+Shift+P` → "AI → Quick Propose"

### AI Assistant Auto-Propose

When enabled (default), the AI Assistant automatically:

1. Detects when it provides code in responses
2. Checks if you asked for code changes
3. Opens the diff viewer with proposed changes
4. Lets you accept or reject

**To disable**: Uncheck "Auto-propose" in the AI Assistant header.

## Model Parameters

The following parameters are optimized for fast code completions:

```python
{
  "temperature": 0.2,      # Low for deterministic suggestions
  "top_p": 0.15,          # Focused sampling
  "top_k": 5,             # Limited candidate pool
  "num_predict": 200,     # Max tokens for inline completions
  "stop": ["\n\n", "```", "###"]  # Stop sequences
}
```

For chat/proposals, different parameters are used for more comprehensive responses.

## Troubleshooting

### "Model not found" Error

If you get a model not found error:

```bash
# Check available models
docker exec ollama ollama list

# Pull the missing model
docker exec ollama ollama pull deepseek-coder:6.7b
```

### Slow Completions

If completions are slow:

1. Switch to a smaller model (e.g., `deepseek-coder:1.3b`)
2. Check system resources (CPU/GPU usage)
3. Verify Ollama container is running: `docker ps | grep ollama`

### Completions Not Appearing

1. Check Copilot is enabled (ON toggle)
2. Verify you have a file open and are typing
3. Wait for 600ms pause (stop typing briefly)
4. Check browser console for errors (F12)

### Auto-Propose Not Working

1. Check "Auto-propose" is enabled in AI Assistant
2. Verify TODO comment format: `// TODO: instruction`
3. Check localStorage: `localStorage.getItem('auto_propose_enabled')`
4. Wait 1 second after typing the comment

## Advanced Configuration

### Custom Model Parameters

To customize model parameters, edit `python_back_end/vibecoding/ide_ai.py`:

```python
COMPLETION_PARAMS = {
    "temperature": 0.2,
    "top_p": 0.15,
    "top_k": 5,
    "stop": ["\n\n", "```", "###"],
    "num_predict": 200
}
```

### Rate Limiting

Inline completions are rate-limited to prevent excessive API calls:

- Max 10 suggestions per minute per user
- Exceeded limit returns 429 error
- Adjust in `ide_ai.py`: `RATE_LIMIT_MAX` and `RATE_LIMIT_WINDOW`

## Best Practices

1. **Use specialized models for completions**: DeepSeek Coder or CodeLlama
2. **Use general models for chat**: gpt-oss or mistral
3. **Enable auto-propose for exploration**: Let AI suggest changes automatically
4. **Disable auto-propose for focused work**: Manually trigger proposals when needed
5. **Use TODO comments for large changes**: Let AI understand context from comments
6. **Use Quick Propose for small changes**: Ctrl+Shift+I for targeted edits

## See Also

- [Project Overview](./project-overview.md)
- [LLM Integration](./llm-integration.md)
- [System Architecture](./system-architecture.md)





