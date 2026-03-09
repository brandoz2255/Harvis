"use client"

import { useState, useEffect, useRef } from "react"
import {
  Play, Pause, Loader2, Plus, Trash2,
  Headphones, Download, AlertCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"

interface Podcast {
  id: string
  title: string
  topic?: string
  status: "completed" | "processing" | "failed" | "pending"
  created_at: string
  audio_url?: string
  duration?: number
  speakers?: string[]
}

export default function PodcastContent() {
  const [podcasts, setPodcasts] = useState<Podcast[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isGenerating, setIsGenerating] = useState(false)
  const [topic, setTopic] = useState("")
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    loadPodcasts()
  }, [])

  const loadPodcasts = async () => {
    setIsLoading(true)
    try {
      const res = await fetch("/api/podcasts")
      if (!res.ok) throw new Error("Failed to load podcasts")
      const data = await res.json()
      setPodcasts(data.podcasts || data || [])
    } catch {
      setPodcasts([])
    } finally {
      setIsLoading(false)
    }
  }

  const generatePodcast = async () => {
    if (!topic.trim()) return
    setIsGenerating(true)
    setError(null)
    try {
      const res = await fetch("/api/podcast/generate-segment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: topic.trim() }),
      })
      if (!res.ok) throw new Error("Generation failed")
      setTopic("")
      await loadPodcasts()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Generation failed"
      setError(msg)
    } finally {
      setIsGenerating(false)
    }
  }

  const togglePlayback = (podcast: Podcast) => {
    if (!podcast.audio_url) return

    if (playingId === podcast.id) {
      audioRef.current?.pause()
      setPlayingId(null)
      return
    }

    if (audioRef.current) {
      audioRef.current.pause()
    }
    const audio = new Audio(podcast.audio_url)
    audio.onended = () => setPlayingId(null)
    audio.play()
    audioRef.current = audio
    setPlayingId(podcast.id)
  }

  const deletePodcast = async (id: string) => {
    try {
      await fetch(`/api/podcasts/${id}`, { method: "DELETE" })
      setPodcasts((prev) => prev.filter((p) => p.id !== id))
      if (playingId === id) {
        audioRef.current?.pause()
        setPlayingId(null)
      }
    } catch {
      // silently fail
    }
  }

  const STATUS_BADGE: Record<string, string> = {
    completed:  "bg-green-500/20 text-green-400 border-green-500/30",
    processing: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    failed:     "bg-red-500/20 text-red-400 border-red-500/30",
    pending:    "bg-muted text-muted-foreground border-border",
  }

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      <div className="flex gap-2">
        <Input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Podcast topic..."
          className="flex-1 text-sm"
          onKeyDown={(e) => e.key === "Enter" && generatePodcast()}
          disabled={isGenerating}
        />
        <Button
          size="sm"
          onClick={generatePodcast}
          disabled={isGenerating || !topic.trim()}
          className="shrink-0"
        >
          {isGenerating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          {error}
        </div>
      )}

      <div className="flex-1 space-y-2 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        ) : podcasts.length === 0 ? (
          <div className="text-center py-12">
            <Headphones className="w-8 h-8 mx-auto mb-3 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">No podcasts yet</p>
            <p className="text-xs text-muted-foreground/60 mt-1">Enter a topic to generate one</p>
          </div>
        ) : (
          podcasts.map((podcast) => (
            <div
              key={podcast.id}
              className="group rounded-lg border border-border bg-background/50 p-3 hover:border-primary/30 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground truncate">
                    {podcast.title || podcast.topic || "Untitled"}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <Badge
                      variant="outline"
                      className={`text-[10px] px-1.5 py-0 ${STATUS_BADGE[podcast.status] || ""}`}
                    >
                      {podcast.status}
                    </Badge>
                    {podcast.duration != null && (
                      <span className="text-[10px] text-muted-foreground">
                        {Math.floor(podcast.duration / 60)}:{String(Math.floor(podcast.duration % 60)).padStart(2, "0")}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  {podcast.audio_url && podcast.status === "completed" && (
                    <>
                      <button
                        onClick={() => togglePlayback(podcast)}
                        className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                        title={playingId === podcast.id ? "Pause" : "Play"}
                      >
                        {playingId === podcast.id
                          ? <Pause className="w-3.5 h-3.5" />
                          : <Play className="w-3.5 h-3.5" />
                        }
                      </button>
                      <a
                        href={podcast.audio_url}
                        download
                        className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                        title="Download"
                      >
                        <Download className="w-3.5 h-3.5" />
                      </a>
                    </>
                  )}
                  <button
                    onClick={() => deletePodcast(podcast.id)}
                    className="p-1.5 rounded-md text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
