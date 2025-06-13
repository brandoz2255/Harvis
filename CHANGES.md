# Summary of Changes

This file documents the key improvements and additions made to the project.

## Code Improvements

1. **CUDA Error Handling**:
   - Added robust error handling for CUDA operations in TTS
   - Implemented retry mechanisms with fallback to CPU when necessary
   - Added dynamic VRAM threshold based on available GPU memory
   - Improved logging for better debugging and troubleshooting

2. **Docker Security**:
   - Updated Dockerfile to run the application as a non-root user
   - Created system group and user `app` for improved security

## Documentation

1. **README.md**:
   - Added detailed project description, features, and requirements
   - Provided comprehensive installation instructions (local and Docker)
   - Documented all Docker Compose services including the new agent-zero-run microservice
   - Added information about VRAM management and CUDA handling
   - Included troubleshooting steps for common issues

2. **CHANGES.md**:
   - Created this file to document key improvements and additions

## Docker Configuration

1. **docker-compose.yaml**:
   - Added the `agent-zero-run` microservice connected to Ollama
   - Updated documentation in README.md to reflect the new service

## Next Steps

1. Test the application thoroughly, especially the CUDA error handling and fallback mechanisms
2. Review all logging output for completeness and usefulness
3. Consider adding more detailed error messages or status indicators in the web UI
