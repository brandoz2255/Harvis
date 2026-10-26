# Helm Chart Resource Fix Documentation

## Problem Summary

After a git pull and FluxCD update, the Harvis AI application was experiencing 502 errors and backend pod crashes. The application was inaccessible via its MetalLB LoadBalancer IP (10.20.0.201).

## Root Cause Analysis

### Primary Issue: Helm Template Resource Reference Bug

**Critical Bug**: The deployment template was referencing the wrong values path for resource allocation:

**File**: `templates/merged-ollama-backend-deployment.yaml`
**Line 91-97**:

```yaml
# WRONG - Referenced backend resources instead of mergedOllamaBackend
resources:
  {{ .Values.backend.resources | toYaml | nindent 12 }}
```

This caused all resource limit updates in `values.yaml` to be ignored, leaving the pods with insufficient memory.

### Secondary Issues

1. **Memory Constraints**: Backend limited to 2GB couldn't load TTS models alongside Ollama
2. **Ollama Endpoint Misconfiguration**: External endpoint returning HTML instead of JSON
3. **Missing Error Handling**: TTS failures caused pod crashes instead of graceful degradation

## Solution Implementation

### 1. Fix Helm Template Resource Reference

**File**: `templates/merged-ollama-backend-deployment.yaml`

**Before**:
```yaml
resources:
  {{ .Values.backend.resources | toYaml | nindent 12 }}
```

**After**:
```yaml
resources:
  requests:
    memory: {{ .Values.mergedOllamaBackend.resources.requests.memory }}
    cpu: {{ .Values.mergedOllamaBackend.resources.requests.cpu }}
  limits:
    memory: {{ .Values.mergedOllamaBackend.resources.limits.memory }}
    cpu: {{ .Values.mergedOllamaBackend.resources.limits.cpu }}
```

### 2. Update Resource Allocation

**File**: `values.yaml`

**Resource Configuration for High-Performance Hardware**:
```yaml
mergedOllamaBackend:
  resources:
    requests:
      cpu: 1000m      # 1 CPU core minimum
      memory: 8Gi     # 8GB RAM minimum
      nvidia.com/gpu: 1
    limits:
      cpu: 12000m     # 12 CPU cores maximum (50% of 24-core system)
      memory: 32Gi    # 32GB RAM maximum (50% of 64GB system)
      nvidia.com/gpu: 1
```

**Hardware Context**:
- AMD Ryzen 9 9900X (24 cores) @ 5.658GHz
- 64GB total system memory
- NVIDIA RTX 4090 (24GB VRAM)

### 3. Fix Ollama Endpoint Configuration

**File**: `values.yaml`

**Before**:
```yaml
backend:
  env:
    OLLAMA_CLOUD_URL: "http://ollama:11434"  # External endpoint
```

**After**:
```yaml
# Deployment template uses localhost since containers share network
OLLAMA_URL: "http://localhost:11434"
```

### 4. Add Comprehensive Error Handling

**File**: `python_back_end/model_manager.py`

Added CUDA diagnostics and graceful TTS failure handling:
```python
# COMPREHENSIVE CUDA DIAGNOSTICS
logger.info("🔧 Starting comprehensive CUDA diagnostics for TTS...")
if torch.cuda.is_available():
    try:
        logger.info(f"📊 CUDA Device Count: {torch.cuda.device_count()}")
        logger.info(f"📊 Current CUDA Device: {torch.cuda.current_device()}")
        logger.info(f"📊 CUDA Device Name: {torch.cuda.get_device_name()}")
        test_tensor = torch.ones(100, device='cuda')
        logger.info(f"✅ Basic CUDA tensor creation successful: {test_tensor.device}")
        del test_tensor
    except Exception as cuda_test_e:
        logger.error(f"❌ Basic CUDA test failed: {cuda_test_e}")

# Graceful TTS failure handling
except Exception as cuda_load_e:
    signal.alarm(0)  # Cancel timeout
    logger.error(f"❌ TTS CUDA loading failed: {cuda_load_e}")
    logger.error(f"❌ Exception type: {type(cuda_load_e).__name__}")
    # DON'T RAISE - return None and handle gracefully
    logger.error("❌ TTS completely unavailable - continuing without TTS")
    return None
```

**File**: `python_back_end/main.py`

Added safe TTS wrapper function:
```python
def safe_generate_speech_optimized(text, audio_prompt=None, exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    """Generate speech with graceful error handling - never crashes the app"""
    try:
        result = generate_speech_optimized(text, audio_prompt, exaggeration, temperature, cfg_weight)
        if result is None or result == (None, None):
            logger.warning("⚠️ TTS unavailable - skipping audio generation")
            return None, None
        return result
    except Exception as tts_e:
        logger.error(f"❌ TTS generation failed gracefully: {tts_e}")
        logger.warning("⚠️ Continuing without TTS - chat will work without audio")
        return None, None
```

## Deployment and Verification

### Helm Upgrade Command
```bash
cd /home/guruai/compose/aidev/harvis-helm-chart
helm upgrade harvis-prod . -n ai-agents
```

### Success Verification

**Logs showing successful TTS loading on CUDA**:
```
INFO:model_manager:🔧 Starting comprehensive CUDA diagnostics for TTS...
INFO:model_manager:📊 CUDA Device Count: 1
INFO:model_manager:📊 Current CUDA Device: 0
INFO:model_manager:📊 CUDA Device Name: NVIDIA GeForce RTX 4090
INFO:model_manager:✅ Basic CUDA tensor creation successful: cuda:0
INFO:model_manager:🔊 Loading TTS model on device: cuda
INFO:model_manager:✅ TTS generation completed
INFO:main:Audio written to /tmp/response_a0db0a13-0df6-4e1b-85bb-6a5c4fc0342a.wav
```

**Application Status**:
- MetalLB LoadBalancer: `10.20.0.201` (accessible)
- Backend pods: Stable, no crashes
- TTS functionality: Working on GPU with CUDA
- Ollama integration: Connected via localhost endpoint

## Key Insights

1. **User Insight**: "could it be the helm chart maybe ??" - Led to discovering the template reference bug
2. **Hardware Optimization**: 50% resource allocation (12 cores, 32GB) leaves room for system overhead
3. **VRAM Management**: 24GB RTX 4090 provides ample VRAM for TTS + Ollama models
4. **Error Handling**: Graceful degradation prevents pod crashes when TTS fails

## Resolution Summary

The 502 errors were caused by a Helm template bug that prevented resource limit updates from applying, leaving pods with insufficient memory for TTS model loading. The fix involved:

1. **Correcting the template reference** to use the right values path
2. **Increasing resource limits** to match high-performance hardware capabilities
3. **Adding robust error handling** to prevent future pod crashes
4. **Optimizing the Ollama endpoint** for container networking

The application now successfully loads TTS models on CUDA, manages GPU memory properly, and maintains stable operation without crashes.

## Files Modified

- `templates/merged-ollama-backend-deployment.yaml`: Fixed resource template reference
- `values.yaml`: Updated resource limits and Ollama endpoint
- `python_back_end/model_manager.py`: Added CUDA diagnostics and error handling
- `python_back_end/main.py`: Added safe TTS wrapper functions

## Related Documentation

- [Resource Optimization Configuration](resource-optimization.md): Detailed hardware optimization guidelines
- [CLAUDE.md](../CLAUDE.md): Project architecture and development guidelines