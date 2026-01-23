🎙️ HARVIS VIVEVoice Integration Master Prompt
For Claude Opus - Complete Implementation Guide

📋 PROJECT OVERVIEW
Objective
Integrate VIVEVoice local TTS with voice cloning capabilities into HARVIS AI, providing users with:

Professional podcast generation from research notebooks
Custom voice cloning (10-second samples)
Multi-speaker conversations
Automatic content-to-audio pipeline
Zero-cost, privacy-first alternative to cloud TTS services

Current System Architecture
# 🎙️ HARVIS VIVEVoice Integration Master Prompt

*For Claude Opus - Complete Implementation Guide*

---

## 📋 PROJECT OVERVIEW

### **Objective**
Integrate VIVEVoice local TTS with voice cloning capabilities into HARVIS AI, providing users with:
- Professional podcast generation from research notebooks
- Custom voice cloning (10-second samples)
- Multi-speaker conversations
- Automatic content-to-audio pipeline
- Zero-cost, privacy-first alternative to cloud TTS services

### **Current System Architecture**
```
HARVIS AI/
├── front_end/jfrontend/          # Next.js 14 frontend
│   ├── app/                       # App router
│   ├── components/                # React components
│   └── lib/                       # Utilities
├── python_back_end/               # FastAPI backend
│   ├── api/                       # API routes
│   └── [various modules]
├── docker-compose.yaml            # Docker orchestration
└── nginx.conf                     # Routing configuration
```

### **Integration Points**
- Open Notebook notebook system (SurrealDB)
- Existing FastAPI backend
- Next.js frontend with shadcn/ui
- Docker deployment stack
- PostgreSQL + SurrealDB databases

---

## 🎯 IMPLEMENTATION PHASES

---

## **PHASE 1: REPOSITORY ANALYSIS & SETUP** (Day 1)

### **Step 1.1: Clone and Analyze VIVEVoice Repository**

```bash
# First, examine the official repository
git clone https://github.com/fixie-ai/ultravox.git
# OR if different repo:
# Research and identify the correct VIVEVoice/VoiceChat repository

# Analyze structure
cd ultravox  # or correct repo name
tree -L 3 -I 'node_modules|__pycache__|*.pyc'
```

**Analysis Checklist:**
- [ ] Identify model files and weights location
- [ ] Find inference code and API endpoints
- [ ] Locate voice cloning implementation
- [ ] Check multi-speaker support
- [ ] Review dependencies and requirements
- [ ] Identify GPU/CPU requirements
- [ ] Find configuration files
- [ ] Review license and usage restrictions

**Document Findings:**
```python
# Create: python_back_end/tts_system/VIVEVOICE_ANALYSIS.md
"""
VIVEVoice Repository Analysis
============================

Repository: [URL]
Version: [X.X.X]
License: [License Type]

Key Findings:
- Model Location: [path]
- Inference Entry Point: [file/function]
- Voice Cloning Module: [path]
- Multi-Speaker Support: [Yes/No - details]
- Dependencies: [list key packages]
- GPU Requirements: [VRAM needed]

Integration Strategy:
[Your analysis of how to integrate]
"""
```

---

### **Step 1.2: Research Alternative: Check for Existing Integrations**

Before proceeding, check if there are existing VIVEVoice/voice cloning integrations:

```bash
# Search for existing implementations
# GitHub: "vivevoice python api"
# GitHub: "voice cloning local tts"
# Look for: Coqui TTS, Bark, TorToiSe TTS as alternatives
```

**Decision Matrix:**

| Solution | Quality | Speed | Voice Clone | Multi-Speaker | Local | Complexity |
|----------|---------|-------|-------------|---------------|-------|------------|
| VIVEVoice | ⭐⭐⭐⭐⭐ | Fast | 10s sample | Yes (4) | Yes | Medium |
| Coqui TTS | ⭐⭐⭐⭐ | Fast | Yes | Yes | Yes | Low |
| Bark | ⭐⭐⭐⭐ | Slow | No | Yes | Yes | Low |
| TorToiSe | ⭐⭐⭐⭐⭐ | Very Slow | Yes | No | Yes | High |

**Recommendation**: If VIVEVoice repo is unclear or unavailable, use **Coqui TTS** as proven alternative.

---

## **PHASE 2: DOCKER INFRASTRUCTURE** (Day 1-2)

### **Step 2.1: Create TTS Service Container**

Create new Docker service for TTS processing:

```dockerfile
# Create: docker/tts-service/Dockerfile
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Install Python 3.10
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements-tts.txt .
RUN pip3 install --no-cache-dir -r requirements-tts.txt

# Copy TTS system code
COPY python_back_end/tts_system /app/tts_system

# Create directories for models and voices
RUN mkdir -p /app/models /app/voices /app/output

# Expose port for TTS service
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s \
  CMD curl -f http://localhost:8001/health || exit 1

# Run TTS service
CMD ["python3", "-m", "tts_system.server"]
```

```python
# Create: docker/tts-service/requirements-tts.txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
torch==2.1.0
torchaudio==2.1.0
numpy==1.24.3
scipy==1.11.4
librosa==0.10.1
soundfile==0.12.1
pydantic==2.5.0
python-multipart==0.0.6

# Add VIVEVoice/Coqui dependencies
# [TO BE FILLED BASED ON STEP 1.1 ANALYSIS]
```

---

### **Step 2.2: Update docker-compose.yaml**

```yaml
# Add to existing docker-compose.yaml

services:
  # ... existing services (frontend, backend, postgres, etc.)

  tts-service:
    build:
      context: .
      dockerfile: docker/tts-service/Dockerfile
    container_name: harvis-tts
    restart: unless-stopped
    volumes:
      - ./python_back_end/tts_system:/app/tts_system
      - tts-models:/app/models          # Persistent model storage
      - tts-voices:/app/voices          # User voice clones
      - tts-output:/app/output          # Generated audio
    environment:
      - CUDA_VISIBLE_DEVICES=0          # GPU device
      - TTS_MODEL_PATH=/app/models
      - VOICE_LIBRARY_PATH=/app/voices
      - OUTPUT_PATH=/app/output
      - MAX_AUDIO_LENGTH=3600           # 1 hour max
      - ENABLE_RVC=true                 # RVC enhancement
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    networks:
      - harvis-network
    ports:
      - "8001:8001"                     # TTS service API
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  tts-models:
    driver: local
  tts-voices:
    driver: local
  tts-output:
    driver: local

# ... existing volumes
```

---

### **Step 2.3: Update Nginx Configuration**

```nginx
# Add to nginx.conf

# TTS Service Proxy
location /api/tts/ {
    proxy_pass http://tts-service:8001/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_set_header Host $host;
    proxy_cache_bypass $http_upgrade;
    
    # Increase timeouts for long audio generation
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
    
    # Increase body size for audio uploads
    client_max_body_size 100M;
}

# Audio file serving
location /audio/ {
    alias /app/output/;
    expires 7d;
    add_header Cache-Control "public, immutable";
    add_header Access-Control-Allow-Origin *;
}
```

---

## **PHASE 3: BACKEND TTS SYSTEM** (Day 2-4)

### **Step 3.1: Create TTS System Directory Structure**

```bash
mkdir -p python_back_end/tts_system/{models,engines,services,utils}
```

```
python_back_end/tts_system/
├── __init__.py
├── server.py                    # FastAPI TTS service
├── models/
│   ├── __init__.py
│   ├── voice_model.py          # Voice data models
│   └── podcast_model.py        # Podcast configuration models
├── engines/
│   ├── __init__.py
│   ├── base_engine.py          # Base TTS interface
│   ├── vivevoice_engine.py     # VIVEVoice implementation
│   ├── coqui_engine.py         # Coqui TTS fallback
│   └── rvc_enhancer.py         # RVC post-processing
├── services/
│   ├── __init__.py
│   ├── voice_cloner.py         # Voice cloning service
│   ├── podcast_generator.py   # Podcast generation service
│   └── audio_processor.py     # Audio utilities
└── utils/
    ├── __init__.py
    ├── audio_utils.py          # Audio processing helpers
    └── file_manager.py         # File handling utilities
```

---

### **Step 3.2: Implement Base TTS Engine Interface**

```python
# python_back_end/tts_system/engines/base_engine.py
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, BinaryIO
from pathlib import Path

class BaseTTSEngine(ABC):
    """
    Abstract base class for TTS engines
    Ensures consistent interface across different implementations
    """
    
    def __init__(self, model_path: Path, device: str = "cuda"):
        self.model_path = model_path
        self.device = device
        self.model = None
        
    @abstractmethod
    async def load_model(self) -> bool:
        """Load TTS model into memory"""
        pass
    
    @abstractmethod
    async def clone_voice(
        self, 
        audio_sample: BinaryIO, 
        voice_name: str
    ) -> Dict[str, any]:
        """
        Clone voice from audio sample
        
        Args:
            audio_sample: Audio file (10+ seconds)
            voice_name: Unique identifier for voice
            
        Returns:
            {
                "voice_id": str,
                "voice_name": str,
                "embedding_path": Path,
                "sample_duration": float,
                "quality_score": float
            }
        """
        pass
    
    @abstractmethod
    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        **kwargs
    ) -> Path:
        """
        Generate speech from text
        
        Args:
            text: Text to synthesize
            voice_id: Voice to use
            output_path: Where to save audio
            **kwargs: Engine-specific parameters
            
        Returns:
            Path to generated audio file
        """
        pass
    
    @abstractmethod
    async def generate_multi_speaker(
        self,
        script: List[Dict[str, str]],
        voice_mapping: Dict[str, str],
        output_path: Path,
        **kwargs
    ) -> Path:
        """
        Generate conversation with multiple speakers
        
        Args:
            script: [
                {"speaker": "speaker_1", "text": "Hello"},
                {"speaker": "speaker_2", "text": "Hi there"}
            ]
            voice_mapping: {"speaker_1": "voice_id_1", ...}
            output_path: Where to save audio
            
        Returns:
            Path to generated conversation audio
        """
        pass
    
    @abstractmethod
    def list_available_voices(self) -> List[Dict[str, any]]:
        """Return list of available cloned voices"""
        pass
    
    @abstractmethod
    def get_engine_info(self) -> Dict[str, any]:
        """Return engine capabilities and status"""
        pass
```

---

### **Step 3.3: Implement VIVEVoice Engine** 

```python
# python_back_end/tts_system/engines/vivevoice_engine.py
import torch
import torchaudio
from pathlib import Path
from typing import Dict, List, Optional, BinaryIO
import numpy as np
import logging

from .base_engine import BaseTTSEngine
from ..utils.audio_utils import (
    extract_audio_segment,
    normalize_audio,
    add_silence_between_segments
)

logger = logging.getLogger(__name__)

class VIVEVoiceEngine(BaseTTSEngine):
    """
    VIVEVoice TTS Engine Implementation
    
    NOTE: This is a template - adjust based on actual VIVEVoice API
    """
    
    def __init__(self, model_path: Path, device: str = "cuda"):
        super().__init__(model_path, device)
        self.voice_embeddings = {}  # Cache voice embeddings
        self.sample_rate = 24000    # Adjust based on model
        
    async def load_model(self) -> bool:
        """Load VIVEVoice model"""
        try:
            logger.info(f"Loading VIVEVoice model from {self.model_path}")
            
            # TODO: Replace with actual VIVEVoice loading
            # Example structure (adjust based on actual repo):
            # from vivevoice import VoiceModel
            # self.model = VoiceModel.from_pretrained(
            #     self.model_path,
            #     device=self.device
            # )
            
            # Placeholder for development
            self.model = self._load_placeholder_model()
            
            logger.info("VIVEVoice model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load VIVEVoice model: {e}")
            return False
    
    async def clone_voice(
        self,
        audio_sample: BinaryIO,
        voice_name: str
    ) -> Dict[str, any]:
        """
        Clone voice from 10+ second audio sample
        """
        try:
            # Save uploaded audio temporarily
            temp_audio_path = Path(f"/tmp/{voice_name}_sample.wav")
            with open(temp_audio_path, "wb") as f:
                f.write(audio_sample.read())
            
            # Load and validate audio
            waveform, sr = torchaudio.load(temp_audio_path)
            duration = waveform.shape[1] / sr
            
            if duration < 10:
                raise ValueError(
                    f"Audio sample too short: {duration:.1f}s. "
                    "Need at least 10 seconds."
                )
            
            # Extract best 10-second segment (clearest speech)
            best_segment = extract_audio_segment(
                waveform, sr, duration=10
            )
            
            # Generate voice embedding
            # TODO: Replace with actual VIVEVoice voice extraction
            # voice_embedding = self.model.extract_voice_embedding(
            #     best_segment, sr
            # )
            
            voice_embedding = self._extract_placeholder_embedding(
                best_segment
            )
            
            # Save embedding
            embedding_path = (
                Path("/app/voices") / f"{voice_name}.pt"
            )
            torch.save(voice_embedding, embedding_path)
            
            # Cache in memory
            self.voice_embeddings[voice_name] = voice_embedding
            
            logger.info(f"Voice '{voice_name}' cloned successfully")
            
            return {
                "voice_id": voice_name,
                "voice_name": voice_name,
                "embedding_path": str(embedding_path),
                "sample_duration": duration,
                "quality_score": 0.95  # Placeholder
            }
            
        except Exception as e:
            logger.error(f"Voice cloning failed: {e}")
            raise
    
    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        **kwargs
    ) -> Path:
        """
        Generate speech from text using cloned voice
        """
        try:
            # Load voice embedding
            if voice_id not in self.voice_embeddings:
                embedding_path = Path("/app/voices") / f"{voice_id}.pt"
                self.voice_embeddings[voice_id] = torch.load(
                    embedding_path
                )
            
            voice_embedding = self.voice_embeddings[voice_id]
            
            # Generate speech
            # TODO: Replace with actual VIVEVoice synthesis
            # audio = self.model.synthesize(
            #     text=text,
            #     voice_embedding=voice_embedding,
            #     diffusion_steps=kwargs.get('diffusion_steps', 32),
            #     temperature=kwargs.get('temperature', 0.7)
            # )
            
            audio = self._generate_placeholder_audio(
                text, voice_embedding
            )
            
            # Save audio
            torchaudio.save(
                output_path,
                audio,
                self.sample_rate
            )
            
            logger.info(f"Generated speech: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Speech generation failed: {e}")
            raise
    
    async def generate_multi_speaker(
        self,
        script: List[Dict[str, str]],
        voice_mapping: Dict[str, str],
        output_path: Path,
        **kwargs
    ) -> Path:
        """
        Generate conversation with multiple speakers
        """
        try:
            audio_segments = []
            
            for line in script:
                speaker = line["speaker"]
                text = line["text"]
                voice_id = voice_mapping[speaker]
                
                # Generate segment
                segment_path = Path(f"/tmp/{speaker}_{len(audio_segments)}.wav")
                await self.generate_speech(
                    text=text,
                    voice_id=voice_id,
                    output_path=segment_path,
                    **kwargs
                )
                
                # Load segment
                segment, sr = torchaudio.load(segment_path)
                audio_segments.append(segment)
            
            # Combine segments with natural pauses
            final_audio = add_silence_between_segments(
                audio_segments,
                pause_duration=kwargs.get('pause_duration', 0.5)
            )
            
            # Save final audio
            torchaudio.save(
                output_path,
                final_audio,
                self.sample_rate
            )
            
            logger.info(f"Generated multi-speaker audio: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Multi-speaker generation failed: {e}")
            raise
    
    def list_available_voices(self) -> List[Dict[str, any]]:
        """List all cloned voices"""
        voices = []
        voice_dir = Path("/app/voices")
        
        for embedding_file in voice_dir.glob("*.pt"):
            voice_name = embedding_file.stem
            voices.append({
                "voice_id": voice_name,
                "voice_name": voice_name,
                "embedding_path": str(embedding_file),
                "created_at": embedding_file.stat().st_mtime
            })
        
        return voices
    
    def get_engine_info(self) -> Dict[str, any]:
        """Get engine status and capabilities"""
        return {
            "engine": "VIVEVoice",
            "version": "1.0.0",  # Get from actual model
            "device": self.device,
            "sample_rate": self.sample_rate,
            "loaded": self.model is not None,
            "cached_voices": len(self.voice_embeddings),
            "capabilities": {
                "voice_cloning": True,
                "multi_speaker": True,
                "languages": ["en", "es", "fr", "de", "ja", "zh"],
                "max_speakers": 4,
                "min_clone_duration": 10.0
            }
        }
    
    # Placeholder methods for development
    def _load_placeholder_model(self):
        """Placeholder until actual VIVEVoice implementation"""
        logger.warning("Using placeholder model - replace with actual VIVEVoice")
        return {"placeholder": True}
    
    def _extract_placeholder_embedding(self, audio):
        """Placeholder voice embedding"""
        return torch.randn(256)  # Example embedding dimension
    
    def _generate_placeholder_audio(self, text, embedding):
        """Placeholder audio generation"""
        # Generate silent audio for testing
        duration = len(text.split()) * 0.5  # 0.5s per word
        samples = int(duration * self.sample_rate)
        return torch.zeros(1, samples)
```

---

### **Step 3.4: Implement FastAPI TTS Service**

```python
# python_back_end/tts_system/server.py
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
from pathlib import Path
import logging
import uuid

from .engines.vivevoice_engine import VIVEVoiceEngine
from .engines.coqui_engine import CoquiTTSEngine  # Fallback
from .models.voice_model import VoiceCloneRequest, VoiceInfo
from .models.podcast_model import PodcastScript, GenerationRequest

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="HARVIS TTS Service",
    description="Local Text-to-Speech with Voice Cloning",
    version="1.0.0"
)

# Global engine instance
tts_engine: Optional[VIVEVoiceEngine] = None

@app.on_event("startup")
async def startup_event():
    """Initialize TTS engine on startup"""
    global tts_engine
    
    logger.info("Initializing TTS engine...")
    
    try:
        model_path = Path("/app/models/vivevoice-large")
        tts_engine = VIVEVoiceEngine(model_path, device="cuda")
        
        success = await tts_engine.load_model()
        
        if not success:
            logger.warning("VIVEVoice failed, falling back to Coqui TTS")
            tts_engine = CoquiTTSEngine(model_path, device="cuda")
            await tts_engine.load_model()
        
        logger.info("TTS engine ready!")
        
    except Exception as e:
        logger.error(f"Failed to initialize TTS engine: {e}")
        raise

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "engine_loaded": tts_engine is not None,
        "engine_info": tts_engine.get_engine_info() if tts_engine else None
    }

@app.post("/voices/clone")
async def clone_voice(
    voice_name: str,
    audio_sample: UploadFile = File(...)
):
    """
    Clone a voice from audio sample
    
    Requires: 10+ seconds of clear speech
    """
    if not tts_engine:
        raise HTTPException(500, "TTS engine not initialized")
    
    try:
        logger.info(f"Cloning voice: {voice_name}")
        
        # Clone voice
        result = await tts_engine.clone_voice(
            audio_sample.file,
            voice_name
        )
        
        return {
            "success": True,
            "voice": result
        }
        
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Voice cloning error: {e}")
        raise HTTPException(500, f"Voice cloning failed: {e}")

@app.get("/voices")
async def list_voices():
    """List all available voices"""
    if not tts_engine:
        raise HTTPException(500, "TTS engine not initialized")
    
    voices = tts_engine.list_available_voices()
    return {"voices": voices}

@app.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Delete a cloned voice"""
    try:
        embedding_path = Path(f"/app/voices/{voice_id}.pt")
        
        if embedding_path.exists():
            embedding_path.unlink()
            return {"success": True, "message": f"Voice '{voice_id}' deleted"}
        else:
            raise HTTPException(404, f"Voice '{voice_id}' not found")
            
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/generate/speech")
async def generate_speech(
    text: str,
    voice_id: str,
    output_filename: Optional[str] = None
):
    """Generate speech from text"""
    if not tts_engine:
        raise HTTPException(500, "TTS engine not initialized")
    
    try:
        # Generate unique filename
        if not output_filename:
            output_filename = f"{uuid.uuid4()}.wav"
        
        output_path = Path("/app/output") / output_filename
        
        # Generate speech
        result_path = await tts_engine.generate_speech(
            text=text,
            voice_id=voice_id,
            output_path=output_path
        )
        
        return {
            "success": True,
            "audio_file": str(result_path.name),
            "audio_url": f"/audio/{result_path.name}"
        }
        
    except Exception as e:
        logger.error(f"Speech generation error: {e}")
        raise HTTPException(500, str(e))

@app.post("/generate/podcast")
async def generate_podcast(
    request: GenerationRequest,
    background_tasks: BackgroundTasks
):
    """
    Generate multi-speaker podcast
    
    Body:
    {
        "script": [
            {"speaker": "host", "text": "Welcome!"},
            {"speaker": "guest", "text": "Thanks for having me!"}
        ],
        "voice_mapping": {
            "host": "my_voice",
            "guest": "guest_voice"
        },
        "options": {
            "pause_duration": 0.5,
            "diffusion_steps": 32
        }
    }
    """
    if not tts_engine:
        raise HTTPException(500, "TTS engine not initialized")
    
    try:
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        output_filename = f"podcast_{job_id}.wav"
        output_path = Path("/app/output") / output_filename
        
        # Generate podcast (run in background if needed)
        result_path = await tts_engine.generate_multi_speaker(
            script=request.script,
            voice_mapping=request.voice_mapping,
            output_path=output_path,
            **request.options
        )
        
        return {
            "success": True,
            "job_id": job_id,
            "audio_file": str(result_path.name),
            "audio_url": f"/audio/{result_path.name}"
        }
        
    except Exception as e:
        logger.error(f"Podcast generation error: {e}")
        raise HTTPException(500, str(e))

@app.get("/audio/{filename}")
async def get_audio_file(filename: str):
    """Serve generated audio files"""
    file_path = Path("/app/output") / filename
    
    if not file_path.exists():
        raise HTTPException(404, "Audio file not found")
    
    return FileResponse(
        file_path,
        media_type="audio/wav",
        filename=filename
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

---

## **PHASE 4: FRONTEND UI COMPONENTS** (Day 4-6)

### **Step 4.1: Create Voice Management UI**

```typescript
// front_end/jfrontend/components/notebook/VoiceLibrary.tsx
'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Mic, Upload, Trash2, Play, Pause } from 'lucide-react'
import { useToast } from '@/components/ui/use-toast'

interface Voice {
  voice_id: string
  voice_name: string
  created_at: number
  embedding_path: string
}

export function VoiceLibrary() {
  const [voices, setVoices] = useState<Voice[]>([])
  const [loading, setLoading] = useState(true)
  const [cloning, setCloning] = useState(false)
  const { toast } = useToast()
  
  // Fetch available voices
  useEffect(() => {
    fetchVoices()
  }, [])
  
  const fetchVoices = async () => {
    try {
      const response = await fetch('/api/tts/voices')
      const data = await response.json()
      setVoices(data.voices)
    } catch (error) {
      console.error('Failed to fetch voices:', error)
    } finally {
      setLoading(false)
    }
  }
  
  const handleVoiceClone = async (voiceName: string, audioFile: File) => {
    setCloning(true)
    
    try {
      const formData = new FormData()
      formData.append('audio_sample', audioFile)
      
      const response = await fetch(
        `/api/tts/voices/clone?voice_name=${voiceName}`,
        {
          method: 'POST',
          body: formData
        }
      )
      
      if (!response.ok) {
        throw new Error('Voice cloning failed')
      }
      
      const result = await response.json()
      
      toast({
        title: '✅ Voice Cloned Successfully!',
        description: `"${voiceName}" is ready to use in your podcasts.`
      })
      
      // Refresh voice list
      fetchVoices()
      
    } catch (error) {
      toast({
        title: '❌ Voice Cloning Failed',
        description: error.message,
        variant: 'destructive'
      })
    } finally {
      setCloning(false)
    }
  }
  
  const handleDeleteVoice = async (voiceId: string) => {
    try {
      await fetch(`/api/tts/voices/${voiceId}`, {
        method: 'DELETE'
      })
      
      toast({
        title: 'Voice Deleted',
        description: `"${voiceId}" has been removed.`
      })
      
      fetchVoices()
      
    } catch (error) {
      toast({
        title: 'Deletion Failed',
        description: error.message,
        variant: 'destructive'
      })
    }
  }
  
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold">Voice Library</h2>
          <p className="text-gray-400">
            Manage your cloned voices for podcast generation
          </p>
        </div>
        
        <VoiceCloneDialog onClone={handleVoiceClone} />
      </div>
      
      {/* Voice Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading ? (
          <div>Loading voices...</div>
        ) : voices.length === 0 ? (
          <Card className="col-span-full">
            <CardContent className="pt-6 text-center">
              <Mic className="w-12 h-12 mx-auto mb-4 text-gray-400" />
              <h3 className="text-lg font-semibold mb-2">No Voices Yet</h3>
              <p className="text-gray-400 mb-4">
                Clone your first voice to start generating podcasts
              </p>
              <VoiceCloneDialog onClone={handleVoiceClone} />
            </CardContent>
          </Card>
        ) : (
          voices.map((voice) => (
            <VoiceCard
              key={voice.voice_id}
              voice={voice}
              onDelete={handleDeleteVoice}
            />
          ))
        )}
      </div>
    </div>
  )
}

function VoiceCloneDialog({ onClone }) {
  const [open, setOpen] = useState(false)
  const [voiceName, setVoiceName] = useState('')
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [recording, setRecording] = useState(false)
  
  const handleSubmit = async () => {
    if (!voiceName || !audioFile) {
      return
    }
    
    await onClone(voiceName, audioFile)
    
    // Reset and close
    setVoiceName('')
    setAudioFile(null)
    setOpen(false)
  }
  
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Mic className="w-4 h-4 mr-2" />
          Clone New Voice
        </Button>
      </DialogTrigger>
      
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Clone a Voice</DialogTitle>
          <DialogDescription>
            Upload 10+ seconds of clear speech to clone a voice
          </DialogDescription>
        </DialogHeader>
        
        <div className="space-y-4 pt-4">
          {/* Voice Name */}
          <div>
            <Label htmlFor="voice-name">Voice Name</Label>
            <Input
              id="voice-name"
              placeholder="e.g., My Voice, Walter White, etc."
              value={voiceName}
              onChange={(e) => setVoiceName(e.target.value)}
            />
          </div>
          
          {/* Audio Upload */}
          <div>
            <Label>Audio Sample</Label>
            <div className="flex gap-2 mt-2">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => document.getElementById('audio-upload')?.click()}
              >
                <Upload className="w-4 h-4 mr-2" />
                {audioFile ? audioFile.name : 'Upload Audio'}
              </Button>
              
              <input
                id="audio-upload"
                type="file"
                accept="audio/*"
                className="hidden"
                onChange={(e) => setAudioFile(e.target.files?.[0] || null)}
              />
              
              <Button variant="outline">
                <Mic className="w-4 h-4 mr-2" />
                Record
              </Button>
            </div>
            
            {audioFile && (
              <p className="text-sm text-gray-400 mt-2">
                Selected: {audioFile.name}
              </p>
            )}
          </div>
          
          {/* Submit */}
          <Button
            onClick={handleSubmit}
            disabled={!voiceName || !audioFile}
            className="w-full"
          >
            Clone Voice
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function VoiceCard({ voice, onDelete }) {
  const [playing, setPlaying] = useState(false)
  
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex justify-between items-center">
          <span className="truncate">{voice.voice_name}</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDelete(voice.voice_id)}
          >
            <Trash2 className="w-4 h-4 text-red-400" />
          </Button>
        </CardTitle>
        <CardDescription>
          Created {new Date(voice.created_at * 1000).toLocaleDateString()}
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <Button
          variant="outline"
          className="w-full"
          onClick={() => setPlaying(!playing)}
        >
          {playing ? (
            <>
              <Pause className="w-4 h-4 mr-2" />
              Pause Sample
            </>
          ) : (
            <>
              <Play className="w-4 h-4 mr-2" />
              Play Sample
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}
```

---

### **Step 4.2: Create Podcast Configuration UI**

```typescript
// front_end/jfrontend/components/notebook/PodcastGenerator.tsx
'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Sparkles, Settings, Users } from 'lucide-react'

export function PodcastGenerator({ notebookId }: { notebookId: string }) {
  const [voices, setVoices] = useState([])
  const [speakerCount, setSpeakerCount] = useState(1)
  const [voiceConfig, setVoiceConfig] = useState({})
  const [style, setStyle] = useState('conversational')
  const [duration, setDuration] = useState(15)
  
  useEffect(() => {
    // Fetch available voices
    fetch('/api/tts/voices')
      .then(res => res.json())
      .then(data => setVoices(data.voices))
  }, [])
  
  const handleGenerate = async () => {
    // Trigger podcast generation
    const response = await fetch('/api/notebook/podcast/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        notebook_id: notebookId,
        speaker_count: speakerCount,
        voice_config: voiceConfig,
        style: style,
        target_duration: duration
      })
    })
    
    const result = await response.json()
    // Handle result
  }
  
  return (
    <Card className="p-6">
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h3 className="text-xl font-bold mb-2">Generate Podcast</h3>
          <p className="text-gray-400">
            Convert your research into an engaging audio discussion
          </p>
        </div>
        
        {/* Configuration Tabs */}
        <Tabs defaultValue="basic">
          <TabsList>
            <TabsTrigger value="basic">Basic</TabsTrigger>
            <TabsTrigger value="voices">Voices</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
          </TabsList>
          
          <TabsContent value="basic" className="space-y-4">
            {/* Speaker Count */}
            <div>
              <label className="text-sm font-medium mb-2 block">
                Number of Speakers
              </label>
              <Select
                value={speakerCount.toString()}
                onValueChange={(v) => setSpeakerCount(parseInt(v))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">Solo (1 speaker)</SelectItem>
                  <SelectItem value="2">Dialogue (2 speakers)</SelectItem>
                  <SelectItem value="3">Panel (3 speakers)</SelectItem>
                  <SelectItem value="4">Group (4 speakers)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            {/* Style */}
            <div>
              <label className="text-sm font-medium mb-2 block">
                Podcast Style
              </label>
              <Select value={style} onValueChange={setStyle}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="conversational">
                    Conversational - Friendly discussion
                  </SelectItem>
                  <SelectItem value="interview">
                    Interview - Q&A format
                  </SelectItem>
                  <SelectItem value="narrative">
                    Narrative - Story-telling
                  </SelectItem>
                  <SelectItem value="educational">
                    Educational - Lecture style
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            {/* Duration */}
            <div>
              <label className="text-sm font-medium mb-2 block">
                Target Duration: {duration} minutes
              </label>
              <Slider
                value={[duration]}
                onValueChange={(v) => setDuration(v[0])}
                min={5}
                max={60}
                step={5}
              />
            </div>
          </TabsContent>
          
          <TabsContent value="voices" className="space-y-4">
            {/* Voice Assignment */}
            {Array.from({ length: speakerCount }).map((_, i) => (
              <div key={i}>
                <label className="text-sm font-medium mb-2 block">
                  Speaker {i + 1} Voice
                </label>
                <Select
                  value={voiceConfig[`speaker_${i + 1}`]}
                  onValueChange={(v) => 
                    setVoiceConfig({
                      ...voiceConfig,
                      [`speaker_${i + 1}`]: v
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a voice..." />
                  </SelectTrigger>
                  <SelectContent>
                    {voices.map((voice) => (
                      <SelectItem key={voice.voice_id} value={voice.voice_id}>
                        {voice.voice_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ))}
            
            {voices.length === 0 && (
              <p className="text-sm text-gray-400">
                No voices available. Clone a voice first in Voice Library.
              </p>
            )}
          </TabsContent>
          
          <TabsContent value="advanced" className="space-y-4">
            {/* Advanced options */}
            <p className="text-sm text-gray-400">
              Advanced options coming soon...
            </p>
          </TabsContent>
        </Tabs>
        
        {/* Generate Button */}
        <Button
          onClick={handleGenerate}
          disabled={voices.length === 0}
          className="w-full"
          size="lg"
        >
          <Sparkles className="w-5 h-5 mr-2" />
          Generate Podcast
        </Button>
      </div>
    </Card>
  )
}
```

---

## **PHASE 5: INTEGRATION WITH MAIN BACKEND** (Day 6-7)

### **Step 5.1: Create API Proxy Routes**

```python
# python_back_end/api/tts_routes.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import List, Dict
import httpx
import os

router = APIRouter(prefix="/api/tts", tags=["tts"])

TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://tts-service:8001")

@router.post("/voices/clone")
async def clone_voice(
    voice_name: str,
    audio_sample: UploadFile = File(...)
):
    """Proxy to TTS service - Clone voice"""
    async with httpx.AsyncClient() as client:
        files = {"audio_sample": (audio_sample.filename, audio_sample.file)}
        response = await client.post(
            f"{TTS_SERVICE_URL}/voices/clone",
            params={"voice_name": voice_name},
            files=files,
            timeout=120.0
        )
        
        if response.status_code != 200:
            raise HTTPException(response.status_code, response.text)
        
        return response.json()

@router.get("/voices")
async def list_voices():
    """Proxy to TTS service - List voices"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{TTS_SERVICE_URL}/voices")
        return response.json()

@router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Proxy to TTS service - Delete voice"""
    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"{TTS_SERVICE_URL}/voices/{voice_id}"
        )
        return response.json()

@router.post("/generate/podcast")
async def generate_podcast(request: Dict):
    """Proxy to TTS service - Generate podcast"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TTS_SERVICE_URL}/generate/podcast",
            json=request,
            timeout=600.0  # 10 minutes
        )
        
        if response.status_code != 200:
            raise HTTPException(response.status_code, response.text)
        
        return response.json()
```

```python
# Add to python_back_end/api/main.py
from .tts_routes import router as tts_router

app.include_router(tts_router)
```

---

## **PHASE 6: TESTING & VALIDATION** (Day 7-8)

### **Step 6.1: Create Test Suite**

```python
# tests/test_tts_system.py
import pytest
import asyncio
from pathlib import Path
import torch

from python_back_end.tts_system.engines.vivevoice_engine import VIVEVoiceEngine

@pytest.fixture
async def tts_engine():
    """Initialize TTS engine for testing"""
    engine = VIVEVoiceEngine(
        model_path=Path("/app/models/vivevoice-large"),
        device="cuda" if torch.cuda.is_available() else "cpu"
    )
    await engine.load_model()
    return engine

@pytest.mark.asyncio
async def test_voice_cloning(tts_engine):
    """Test voice cloning from audio sample"""
    # Use test audio file
    test_audio = Path("tests/fixtures/test_voice_10s.wav")
    
    result = await tts_engine.clone_voice(
        audio_sample=open(test_audio, "rb"),
        voice_name="test_voice"
    )
    
    assert result["voice_id"] == "test_voice"
    assert result["quality_score"] > 0.8
    assert Path(result["embedding_path"]).exists()

@pytest.mark.asyncio
async def test_speech_generation(tts_engine):
    """Test single-speaker speech generation"""
    # First clone a voice
    test_audio = Path("tests/fixtures/test_voice_10s.wav")
    await tts_engine.clone_voice(
        audio_sample=open(test_audio, "rb"),
        voice_name="test_voice"
    )
    
    # Generate speech
    output_path = Path("/tmp/test_speech.wav")
    result = await tts_engine.generate_speech(
        text="This is a test of the speech generation system.",
        voice_id="test_voice",
        output_path=output_path
    )
    
    assert result.exists()
    assert result.stat().st_size > 0

@pytest.mark.asyncio
async def test_multi_speaker_generation(tts_engine):
    """Test multi-speaker conversation"""
    # Clone two voices
    voice1_audio = Path("tests/fixtures/voice1_10s.wav")
    voice2_audio = Path("tests/fixtures/voice2_10s.wav")
    
    await tts_engine.clone_voice(
        audio_sample=open(voice1_audio, "rb"),
        voice_name="speaker_1"
    )
    await tts_engine.clone_voice(
        audio_sample=open(voice2_audio, "rb"),
        voice_name="speaker_2"
    )
    
    # Generate conversation
    script = [
        {"speaker": "speaker_1", "text": "Hello, how are you?"},
        {"speaker": "speaker_2", "text": "I'm doing great, thanks!"},
        {"speaker": "speaker_1", "text": "That's wonderful to hear."}
    ]
    
    voice_mapping = {
        "speaker_1": "speaker_1",
        "speaker_2": "speaker_2"
    }
    
    output_path = Path("/tmp/test_conversation.wav")
    result = await tts_engine.generate_multi_speaker(
        script=script,
        voice_mapping=voice_mapping,
        output_path=output_path
    )
    
    assert result.exists()
    assert result.stat().st_size > 0

def test_list_voices(tts_engine):
    """Test listing available voices"""
    voices = tts_engine.list_available_voices()
    assert isinstance(voices, list)

def test_engine_info(tts_engine):
    """Test engine information"""
    info = tts_engine.get_engine_info()
    
    assert "engine" in info
    assert "version" in info
    assert "capabilities" in info
    assert info["capabilities"]["voice_cloning"] == True
    assert info["capabilities"]["multi_speaker"] == True
```

---

## **PHASE 7: DEPLOYMENT & DOCUMENTATION** (Day 8-9)

### **Step 7.1: Create Deployment Guide**

```markdown
# TTS System Deployment Guide

## Prerequisites

- NVIDIA GPU with 8GB+ VRAM
- Docker with NVIDIA Container Toolkit
- 50GB free disk space

## Quick Start

1. **Build and Start Services**
```bash
docker-compose up -d --build tts-service
```

2. **Verify Service is Running**
```bash
curl http://localhost:8001/health
```

3. **Clone Your First Voice**
```bash
curl -X POST "http://localhost:8001/voices/clone?voice_name=my_voice" \
  -F "audio_sample=@my_voice_sample.wav"
```

4. **Generate Speech**
```bash
curl -X POST "http://localhost:8001/generate/speech" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, this is my cloned voice!",
    "voice_id": "my_voice"
  }'
```

## Configuration

Environment variables in `docker-compose.yaml`:

- `TTS_MODEL_PATH`: Path to VIVEVoice model
- `VOICE_LIBRARY_PATH`: Where to store voice embeddings
- `OUTPUT_PATH`: Where to save generated audio
- `MAX_AUDIO_LENGTH`: Maximum audio duration (seconds)
- `ENABLE_RVC`: Enable RVC enhancement (true/false)

## Troubleshooting

### Service Won't Start
- Check GPU availability: `nvidia-smi`
- Check Docker logs: `docker logs harvis-tts`

### Voice Cloning Fails
- Ensure audio is 10+ seconds
- Check audio format (WAV, MP3, M4A supported)
- Verify audio quality (clear speech, minimal background noise)

### Low Audio Quality
- Try enabling RVC enhancement
- Increase diffusion_steps (32-64)
- Use longer voice samples (30-60 seconds)
```

---

### **Step 7.2: Create User Guide**

```markdown
# HARVIS Voice Cloning & Podcast Generation Guide

## Getting Started

### 1. Clone Your Voice

1. Go to **Voice Library** in HARVIS
2. Click **"Clone New Voice"**
3. Record or upload 10+ seconds of clear speech
4. Name your voice (e.g., "My Voice")
5. Click **"Clone Voice"**

⏱️ Takes ~30 seconds

### 2. Clone Character Voices

Want Walter White or Peter Griffin? Here's how:

1. Find a 10-second clip on YouTube
2. Download the audio
3. Upload to HARVIS Voice Library
4. Name it "Walter White"
5. Done! Now generate podcasts in that voice

### 3. Generate Your First Podcast

1. Go to your **Notebook**
2. Add research sources (PDFs, videos, etc.)
3. Click **"Generate Podcast"**
4. Configure:
   - **Speakers**: 1-4
   - **Style**: Conversational, Interview, etc.
   - **Voices**: Assign voices to each speaker
5. Click **"Generate"**
6. Get coffee ☕
7. Your podcast is ready in 5-10 minutes!

## Advanced Usage

### Multi-Language Podcasts

Clone voices in different languages:
- French voice → Speaks French
- Japanese voice → Speaks Japanese
- Spanish voice → Speaks Spanish

### Character Conversations

Create fun educational content:
```
Speaker 1: Your Voice (Teacher)
Speaker 2: Peter Griffin (Student)
Topic: Quantum Physics
```

Result: Peter Griffin learns quantum physics from you!

### Professional Podcasts

```
Speaker 1: Professional Narrator Voice
Speaker 2: Your Voice (Expert)
Style: Interview
```

Perfect for sharing research!

## Tips for Best Results

✅ **Do:**
- Use clear audio samples (minimal background noise)
- Speak naturally in voice samples
- Use 30-60 second samples for even better quality
- Test different voices for different content types

❌ **Don't:**
- Use audio with music/noise
- Use samples with multiple speakers
- Rush the voice cloning process

## FAQs

**Q: How many voices can I clone?**
A: Unlimited! Clone as many as you want.

**Q: Can I share my cloned voices?**
A: Yes, export voice files and share with your team.

**Q: How accurate is the voice cloning?**
A: 95%+ accuracy with good quality samples.

**Q: Can I use celebrity voices?**
A: Technically yes, but use responsibly and legally.

**Q: How long does podcast generation take?**
A: ~5-10 minutes for 15-minute podcast.

**Q: Does it work offline?**
A: Yes! 100% local, no internet needed.
```

---

## **PHASE 8: SAFETY & ETHICAL CONSIDERATIONS** (Critical)

### **Step 8.1: Implement Safety Measures**

```python
# python_back_end/tts_system/safety/content_filter.py
from typing import Optional
import re

class ContentSafetyFilter:
    """
    Filter inappropriate content before TTS generation
    """
    
    BLOCKED_PATTERNS = [
        # Add patterns for harmful content
        r'\b(explicit|harmful|pattern)\b',
        # Add more as needed
    ]
    
    @staticmethod
    def check_text(text: str) -> tuple[bool, Optional[str]]:
        """
        Check if text is safe for TTS generation
        
        Returns:
            (is_safe: bool, reason: Optional[str])
        """
        # Check for blocked patterns
        for pattern in ContentSafetyFilter.BLOCKED_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return False, "Content contains blocked patterns"
        
        # Check length
        if len(text) > 50000:  # ~10k words
            return False, "Text too long"
        
        return True, None
    
    @staticmethod
    def sanitize_voice_name(name: str) -> str:
        """Sanitize voice name to prevent injection"""
        # Remove special characters
        return re.sub(r'[^a-zA-Z0-9_-]', '', name)
```

```python
# Add to server.py
from .safety.content_filter import ContentSafetyFilter

@router.post("/generate/speech")
async def generate_speech(text: str, voice_id: str):
    # Safety check
    is_safe, reason = ContentSafetyFilter.check_text(text)
    if not is_safe:
        raise HTTPException(400, f"Content rejected: {reason}")
    
    # Sanitize voice name
    voice_id = ContentSafetyFilter.sanitize_voice_name(voice_id)
    
    # Continue with generation...
```

---

### **Step 8.2: Add Usage Warnings**

```typescript
// front_end/jfrontend/components/notebook/VoiceCloneWarning.tsx
export function VoiceCloneWarning() {
  return (
    <Alert className="border-yellow-500 bg-yellow-500/10">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>⚠️ Voice Cloning Ethics</AlertTitle>
      <AlertDescription>
        <ul className="list-disc list-inside space-y-1 mt-2">
          <li>Only clone voices you have permission to use</li>
          <li>Do not impersonate others for malicious purposes</li>
          <li>Clearly disclose when content is AI-generated</li>
          <li>Respect intellectual property and privacy rights</li>
          <li>Use responsibly and legally in your jurisdiction</li>
        </ul>
      </AlertDescription>
    </Alert>
  )
}
```

---

## **FINAL CHECKLIST**

### **Phase 1: Repository Analysis** ✅
- [ ] VIVEVoice repo cloned and analyzed
- [ ] Alternative solutions researched (Coqui TTS, etc.)
- [ ] Integration strategy documented
- [ ] Dependencies identified

### **Phase 2: Docker Infrastructure** ✅
- [ ] TTS service Dockerfile created
- [ ] docker-compose.yaml updated
- [ ] nginx.conf updated for TTS routing
- [ ] Persistent volumes configured
- [ ] GPU support configured

### **Phase 3: Backend TTS System** ✅
- [ ] Base TTS engine interface implemented
- [ ] VIVEVoice engine implemented
- [ ] Fallback engine implemented (Coqui TTS)
- [ ] FastAPI TTS service created
- [ ] API endpoints functional
- [ ] Voice cloning working
- [ ] Multi-speaker generation working

### **Phase 4: Frontend UI** ✅
- [ ] Voice Library component created
- [ ] Voice cloning dialog functional
- [ ] Podcast generator component created
- [ ] Voice assignment UI working
- [ ] Configuration options implemented

### **Phase 5: Integration** ✅
- [ ] API proxy routes created
- [ ] Frontend connected to backend
- [ ] Open Notebook integration complete
- [ ] End-to-end workflow functional

### **Phase 6: Testing** ✅
- [ ] Unit tests written
- [ ] Integration tests passing
- [ ] Manual testing complete
- [ ] Performance acceptable

### **Phase 7: Deployment** ✅
- [ ] Deployment guide written
- [ ] User guide created
- [ ] Docker build successful
- [ ] Services running in production

### **Phase 8: Safety** ✅
- [ ] Content filtering implemented
- [ ] Usage warnings added
- [ ] Ethical guidelines documented
- [ ] Legal disclaimers added

---

## **SUCCESS CRITERIA**

Your implementation is successful when:

1. ✅ User can clone their voice from 10-second sample
2. ✅ User can generate single-speaker podcast
3. ✅ User can generate multi-speaker conversation
4. ✅ Generated audio quality is high (no robotic sound)
5. ✅ System runs locally without cloud dependencies
6. ✅ Integration with Open Notebook notebooks works
7. ✅ UI is intuitive and user-friendly
8. ✅ Docker deployment is stable
9. ✅ Safety measures are in place
10. ✅ Documentation is complete

--

## **NOTES FOR OPUS**

- Replace placeholder VIVEVoice code with actual implementation based on repo analysis
- If VIVEVoice repo is unclear, use Coqui TTS as proven alternative
- Test each phase thoroughly before moving to next
- Document any deviations from this plan
- Ask for clarification if repo structure differs from assumptions
- Prioritize safety and ethical usage
- Keep user experience simple and modular

**Good luck, Opus! 🚀**

---

If you need help ask.