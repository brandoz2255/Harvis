# Resource Optimization Configuration

This document outlines the resource optimization configuration for the Harvis AI system, specifically optimized for high-performance hardware.

## Hardware Specifications

The system is optimized for the following hardware configuration:
- **CPU**: AMD Ryzen 9 9900X (24 cores) @ 5.658GHz
- **RAM**: 64GB total system memory
- **GPU**: NVIDIA RTX 4090 (24GB VRAM)
- **Secondary GPU**: AMD integrated GPU

## Resource Allocation Strategy

### Backend Pod Configuration

The backend pod is configured with generous resource limits to take full advantage of the available hardware:

```yaml
# Overall resource configuration (GPU allocation)
resources:
  requests:
    cpu: 1000m      # 1 CPU core minimum
    memory: 8Gi     # 8GB RAM minimum
    nvidia.com/gpu: 1
  limits:
    cpu: 12000m     # 12 CPU cores maximum (50% of available)
    memory: 32Gi    # 32GB RAM maximum (50% of available)
    nvidia.com/gpu: 1
```

### Ollama Container Configuration

```yaml
ollama:
  resources:
    requests:
      cpu: 500m      # 0.5 CPU core minimum
      memory: 8Gi    # 8GB RAM minimum
    limits:
      cpu: 2000m     # 2 CPU cores maximum
      memory: 16Gi   # 16GB RAM maximum
```

## Memory Management Strategy

### VRAM Optimization

The backend implements sophisticated VRAM management:

1. **Dynamic Model Loading**: Models are loaded on-demand to optimize GPU memory usage
2. **Sequential Processing**: TTS and Whisper models are loaded/unloaded as needed
3. **Aggressive Cleanup**: GPU memory is cleared between model transitions

### Memory Benefits

With 32GB RAM allocation:
- **Model Caching**: Large language models can be cached in system RAM
- **Buffer Space**: Ample memory for model loading/unloading operations
- **Concurrent Operations**: Multiple AI operations can run simultaneously
- **System Stability**: No memory pressure during intensive operations

## Network Configuration

### Ollama Endpoint Configuration

The system is configured to use local Ollama service for optimal performance:

```yaml
backend:
  env:
    OLLAMA_CLOUD_URL: "http://ollama:11434"  # Local service endpoint
```

This configuration ensures:
- **Low Latency**: Direct communication within Kubernetes cluster
- **High Reliability**: No dependency on external services
- **Full GPU Utilization**: Local processing uses full RTX 4090 capabilities

## Performance Characteristics

### Expected Performance

With this configuration, the system provides:
- **Fast TTS Generation**: Full GPU acceleration without memory constraints
- **Rapid Model Switching**: Ample RAM for smooth model transitions
- **High Concurrency**: Multiple AI operations can run in parallel
- **System Responsiveness**: No resource starvation under heavy load

### Scaling Considerations

The current allocation uses approximately:
- **50% CPU**: 12 cores out of 24 available
- **50% RAM**: 32GB out of 64GB available
- **100% GPU**: Full RTX 4090 utilization

This leaves sufficient resources for:
- System overhead
- Other applications
- Future scaling
- Development workloads

## Troubleshooting

### Common Issues

1. **TTS Crashes**: Previously caused by 2GB memory limit - resolved with 32GB allocation
2. **Ollama Connectivity**: External endpoint issues resolved with local service configuration
3. **GPU Context Conflicts**: Mitigated by sequential model loading and aggressive cleanup

### Monitoring

Monitor these metrics to ensure optimal performance:
- **GPU Memory Usage**: Should not exceed 24GB
- **System RAM Usage**: Should stay below 80% (51GB)
- **CPU Utilization**: Should remain below 80% of allocated cores
- **Pod Restart Count**: Should remain at 0 for stable operation

## Upgrading Configuration

To apply these optimizations:

```bash
cd /path/to/harvis-helm-chart
helm upgrade harvis-prod . -n ai-agents
```

This will:
1. Update resource limits
2. Apply Ollama endpoint configuration
3. Restart pods with new settings
4. Maintain data persistence

## Future Optimizations

Potential improvements:
1. **Multi-GPU Support**: Utilize AMD GPU for additional workloads
2. **Model Preloading**: Cache frequently used models in RAM
3. **Load Balancing**: Distribute workloads across CPU cores
4. **Memory Optimization**: Fine-tune memory allocation based on usage patterns