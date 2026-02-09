'use client'

import { useState, useEffect, useRef } from 'react'
import { NotebookSource, NotebookNote } from '@/stores/notebookStore'
import { useVoiceStore, Voice, RVCVoice } from '@/stores/voiceStore'
import {
  Mic,
  Play,
  Pause,
  Loader2,
  Users,
  Clock,
  MessageSquare,
  BookOpen,
  Sword,
  GraduationCap,
  Coffee,
  Download,
  RefreshCw,
  Trash2,
  Volume2,
  VolumeX,
  SkipBack,
  SkipForward,
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  StickyNote,
  AlertCircle,
  Info,
  Headphones,
  UserCircle2,
  Sparkles
} from 'lucide-react'

interface PodcastStyle {
  id: string
  name: string
  description: string
  icon: React.ReactNode
}

const PODCAST_STYLES: PodcastStyle[] = [
  { id: 'conversational', name: 'Conversational', description: 'Casual, friendly discussion', icon: <Coffee className="w-5 h-5" /> },
  { id: 'interview', name: 'Interview', description: 'Q&A format with host', icon: <MessageSquare className="w-5 h-5" /> },
  { id: 'educational', name: 'Educational', description: 'Structured teaching format', icon: <GraduationCap className="w-5 h-5" /> },
  { id: 'debate', name: 'Debate', description: 'Multiple perspectives', icon: <Sword className="w-5 h-5" /> },
  { id: 'storytelling', name: 'Storytelling', description: 'Narrative format', icon: <BookOpen className="w-5 h-5" /> },
]

const SPEAKER_LABELS = ['Host', 'Guest 1', 'Guest 2', 'Guest 3']

const SPEAKER_COLORS = [
  'from-violet-500 to-fuchsia-500',
  'from-emerald-500 to-teal-500',
  'from-amber-500 to-orange-500',
  'from-sky-500 to-blue-500'
]

interface Podcast {
  id: string
  title: string
  status: 'pending' | 'generating' | 'completed' | 'script_only' | 'error'
  style: string
  speakers: number
  duration_minutes: number
  audio_path?: string
  audio_url?: string  // URL to access the audio file
  transcript?: Array<{ speaker: string; dialogue: string }>
  outline?: string
  error_message?: string
  duration_seconds?: number
  speaker_profiles?: Array<{ name: string; role?: string; personality?: string; voice_id?: string }>
  script?: any
  created_at: string
  completed_at?: string
}

interface SpeakerProfileDraft {
  name: string
  role?: string
  personality?: string
  rvc_voice_id?: string  // RVC character voice slug
}

interface PodcastViewProps {
  notebookId: string
  notebookTitle: string
  sources: NotebookSource[]
  notes?: NotebookNote[]
}

// Generation step type for progress tracking
type GenerationStep = 'outline' | 'script' | 'audio' | null

// Step display config
const STEP_CONFIG: Record<string, { label: string; description: string; order: number }> = {
  outline: { label: 'Outline', description: 'Generating podcast outline...', order: 1 },
  script: { label: 'Script', description: 'Writing podcast script...', order: 2 },
  audio: { label: 'Audio', description: 'Creating podcast audio...', order: 3 },
}

const DEFAULT_SPEAKER_NAMES = ['Host', 'Guest', 'Speaker 3', 'Speaker 4']
const DEFAULT_SPEAKER_ROLES = ['Host', 'Guest', 'Speaker', 'Speaker']

export default function PodcastView({ notebookId, notebookTitle, sources, notes = [] }: PodcastViewProps) {
  const [title, setTitle] = useState(`${notebookTitle} Podcast`)
  const [style, setStyle] = useState('conversational')
  const [speakers, setSpeakers] = useState(2)
  const [duration, setDuration] = useState(10)
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set())
  const [selectedNotes, setSelectedNotes] = useState<Set<string>>(new Set())
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationStep, setGenerationStep] = useState<GenerationStep>(null)
  const [generationMessage, setGenerationMessage] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [podcasts, setPodcasts] = useState<Podcast[]>([])
  const [loadingPodcasts, setLoadingPodcasts] = useState(true)
  const [showContentSelector, setShowContentSelector] = useState(true)  // Start expanded
  const [voiceMapping, setVoiceMapping] = useState<Record<string, string>>({})
  const [showVoiceSelection, setShowVoiceSelection] = useState(false)
  const [generateAudioAutomatically, setGenerateAudioAutomatically] = useState(true)

  const [speakerProfilesDraft, setSpeakerProfilesDraft] = useState<SpeakerProfileDraft[]>([
    { name: DEFAULT_SPEAKER_NAMES[0], role: DEFAULT_SPEAKER_ROLES[0], personality: '' },
    { name: DEFAULT_SPEAKER_NAMES[1], role: DEFAULT_SPEAKER_ROLES[1], personality: '' },
  ])

  // Script editing flow
  const [showScriptEditor, setShowScriptEditor] = useState(false)
  const [draftPodcastId, setDraftPodcastId] = useState<string | null>(null)
  const [draftTranscript, setDraftTranscript] = useState<Array<{ speaker: string; dialogue: string }>>([])
  const [draftSpeakerProfiles, setDraftSpeakerProfiles] = useState<Array<{ name: string; role?: string; personality?: string; voice_id?: string }>>([])
  const [isGeneratingAudioFromDraft, setIsGeneratingAudioFromDraft] = useState(false)

  const {
    voices,
    rvcVoices,
    rvcAvailable,
    fetchVoices,
    fetchRvcVoices,
    isLoading: loadingVoices
  } = useVoiceStore()

  const readySources = sources.filter(s => s.status === 'ready')

  useEffect(() => {
    fetchVoices()
    fetchRvcVoices()
  }, [fetchVoices, fetchRvcVoices])

  // Keep speaker profile draft array sized to `speakers`
  useEffect(() => {
    setSpeakerProfilesDraft(prev => {
      const next = [...prev]
      for (let i = 0; i < speakers; i++) {
        if (!next[i]) {
          next[i] = {
            name: DEFAULT_SPEAKER_NAMES[i] || `Speaker ${i + 1}`,
            role: DEFAULT_SPEAKER_ROLES[i] || 'Speaker',
            personality: ''
          }
        }
      }
      return next.slice(0, speakers)
    })
  }, [speakers])

  // Select all ready sources by default
  useEffect(() => {
    if (selectedSources.size === 0 && readySources.length > 0) {
      setSelectedSources(new Set(readySources.map(s => s.id)))
    }
  }, [readySources])

  // Select all notes by default
  useEffect(() => {
    if (selectedNotes.size === 0 && notes.length > 0) {
      setSelectedNotes(new Set(notes.map(n => n.id)))
    }
  }, [notes])

  const fetchPodcasts = async () => {
    setLoadingPodcasts(true)
    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`/api/notebooks/podcasts/by-notebook/${encodeURIComponent(notebookId)}`, {
        headers: {
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setPodcasts(data.podcasts || [])
      }
    } catch (err) {
      console.error('Failed to fetch podcasts:', err)
    } finally {
      setLoadingPodcasts(false)
    }
  }

  // Load saved podcasts on mount
  useEffect(() => {
    if (notebookId) {
      fetchPodcasts()
    }
  }, [notebookId])

  const handleGenerate = async () => {
    if (!title.trim() || totalSelected === 0) return

    setIsGenerating(true)
    setGenerationStep('outline')  // Start with outline step immediately
    setGenerationMessage('Starting podcast generation...')
    setError(null)
    setShowScriptEditor(false)
    setDraftPodcastId(null)
    setDraftTranscript([])
    setDraftSpeakerProfiles([])

    try {
      const token = localStorage.getItem('token')
      const sourcesArray = Array.from(selectedSources)
      const notesArray = Array.from(selectedNotes)

      const customSpeakers = Array.from({ length: speakers }).map((_, index) => {
        const base = speakerProfilesDraft[index] || { name: DEFAULT_SPEAKER_NAMES[index] || `Speaker ${index + 1}` }
        return {
          name: (base.name || DEFAULT_SPEAKER_NAMES[index] || `Speaker ${index + 1}`).trim(),
          role: (base.role || DEFAULT_SPEAKER_ROLES[index] || 'Speaker').trim(),
          personality: (base.personality || '').trim() || undefined,
          voice_id: voiceMapping[String(index + 1)] || undefined,
          rvc_voice_id: base.rvc_voice_id || undefined  // RVC character voice
        }
      })

      const requestBody = {
        notebook_id: notebookId,
        title: title.trim(),
        style,
        speakers,
        duration_minutes: duration,
        source_ids: sourcesArray.length > 0 ? sourcesArray : undefined,
        note_ids: notesArray.length > 0 ? notesArray : undefined,
        generate_audio: generateAudioAutomatically,
        custom_speakers: customSpeakers
      }

      // Use SSE streaming endpoint for progress updates
      const response = await fetch('/api/notebooks/podcasts/generate/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify(requestBody)
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        let errorMessage = 'Failed to generate podcast'
        if (typeof errorData.detail === 'string') {
          errorMessage = errorData.detail
        } else if (Array.isArray(errorData.detail)) {
          errorMessage = errorData.detail.map((e: any) => e.msg || e.message || JSON.stringify(e)).join(', ')
        }
        throw new Error(errorMessage)
      }

      // Process SSE stream
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        throw new Error('Failed to read response stream')
      }

      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Process complete SSE events
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // Keep incomplete line in buffer

        let currentEvent = ''
        let currentData = ''

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            currentData = line.slice(5).trim()
          } else if (line === '' && currentData) {
            // End of event
            try {
              const eventData = JSON.parse(currentData)
              if (currentEvent === 'progress') {
                setGenerationStep(eventData.step as GenerationStep)
                setGenerationMessage(eventData.message || '')
              } else if (currentEvent === 'result') {
                setPodcasts(prev => [eventData, ...prev])
                setTitle(`${notebookTitle} Podcast ${podcasts.length + 2}`)

                // If script-only (audio disabled), show editor to tweak and then generate audio
                if (eventData?.status === 'script_only' && Array.isArray(eventData?.transcript)) {
                  setDraftPodcastId(eventData.id)
                  setDraftTranscript(eventData.transcript)
                  setDraftSpeakerProfiles(eventData.speaker_profiles || requestBody.custom_speakers || [])
                  setShowScriptEditor(true)
                }
              } else if (currentEvent === 'error') {
                throw new Error(eventData.error || 'Generation failed')
              }
            } catch (parseError) {
              console.error('Failed to parse SSE event:', parseError)
            }
            currentEvent = ''
            currentData = ''
          }
        }
      }
    } catch (err: any) {
      setError(err.message || 'Failed to generate podcast')
    } finally {
      setIsGenerating(false)
      setGenerationStep(null)
      setGenerationMessage('')
    }
  }

  const handleGenerateAudioFromEditedScript = async () => {
    if (!draftTranscript.length) return

    setIsGeneratingAudioFromDraft(true)
    setError(null)
    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/notebooks/podcasts/generate/audio', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({
          podcast_id: draftPodcastId,
          notebook_id: notebookId,
          title: title.trim(),
          style,
          speakers,
          duration_minutes: duration,
          transcript: draftTranscript,
          custom_speakers: draftSpeakerProfiles
        })
      })
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Failed to generate audio')
      }
      const saved = await response.json()
      // Replace existing draft row if present, otherwise prepend
      setPodcasts(prev => {
        const idx = prev.findIndex(p => p.id === saved.id)
        if (idx >= 0) {
          const copy = [...prev]
          copy[idx] = saved
          return copy
        }
        return [saved, ...prev]
      })
      setShowScriptEditor(false)
      setDraftPodcastId(null)
      setDraftTranscript([])
      setDraftSpeakerProfiles([])
    } catch (e: any) {
      setError(e.message || 'Failed to generate audio')
    } finally {
      setIsGeneratingAudioFromDraft(false)
    }
  }

  const pollPodcastStatus = async (podcastId: string) => {
    // Standalone endpoint generates synchronously, no polling needed
    // This function is kept for future async generation support
  }

  const handleDeletePodcast = async (podcastId: string) => {
    const confirmed = window.confirm('Are you sure you want to delete this podcast?')
    if (!confirmed) return

    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`/api/notebooks/podcasts/${podcastId}`, {
        method: 'DELETE',
        headers: {
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
      })
      if (response.ok) {
        setPodcasts(prev => prev.filter(p => p.id !== podcastId))
      } else {
        const errorData = await response.json().catch(() => ({}))
        console.error('Failed to delete podcast:', errorData)
      }
    } catch (err) {
      console.error('Failed to delete podcast:', err)
    }
  }

  const toggleSourceSelection = (sourceId: string) => {
    const newSelected = new Set(selectedSources)
    if (newSelected.has(sourceId)) {
      newSelected.delete(sourceId)
    } else {
      newSelected.add(sourceId)
    }
    setSelectedSources(newSelected)
  }

  const toggleNoteSelection = (noteId: string) => {
    const newSelected = new Set(selectedNotes)
    if (newSelected.has(noteId)) {
      newSelected.delete(noteId)
    } else {
      newSelected.add(noteId)
    }
    setSelectedNotes(newSelected)
  }

  const selectAllSources = () => {
    setSelectedSources(new Set(readySources.map(s => s.id)))
  }

  const deselectAllSources = () => {
    setSelectedSources(new Set())
  }

  const selectAllNotes = () => {
    setSelectedNotes(new Set(notes.map(n => n.id)))
  }

  const deselectAllNotes = () => {
    setSelectedNotes(new Set())
  }

  const updateVoiceMapping = (speakerIndex: number, voiceId: string) => {
    setVoiceMapping(prev => ({
      ...prev,
      [String(speakerIndex + 1)]: voiceId
    }))
  }

  const getVoiceForSpeaker = (speakerIndex: number): Voice | undefined => {
    const voiceId = voiceMapping[String(speakerIndex + 1)]
    return voices.find(v => v.voice_id === voiceId)
  }

  const totalSelected = selectedSources.size + selectedNotes.size
  const hasContent = readySources.length > 0 || notes.length > 0
  const availableVoices = voices.filter(v => v.voice_type === 'user' || v.activated)

  return (
    <div className="flex-1 flex overflow-hidden bg-[#0a0a0a]">
      {/* Left Panel - Configuration */}
      <div className="w-96 flex-shrink-0 border-r border-gray-800 flex flex-col overflow-hidden">
        <div className="p-6 border-b border-gray-800">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500 to-pink-500 flex items-center justify-center">
              <Mic className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Generate Podcast</h2>
              <p className="text-sm text-gray-500">Turn your sources into audio</p>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Title */}
          <div>
            <label className="block text-sm text-gray-400 mb-2">Episode Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Enter podcast title..."
              className="w-full px-4 py-3 bg-[#111111] border border-gray-800 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-orange-500"
            />
          </div>

          {/* Style Selection */}
          <div>
            <label className="block text-sm text-gray-400 mb-2">Style</label>
            <div className="grid grid-cols-1 gap-2">
              {PODCAST_STYLES.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setStyle(s.id)}
                  className={`flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${style === s.id
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-gray-800 hover:border-gray-700 bg-[#111111]'
                    }`}
                >
                  <div className={`${style === s.id ? 'text-orange-400' : 'text-gray-400'}`}>
                    {s.icon}
                  </div>
                  <div>
                    <span className={`text-sm font-medium ${style === s.id ? 'text-white' : 'text-gray-300'}`}>
                      {s.name}
                    </span>
                    <p className="text-xs text-gray-500">{s.description}</p>
                  </div>
                  {style === s.id && (
                    <Check className="w-4 h-4 text-orange-400 ml-auto" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Speakers and Duration */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-2 flex items-center gap-1">
                <Users className="w-3.5 h-3.5" /> Speakers
              </label>
              <select
                value={speakers}
                onChange={(e) => setSpeakers(Number(e.target.value))}
                className="w-full px-4 py-3 bg-[#111111] border border-gray-800 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-orange-500"
              >
                <option value={1}>1 (Monologue)</option>
                <option value={2}>2 (Dialogue)</option>
                <option value={3}>3</option>
                <option value={4}>4</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-2 flex items-center gap-1">
                <Clock className="w-3.5 h-3.5" /> Duration
              </label>
              <select
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="w-full px-4 py-3 bg-[#111111] border border-gray-800 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-orange-500"
              >
                <option value={5}>~5 min</option>
                <option value={10}>~10 min</option>
                <option value={15}>~15 min</option>
                <option value={20}>~20 min</option>
                <option value={30}>~30 min</option>
              </select>
            </div>
          </div>

          {/* Audio generation toggle */}
          <div className="flex items-center justify-between p-4 rounded-xl bg-[#111111] border border-gray-800">
            <div className="flex items-start gap-3">
              <Info className="w-4 h-4 text-gray-500 mt-0.5" />
              <div>
                <p className="text-sm text-gray-200 font-medium">Generate audio automatically</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Turn off to generate a script first, edit it, then generate audio.
                </p>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={generateAudioAutomatically}
                onChange={(e) => setGenerateAudioAutomatically(e.target.checked)}
                className="rounded border-gray-600 bg-gray-800 text-orange-500 focus:ring-orange-500"
              />
            </label>
          </div>

          {/* Voice Selection */}
          <div>
            <button
              onClick={() => setShowVoiceSelection(!showVoiceSelection)}
              className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
            >
              <Headphones className="w-4 h-4" />
              Voice Profiles
              <ChevronDown className={`w-4 h-4 transition-transform ${showVoiceSelection ? 'rotate-180' : ''}`} />
              {Object.values(voiceMapping).some(Boolean) && (
                <span className="px-2 py-0.5 text-xs bg-orange-500/20 text-orange-400 rounded-full">
                  {Object.values(voiceMapping).filter(Boolean).length} assigned
                </span>
              )}
            </button>

            {showVoiceSelection && (
              <div className="mt-3 space-y-3">
                {loadingVoices ? (
                  <div className="flex items-center justify-center py-4">
                    <Loader2 className="w-5 h-5 animate-spin text-gray-500" />
                  </div>
                ) : availableVoices.length === 0 ? (
                  <div className="p-4 rounded-xl bg-[#111111] border border-dashed border-gray-800 text-center">
                    <Mic className="w-8 h-8 mx-auto text-gray-600 mb-2" />
                    <p className="text-sm text-gray-500">No voices available</p>
                    <p className="text-xs text-gray-600 mt-1">
                      Clone voices in Voice Studio to use them here
                    </p>
                  </div>
                ) : (
                  <>
                    {Array.from({ length: speakers }).map((_, index) => {
                      const selectedVoice = getVoiceForSpeaker(index)
                      return (
                        <div key={index} className="space-y-2">
                          <div className="flex items-center gap-3">
                            <div className={`flex items-center gap-2 w-28 px-3 py-2 rounded-lg bg-gradient-to-r ${SPEAKER_COLORS[index]} bg-opacity-20`}>
                              <UserCircle2 className="w-4 h-4 text-white" />
                              <span className="text-sm text-white font-medium">{SPEAKER_LABELS[index]}</span>
                            </div>
                            {/* Unified Voice Selector: Cloned + RVC in one dropdown */}
                            {/* Disabled Voice Selector - Restricted to Harvis */}
                            <div className="flex-1 px-4 py-2.5 bg-[#111111] border border-gray-800 rounded-xl text-sm text-gray-400 flex items-center justify-between cursor-not-allowed opacity-75">
                              <span>Harvis (Default)</span>
                              <div className="flex items-center gap-2">
                                <span className="text-[10px] uppercase font-bold tracking-wider text-orange-500/80">Only Available</span>
                              </div>
                            </div>

                            {selectedVoice && (
                              <div className="flex items-center gap-1 text-xs text-gray-500">
                                <Volume2 className="w-3 h-3" />
                                {selectedVoice.quality_score ? `${Math.round(selectedVoice.quality_score * 100)}%` : 'Ready'}
                              </div>
                            )}
                          </div>

                          {/* Speaker identity & persona */}
                          <div className="grid grid-cols-2 gap-3 pl-[7.5rem]">
                            <div>
                              <label className="block text-[11px] text-gray-500 mb-1">Speaker name (in script)</label>
                              <input
                                type="text"
                                value={speakerProfilesDraft[index]?.name || ''}
                                onChange={(e) => {
                                  const v = e.target.value
                                  setSpeakerProfilesDraft(prev => {
                                    const next = [...prev]
                                    next[index] = { ...(next[index] || {} as any), name: v }
                                    return next
                                  })
                                }}
                                placeholder={DEFAULT_SPEAKER_NAMES[index] || `Speaker ${index + 1}`}
                                className="w-full px-3 py-2 bg-[#0f0f0f] border border-gray-800 rounded-lg text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500"
                              />
                            </div>
                            <div>
                              <label className="block text-[11px] text-gray-500 mb-1">Persona / instructions</label>
                              <input
                                type="text"
                                value={speakerProfilesDraft[index]?.personality || ''}
                                onChange={(e) => {
                                  const v = e.target.value
                                  setSpeakerProfilesDraft(prev => {
                                    const next = [...prev]
                                    next[index] = { ...(next[index] || {} as any), personality: v }
                                    return next
                                  })
                                }}
                                placeholder="e.g., confident, concise, no intro"
                                className="w-full px-3 py-2 bg-[#0f0f0f] border border-gray-800 rounded-lg text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500"
                              />
                            </div>
                          </div>
                        </div>
                      )
                    })}
                    <div className="mt-4 bg-blue-500/10 border border-blue-500/20 rounded-xl p-3 flex items-start gap-3">
                      <div className="p-1.5 bg-blue-500/20 rounded-lg shrink-0">
                        <Sparkles className="w-4 h-4 text-blue-400" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-blue-400">Voice Update In Progress</p>
                        <p className="text-xs text-blue-300/70 mt-1">
                          We are enhancing our voice engine. During this period, all podcasts are generated using the stable <span className="text-white font-medium">Harvis</span> default voice.
                        </p>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          {/* Content Selection */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm text-gray-400">Content to Include</label>
              <span className="text-xs px-2 py-1 bg-gray-800 rounded-lg text-gray-400">
                {totalSelected} item{totalSelected !== 1 ? 's' : ''} selected
              </span>
            </div>

            {!hasContent ? (
              <div className="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-xl">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm text-yellow-400 font-medium">No content available</p>
                    <p className="text-xs text-yellow-500/80 mt-1">
                      Add sources to your notebook and wait for them to be processed before generating a podcast.
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {/* Sources Section */}
                <div className="bg-[#111111] border border-gray-800 rounded-xl overflow-hidden">
                  <button
                    onClick={() => setShowContentSelector(!showContentSelector)}
                    className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-800/30 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <ChevronRight className={`w-4 h-4 text-gray-400 transition-transform ${showContentSelector ? 'rotate-90' : ''}`} />
                      <FileText className="w-4 h-4 text-blue-400" />
                      <span className="text-sm font-medium text-white">Sources</span>
                      <span className="text-xs px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded">
                        {selectedSources.size}/{readySources.length}
                      </span>
                    </div>
                    {readySources.length > 0 && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          selectedSources.size === readySources.length ? deselectAllSources() : selectAllSources()
                        }}
                        className="text-xs text-gray-500 hover:text-gray-300"
                      >
                        {selectedSources.size === readySources.length ? 'Deselect all' : 'Select all'}
                      </button>
                    )}
                  </button>

                  {showContentSelector && (
                    <div className="border-t border-gray-800 max-h-40 overflow-y-auto">
                      {readySources.length === 0 ? (
                        <p className="text-sm text-gray-500 text-center py-4">No processed sources yet</p>
                      ) : (
                        readySources.map(source => (
                          <label
                            key={source.id}
                            className="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800/30 cursor-pointer border-b border-gray-800/50 last:border-b-0"
                          >
                            <input
                              type="checkbox"
                              checked={selectedSources.has(source.id)}
                              onChange={() => toggleSourceSelection(source.id)}
                              className="rounded border-gray-600 bg-gray-800 text-orange-500 focus:ring-orange-500"
                            />
                            <span className="text-sm text-gray-300 truncate flex-1">
                              {source.title || source.original_filename || 'Untitled'}
                            </span>
                            <span className="text-xs text-gray-600">
                              {source.source_type}
                            </span>
                          </label>
                        ))
                      )}
                    </div>
                  )}
                </div>

                {/* Notes Section */}
                {notes.length > 0 && (
                  <div className="bg-[#111111] border border-gray-800 rounded-xl overflow-hidden">
                    <div className="flex items-center justify-between px-4 py-3">
                      <div className="flex items-center gap-2">
                        <StickyNote className="w-4 h-4 text-amber-400" />
                        <span className="text-sm font-medium text-white">Notes</span>
                        <span className="text-xs px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded">
                          {selectedNotes.size}/{notes.length}
                        </span>
                      </div>
                      <button
                        onClick={() => selectedNotes.size === notes.length ? deselectAllNotes() : selectAllNotes()}
                        className="text-xs text-gray-500 hover:text-gray-300"
                      >
                        {selectedNotes.size === notes.length ? 'Deselect all' : 'Select all'}
                      </button>
                    </div>

                    <div className="border-t border-gray-800 max-h-32 overflow-y-auto">
                      {notes.map(note => (
                        <label
                          key={note.id}
                          className="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800/30 cursor-pointer border-b border-gray-800/50 last:border-b-0"
                        >
                          <input
                            type="checkbox"
                            checked={selectedNotes.has(note.id)}
                            onChange={() => toggleNoteSelection(note.id)}
                            className="rounded border-gray-600 bg-gray-800 text-orange-500 focus:ring-orange-500"
                          />
                          <span className="text-sm text-gray-300 truncate flex-1">
                            {note.title || 'Untitled Note'}
                          </span>
                          <span className="text-xs text-gray-600 capitalize">
                            {note.note_type}
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Info Box */}
          {hasContent && totalSelected > 0 && (
            <div className="p-3 bg-gray-800/30 border border-gray-700 rounded-xl flex items-start gap-2">
              <Info className="w-4 h-4 text-gray-500 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-gray-500">
                Podcast generation typically takes 3-10 minutes depending on content length. You can continue using the app while it generates in the background.
              </p>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
              {typeof error === 'object' ? JSON.stringify(error) : error}
            </div>
          )}
        </div>

        {/* Generation Progress */}
        {isGenerating && generationStep && (
          <div className="px-6 py-4 border-t border-gray-800">
            <div className="space-y-3">
              {/* Step indicators */}
              <div className="flex items-center justify-between gap-2">
                {Object.entries(STEP_CONFIG).map(([step, config]) => {
                  const isActive = generationStep === step
                  const isCompleted = generationStep && STEP_CONFIG[generationStep]?.order > config.order

                  return (
                    <div
                      key={step}
                      className={`flex-1 flex flex-col items-center gap-1.5 p-2 rounded-lg transition-all ${isActive ? 'bg-orange-500/20 border border-orange-500/40' :
                          isCompleted ? 'bg-green-500/10 border border-green-500/30' :
                            'bg-gray-800/50 border border-gray-700/50'
                        }`}
                    >
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center ${isActive ? 'bg-orange-500 text-white' :
                          isCompleted ? 'bg-green-500 text-white' :
                            'bg-gray-700 text-gray-400'
                        }`}>
                        {isCompleted ? (
                          <Check className="w-3.5 h-3.5" />
                        ) : isActive ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <span className="text-xs font-medium">{config.order}</span>
                        )}
                      </div>
                      <span className={`text-xs font-medium ${isActive ? 'text-orange-400' :
                          isCompleted ? 'text-green-400' :
                            'text-gray-500'
                        }`}>
                        {config.label}
                      </span>
                    </div>
                  )
                })}
              </div>

              {/* Current step message */}
              <div className="text-center">
                <p className="text-sm text-gray-400 animate-pulse">
                  {generationMessage || STEP_CONFIG[generationStep]?.description || 'Processing...'}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Generate Button */}
        <div className="p-6 border-t border-gray-800 space-y-3">
          <button
            onClick={handleGenerate}
            disabled={isGenerating || !title.trim() || totalSelected === 0}
            className="w-full py-3.5 bg-gradient-to-r from-orange-500 to-pink-500 text-white rounded-xl hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 font-medium shadow-lg shadow-orange-500/20"
          >
            {isGenerating ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {generationStep ? `${STEP_CONFIG[generationStep]?.label || 'Processing'}...` : 'Starting Generation...'}
              </>
            ) : (
              <>
                <Mic className="w-5 h-5" />
                Generate Podcast
              </>
            )}
          </button>

          {totalSelected === 0 && hasContent && (
            <p className="text-xs text-center text-gray-500">
              Select at least one source or note to generate a podcast
            </p>
          )}
        </div>
      </div>

      {/* Right Panel - Generated Podcasts */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <h3 className="text-lg font-semibold text-white">Your Podcasts</h3>
          <button
            onClick={fetchPodcasts}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {showScriptEditor && (
            <div className="mb-6 p-4 bg-[#111111] border border-orange-500/30 rounded-xl">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h4 className="text-sm font-semibold text-white">Edit script (optional)</h4>
                  <p className="text-xs text-gray-500 mt-1">
                    Tweak a few lines, then generate audio using your selected voice profiles.
                  </p>
                </div>
                <button
                  onClick={() => setShowScriptEditor(false)}
                  className="text-xs text-gray-400 hover:text-white"
                >
                  Hide
                </button>
              </div>

              <div className="mt-4 space-y-3 max-h-80 overflow-y-auto pr-1">
                {draftTranscript.slice(0, 60).map((seg, idx) => (
                  <div key={idx} className="p-3 rounded-lg bg-[#0f0f0f] border border-gray-800">
                    <div className="flex items-center gap-2 mb-2">
                      <label className="text-xs text-gray-500">Speaker</label>
                      <select
                        value={seg.speaker}
                        onChange={(e) => {
                          const v = e.target.value
                          setDraftTranscript(prev => {
                            const next = [...prev]
                            next[idx] = { ...next[idx], speaker: v }
                            return next
                          })
                        }}
                        className="px-2 py-1 bg-[#111111] border border-gray-800 rounded text-xs text-white focus:outline-none focus:ring-2 focus:ring-orange-500"
                      >
                        {draftSpeakerProfiles.map(sp => (
                          <option key={sp.name} value={sp.name}>{sp.name}</option>
                        ))}
                      </select>
                    </div>
                    <textarea
                      value={seg.dialogue}
                      onChange={(e) => {
                        const v = e.target.value
                        setDraftTranscript(prev => {
                          const next = [...prev]
                          next[idx] = { ...next[idx], dialogue: v }
                          return next
                        })
                      }}
                      rows={2}
                      className="w-full px-3 py-2 bg-[#111111] border border-gray-800 rounded-lg text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500"
                    />
                  </div>
                ))}
                {draftTranscript.length > 60 && (
                  <p className="text-xs text-gray-500">
                    Showing first 60 segments. Generate audio to render the full script.
                  </p>
                )}
              </div>

              <div className="mt-4 flex items-center gap-3">
                <button
                  onClick={handleGenerateAudioFromEditedScript}
                  disabled={isGeneratingAudioFromDraft || draftTranscript.length === 0}
                  className="px-4 py-2 bg-gradient-to-r from-orange-500 to-pink-500 text-white rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium flex items-center gap-2"
                >
                  {isGeneratingAudioFromDraft ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mic className="w-4 h-4" />}
                  Generate Audio from Edited Script
                </button>
                <button
                  onClick={() => {
                    setShowScriptEditor(false)
                    setDraftPodcastId(null)
                    setDraftTranscript([])
                    setDraftSpeakerProfiles([])
                  }}
                  className="px-3 py-2 bg-gray-800 text-gray-200 rounded-lg hover:bg-gray-700 text-sm"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {loadingPodcasts ? (
            <div className="flex items-center justify-center h-64">
              <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
            </div>
          ) : podcasts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-center">
              <div className="w-16 h-16 mb-6 rounded-2xl bg-gradient-to-br from-orange-500/20 to-pink-500/20 flex items-center justify-center">
                <Mic className="w-8 h-8 text-gray-500" />
              </div>
              <h4 className="text-lg font-medium text-white mb-2">No podcasts yet</h4>
              <p className="text-gray-500 max-w-sm">
                Generate your first podcast by configuring the settings and clicking Generate.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {podcasts.map((podcast) => (
                <PodcastCard key={podcast.id} podcast={podcast} onDelete={handleDeletePodcast} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// Format a timestamp into a relative time string
function formatRelativeTime(dateString: string): string {
  const now = Date.now()
  const date = new Date(dateString).getTime()
  const diffMs = now - date
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHr = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHr / 24)

  if (diffSec < 60) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return new Date(dateString).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// Podcast Card Component
function PodcastCard({ podcast, onDelete }: { podcast: Podcast; onDelete: (id: string) => void }) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [showTranscript, setShowTranscript] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const blobUrlRef = useRef<string | null>(null)

  // Cleanup blob URL on unmount
  useEffect(() => {
    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current)
      if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    }
  }, [])

  // Fetch audio with auth headers and return a blob URL
  const fetchAuthenticatedAudio = async (url: string): Promise<string> => {
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const response = await fetch(url, { headers, credentials: 'include' })
    if (!response.ok) throw new Error(`Audio fetch failed: ${response.status}`)
    const blob = await response.blob()
    return URL.createObjectURL(blob)
  }

  const togglePlayback = async () => {
    if (!audioRef.current) {
      const audioSource = podcast.audio_url || podcast.audio_path
      if (!audioSource) return

      try {
        const blobUrl = await fetchAuthenticatedAudio(audioSource)
        blobUrlRef.current = blobUrl
        audioRef.current = new Audio(blobUrl)
        audioRef.current.addEventListener('timeupdate', () => {
          setCurrentTime(audioRef.current?.currentTime || 0)
        })
        audioRef.current.addEventListener('loadedmetadata', () => {
          setDuration(audioRef.current?.duration || 0)
        })
        audioRef.current.addEventListener('ended', () => {
          setIsPlaying(false)
        })
      } catch (err) {
        console.error('Failed to load podcast audio:', err)
        return
      }
    }

    if (isPlaying) {
      audioRef.current.pause()
    } else {
      audioRef.current.play()
    }
    setIsPlaying(!isPlaying)
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const getStatusBadge = () => {
    switch (podcast.status) {
      case 'pending':
        return <span className="px-2 py-1 text-xs bg-yellow-500/20 text-yellow-400 rounded-lg">Pending</span>
      case 'generating':
        return (
          <span className="px-2 py-1 text-xs bg-blue-500/20 text-blue-400 rounded-lg flex items-center gap-1">
            <Loader2 className="w-3 h-3 animate-spin" /> Generating
          </span>
        )
      case 'completed':
        return <span className="px-2 py-1 text-xs bg-green-500/20 text-green-400 rounded-lg">Ready</span>
      case 'script_only':
        return <span className="px-2 py-1 text-xs bg-purple-500/20 text-purple-300 rounded-lg">Script only</span>
      case 'error':
        return <span className="px-2 py-1 text-xs bg-red-500/20 text-red-400 rounded-lg">Error</span>
      default:
        return null
    }
  }

  return (
    <div className="p-4 bg-[#111111] border border-gray-800 rounded-xl">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h4 className="font-medium text-white truncate">{podcast.title}</h4>
            {getStatusBadge()}
          </div>
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span className="capitalize">{podcast.style}</span>
            <span>{podcast.speakers} speakers</span>
            <span>~{podcast.duration_minutes} min</span>
            {podcast.created_at && (
              <span title={new Date(podcast.created_at).toLocaleString()}>
                {formatRelativeTime(podcast.created_at)}
              </span>
            )}
          </div>
          {podcast.error_message && (
            <p className="text-xs text-red-400 mt-2">{typeof podcast.error_message === 'object' ? JSON.stringify(podcast.error_message) : podcast.error_message}</p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {podcast.status === 'completed' && (podcast.audio_url || podcast.audio_path) && (
            <>
              <button
                onClick={togglePlayback}
                className="w-10 h-10 flex items-center justify-center bg-orange-500 hover:bg-orange-600 rounded-full transition-colors"
              >
                {isPlaying ? (
                  <Pause className="w-5 h-5 text-white" />
                ) : (
                  <Play className="w-5 h-5 text-white ml-0.5" />
                )}
              </button>
              <button
                onClick={async () => {
                  const audioSource = podcast.audio_url || podcast.audio_path
                  if (!audioSource) return
                  try {
                    const blobUrl = blobUrlRef.current || await fetchAuthenticatedAudio(audioSource)
                    const a = document.createElement('a')
                    a.href = blobUrl
                    a.download = audioSource.split('/').pop() || 'podcast.wav'
                    a.click()
                  } catch (err) {
                    console.error('Failed to download podcast audio:', err)
                  }
                }}
                className="w-10 h-10 flex items-center justify-center bg-gray-800 hover:bg-gray-700 rounded-full transition-colors"
              >
                <Download className="w-4 h-4 text-white" />
              </button>
            </>
          )}
          <button
            onClick={() => onDelete(podcast.id)}
            className="w-10 h-10 flex items-center justify-center bg-gray-800 hover:bg-red-500/20 hover:text-red-400 text-gray-400 rounded-full transition-colors"
            title="Delete podcast"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Audio Progress */}
      {podcast.status === 'completed' && (podcast.audio_url || podcast.audio_path) && isPlaying && (
        <div className="mt-4">
          <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-orange-500 transition-all"
              style={{ width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%` }}
            />
          </div>
          <div className="flex items-center justify-between mt-1 text-xs text-gray-500">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>
      )}

      {/* Transcript Preview */}
      {podcast.transcript && podcast.transcript.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => setShowTranscript(!showTranscript)}
            className="text-xs text-gray-500 hover:text-gray-400 flex items-center gap-1"
          >
            <ChevronDown className={`w-3 h-3 transition-transform ${showTranscript ? 'rotate-180' : ''}`} />
            {showTranscript ? 'Hide' : 'Show'} Transcript ({podcast.transcript.length} segments)
          </button>

          {showTranscript && (
            <div className="mt-3 max-h-48 overflow-y-auto space-y-2 text-sm">
              {podcast.transcript.slice(0, 10).map((entry, i) => (
                <div key={i} className="pl-3 border-l-2 border-gray-700">
                  <span className="text-orange-400 font-medium">{entry.speaker}:</span>{' '}
                  <span className="text-gray-400">{entry.dialogue}</span>
                </div>
              ))}
              {podcast.transcript.length > 10 && (
                <p className="text-xs text-gray-500">
                  ...and {podcast.transcript.length - 10} more segments
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
