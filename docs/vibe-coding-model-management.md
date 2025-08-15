# Vibe Coding Model Management & Import Fixes

## Overview
This document details the resolution of circular import issues and the implementation of intelligent model management for the vibe coding system.

## Problems Resolved

### 1. ChatterboxTTS Import Error
**Error**: `NameError: name 'ChatterboxTTS' is not defined`

**Root Cause**: 
- Duplicate model management functions in `main.py` and `model_manager.py`
- Missing ChatterboxTTS import in functions that referenced it
- Circular import between `vibe_agent.py` importing from `main.py`

### 2. Circular Import Issue
**Error**: Import cycle between `main.py` ↔ `vibe_agent.py`

**Root Cause**:
- `vibe_agent.py` was importing model management functions from `main.py`
- `main.py` was importing `VibeAgent` class from `vibe_agent.py`

## Solutions Implemented

### 1. Consolidated Model Management
**File**: `/python_back_end/model_manager.py`

Created centralized model management module with:
- ✅ All TTS/Whisper loading functions
- ✅ GPU memory monitoring and cleanup
- ✅ Proper ChatterboxTTS import handling
- ✅ Error handling for CUDA fallbacks

```python
# Key functions in model_manager.py
def load_tts_model(force_cpu=False)
def load_whisper_model()
def unload_models()
def unload_all_models()
def reload_models_if_needed()
def generate_speech(text, model=None, ...)
```

### 2. Removed Duplicate Functions
**File**: `/python_back_end/main.py`

**Removed**:
- Duplicate `log_gpu_memory()` function
- Duplicate `unload_models()` function  
- Duplicate `unload_all_models()` function
- Duplicate `reload_models_if_needed()` function
- Duplicate `load_tts_model()` function
- Duplicate `generate_speech()` function
- Global `tts_model` and `whisper_model` variables

**Updated**:
- All model references to use `get_tts_model()` and `get_whisper_model()`
- Import statements to use model_manager functions

### 3. Fixed Circular Imports
**File**: `/python_back_end/ollama_cli/vibe_agent.py`

**Changed import from**:
```python
from main import unload_all_models, reload_models_if_needed, log_gpu_memory
```

**To**:
```python
from model_manager import unload_all_models, reload_models_if_needed, log_gpu_memory
```

### 4. Safe VibeAgent Initialization
**File**: `/python_back_end/main.py`

Added error handling for VibeAgent initialization:
```python
try:
    vibe_agent = VibeAgent(project_dir=os.getcwd())
    logger.info("✅ VibeAgent initialized successfully")
except Exception as e:
    logger.error(f"❌ Failed to initialize VibeAgent: {e}")
    vibe_agent = None
```

## Model Management Flow

### 1. Vibe Coding Execution
```
User Request → Frontend → /api/vibe-coding → Backend Processing:

1. 🗑️ unload_all_models() - Free GPU memory
2. 🤖 Mistral LLM - Generate code plan  
3. 🔄 reload_models_if_needed() - Restore TTS/Whisper
4. 🔊 TTS - Generate voice response
```

### 2. Voice Processing
```
Voice Input → /api/voice-transcribe → Processing:

1. 🎤 get_whisper_model() - Load if needed
2. 📝 Transcribe audio to text
3. 🔄 Keep models loaded for TTS response
```

### 3. Memory Optimization
```
Vision Processing → Screen Analysis:

1. 🗑️ unload_all_models() - Free maximum memory
2. 👁️ Load Qwen2VL for screen analysis
3. 🔄 unload_qwen_model() - Clean up vision model
4. 🤖 LLM processing with freed memory
5. 🔄 reload_models_if_needed() - Restore audio models
```

## API Endpoints Fixed

### ✅ Working Endpoints
- `/api/vibe-coding` - AI-powered coding with model management
- `/api/voice-transcribe` - Voice to text with Whisper
- `/api/run-command` - Execute shell commands
- `/api/save-file` - Save generated code files

### ✅ Frontend Integration
- Vibe Coding Page: `/vibe-coding`
- Voice recording and transcription
- Real-time AI coding assistance
- Terminal output display
- File management interface

## Testing Verification

### Import Test
```bash
python3 -c "from main import app; print('✅ main.py imports successfully')"
```

### Model Loading Test
```python
from model_manager import get_tts_model, get_whisper_model
tts = get_tts_model()  # Should load without ChatterboxTTS error
whisper = get_whisper_model()  # Should load Whisper model
```

## Performance Benefits

### 1. Memory Efficiency
- **Before**: Models stayed loaded, causing CUDA OOM errors
- **After**: Intelligent unloading/reloading based on processing phase

### 2. Import Performance  
- **Before**: Circular import errors and startup failures
- **After**: Clean module separation and fast startup

### 3. Error Handling
- **Before**: Hard crashes on model loading failures
- **After**: Graceful fallback to CPU, proper error reporting

## Troubleshooting

### If ChatterboxTTS errors return:
1. Check `model_manager.py` has proper ChatterboxTTS import
2. Verify no duplicate model functions in `main.py`
3. Ensure `vibe_agent.py` imports from `model_manager` not `main`

### If circular import errors return:
1. Check import paths in `vibe_agent.py`
2. Verify `main.py` doesn't import from modules that import from it
3. Use model_manager as the central import hub

### If GPU memory errors return:
1. Verify `unload_all_models()` is called before vision processing
2. Check `reload_models_if_needed()` is called after processing
3. Monitor GPU memory with `log_gpu_memory()` calls

## Related Files
- `/python_back_end/model_manager.py` - Central model management
- `/python_back_end/main.py` - Main FastAPI application  
- `/python_back_end/ollama_cli/vibe_agent.py` - Vibe coding agent
- `/front_end/jfrontend/app/vibe-coding/page.tsx` - Frontend interface

## Success Metrics
- ✅ No more ChatterboxTTS import errors
- ✅ No more circular import issues  
- ✅ Successful model loading/unloading
- ✅ Working vibe coding system end-to-end
- ✅ Efficient GPU memory usage
- ✅ Stable voice processing pipeline