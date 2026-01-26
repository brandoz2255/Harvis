# 🎙️ HARVIS VIBEVOICE INTEGRATION - COMPLETE MASTER PROMPT

*Voice Cloning & Podcast Generation Implementation Guide*

---

## 📋 TABLE OF CONTENTS

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Phase 1: Backend Setup](#phase-1-backend-setup)
4. [Phase 2: Frontend UI](#phase-2-frontend-ui)
5. [Phase 3: Integration](#phase-3-integration)
6. [Phase 4: Testing](#phase-4-testing)
7. [Phase 5: Deployment](#phase-5-deployment)
8. [Troubleshooting](#troubleshooting)
9. [API Reference](#api-reference)

---

## 🚀 QUICK START

### **Goal**
Add VibeVoice voice cloning to HARVIS, enabling users to:
- Clone ANY voice from 10-60 second samples (Walter White, Peter Griffin, etc.)
- Generate multi-speaker podcasts (up to 4 speakers)
- Create long-form audio (up to 90 minutes)
- All running locally on 7-8GB VRAM GPU

### **Key Model Info**
```yaml
Model: microsoft/VibeVoice-1.5B
License: MIT (fully open)
Access Token: NOT REQUIRED ✅
VRAM: 6-8GB (with 4-bit quantization)
Quality: Excellent
Voice Cloning: Zero-shot (no training needed)
Languages: English + Chinese (+ experimental multilingual)
```

### **Implementation Time**
- Backend: 2-3 days
- Frontend: 2-3 days
- Integration & Testing: 1-2 days
- **Total: ~7 days**

---

## 🏗️ ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────┐
│           Frontend (Next.js)                │
│  ┌─────────────┐    ┌──────────────────┐  │
│  │Voice Library│    │Podcast Generator │  │
│  │   UI        │    │       UI         │  │
│  └──────┬──────┘    └────────┬─────────┘  │
└─────────┼──────────────────────┼────────────┘
          │                      │
          │    API Requests      │
          ▼                      ▼
┌─────────────────────────────────────────────┐
│         HARVIS Backend (FastAPI)            │
│         /api/tts/* proxy routes             │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│      TTS Service (Docker Container)         │
│  ┌────────────────────────────────────┐    │
│  │    VibeVoice Engine                │    │
│  │  - Voice Cloning                   │    │
│  │  - Multi-Speaker Generation        │    │
│  │  - 4-bit Quantization              │    │
│  └────────────────────────────────────┘    │
│                                             │
│  Volumes:                                   │
│  - /app/models  (Model weights)            │
│  - /app/voices  (Voice library)            │
│  - /app/output  (Generated audio)          │
└─────────────────────────────────────────────┘
```

---

## 📦 PHASE 1: BACKEND SETUP

### **Step 1.1: File Structure**

Create this directory structure:

```
python_back_end/
└── tts_system/
    ├── __init__.py
    ├── server.py                    # FastAPI service
    ├── engines/
    │   ├── __init__.py
    │   └── vibevoice_engine.py     # VibeVoice implementation
    └── models/
        ├── __init__.py
        └── voice_model.py          # Data models
```

### **Step 1.2: Install Dependencies**

All backend files have been created in `/mnt/user-data/outputs/python_back_end/tts_system/`

Copy them to your project:
```bash
cp -r /mnt/user-data/outputs/python_back_end/tts_system/* python_back_end/tts_system/
```

### **Step 1.3: Docker Setup**

Files created in `/mnt/user-data/outputs/docker/`:

1. **Dockerfile** - `docker/tts-service/Dockerfile`
2. **Requirements** - `docker/tts-service/requirements-tts.txt`
3. **Docker Compose Addition** - `docker-compose-tts-addition.yaml`
4. **Nginx Config Addition** - `nginx-tts-addition.conf`

**Integration Steps:**

```bash
# 1. Copy Docker files
mkdir -p docker/tts-service
cp /mnt/user-data/outputs/docker/tts-service/* docker/tts-service/

# 2. Add TTS service to docker-compose.yaml
# Append contents of docker-compose-tts-addition.yaml to your docker-compose.yaml

# 3. Update nginx.conf
# Append contents of nginx-tts-addition.conf to your nginx.conf

# 4. Build and start
docker-compose up -d --build tts-service
```

### **Step 1.4: Verify Backend**

```bash
# Check service is running
docker logs harvis-tts

# Should see:
# ✅ TTS Service Ready!

# Test health endpoint
curl http://localhost:8001/health

# Should return:
# {"status": "healthy", "engine_info": {...}}
```

---

## 🎨 PHASE 2: FRONTEND UI

### **Step 2.1: Voice Library Component**

Create: `front_end/jfrontend/components/notebook/VoiceLibrary.tsx`

```typescript
'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Mic, Upload, Trash2, Play, Pause, Sparkles } from 'lucide-react'
import { useToast } from '@/components/ui/use-toast'

interface Voice {
  voice_id: string
  voice_name: string
  description?: string
  reference_duration: number
  created_at: string
  quality_score?: number
}

export function VoiceLibrary() {
  const [voices, setVoices] = useState<Voice[]>([])
  const [loading, setLoading] = useState(true)
  const { toast } = useToast()
  
  useEffect(() => {
    fetchVoices()
  }, [])
  
  const fetchVoices = async () => {
    try {
      const res = await fetch('/api/tts/voices')
      const data = await res.json()
      setVoices(data.voices)
    } catch (error) {
      console.error('Failed to fetch voices:', error)
    } finally {
      setLoading(false)
    }
  }
  
  const handleCloneVoice = async (voiceName: string, audioFile: File, description?: string) => {
    try {
      const formData = new FormData()
      formData.append('audio_sample', audioFile)
      
      const res = await fetch(
        `/api/tts/voices/clone?voice_name=${encodeURIComponent(voiceName)}${
          description ? `&description=${encodeURIComponent(description)}` : ''
        }`,
        {
          method: 'POST',
          body: formData
        }
      )
      
      if (!res.ok) throw new Error('Voice cloning failed')
      
      const result = await res.json()
      
      toast({
        title: '✅ Voice Cloned!',
        description: `"${voiceName}" is ready to use in podcasts.`
      })
      
      fetchVoices()
      
    } catch (error) {
      toast({
        title: '❌ Cloning Failed',
        description: error.message,
        variant: 'destructive'
      })
    }
  }
  
  const handleDeleteVoice = async (voiceId: string) => {
    try {
      await fetch(`/api/tts/voices/${voiceId}`, { method: 'DELETE' })
      
      toast({
        title: 'Voice Deleted',
        description: `Voice removed from library.`
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
          <p className="text-sm text-gray-400 mt-1">
            Clone voices from 10-60 second audio samples
          </p>
        </div>
        
        <VoiceCloneDialog onClone={handleCloneVoice} />
      </div>
      
      {/* Voice Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading ? (
          <div className="col-span-full text-center py-12">
            <div className="animate-spin w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
            <p className="text-gray-400">Loading voices...</p>
          </div>
        ) : voices.length === 0 ? (
          <Card className="col-span-full bg-gray-900/50 border-gray-800">
            <CardContent className="pt-12 pb-12 text-center">
              <Mic className="w-16 h-16 mx-auto mb-4 text-gray-600" />
              <h3 className="text-lg font-semibold mb-2">No Voices Yet</h3>
              <p className="text-gray-400 mb-6">
                Clone your first voice to start generating podcasts
              </p>
              <VoiceCloneDialog onClone={handleCloneVoice} />
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
  const [description, setDescription] = useState('')
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [isCloning, setIsCloning] = useState(false)
  
  const handleSubmit = async () => {
    if (!voiceName || !audioFile) return
    
    setIsCloning(true)
    await onClone(voiceName, audioFile, description)
    setIsCloning(false)
    
    // Reset
    setVoiceName('')
    setDescription('')
    setAudioFile(null)
    setOpen(false)
  }
  
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="bg-blue-600 hover:bg-blue-700">
          <Sparkles className="w-4 h-4 mr-2" />
          Clone Voice
        </Button>
      </DialogTrigger>
      
      <DialogContent className="sm:max-w-[500px] bg-gray-900 border-gray-800">
        <DialogHeader>
          <DialogTitle>Clone a Voice</DialogTitle>
          <DialogDescription className="text-gray-400">
            Upload 10-60 seconds of clear speech. Works with any voice!
          </DialogDescription>
        </DialogHeader>
        
        <div className="space-y-4 pt-4">
          {/* Voice Name */}
          <div>
            <Label htmlFor="voice-name" className="text-sm font-medium">
              Voice Name *
            </Label>
            <Input
              id="voice-name"
              placeholder="e.g., Walter White, My Voice, etc."
              value={voiceName}
              onChange={(e) => setVoiceName(e.target.value)}
              className="mt-1.5 bg-gray-800 border-gray-700"
            />
          </div>
          
          {/* Description */}
          <div>
            <Label htmlFor="description" className="text-sm font-medium">
              Description (optional)
            </Label>
            <Input
              id="description"
              placeholder="e.g., Character from Breaking Bad"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="mt-1.5 bg-gray-800 border-gray-700"
            />
          </div>
          
          {/* Audio Upload */}
          <div>
            <Label className="text-sm font-medium mb-2 block">
              Audio Sample * (10-60 seconds)
            </Label>
            <Button
              variant="outline"
              className="w-full justify-start bg-gray-800 border-gray-700 hover:bg-gray-750"
              onClick={() => document.getElementById('audio-upload')?.click()}
            >
              <Upload className="w-4 h-4 mr-2" />
              {audioFile ? audioFile.name : 'Choose audio file...'}
            </Button>
            
            <input
              id="audio-upload"
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={(e) => setAudioFile(e.target.files?.[0] || null)}
            />
            
            {audioFile && (
              <p className="text-xs text-gray-400 mt-2">
                ✓ {(audioFile.size / 1024 / 1024).toFixed(2)} MB
              </p>
            )}
          </div>
          
          {/* Submit */}
          <Button
            onClick={handleSubmit}
            disabled={!voiceName || !audioFile || isCloning}
            className="w-full bg-blue-600 hover:bg-blue-700"
          >
            {isCloning ? (
              <>
                <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full mr-2"></div>
                Cloning Voice...
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4 mr-2" />
                Clone Voice
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function VoiceCard({ voice, onDelete }) {
  const [playing, setPlaying] = useState(false)
  const [showDelete, setShowDelete] = useState(false)
  
  return (
    <Card className="bg-gray-900/50 border-gray-800 hover:border-gray-700 transition-colors">
      <CardHeader className="pb-3">
        <div className="flex justify-between items-start">
          <div className="flex-1 min-w-0">
            <CardTitle className="text-base truncate">
              {voice.voice_name}
            </CardTitle>
            {voice.description && (
              <CardDescription className="text-xs mt-1">
                {voice.description}
              </CardDescription>
            )}
          </div>
          
          <Button
            variant="ghost"
            size="sm"
            className="text-gray-400 hover:text-red-400 -mr-2"
            onClick={() => setShowDelete(true)}
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        </div>
      </CardHeader>
      
      <CardContent className="space-y-2">
        <div className="flex justify-between text-xs text-gray-400">
          <span>{voice.reference_duration.toFixed(1)}s sample</span>
          {voice.quality_score && (
            <span>Quality: {(voice.quality_score * 100).toFixed(0)}%</span>
          )}
        </div>
        
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => setPlaying(!playing)}
        >
          {playing ? (
            <>
              <Pause className="w-3 h-3 mr-2" />
              Pause Sample
            </>
          ) : (
            <>
              <Play className="w-3 h-3 mr-2" />
              Play Sample
            </>
          )}
        </Button>
      </CardContent>
      
      {/* Delete Confirmation */}
      {showDelete && (
        <div className="absolute inset-0 bg-black/80 flex items-center justify-center rounded-lg">
          <div className="text-center p-4">
            <p className="text-sm mb-3">Delete this voice?</p>
            <div className="flex gap-2 justify-center">
              <Button
                size="sm"
                variant="destructive"
                onClick={() => {
                  onDelete(voice.voice_id)
                  setShowDelete(false)
                }}
              >
                Delete
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowDelete(false)}
              >
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}
```

### **Step 2.2: Podcast Generator Component**

Create: `front_end/jfrontend/components/notebook/PodcastGenerator.tsx`

```typescript
'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Sparkles, Volume2, Download } from 'lucide-react'
import { useToast } from '@/components/ui/use-toast'

interface Voice {
  voice_id: string
  voice_name: string
}

export function PodcastGenerator({ notebookId }: { notebookId: string }) {
  const [voices, setVoices] = useState<Voice[]>([])
  const [script, setScript] = useState('')
  const [speakerCount, setSpeakerCount] = useState(2)
  const [voiceMapping, setVoiceMapping] = useState<Record<string, string>>({})
  const [generating, setGenerating] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const { toast } = useToast()
  
  useEffect(() => {
    fetchVoices()
  }, [])
  
  const fetchVoices = async () => {
    try {
      const res = await fetch('/api/tts/voices')
      const data = await res.json()
      setVoices(data.voices)
    } catch (error) {
      console.error('Failed to fetch voices:', error)
    }
  }
  
  const parseScript = (scriptText: string) => {
    // Parse format: [1] Text or Speaker 1: Text
    const lines = scriptText.split('\n').filter(line => line.trim())
    const parsed = []
    
    for (const line of lines) {
      const match = line.match(/^\[(\d+)\](.+)$/) || line.match(/^Speaker (\d+):(.+)$/)
      if (match) {
        parsed.push({
          speaker: match[1],
          text: match[2].trim()
        })
      }
    }
    
    return parsed
  }
  
  const handleGenerate = async () => {
    if (!script.trim()) {
      toast({
        title: 'No Script',
        description: 'Please enter a podcast script.',
        variant: 'destructive'
      })
      return
    }
    
    // Check voice mapping
    for (let i = 1; i <= speakerCount; i++) {
      if (!voiceMapping[i.toString()]) {
        toast({
          title: 'Missing Voice',
          description: `Please assign a voice to Speaker ${i}.`,
          variant: 'destructive'
        })
        return
      }
    }
    
    setGenerating(true)
    
    try {
      const parsedScript = parseScript(script)
      
      const res = await fetch('/api/tts/generate/podcast', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          script: parsedScript,
          voice_mapping: voiceMapping,
          settings: {
            cfg_scale: 1.3,
            inference_steps: 10
          }
        })
      })
      
      if (!res.ok) throw new Error('Generation failed')
      
      const result = await res.json()
      
      setAudioUrl(result.audio_url)
      
      toast({
        title: '✅ Podcast Generated!',
        description: `Duration: ${result.duration.toFixed(1)}s`
      })
      
    } catch (error) {
      toast({
        title: '❌ Generation Failed',
        description: error.message,
        variant: 'destructive'
      })
    } finally {
      setGenerating(false)
    }
  }
  
  return (
    <div className="space-y-6">
      <Card className="bg-gray-900/50 border-gray-800">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Volume2 className="w-5 h-5" />
            Generate Podcast
          </CardTitle>
        </CardHeader>
        
        <CardContent className="space-y-4">
          {/* Number of Speakers */}
          <div>
            <Label className="text-sm font-medium mb-2 block">
              Number of Speakers
            </Label>
            <Select
              value={speakerCount.toString()}
              onValueChange={(v) => setSpeakerCount(parseInt(v))}
            >
              <SelectTrigger className="bg-gray-800 border-gray-700">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">1 Speaker (Monologue)</SelectItem>
                <SelectItem value="2">2 Speakers (Dialogue)</SelectItem>
                <SelectItem value="3">3 Speakers (Panel)</SelectItem>
                <SelectItem value="4">4 Speakers (Group)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          
          {/* Voice Assignment */}
          {Array.from({ length: speakerCount }).map((_, i) => {
            const speakerId = (i + 1).toString()
            return (
              <div key={speakerId}>
                <Label className="text-sm font-medium mb-2 block">
                  Speaker {speakerId} Voice
                </Label>
                <Select
                  value={voiceMapping[speakerId]}
                  onValueChange={(v) => 
                    setVoiceMapping({ ...voiceMapping, [speakerId]: v })
                  }
                >
                  <SelectTrigger className="bg-gray-800 border-gray-700">
                    <SelectValue placeholder="Select voice..." />
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
            )
          })}
          
          {voices.length === 0 && (
            <p className="text-sm text-yellow-500">
              ⚠️ No voices available. Clone voices first in Voice Library.
            </p>
          )}
          
          {/* Script Input */}
          <div>
            <Label className="text-sm font-medium mb-2 block">
              Podcast Script
            </Label>
            <p className="text-xs text-gray-400 mb-2">
              Format: [1] Text or Speaker 1: Text
            </p>
            <Textarea
              placeholder={`[1] Welcome to the show!\n[2] Thanks for having me!\n[1] Let's dive in...`}
              value={script}
              onChange={(e) => setScript(e.target.value)}
              className="min-h-[200px] bg-gray-800 border-gray-700 font-mono text-sm"
            />
          </div>
          
          {/* Generate Button */}
          <Button
            onClick={handleGenerate}
            disabled={generating || voices.length === 0}
            className="w-full bg-blue-600 hover:bg-blue-700"
            size="lg"
          >
            {generating ? (
              <>
                <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full mr-2"></div>
                Generating Podcast...
              </>
            ) : (
              <>
                <Sparkles className="w-5 h-5 mr-2" />
                Generate Podcast
              </>
            )}
          </Button>
          
          {/* Audio Player */}
          {audioUrl && (
            <div className="pt-4 border-t border-gray-800">
              <Label className="text-sm font-medium mb-2 block">
                Generated Podcast
              </Label>
              <audio controls className="w-full" src={audioUrl}>
                Your browser does not support audio.
              </audio>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => window.open(audioUrl, '_blank')}
              >
                <Download className="w-4 h-4 mr-2" />
                Download
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
```

### **Step 2.3: Add to Notebook Page**

Update: `front_end/jfrontend/app/notebook/[id]/page.tsx`

```typescript
import { VoiceLibrary } from '@/components/notebook/VoiceLibrary'
import { PodcastGenerator } from '@/components/notebook/PodcastGenerator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export default function NotebookPage({ params }: { params: { id: string } }) {
  return (
    <div className="container mx-auto p-6">
      <Tabs defaultValue="sources">
        <TabsList>
          <TabsTrigger value="sources">Sources</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="podcast">🎙️ Podcast</TabsTrigger>
          <TabsTrigger value="voices">🎤 Voices</TabsTrigger>
        </TabsList>
        
        <TabsContent value="sources">
          {/* Existing sources UI */}
        </TabsContent>
        
        <TabsContent value="chat">
          {/* Existing chat UI */}
        </TabsContent>
        
        <TabsContent value="podcast">
          <PodcastGenerator notebookId={params.id} />
        </TabsContent>
        
        <TabsContent value="voices">
          <VoiceLibrary />
        </TabsContent>
      </Tabs>
    </div>
  )
}
```

---

## 🔗 PHASE 3: INTEGRATION

### **Step 3.1: Create Backend API Proxy**

Create: `python_back_end/api/tts_routes.py`

```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import Dict
import httpx
import os

router = APIRouter(prefix="/api/tts", tags=["tts"])

TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://tts-service:8001")

@router.post("/voices/clone")
async def clone_voice(
    voice_name: str,
    audio_sample: UploadFile = File(...),
    description: str = None
):
    """Proxy to TTS service - Clone voice"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        files = {"audio_sample": (audio_sample.filename, audio_sample.file)}
        params = {"voice_name": voice_name}
        if description:
            params["description"] = description
        
        response = await client.post(
            f"{TTS_SERVICE_URL}/voices/clone",
            params=params,
            files=files
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
        response = await client.delete(f"{TTS_SERVICE_URL}/voices/{voice_id}")
        return response.json()

@router.post("/generate/podcast")
async def generate_podcast(request: Dict):
    """Proxy to TTS service - Generate podcast"""
    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(
            f"{TTS_SERVICE_URL}/generate/podcast",
            json=request
        )
        
        if response.status_code != 200:
            raise HTTPException(response.status_code, response.text)
        
        return response.json()
```

Add to main backend:

```python
# python_back_end/api/main.py
from .tts_routes import router as tts_router

app.include_router(tts_router)
```

---

## 🧪 PHASE 4: TESTING

### **Step 4.1: Test Voice Cloning**

```bash
# 1. Prepare test audio (10+ seconds of clear speech)
# Download a sample: Walter White saying "I am the one who knocks"

# 2. Test cloning via API
curl -X POST "http://localhost:8001/voices/clone?voice_name=walter_white" \
  -F "audio_sample=@walter_white.wav"

# Expected response:
# {
#   "success": true,
#   "voice": {
#     "voice_id": "walter_white",
#     "voice_name": "walter_white",
#     ...
#   }
# }

# 3. Verify voice is listed
curl http://localhost:8001/voices

# 4. Test in UI
# - Go to http://localhost:3000/notebook/123/voices
# - Click "Clone Voice"
# - Upload audio & name it
# - Should appear in voice library
```

### **Step 4.2: Test Podcast Generation**

```bash
# Test via API
curl -X POST "http://localhost:8001/generate/podcast" \
  -H "Content-Type: application/json" \
  -d '{
    "script": [
      {"speaker": "1", "text": "Say my name."},
      {"speaker": "2", "text": "Heisenberg?"},
      {"speaker": "1", "text": "You are goddamn right."}
    ],
    "voice_mapping": {
      "1": "walter_white",
      "2": "peter_griffin"
    }
  }'

# Expected response:
# {
#   "success": true,
#   "audio_url": "/audio/podcast_xxx.wav",
#   "duration": 15.3,
#   ...
# }

# Download and listen
curl http://localhost:8001/audio/podcast_xxx.wav -o test_podcast.wav
```

### **Step 4.3: Test in UI**

1. **Voice Library Tab:**
   - Clone 2-3 voices
   - Play samples
   - Delete a voice
   - Verify it works

2. **Podcast Tab:**
   - Select 2 speakers
   - Assign voices
   - Enter script
   - Generate podcast
   - Listen to result
   - Download file

---

## 🚀 PHASE 5: DEPLOYMENT

### **Step 5.1: Production Build**

```bash
# 1. Build all services
docker-compose build

# 2. Start services
docker-compose up -d

# 3. Check logs
docker-compose logs -f tts-service

# 4. Verify services
curl http://localhost:8001/health
curl http://localhost:3000
```

### **Step 5.2: Model Download**

First run will auto-download VibeVoice-1.5B (~10GB):

```bash
# Monitor download progress
docker logs -f harvis-tts

# You'll see:
# Downloading microsoft/VibeVoice-1.5B...
# ✅ Model loaded successfully
```

### **Step 5.3: GPU Verification**

```bash
# Check GPU is being used
docker exec harvis-tts nvidia-smi

# Should show:
# +-----------------------------------------------------------------------------+
# | Processes:                                                                  |
# |  GPU   GI   CI        PID   Type   Process name                  GPU Memory |
# |        ID   ID                                                   Usage      |
# |=============================================================================|
# |    0   N/A  N/A      1234      C   python                          7500MiB |
# +-----------------------------------------------------------------------------+
```

---

## 🔧 TROUBLESHOOTING

### **Issue: Service won't start**

```bash
# Check GPU availability
nvidia-smi

# Check NVIDIA Docker runtime
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi

# Check logs
docker logs harvis-tts --tail 100
```

### **Issue: Out of VRAM**

```bash
# Enable 4-bit quantization (should be default)
# In docker-compose.yaml:
environment:
  - QUANTIZE_4BIT=true

# Restart service
docker-compose restart tts-service
```

### **Issue: Voice cloning fails**

Check audio requirements:
- Duration: 10-60 seconds
- Format: WAV, MP3, M4A, etc.
- Quality: Clear speech, minimal background noise
- Mono or stereo (will be converted to mono)

### **Issue: Generated audio quality is poor**

Try adjusting parameters:
```python
# Increase inference steps (slower but better quality)
settings = {
    "cfg_scale": 1.5,      # Higher = stricter to reference (1.0-2.0)
    "inference_steps": 20   # More steps = better quality (10-50)
}
```

---

## 📚 API REFERENCE

### **Voice Cloning**

```http
POST /api/tts/voices/clone?voice_name=walter_white
Content-Type: multipart/form-data

audio_sample: <audio file>
description: "Character from Breaking Bad" (optional)
```

### **List Voices**

```http
GET /api/tts/voices

Response:
{
  "voices": [
    {
      "voice_id": "walter_white",
      "voice_name": "walter_white",
      "reference_duration": 15.3,
      "quality_score": 0.95,
      "created_at": "2025-01-23T..."
    }
  ],
  "count": 1
}
```

### **Generate Podcast**

```http
POST /api/tts/generate/podcast
Content-Type: application/json

{
  "script": [
    {"speaker": "1", "text": "Hello"},
    {"speaker": "2", "text": "Hi"}
  ],
  "voice_mapping": {
    "1": "voice_id_1",
    "2": "voice_id_2"
  },
  "settings": {
    "cfg_scale": 1.3,
    "inference_steps": 10
  }
}

Response:
{
  "success": true,
  "job_id": "uuid",
  "audio_url": "/audio/podcast_uuid.wav",
  "duration": 30.5,
  "generation_time": 45.2
}
```

---

## ✅ SUCCESS CRITERIA

Your implementation is complete when:

1. ✅ TTS service starts without errors
2. ✅ VibeVoice model loads successfully
3. ✅ Can clone voice from 10-second sample via UI
4. ✅ Cloned voice appears in Voice Library
5. ✅ Can generate single-speaker speech
6. ✅ Can generate multi-speaker podcast (2-4 speakers)
7. ✅ Generated audio quality is high
8. ✅ Audio plays in browser
9. ✅ Can download generated podcasts
10. ✅ VRAM usage stays under 8GB

---

## 🎯 NEXT STEPS

After core implementation:

1. **Automatic Podcast Generation**
   - Integrate with Open Notebook
   - Auto-generate from notebook content
   - AI script writing

2. **Advanced Features**
   - Voice mixing (background music, effects)
   - Multi-language support
   - Batch generation
   - Voice presets library

3. **Optimization**
   - Caching for faster generation
   - Background job queue
   - Progress tracking
   - Preview generation (first 2 minutes)

---

## 📞 SUPPORT

If you encounter issues:

1. Check logs: `docker logs harvis-tts`
2. Verify GPU: `nvidia-smi`
3. Test API directly: `curl http://localhost:8001/health`
4. Check this master prompt for troubleshooting

**Good luck! 🚀🎙️**

---

*End of Master Prompt*