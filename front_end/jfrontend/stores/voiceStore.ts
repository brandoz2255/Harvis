import { create } from 'zustand'

// Types
export interface Voice {
  voice_id: string
  voice_name: string
  description?: string
  voice_type: 'user' | 'builtin'
  reference_audio_path?: string
  reference_duration?: number
  quality_score?: number
  created_at?: string
  user_id?: string
  // For built-in presets
  category?: string
  requires_activation?: boolean
  activated?: boolean
}

export interface VoicePreset {
  preset_id: string
  name: string
  description: string
  category: 'narrator' | 'host' | 'character' | 'educator' | 'storyteller'
  sample_text: string
  icon?: string
  requires_activation: boolean
  activated?: boolean
}

export interface GenerationSettings {
  cfg_scale: number
  inference_steps: number
  temperature: number
  seed?: number
}

export interface ScriptSegment {
  speaker: string
  text: string
  voice_id?: string
}

export interface PodcastRequest {
  script: ScriptSegment[]
  voice_mapping: Record<string, string>
  settings?: GenerationSettings
  output_format?: 'wav' | 'mp3' | 'ogg'
  normalize_audio?: boolean
  add_silence_between_speakers?: number
}

export interface GenerationResult {
  success: boolean
  job_id: string
  audio_url?: string
  audio_path?: string
  duration?: number
  generation_time?: number
  error?: string
  segments_count?: number
}

interface VoiceState {
  // State
  voices: Voice[]
  presets: VoicePreset[]
  isLoading: boolean
  isCloning: boolean
  isGenerating: boolean
  error: string | null
  currentGenerationJobId: string | null
  serviceAvailable: boolean
  
  // API base URL
  apiBase: string
  
  // Actions - Voice Management
  fetchVoices: () => Promise<void>
  fetchPresets: () => Promise<void>
  cloneVoice: (name: string, audioFile: File, description?: string) => Promise<Voice | null>
  deleteVoice: (voiceId: string) => Promise<boolean>
  activatePreset: (presetId: string, audioFile: File) => Promise<boolean>
  
  // Actions - Audio Generation
  generateSpeech: (text: string, voiceId: string, settings?: GenerationSettings) => Promise<GenerationResult | null>
  generatePodcast: (request: PodcastRequest) => Promise<GenerationResult | null>
  
  // Utility
  getVoiceById: (voiceId: string) => Voice | undefined
  getVoicesByCategory: (category: string) => Voice[]
  getUserVoices: () => Voice[]
  getBuiltInVoices: () => Voice[]
  getActivatedVoices: () => Voice[]
  clearError: () => void
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api'

export const useVoiceStore = create<VoiceState>((set, get) => ({
  // Initial state
  voices: [],
  presets: [],
  isLoading: false,
  isCloning: false,
  isGenerating: false,
  error: null,
  currentGenerationJobId: null,
  serviceAvailable: true,
  apiBase: `${API_BASE}/tts`,
  
  // Fetch all voices (user + built-in)
  fetchVoices: async () => {
    set({ isLoading: true, error: null })
    
    try {
      const response = await fetch(`${get().apiBase}/voices`, {
        credentials: 'include'
      })
      
      if (!response.ok) {
        throw new Error('Failed to fetch voices')
      }
      
      const data = await response.json()
      set({ 
        voices: data.voices || [], 
        isLoading: false,
        serviceAvailable: data.service_status !== 'unavailable'
      })
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'Failed to fetch voices',
        isLoading: false 
      })
    }
  },
  
  // Fetch built-in presets
  fetchPresets: async () => {
    try {
      const response = await fetch(`${get().apiBase}/presets`, {
        credentials: 'include'
      })
      
      if (!response.ok) {
        throw new Error('Failed to fetch presets')
      }
      
      const data = await response.json()
      set({ presets: data.presets || [] })
    } catch (error) {
      console.error('Failed to fetch presets:', error)
    }
  },
  
  // Clone a new voice from audio
  cloneVoice: async (name: string, audioFile: File, description?: string) => {
    set({ isCloning: true, error: null })
    
    try {
      const formData = new FormData()
      formData.append('audio_sample', audioFile)
      
      const params = new URLSearchParams({ voice_name: name })
      if (description) params.append('description', description)
      
      const response = await fetch(`${get().apiBase}/voices/clone?${params}`, {
        method: 'POST',
        credentials: 'include',
        body: formData
      })
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Voice cloning failed')
      }
      
      const result = await response.json()
      
      if (result.success && result.voice) {
        // Add the new voice to the store
        set(state => ({
          voices: [...state.voices, result.voice],
          isCloning: false
        }))
        return result.voice
      }
      
      throw new Error(result.error || 'Voice cloning failed')
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'Voice cloning failed',
        isCloning: false 
      })
      return null
    }
  },
  
  // Delete a user voice
  deleteVoice: async (voiceId: string) => {
    try {
      const response = await fetch(`${get().apiBase}/voices/${voiceId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      
      if (!response.ok) {
        throw new Error('Failed to delete voice')
      }
      
      // Remove from store
      set(state => ({
        voices: state.voices.filter(v => v.voice_id !== voiceId)
      }))
      
      return true
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to delete voice' })
      return false
    }
  },
  
  // Activate a built-in preset with custom audio
  activatePreset: async (presetId: string, audioFile: File) => {
    set({ isCloning: true, error: null })
    
    try {
      const formData = new FormData()
      formData.append('audio_sample', audioFile)
      
      const response = await fetch(`${get().apiBase}/presets/${presetId}/activate`, {
        method: 'POST',
        credentials: 'include',
        body: formData
      })
      
      if (!response.ok) {
        throw new Error('Failed to activate preset')
      }
      
      // Refresh voices to get updated activation status
      await get().fetchVoices()
      set({ isCloning: false })
      
      return true
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'Failed to activate preset',
        isCloning: false 
      })
      return false
    }
  },
  
  // Generate speech for a single text
  generateSpeech: async (text: string, voiceId: string, settings?: GenerationSettings) => {
    set({ isGenerating: true, error: null })
    
    try {
      const response = await fetch(`${get().apiBase}/generate/speech`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          voice_id: voiceId,
          settings
        })
      })
      
      if (!response.ok) {
        throw new Error('Speech generation failed')
      }
      
      const result = await response.json()
      set({ 
        isGenerating: false,
        currentGenerationJobId: result.job_id || null
      })
      
      return result as GenerationResult
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'Speech generation failed',
        isGenerating: false 
      })
      return null
    }
  },
  
  // Generate multi-speaker podcast
  generatePodcast: async (request: PodcastRequest) => {
    set({ isGenerating: true, error: null })
    
    try {
      const response = await fetch(`${get().apiBase}/generate/podcast`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
      })
      
      if (!response.ok) {
        throw new Error('Podcast generation failed')
      }
      
      const result = await response.json()
      set({ 
        isGenerating: false,
        currentGenerationJobId: result.job_id || null
      })
      
      return result as GenerationResult
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'Podcast generation failed',
        isGenerating: false 
      })
      return null
    }
  },
  
  // Utility functions
  getVoiceById: (voiceId: string) => {
    return get().voices.find(v => v.voice_id === voiceId)
  },
  
  getVoicesByCategory: (category: string) => {
    return get().voices.filter(v => v.category === category)
  },
  
  getUserVoices: () => {
    return get().voices.filter(v => v.voice_type === 'user')
  },
  
  getBuiltInVoices: () => {
    return get().voices.filter(v => v.voice_type === 'builtin')
  },
  
  getActivatedVoices: () => {
    return get().voices.filter(v => v.voice_type === 'user' || v.activated)
  },
  
  clearError: () => {
    set({ error: null })
  }
}))
