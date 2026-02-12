"use client"

import { useEffect, useMemo, useState } from "react"
import { Mic, Plus, Loader2, Play, Download } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { useNotebookStore } from "@/stores/notebookStore"

export default function NotebookPodcastsPage() {
  const { notebooks, fetchNotebooks } = useNotebookStore()
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [styles, setStyles] = useState<Record<string, string>>({})
  const [episodes, setEpisodes] = useState<any[]>([])

  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedNotebookId, setSelectedNotebookId] = useState<string>("")
  const [title, setTitle] = useState("")
  const [style, setStyle] = useState<string>("conversational")
  const [speakers, setSpeakers] = useState(2)
  const [durationMinutes, setDurationMinutes] = useState(10)
  const [isCreating, setIsCreating] = useState(false)

  const load = async () => {
    setIsLoading(true)
    setError(null)
    try {
      await fetchNotebooks()

      const token = localStorage.getItem("token")
      const styleRes = await fetch("/api/notebooks/podcasts/styles", {
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      })
      if (styleRes.ok) {
        const data = await styleRes.json()
        setStyles(data.styles || {})
      }
    } catch (e: any) {
      setError(e?.message || "Failed to load podcasts")
    } finally {
      setIsLoading(false)
    }
  }

  const loadEpisodes = async (notebookIds: string[]) => {
    const token = localStorage.getItem("token")
    const perNotebook = await Promise.all(
      notebookIds.map(async (id) => {
        const res = await fetch(`/api/notebooks/${id}/podcasts?limit=20&offset=0`, {
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        })
        if (!res.ok) return []
        const data = await res.json()
        const pods = data.podcasts || []
        return pods.map((p: any) => ({ ...p, notebook_id: id }))
      })
    )
    setEpisodes(perNotebook.flat())
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (notebooks.length > 0) {
      if (!selectedNotebookId) setSelectedNotebookId(notebooks[0].id)
      loadEpisodes(notebooks.map((n) => n.id))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notebooks])

  const notebookTitleById = useMemo(() => {
    const m = new Map<string, string>()
    notebooks.forEach((n) => m.set(n.id, n.title))
    return m
  }, [notebooks])

  const handleCreate = async () => {
    if (!selectedNotebookId || !title.trim()) return
    setIsCreating(true)
    setError(null)
    try {
      const token = localStorage.getItem("token")
      const res = await fetch(`/api/notebooks/${selectedNotebookId}/podcasts`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          title: title.trim(),
          style,
          speakers,
          duration_minutes: durationMinutes,
        }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `Failed (${res.status})`)
      }
      setDialogOpen(false)
      setTitle("")
      await loadEpisodes(notebooks.map((n) => n.id))
    } catch (e: any) {
      setError(e?.message || "Failed to create podcast")
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="h-full w-full overflow-y-auto p-6 bg-[#0a0a0a]">
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-white">Podcasts</h1>
            <p className="text-sm text-gray-400">
              This page exists to manage and replay podcasts generated from any notebook (global episodes list).
            </p>
          </div>
          <button
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-600 text-white text-sm"
            onClick={() => setDialogOpen(true)}
            disabled={notebooks.length === 0}
          >
            <Plus className="h-4 w-4" />
            Generate Podcast
          </button>
        </div>

        {error && (
          <div className="p-3 bg-red-900/30 border border-red-800 rounded text-sm text-red-200">
            {error}
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader2 className="h-6 w-6 animate-spin mr-2" />
            Loading…
          </div>
        ) : episodes.length === 0 ? (
          <div className="border border-gray-800 rounded-lg p-6 bg-gray-900/40 text-gray-400 text-sm flex flex-col items-center justify-center gap-3">
            <Mic className="h-8 w-8" />
            No podcasts yet. Generate one from a notebook.
          </div>
        ) : (
          <div className="space-y-3">
            {episodes.map((ep) => {
              const nbTitle = notebookTitleById.get(ep.notebook_id) || ep.notebook_id
              const audioUrl = ep.audio_path
                ? `/api/notebooks/${ep.notebook_id}/podcasts/${ep.id}/audio`
                : null
              return (
                <div
                  key={ep.id}
                  className="border border-gray-800 rounded-lg p-4 bg-gray-900/40"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-white">
                        {ep.title || "Untitled Podcast"}
                      </div>
                      <div className="text-xs text-gray-500 mt-1">
                        Notebook: {nbTitle} • {ep.status} • {ep.style} • {ep.speakers} speakers
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {audioUrl && (
                        <>
                          <a
                            href={audioUrl}
                            className="p-2 rounded bg-gray-800 text-gray-200 hover:bg-gray-700"
                            title="Play/Download"
                          >
                            <Play className="h-4 w-4" />
                          </a>
                          <a
                            href={audioUrl}
                            download
                            className="p-2 rounded bg-gray-800 text-gray-200 hover:bg-gray-700"
                            title="Download"
                          >
                            <Download className="h-4 w-4" />
                          </a>
                        </>
                      )}
                    </div>
                  </div>
                  {audioUrl && (
                    <audio className="w-full mt-3" controls src={audioUrl} />
                  )}
                  {ep.error_message && (
                    <div className="mt-2 text-xs text-red-300">
                      {ep.error_message}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-gray-900 border-gray-800 text-white">
          <DialogHeader>
            <DialogTitle>Generate Podcast</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1">
              <label className="text-xs text-gray-400">Notebook</label>
              <select
                value={selectedNotebookId}
                onChange={(e) => setSelectedNotebookId(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              >
                {notebooks.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.title}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-gray-400">Title</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
                placeholder="Episode title"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-gray-400">Style</label>
                <select
                  value={style}
                  onChange={(e) => setStyle(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
                >
                  {Object.keys(styles).length > 0 ? (
                    Object.entries(styles).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="conversational">Conversational</option>
                      <option value="interview">Interview</option>
                      <option value="educational">Educational</option>
                    </>
                  )}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-gray-400">Speakers (1-4)</label>
                <input
                  type="number"
                  min={1}
                  max={4}
                  value={speakers}
                  onChange={(e) => setSpeakers(Number(e.target.value))}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-gray-400">Duration (minutes)</label>
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={durationMinutes}
                  onChange={(e) => setDurationMinutes(Number(e.target.value))}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
                />
              </div>
            </div>
          </div>

          <DialogFooter className="pt-4">
            <Button variant="ghost" onClick={() => setDialogOpen(false)} className="text-gray-300">
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              className="bg-blue-600 hover:bg-blue-700"
              disabled={isCreating || !title.trim() || !selectedNotebookId}
            >
              {isCreating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Creating…
                </>
              ) : (
                "Generate"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

