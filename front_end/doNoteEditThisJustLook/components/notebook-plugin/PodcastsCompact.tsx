'use client'

import { useEffect, useState } from 'react'
import { Mic, Play, Pause, Loader2, ArrowLeft, Plus, Trash2 } from 'lucide-react'
import OpenNotebookAPI from '@/lib/openNotebookApi'
import { useNotebookPluginStore } from '@/stores/notebookPluginStore'
import { useNotebookStore } from '@/stores/notebookStore'

interface Podcast {
  id: string
  title: string
  status: string
  created: string
  audio_url?: string
}

export default function PodcastsCompact() {
  const { selectedNotebookId, setActiveTab, selectNotebook } = useNotebookPluginStore()
  const { currentNotebook } = useNotebookStore()
  const [podcasts, setPodcasts] = useState<Podcast[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [audioRef, setAudioRef] = useState<HTMLAudioElement | null>(null)

  useEffect(() => {
    if (selectedNotebookId) {
      loadPodcasts()
    }
  }, [selectedNotebookId])

  const loadPodcasts = async () => {
    if (!selectedNotebookId) return
    setIsLoading(true)
    try {
      const resp = await OpenNotebookAPI.podcasts.list(selectedNotebookId)
      setPodcasts(resp.podcasts || [])
    } catch {
      setPodcasts([])
    } finally {
      setIsLoading(false)
    }
  }

  const handleGenerate = async () => {
    if (!selectedNotebookId) return
    setIsGenerating(true)
    try {
      await OpenNotebookAPI.podcasts.generate(selectedNotebookId)
      await loadPodcasts()
    } catch (err) {
      console.error('Podcast generation failed:', err)
    } finally {
      setIsGenerating(false)
    }
  }

  const handlePlay = (podcast: Podcast) => {
    if (playingId === podcast.id) {
      audioRef?.pause()
      setPlayingId(null)
      return
    }
    if (audioRef) {
      audioRef.pause()
    }
    const url = podcast.audio_url || OpenNotebookAPI.podcasts.audioUrl(podcast.id)
    const audio = new Audio(url)
    audio.play()
    audio.onended = () => setPlayingId(null)
    setAudioRef(audio)
    setPlayingId(podcast.id)
  }

  const handleDelete = async (e: React.MouseEvent, podcastId: string) => {
    e.stopPropagation()
    if (!confirm('Delete this podcast?')) return
    try {
      await OpenNotebookAPI.podcasts.delete(podcastId)
      await loadPodcasts()
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  if (!selectedNotebookId) {
    return (
      <div className="p-6 text-center">
        <Mic className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">Select a notebook first</p>
        <button
          onClick={() => setActiveTab('notebooks')}
          className="mt-2 text-xs text-primary hover:underline"
        >
          Go to Notebooks
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-3 border-b border-border">
        <div className="flex items-center gap-2 mb-2">
          <button
            onClick={() => { selectNotebook(null); setActiveTab('notebooks') }}
            className="p-1 rounded text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-medium text-foreground truncate flex-1">
            {currentNotebook?.title || 'Podcasts'}
          </span>
        </div>
        <button
          onClick={handleGenerate}
          disabled={isGenerating}
          className="flex items-center justify-center gap-2 w-full px-3 py-2 text-sm font-medium
                     bg-primary text-primary-foreground rounded-md hover:bg-primary/90
                     disabled:opacity-50 transition-colors"
        >
          {isGenerating ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Generating...</>
          ) : (
            <><Plus className="w-4 h-4" /> Generate Podcast</>
          )}
        </button>
      </div>

      {/* Podcast List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 text-center text-sm text-muted-foreground">Loading...</div>
        ) : podcasts.length === 0 ? (
          <div className="p-6 text-center">
            <Mic className="w-8 h-8 mx-auto mb-2 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">No podcasts yet</p>
            <p className="text-xs text-muted-foreground/70 mt-1">Generate one from your notebook sources</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {podcasts.map((podcast) => (
              <div
                key={podcast.id}
                className="flex items-center gap-3 px-4 py-3 hover:bg-secondary/50 transition-colors group"
              >
                <button
                  onClick={() => handlePlay(podcast)}
                  disabled={podcast.status !== 'completed'}
                  className="p-2 rounded-full bg-primary/10 text-primary hover:bg-primary/20
                             disabled:opacity-30 shrink-0"
                >
                  {playingId === podcast.id ? (
                    <Pause className="w-4 h-4" />
                  ) : (
                    <Play className="w-4 h-4" />
                  )}
                </button>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">
                    {podcast.title || 'Untitled Podcast'}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {podcast.status === 'completed' ? 'Ready' : podcast.status}
                  </p>
                </div>
                <button
                  onClick={(e) => handleDelete(e, podcast.id)}
                  className="p-1 rounded text-muted-foreground/50 hover:text-destructive
                             opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
