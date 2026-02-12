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

// RVC Character Voice
export interface RVCVoice {
  slug: string
  name: string
  category: 'cartoon' | 'tv_show' | 'celebrity' | 'custom'
  description?: string
  model_path: string
  index_path?: string
  pitch_shift: number
  is_cached: boolean
  created_at?: string
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
  voice_mapping: Record<string, string>  // speaker -> base voice_id
  rvc_voice_mapping?: Record<string, string>  // speaker -> rvc voice slug
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
  rvcVoices: RVCVoice[]
  rvcAvailable: boolean
  isLoading: boolean
  isCloning: boolean
  isGenerating: boolean
  isImportingRvc: boolean
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
  
  // Actions - RVC Voice Management
  fetchRvcVoices: () => Promise<void>
  fetchUserRvcVoices: (userId: string) => Promise<void>
  importRvcVoice: (name: string, slug: string, category: string, modelFile: File, indexFile?: File, description?: string, pitchShift?: number) => Promise<RVCVoice | null>
  importRvcVoiceFromUrl: (url: string, name: string, slug: string, category: string, userId: string, description?: string) => Promise<RVCVoice | null>
  deleteRvcVoice: (slug: string) => Promise<boolean>
  cacheRvcVoice: (slug: string) => Promise<boolean>
  uncacheRvcVoice: (slug: string) => Promise<boolean>
  
  // Actions - Audio Generation
  generateSpeech: (text: string, voiceId: string, settings?: GenerationSettings) => Promise<GenerationResult | null>
  generateRvcSpeech: (text: string, baseVoiceId: string, rvcSlug: string, pitchShift?: number, settings?: GenerationSettings) => Promise<GenerationResult | null>
  generatePodcast: (request: PodcastRequest) => Promise<GenerationResult | null>
  
  // Utility
  getVoiceById: (voiceId: string) => Voice | undefined
  getRvcVoiceBySlug: (slug: string) => RVCVoice | undefined
  getVoicesByCategory: (category: string) => Voice[]
  getRvcVoicesByCategory: (category: string) => RVCVoice[]
  getUserVoices: () => Voice[]
  getBuiltInVoices: () => Voice[]
  getActivatedVoices: () => Voice[]
  clearError: () => void
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api'

function getUserIdFromToken(): string | null {
  try {
    if (typeof window === 'undefined') return null
    const token = window.localStorage.getItem('token')
    if (!token) return null
    const parts = token.split('.')
    if (parts.length < 2) return null
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const json = JSON.parse(atob(payload))
    const sub = json?.sub ?? json?.user_id
    if (!sub) return null
    return String(sub)
  } catch {
    return null
  }
}

export const useVoiceStore = create<VoiceState>((set, get) => ({
  // Initial state
  voices: [],
  presets: [],
  rvcVoices: [],
  rvcAvailable: false,
  isLoading: false,
  isCloning: false,
  isGenerating: false,
  isImportingRvc: false,
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
  
  // ─── RVC Voice Management ───────────────────────────────────────────────────
  
  // Fetch all RVC character voices
  fetchRvcVoices: async () => {
    try {
      const userId = getUserIdFromToken()

      // Prefer user-scoped endpoint so imported models show up immediately
      const url = userId
        ? `${get().apiBase}/rvc/voices/user/${encodeURIComponent(userId)}`
        : `${get().apiBase}/rvc/voices`

      const response = await fetch(url, { credentials: 'include' })
      if (!response.ok) throw new Error('Failed to fetch RVC voices')

      const data = await response.json()

      // User endpoint doesn't include rvc_available, so fall back if missing
      const rvcAvailable = typeof data.rvc_available === 'boolean' ? data.rvc_available : get().rvcAvailable

      set({
        rvcVoices: data.voices || [],
        rvcAvailable
      })
    } catch (error) {
      console.error('Failed to fetch RVC voices:', error)
      set({ rvcAvailable: false })
    }
  },
  
  // Fetch RVC voices for a specific user
  fetchUserRvcVoices: async (userId: string) => {
    try {
      const response = await fetch(`${get().apiBase}/rvc/voices/user/${userId}`, {
        credentials: 'include'
      })
      
      if (!response.ok) {
        throw new Error('Failed to fetch user RVC voices')
      }
      
      const data = await response.json()
      set({ 
        rvcVoices: data.voices || []
      })
    } catch (error) {
      console.error('Failed to fetch user RVC voices:', error)
    }
  },
  
  // Import a new RVC voice model
  importRvcVoice: async (
    name: string, 
    slug: string, 
    category: string, 
    modelFile: File, 
    indexFile?: File, 
    description?: string, 
    pitchShift?: number
  ) => {
    set({ isImportingRvc: true, error: null })
    
    try {
      const formData = new FormData()
      formData.append('name', name)
      formData.append('slug', slug)
      formData.append('category', category)
      formData.append('model_file', modelFile)
      if (indexFile) formData.append('index_file', indexFile)
      if (description) formData.append('description', description)
      if (pitchShift !== undefined) formData.append('pitch_shift', pitchShift.toString())
      
      const response = await fetch(`${get().apiBase}/rvc/voices/import`, {
        method: 'POST',
        credentials: 'include',
        body: formData
      })
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Failed to import RVC voice')
      }
      
      const result = await response.json()
      
      if (result.success && result.voice) {
        set(state => ({
          rvcVoices: [...state.rvcVoices, result.voice],
          isImportingRvc: false
        }))
        return result.voice as RVCVoice
      }
      
      throw new Error(result.error || 'Import failed')
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'Failed to import RVC voice',
        isImportingRvc: false 
      })
      return null
    }
  },
  
  // Import RVC voice from URL (e.g., from voice-models.com)
  importRvcVoiceFromUrl: async (
    url: string,
    name: string,
    slug: string,
    category: string,
    userId: string,
    description?: string
  ) => {
    set({ isImportingRvc: true, error: null })
    
    try {
      const response = await fetch(`${get().apiBase}/rvc/voices/import-url`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          name,
          slug,
          category,
          user_id: userId,
          description: description || ''
        })
      })
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Failed to import RVC voice from URL')
      }
      
      const result = await response.json()
      
      if (result.success && result.voice) {
        set(state => ({
          rvcVoices: [...state.rvcVoices, result.voice],
          isImportingRvc: false
        }))
        return result.voice as RVCVoice
      }
      
      throw new Error(result.error || 'Import failed')
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'Failed to import RVC voice from URL',
        isImportingRvc: false 
      })
      return null
    }
  },
  
  // Delete an RVC voice
  deleteRvcVoice: async (slug: string) => {
    try {
      const response = await fetch(`${get().apiBase}/rvc/voices/${slug}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      
      if (!response.ok) {
        throw new Error('Failed to delete RVC voice')
      }
      
      set(state => ({
        rvcVoices: state.rvcVoices.filter(v => v.slug !== slug)
      }))
      
      return true
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to delete RVC voice' })
      return false
    }
  },
  
  // Pre-load RVC voice into VRAM cache
  cacheRvcVoice: async (slug: string) => {
    try {
      const response = await fetch(`${get().apiBase}/rvc/voices/${slug}/cache`, {
        method: 'POST',
        credentials: 'include'
      })
      
      if (!response.ok) {
        throw new Error('Failed to cache RVC voice')
      }
      
      // Update cached status
      set(state => ({
        rvcVoices: state.rvcVoices.map(v => 
          v.slug === slug ? { ...v, is_cached: true } : v
        )
      }))
      
      return true
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to cache RVC voice' })
      return false
    }
  },
  
  // Remove RVC voice from VRAM cache
  uncacheRvcVoice: async (slug: string) => {
    try {
      const response = await fetch(`${get().apiBase}/rvc/voices/${slug}/uncache`, {
        method: 'POST',
        credentials: 'include'
      })
      
      if (!response.ok) {
        throw new Error('Failed to uncache RVC voice')
      }
      
      set(state => ({
        rvcVoices: state.rvcVoices.map(v => 
          v.slug === slug ? { ...v, is_cached: false } : v
        )
      }))
      
      return true
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to uncache RVC voice' })
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
  
  // Generate speech with RVC voice conversion
  generateRvcSpeech: async (
    text: string, 
    baseVoiceId: string, 
    rvcSlug: string, 
    pitchShift?: number, 
    settings?: GenerationSettings
  ) => {
    set({ isGenerating: true, error: null })
    
    try {
      const response = await fetch(`${get().apiBase}/rvc/generate/speech`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          base_voice_id: baseVoiceId,
          rvc_voice_slug: rvcSlug,
          pitch_shift: pitchShift || 0,
          settings
        })
      })
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'RVC speech generation failed')
      }
      
      const result = await response.json()
      set({ 
        isGenerating: false,
        currentGenerationJobId: result.job_id || null
      })
      
      return result as GenerationResult
    } catch (error) {
      set({ 
        error: error instanceof Error ? error.message : 'RVC speech generation failed',
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
  
  getRvcVoiceBySlug: (slug: string) => {
    return get().rvcVoices.find(v => v.slug === slug)
  },
  
  getVoicesByCategory: (category: string) => {
    return get().voices.filter(v => v.category === category)
  },
  
  getRvcVoicesByCategory: (category: string) => {
    return get().rvcVoices.filter(v => v.category === category)
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
