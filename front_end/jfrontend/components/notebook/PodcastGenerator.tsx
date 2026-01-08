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
  RefreshCw
} from 'lucide-react'

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

  // Load existing podcasts
  useEffect(() => {
    fetchPodcasts()
  }, [notebookId])

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      audioElement?.pause()
    }
  }, [audioElement])

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
          duration_minutes: duration
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-xl border border-gray-700 max-w-3xl w-full max-h-[85vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Mic className="w-5 h-5 text-orange-400" />
            <h2 className="text-lg font-semibold">Generate Podcast</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* New Podcast Form */}
          <div className="bg-gray-800/50 rounded-lg p-4 space-y-4">
            <h3 className="font-medium flex items-center gap-2">
              <Mic className="w-4 h-4 text-orange-400" />
              Create New Podcast
            </h3>

            {/* Title */}
            <div>
              <label className="block text-sm text-gray-400 mb-1">Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Episode title..."
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
              />
            </div>

            {/* Style Selection */}
            <div>
              <label className="block text-sm text-gray-400 mb-2">Style</label>
              <div className="grid grid-cols-5 gap-2">
                {PODCAST_STYLES.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setStyle(s.id)}
                    className={`p-2 rounded-lg border text-center transition-all ${
                      style === s.id
                        ? 'border-orange-500 bg-orange-500/10'
                        : 'border-gray-700 hover:border-gray-600 bg-gray-800/50'
                    }`}
                  >
                    <div className={`mx-auto mb-1 ${style === s.id ? 'text-orange-400' : 'text-gray-400'}`}>
                      {s.icon}
                    </div>
                    <span className="text-xs">{s.name}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Speakers and Duration */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1 flex items-center gap-1">
                  <Users className="w-3 h-3" /> Speakers
                </label>
                <select
                  value={speakers}
                  onChange={(e) => setSpeakers(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                >
                  <option value={1}>1 (Monologue)</option>
                  <option value={2}>2 (Dialogue)</option>
                  <option value={3}>3</option>
                  <option value={4}>4</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1 flex items-center gap-1">
                  <Clock className="w-3 h-3" /> Duration (minutes)
                </label>
                <select
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                >
                  <option value={5}>~5 minutes</option>
                  <option value={10}>~10 minutes</option>
                  <option value={15}>~15 minutes</option>
                  <option value={20}>~20 minutes</option>
                  <option value={30}>~30 minutes</option>
                </select>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
                {error}
              </div>
            )}

            {/* Generate Button */}
            <button
              onClick={handleGenerate}
              disabled={isGenerating || !title.trim()}
              className="w-full py-2 bg-orange-600 hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Starting Generation...
                </>
              ) : (
                <>
                  <Mic className="w-4 h-4" />
                  Generate Podcast
                </>
              )}
            </button>
          </div>

          {/* Existing Podcasts */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-medium">Your Podcasts</h3>
              <button
                onClick={fetchPodcasts}
                className="p-1 hover:bg-gray-800 rounded transition-colors"
              >
                <RefreshCw className="w-4 h-4 text-gray-400" />
              </button>
            </div>

            {loadingPodcasts ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
              </div>
            ) : podcasts.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <Mic className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p>No podcasts yet</p>
                <p className="text-sm">Generate your first podcast above!</p>
              </div>
            ) : (
              <div className="space-y-2">
                {podcasts.map((podcast) => (
                  <div
                    key={podcast.id}
                    className="p-3 bg-gray-800/50 border border-gray-700 rounded-lg"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <h4 className="font-medium truncate">{podcast.title}</h4>
                          {getStatusBadge(podcast.status)}
                        </div>
                        <div className="flex items-center gap-3 text-xs text-gray-500">
                          <span className="capitalize">{podcast.style}</span>
                          <span>{podcast.speakers} speakers</span>
                          <span>~{podcast.duration_minutes} min</span>
                        </div>
                        {podcast.error_message && (
                          <p className="text-xs text-red-400 mt-1">{podcast.error_message}</p>
                        )}
                      </div>
                      
                      {podcast.status === 'completed' && podcast.audio_path && (
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => togglePlayback(podcast)}
                            className="p-2 bg-orange-600 hover:bg-orange-700 rounded-full transition-colors"
                          >
                            {playingId === podcast.id ? (
                              <Pause className="w-4 h-4" />
                            ) : (
                              <Play className="w-4 h-4" />
                            )}
                          </button>
                          <a
                            href={podcast.audio_path}
                            download
                            className="p-2 bg-gray-700 hover:bg-gray-600 rounded-full transition-colors"
                          >
                            <Download className="w-4 h-4" />
                          </a>
                        </div>
                      )}
                    </div>

                    {/* Transcript Preview */}
                    {podcast.transcript && podcast.transcript.length > 0 && (
                      <details className="mt-3">
                        <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-400">
                          View Transcript ({podcast.transcript.length} segments)
                        </summary>
                        <div className="mt-2 max-h-48 overflow-y-auto space-y-2 text-sm">
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
                      </details>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

