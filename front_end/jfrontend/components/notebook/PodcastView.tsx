'use client'

import { useState, useEffect, useRef } from 'react'
import { NotebookSource, NotebookNote } from '@/stores/notebookStore'
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
  Info
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

interface PodcastViewProps {
  notebookId: string
  notebookTitle: string
  sources: NotebookSource[]
  notes?: NotebookNote[]
}

export default function PodcastView({ notebookId, notebookTitle, sources, notes = [] }: PodcastViewProps) {
  const [title, setTitle] = useState(`${notebookTitle} Podcast`)
  const [style, setStyle] = useState('conversational')
  const [speakers, setSpeakers] = useState(2)
  const [duration, setDuration] = useState(10)
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set())
  const [selectedNotes, setSelectedNotes] = useState<Set<string>>(new Set())
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [podcasts, setPodcasts] = useState<Podcast[]>([])
  const [loadingPodcasts, setLoadingPodcasts] = useState(true)
  const [showContentSelector, setShowContentSelector] = useState(true)  // Start expanded

  const readySources = sources.filter(s => s.status === 'ready')

  // Load existing podcasts
  useEffect(() => {
    fetchPodcasts()
  }, [notebookId])

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
    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`/api/notebooks/${notebookId}/podcasts`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
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
    if (!title.trim() || totalSelected === 0) return

    setIsGenerating(true)
    setError(null)

    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`/api/notebooks/${notebookId}/podcasts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({
          title: title.trim(),
          style,
          speakers,
          duration_minutes: duration,
          source_ids: Array.from(selectedSources),
          note_ids: Array.from(selectedNotes)
        })
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Failed to start podcast generation')
      }

      const podcast = await response.json()
      setPodcasts(prev => [podcast, ...prev])
      pollPodcastStatus(podcast.id)
      
      // Reset title for next podcast
      setTitle(`${notebookTitle} Podcast ${podcasts.length + 2}`)
    } catch (err: any) {
      setError(err.message || 'Failed to generate podcast')
    } finally {
      setIsGenerating(false)
    }
  }

  const pollPodcastStatus = async (podcastId: string) => {
    const token = localStorage.getItem('token')
    const interval = setInterval(async () => {
      try {
        const response = await fetch(
          `/api/notebooks/${notebookId}/podcasts/${podcastId}`,
          {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
            credentials: 'include'
          }
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

  const totalSelected = selectedSources.size + selectedNotes.size
  const hasContent = readySources.length > 0 || notes.length > 0

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
                  className={`flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${
                    style === s.id
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
              {error}
            </div>
          )}
        </div>

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
                Starting Generation...
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
                <PodcastCard key={podcast.id} podcast={podcast} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// Podcast Card Component
function PodcastCard({ podcast }: { podcast: Podcast }) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [showTranscript, setShowTranscript] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const togglePlayback = () => {
    if (!audioRef.current) {
      audioRef.current = new Audio(podcast.audio_path)
      audioRef.current.addEventListener('timeupdate', () => {
        setCurrentTime(audioRef.current?.currentTime || 0)
      })
      audioRef.current.addEventListener('loadedmetadata', () => {
        setDuration(audioRef.current?.duration || 0)
      })
      audioRef.current.addEventListener('ended', () => {
        setIsPlaying(false)
      })
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
          </div>
          {podcast.error_message && (
            <p className="text-xs text-red-400 mt-2">{podcast.error_message}</p>
          )}
        </div>

        {podcast.status === 'completed' && podcast.audio_path && (
          <div className="flex items-center gap-2">
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
            <a
              href={podcast.audio_path}
              download
              className="w-10 h-10 flex items-center justify-center bg-gray-800 hover:bg-gray-700 rounded-full transition-colors"
            >
              <Download className="w-4 h-4 text-white" />
            </a>
          </div>
        )}
      </div>

      {/* Audio Progress */}
      {podcast.status === 'completed' && podcast.audio_path && isPlaying && (
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
