'use client'

import { useState, useEffect } from 'react'
import {
  Mic,
  Play,
  Pause,
  Loader2,
  X,
  Users,
  Clock,
  MessageSquare,
  BookOpen,
  Sword,
  GraduationCap,
  Coffee,
  Download,
  RefreshCw,
  Volume2,
  ChevronDown,
  Headphones,
  Sparkles,
  UserCircle2
} from 'lucide-react'
import { useVoiceStore, Voice } from '@/stores/voiceStore'

interface PodcastStyle {
  id: string
  name: string
  description: string
  icon: React.ReactNode
}

const PODCAST_STYLES: PodcastStyle[] = [
  {
    id: 'conversational',
    name: 'Conversational',
    description: 'Casual, friendly discussion',
    icon: <Coffee className="w-4 h-4" />
  },
  {
    id: 'interview',
    name: 'Interview',
    description: 'Q&A format with host',
    icon: <MessageSquare className="w-4 h-4" />
  },
  {
    id: 'educational',
    name: 'Educational',
    description: 'Structured teaching format',
    icon: <GraduationCap className="w-4 h-4" />
  },
  {
    id: 'debate',
    name: 'Debate',
    description: 'Multiple perspectives',
    icon: <Sword className="w-4 h-4" />
  },
  {
    id: 'storytelling',
    name: 'Storytelling',
    description: 'Narrative format',
    icon: <BookOpen className="w-4 h-4" />
  }
]

// Speaker labels for podcast
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
  status: 'pending' | 'generating' | 'completed' | 'error'
  style: string
  speakers: number
  duration_minutes: number
  audio_path?: string
  transcript?: Array<{ speaker: string; dialogue: string }>
  outline?: string
  error_message?: string
  duration_seconds?: number
  created_at: string
  completed_at?: string
  voice_mapping?: Record<string, string>
}

interface PodcastGeneratorProps {
  notebookId: string
  notebookTitle: string
  onClose: () => void
}

export default function PodcastGenerator({
  notebookId,
  notebookTitle,
  onClose
}: PodcastGeneratorProps) {
  const [title, setTitle] = useState(`${notebookTitle} Podcast`)
  const [style, setStyle] = useState('conversational')
  const [speakers, setSpeakers] = useState(2)
  const [duration, setDuration] = useState(10)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [podcasts, setPodcasts] = useState<Podcast[]>([])
  const [loadingPodcasts, setLoadingPodcasts] = useState(true)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [audioElement, setAudioElement] = useState<HTMLAudioElement | null>(null)

  // Voice selection state
  const [voiceMapping, setVoiceMapping] = useState<Record<string, string>>({})
  const [showVoiceSelection, setShowVoiceSelection] = useState(false)

  // Voice store
  const { voices, fetchVoices, isLoading: loadingVoices } = useVoiceStore()

  // Load existing podcasts and voices
  useEffect(() => {
    fetchPodcasts()
    fetchVoices()
  }, [notebookId, fetchVoices])

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      audioElement?.pause()
    }
  }, [audioElement])

  // Get only activated/available voices
  const availableVoices = voices.filter(v => v.voice_type === 'user' || v.activated)

  const fetchPodcasts = async () => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}/podcasts`, {
        credentials: 'include'
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

  const handleGenerate = async () => {
    if (!title.trim()) return

    setIsGenerating(true)
    setError(null)

    try {
      const response = await fetch(`/api/notebooks/${notebookId}/podcasts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: title.trim(),
          style,
          speakers,
          duration_minutes: duration,
          voice_mapping: voiceMapping
        })
      })

      if (!response.ok) {
        throw new Error('Failed to start podcast generation')
      }

      const podcast = await response.json()
      setPodcasts(prev => [podcast, ...prev])

      // Start polling for status
      pollPodcastStatus(podcast.id)
    } catch (err: any) {
      setError(err.message || 'Failed to generate podcast')
    } finally {
      setIsGenerating(false)
    }
  }

  const pollPodcastStatus = async (podcastId: string) => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(
          `/api/notebooks/${notebookId}/podcasts/${podcastId}`,
          { credentials: 'include' }
        )
        if (response.ok) {
          const podcast = await response.json()
          setPodcasts(prev => prev.map(p => p.id === podcastId ? podcast : p))

          if (podcast.status === 'completed' || podcast.status === 'error') {
            clearInterval(interval)
          }
        }
      } catch (err) {
        console.error('Failed to poll podcast status:', err)
      }
    }, 5000)

    // Stop polling after 10 minutes
    setTimeout(() => clearInterval(interval), 600000)
  }

  const togglePlayback = (podcast: Podcast) => {
    if (playingId === podcast.id) {
      audioElement?.pause()
      setPlayingId(null)
    } else {
      audioElement?.pause()
      const audio = new Audio(podcast.audio_path)
      audio.play()
      audio.onended = () => setPlayingId(null)
      setAudioElement(audio)
      setPlayingId(podcast.id)
    }
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

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'pending':
        return <span className="px-2 py-1 text-xs bg-yellow-500/20 text-yellow-400 rounded">Pending</span>
      case 'generating':
        return (
          <span className="px-2 py-1 text-xs bg-blue-500/20 text-blue-400 rounded flex items-center gap-1">
            <Loader2 className="w-3 h-3 animate-spin" /> Generating
          </span>
        )
      case 'completed':
        return <span className="px-2 py-1 text-xs bg-green-500/20 text-green-400 rounded">Ready</span>
      case 'error':
        return <span className="px-2 py-1 text-xs bg-red-500/20 text-red-400 rounded">Error</span>
      default:
        return null
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-2xl border border-white/10 max-w-3xl w-full max-h-[85vh] overflow-hidden flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-5 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-orange-500 to-rose-500">
              <Mic className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Generate Podcast</h2>
              <p className="text-sm text-white/50">Create audio from your notebook</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-white/60" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* New Podcast Form */}
          <div className="bg-white/5 rounded-xl p-5 space-y-5 border border-white/5">
            <h3 className="font-medium text-white flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-orange-400" />
              Create New Podcast
            </h3>

            {/* Title */}
            <div>
              <label className="block text-sm text-white/60 mb-1.5">Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Episode title..."
                className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent transition-all"
              />
            </div>

            {/* Style Selection */}
            <div>
              <label className="block text-sm text-white/60 mb-2">Style</label>
              <div className="grid grid-cols-5 gap-2">
                {PODCAST_STYLES.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setStyle(s.id)}
                    className={`p-3 rounded-xl border text-center transition-all ${style === s.id
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-white/10 hover:border-white/20 bg-white/5'
                      }`}
                  >
                    <div className={`mx-auto mb-1.5 ${style === s.id ? 'text-orange-400' : 'text-white/40'}`}>
                      {s.icon}
                    </div>
                    <span className="text-xs text-white/80">{s.name}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Speakers and Duration */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-white/60 mb-1.5 flex items-center gap-1.5">
                  <Users className="w-3.5 h-3.5" /> Number of Speakers
                </label>
                <select
                  value={speakers}
                  onChange={(e) => setSpeakers(Number(e.target.value))}
                  className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent transition-all"
                >
                  <option value={1}>1 (Monologue)</option>
                  <option value={2}>2 (Dialogue)</option>
                  <option value={3}>3 Speakers</option>
                  <option value={4}>4 Speakers</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-white/60 mb-1.5 flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" /> Duration
                </label>
                <select
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                  className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent transition-all"
                >
                  <option value={5}>~5 minutes</option>
                  <option value={10}>~10 minutes</option>
                  <option value={15}>~15 minutes</option>
                  <option value={20}>~20 minutes</option>
                  <option value={30}>~30 minutes</option>
                </select>
              </div>
            </div>

            {/* Coming Soon Notice */}
            <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-3 flex items-start gap-3">
              <div className="p-1.5 bg-blue-500/20 rounded-lg shrink-0">
                <Sparkles className="w-4 h-4 text-blue-400" />
              </div>
              <div>
                <p className="text-sm font-medium text-blue-400">Voice Studio Under Construction</p>
                <p className="text-xs text-blue-300/70 mt-1">
                  We're currently upgrading our voice engine. For now, all podcasts use the default
                  <span className="text-white font-medium"> Harvis</span> voice for maximum stability.
                  Custom voices will return soon!
                </p>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
                {error}
              </div>
            )}

            {/* Generate Button */}
            <button
              onClick={handleGenerate}
              disabled={isGenerating || !title.trim()}
              className="w-full py-3 bg-gradient-to-r from-orange-600 to-rose-600 hover:from-orange-500 hover:to-rose-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl transition-all flex items-center justify-center gap-2 font-medium shadow-lg shadow-orange-500/20"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Starting Generation...
                </>
              ) : (
                <>
                  <Mic className="w-5 h-5" />
                  Generate Podcast
                </>
              )}
            </button>
          </div>

          {/* Existing Podcasts */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-medium text-white">Your Podcasts</h3>
              <button
                onClick={fetchPodcasts}
                className="p-1.5 hover:bg-white/10 rounded-lg transition-colors"
              >
                <RefreshCw className="w-4 h-4 text-white/40" />
              </button>
            </div>

            {loadingPodcasts ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-white/40" />
              </div>
            ) : podcasts.length === 0 ? (
              <div className="text-center py-12 bg-white/5 rounded-xl border border-dashed border-white/10">
                <Mic className="w-10 h-10 mx-auto mb-3 text-white/20" />
                <p className="text-white/60">No podcasts yet</p>
                <p className="text-sm text-white/40 mt-1">Generate your first podcast above!</p>
              </div>
            ) : (
              <div className="space-y-2">
                {podcasts.map((podcast) => (
                  <div
                    key={podcast.id}
                    className="p-4 bg-white/5 border border-white/10 rounded-xl hover:bg-white/[0.07] transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <h4 className="font-medium text-white truncate">{podcast.title}</h4>
                          {getStatusBadge(podcast.status)}
                        </div>
                        <div className="flex items-center gap-3 text-xs text-white/40">
                          <span className="capitalize">{podcast.style}</span>
                          <span>{podcast.speakers} speakers</span>
                          <span>~{podcast.duration_minutes} min</span>
                          {podcast.voice_mapping && Object.keys(podcast.voice_mapping).length > 0 && (
                            <span className="text-violet-400">Custom voices</span>
                          )}
                        </div>
                        {podcast.error_message && (
                          <p className="text-xs text-red-400 mt-1">{podcast.error_message}</p>
                        )}
                      </div>

                      {podcast.status === 'completed' && podcast.audio_path && (
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => togglePlayback(podcast)}
                            className="p-2.5 bg-gradient-to-r from-orange-600 to-rose-600 hover:from-orange-500 hover:to-rose-500 rounded-full transition-all shadow-lg"
                          >
                            {playingId === podcast.id ? (
                              <Pause className="w-4 h-4 text-white" />
                            ) : (
                              <Play className="w-4 h-4 text-white" />
                            )}
                          </button>
                          <a
                            href={podcast.audio_path}
                            download
                            className="p-2.5 bg-white/10 hover:bg-white/20 rounded-full transition-colors"
                          >
                            <Download className="w-4 h-4 text-white/70" />
                          </a>
                        </div>
                      )}
                    </div>

                    {/* Transcript Preview */}
                    {podcast.transcript && podcast.transcript.length > 0 && (
                      <details className="mt-3">
                        <summary className="text-xs text-white/40 cursor-pointer hover:text-white/60 transition-colors">
                          View Transcript ({podcast.transcript.length} segments)
                        </summary>
                        <div className="mt-3 max-h-48 overflow-y-auto space-y-2 text-sm">
                          {podcast.transcript.slice(0, 10).map((entry, i) => (
                            <div key={i} className="pl-3 border-l-2 border-white/10">
                              <span className="text-orange-400 font-medium">{entry.speaker}:</span>{' '}
                              <span className="text-white/60">{entry.dialogue}</span>
                            </div>
                          ))}
                          {podcast.transcript.length > 10 && (
                            <p className="text-xs text-white/40">
                              ...and {podcast.transcript.length - 10} more segments
                            </p>
                          )}
                        </div>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div >
      </div >
    </div >
  )
}
