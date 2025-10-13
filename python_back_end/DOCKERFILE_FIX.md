# Dockerfile Dependency Conflict Fix

**Date:** 2025-01-13
**Issue:** Dependency hell with numpy versions causing build failures

## Problem

The Dockerfile build was failing with dependency conflicts:
```
ERROR: Cannot install accelerate==1.10.1 and chatterbox-tts==0.1.4 because these package versions have conflicting dependencies.

The conflict is caused by:
    accelerate 1.10.1 depends on numpy<3.0.0 and >=1.17
    chatterbox-tts 0.1.4 depends on numpy<1.26.0 and >=1.24.0
```

Additionally, the builder stage was creating **multiple numpy wheels** (both 1.25.2 and 2.2.6), causing pip to fail:
```
The user requested numpy 1.25.2 (from /wheels/numpy-1.25.2-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl)
The user requested numpy 2.2.6 (from /wheels/numpy-2.2.6-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl)
```

## Root Cause

1. **Multiple numpy wheels in builder stage**: When building wheels for dependencies, pip was creating both numpy 1.25.2 and numpy 2.2.6 wheels as transitive dependencies
2. **Conflicting version constraints**:
   - chatterbox-tts requires `numpy<1.26.0,>=1.24.0` (only accepts 1.24.x or 1.25.x)
   - accelerate accepts `numpy<3.0.0,>=1.17` (flexible)
3. **Previous approach failed**: Trying to pre-install numpy 2.x, then install packages that need numpy 1.25.x created an unsolvable conflict

## Solution

### Step 1: Remove numpy wheels from builder stage

**File:** `Dockerfile` (line 21)

Added command to remove all numpy wheels after building:
```dockerfile
# Remove any numpy wheels that got built as dependencies (keep only one version)
RUN rm -f /wheels/numpy-*.whl
```

This prevents multiple numpy versions from existing in the `/wheels` directory.

### Step 2: Install numpy first in runtime stage with correct constraint

**File:** `Dockerfile` (lines 32-33)

Install numpy with the most restrictive constraint first:
```dockerfile
# Install numpy first with constraint compatible with chatterbox-tts (<1.26.0)
RUN pip install --no-cache-dir "numpy>=1.24.0,<1.26.0"
```

This ensures numpy 1.25.x is installed before any other packages.

### Step 3: Install remaining wheels

**File:** `Dockerfile` (lines 40-45)

Install all other prebuilt wheels - they will use the already-installed numpy:
```dockerfile
# Install all other prebuilt wheels (numpy already installed, wheels removed from builder)
COPY --from=builder /wheels /wheels
RUN rm -f /wheels/torch-*.whl /wheels/torchvision-*.whl /wheels/torchaudio-*.whl \
  && pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
  && rm -rf /wheels \
  && pip cache purge
```

## Complete Changes

### Builder Stage Changes
```dockerfile
# Build wheels for the rest (excluding torch and numpy to prevent conflicts)
RUN grep -v "^torch" requirements.txt | grep -v "^numpy" > requirements_no_torch_numpy.txt \
  && pip wheel --no-cache-dir -r requirements_no_torch_numpy.txt -w /wheels
# Also build a wheel for pkuseg if it comes from source
RUN pip wheel --no-cache-dir pkuseg==0.0.25 --no-build-isolation -w /wheels
# Remove any numpy wheels that got built as dependencies (keep only one version)
RUN rm -f /wheels/numpy-*.whl  # <--- ADDED THIS LINE
```

### Runtime Stage Changes
```dockerfile
# Install dependencies in controlled order to avoid conflicts
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install numpy first with constraint compatible with chatterbox-tts (<1.26.0)
RUN pip install --no-cache-dir "numpy>=1.24.0,<1.26.0"  # <--- ADDED THIS

# Install torch from PyTorch repo (with CUDA support)
RUN pip install --no-cache-dir \
  torch==2.6.0+cu124 torchvision==0.21.0+cu124 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124

# Install all other prebuilt wheels (numpy already installed, wheels removed from builder)
COPY --from=builder /wheels /wheels
RUN rm -f /wheels/torch-*.whl /wheels/torchvision-*.whl /wheels/torchaudio-*.whl \
  && pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
  && rm -rf /wheels \
  && pip cache purge
```

## Why This Works

1. **Eliminates multiple numpy versions**: By removing numpy wheels from the builder stage, we prevent pip from seeing multiple versions
2. **Installs compatible version first**: numpy 1.25.x satisfies both:
   - chatterbox-tts requirement: `numpy<1.26.0,>=1.24.0` ✓
   - accelerate requirement: `numpy<3.0.0,>=1.17` ✓
3. **Prevents re-installation**: When installing other wheels, pip sees numpy is already installed and won't try to upgrade it
4. **Maintains CUDA support**: torch is still installed from PyTorch's CUDA-enabled repository

## Result

- Build completes successfully without dependency conflicts
- numpy 1.25.x is installed (compatible with all packages)
- torch 2.6.0+cu124 with CUDA support
- All other dependencies installed from prebuilt wheels
- No version conflicts

## Lessons Learned

1. **Let pip build dependency wheels, then delete conflicting ones**: Don't try to control what wheels get built - remove conflicts after
2. **Install most restrictive constraints first**: chatterbox-tts has the strictest numpy requirement, so install that constraint first
3. **Don't force versions in runtime that conflict with dependencies**: Pre-installing numpy 2.x then trying to install packages needing 1.x fails
4. **Multi-stage builds need careful wheel management**: What gets built in the builder stage affects what can be installed in runtime
