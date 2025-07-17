#!/bin/bash
# Test script to verify Docker build with dependency installation

set -e

echo "🐳 Testing Python backend Docker build..."

# Build the Docker image
echo "Building Docker image..."
docker build -t jarvis-backend-test . --no-cache

# Run a container to test if all dependencies are installed
echo "Testing dependency installation..."
docker run --rm jarvis-backend-test python3 -c "
import sys
import subprocess

# List of packages to verify
packages = [
    'fastapi',
    'uvicorn', 
    'asyncpg',
    'passlib',
    'jose',
    'bcrypt',
    'requests',
    'torch',
    'whisper',
    'pydantic',
    'tavily',
    'chatterbox',
    'langchain',
    'langchain_community',
    'ddgs',
    'bs4',
    'newspaper',
    'pytest',
    'httpx',
    'accelerate'
]

print('🔍 Verifying package installations...')
failed_imports = []

for package in packages:
    try:
        __import__(package)
        print(f'✅ {package}')
    except ImportError as e:
        print(f'❌ {package}: {e}')
        failed_imports.append(package)

if failed_imports:
    print(f'\\n❌ Failed to import {len(failed_imports)} packages:')
    for pkg in failed_imports:
        print(f'  - {pkg}')
    sys.exit(1)
else:
    print('\\n✅ All packages imported successfully!')

# Test basic functionality
print('\\n🧪 Testing basic functionality...')
try:
    from fastapi import FastAPI
    app = FastAPI()
    print('✅ FastAPI can be instantiated')
    
    import torch
    print(f'✅ PyTorch version: {torch.__version__}')
    print(f'✅ CUDA available: {torch.cuda.is_available()}')
    
    import whisper
    print('✅ Whisper can be imported')
    
    print('\\n🎉 All tests passed!')
except Exception as e:
    print(f'❌ Functionality test failed: {e}')
    sys.exit(1)
"

echo "✅ Docker build and dependency test completed successfully!"