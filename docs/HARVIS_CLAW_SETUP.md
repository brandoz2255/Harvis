# Harvis Claw LLM Configuration Guide

## Overview

Harvis Claw (formerly Workspace) uses its own LLM for agentic tasks, separate from the main Harvis chat. This guide explains how to configure which LLM it uses.

## Quick Start

### For Docker Users (Laptop Setup)

The default configuration already points to Ollama:

```
Provider Type: Ollama (Local)
API URL: http://ollama:11434
Model: qwen2.5-coder:32b
API Key: (none required)
```

Just make sure Ollama is running in your Harvis stack and you're good to go!

---

## Configuration Options

### 1. Local Ollama (Recommended for Laptop Users)

**Settings:**
- **Provider Type**: Ollama (Local)
- **API URL**: `http://ollama:11434` (Docker) or `http://localhost:11434` (local)
- **Model**: Any model in your Ollama instance
- **API Key**: None required

**To find available models:**
```bash
# In your Ollama container or locally:
ollama list
```

**Popular models:**
- `qwen2.5-coder:32b` - Great for coding tasks
- `deepseek-r1:14b` - Reasoning model with thinking
- `llama3.1:70b` - General purpose
- `phi3:14b` - Lightweight but capable

### 2. Moonshot AI (Kimi)

**Settings:**
- **Provider Type**: Moonshot
- **API URL**: `https://api.moonshot.cn/v1`
- **Model**: `kimi-k2.5`
- **API Key**: Required

**Get API key:** https://platform.moonshot.cn/

### 3. OpenAI

**Settings:**
- **Provider Type**: OpenAI-Compatible
- **API URL**: `https://api.openai.com/v1`
- **Model**: `gpt-4o` or `gpt-4o-mini`
- **API Key**: Required

**Get API key:** https://platform.openai.com/

### 4. Anthropic

**Settings:**
- **Provider Type**: Anthropic
- **API URL**: `https://api.anthropic.com/v1`
- **Model**: `claude-sonnet-4-20250514`
- **API Key**: Required

**Get API key:** https://console.anthropic.com/

### 5. NVIDIA NIM

**Settings:**
- **Provider Type**: NVIDIA NIM
- **API URL**: `https://integrate.api.nvidia.com/v1`
- **Model**: `nvidia-kimi`
- **API Key**: Required

**Get API key:** https://build.nvidia.com/

### 6. Custom OpenAI-Compatible Endpoint

Use for LM Studio, vLLM, or any other OpenAI-compatible server.

**Settings:**
- **Provider Type**: OpenAI-Compatible
- **API URL**: Your server's `/v1` endpoint
- **Model**: As configured in your server
- **API Key**: If required by your server

---

## Configuration Steps

1. Navigate to **Profile** → **Settings** in Harvis
2. Find the **Harvis Claw LLM Configuration** section
3. Enter your settings:
   - Select provider type
   - Enter API endpoint URL
   - Enter model ID
   - Enter API key (if required)
4. Click **Save Configuration**
5. Restart Harvis Claw (Workspace) to apply changes

---

## Troubleshooting

### "Connection Failed" Error

1. Check the API URL is correct (include `/v1` path)
2. For local Ollama: Ensure Ollama is running and accessible
3. Check API key is correct (not the placeholder dots)

### "Model Not Found" Error

1. Verify the model ID matches exactly (case-sensitive)
2. For Ollama: Run `ollama list` to see exact model names
3. Ensure the model is pulled: `ollama pull <model-name>`

### "API Key Required" Error

1. Enter your API key in the API Key field
2. Cloud providers (OpenAI, Anthropic, etc.) require API keys
3. Local Ollama does NOT need an API key

---

## Ollama Model Download (Bonus)

For Docker users who want more models:

1. Open a terminal in your Ollama container:
```bash
docker exec -it harvis-ai-ollama-1 ollama run qwen2.5-coder:32b
```

Or pull models directly:
```bash
docker exec -it harvis-ai-ollama-1 ollama pull qwen2.5-coder:32b
docker exec -it harvis-ai-ollama-1 ollama pull deepseek-r1:14b
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Harvis Claw (OpenClaw)                   │
│   model: "harvis-proxy/harvis-llm"                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              Backend Model Proxy (model_proxy.py)          │
│   Reads config from database                               │
│   Routes to user's chosen LLM                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              User's Configured LLM                          │
│   (Ollama, Moonshot, OpenAI, Anthropic, etc.)            │
└─────────────────────────────────────────────────────────────┘
```

---

## Security Notes

1. **API keys are encrypted** in the database using Fernet encryption
2. Keys never leave the backend - they're used server-side only
3. For maximum security on K8s, use NetworkPolicy to restrict OpenClaw egress

---

## Need Help?

- Check the main Harvis documentation
- Open an issue on GitHub
- Ask in the community Discord
