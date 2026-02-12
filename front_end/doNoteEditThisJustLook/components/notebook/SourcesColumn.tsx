"use client"

import { useMemo } from "react"
import {
  FileText,
  Link as LinkIcon,
  Youtube,
  FileAudio,
  FileImage,
  File,
  Plus,
  MoreVertical,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { NotebookSource } from "@/stores/notebookStore"
import { ContextMode } from "./types"

interface SourcesColumnProps {
  sources: NotebookSource[]
  isLoading: boolean
  contextSelections: Record<string, ContextMode>
  onContextModeChange: (sourceId: string, mode: ContextMode) => void
  onAddSource: () => void
  onDeleteSource: (sourceId: string) => void
  onTransformSource: (source: NotebookSource) => void
  onViewSource?: (source: NotebookSource) => void
}

const sourceTypeIcon = (source: NotebookSource) => {
  switch (source.type) {
    case "url":
      return LinkIcon
    case "youtube":
      return Youtube
    case "audio":
      return FileAudio
    case "image":
      return FileImage
    case "pdf":
      return FileText
    default:
      return File
  }
}

const contextIndicator = (mode: ContextMode) => {
  switch (mode) {
    case "full":
      return { emoji: "🟢", label: "Full Content" }
    case "insights":
      return { emoji: "🟡", label: "Summary Only" }
    case "off":
      return { emoji: "⛔", label: "Not in Context" }
  }
}

const cycleContext = (mode: ContextMode): ContextMode => {
  if (mode === "full") return "insights"
  if (mode === "insights") return "off"
  return "full"
}

export default function SourcesColumn({
  sources,
  isLoading,
  contextSelections,
  onContextModeChange,
  onAddSource,
  onDeleteSource,
  onTransformSource,
  onViewSource,
}: SourcesColumnProps) {
  const countLabel = useMemo(
    () => `Sources (${sources.length})`,
    [sources.length]
  )

  return (
    <div className="flex flex-col min-h-0 border border-gray-800 rounded-lg overflow-hidden bg-[#0a0a0a]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="text-sm font-semibold text-white">{countLabel}</div>
        <Button
          size="sm"
          onClick={onAddSource}
          className="bg-blue-600 hover:bg-blue-700 text-white"
        >
          <Plus className="h-4 w-4 mr-2" />
          Add Source
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {isLoading ? (
          <div className="text-sm text-gray-400">Loading sources…</div>
        ) : sources.length === 0 ? (
          <div className="text-sm text-gray-500">No sources yet.</div>
        ) : (
          sources.map((source) => {
            const Icon = sourceTypeIcon(source)
            const mode = contextSelections[source.id] ?? "full"
            const indicator = contextIndicator(mode)

            return (
              <div
                key={source.id}
                className="border border-gray-800 rounded-lg p-3 bg-gray-900/40 hover:bg-gray-900 transition-colors"
                onClick={() => {
                  if (onViewSource) {
                    onViewSource(source)
                  }
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Icon className="h-4 w-4 text-gray-400 flex-shrink-0" />
                    <div className="min-w-0">
                      <div className="text-sm text-white truncate">
                        {source.title || source.original_filename || "Untitled"}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                        <span>{indicator.emoji} {indicator.label}</span>
                        {source.status === 'processing' || source.status === 'pending' ? (
                          <span className="inline-flex items-center gap-1 rounded bg-blue-500/10 px-1.5 py-0.5 text-blue-400">
                            <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-pulse" />
                            Processing
                          </span>
                        ) : source.status === 'ready' ? (
                          <span className="inline-flex items-center gap-1 rounded bg-green-500/10 px-1.5 py-0.5 text-green-400">
                            <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
                            Ready
                          </span>
                        ) : source.status === 'error' ? (
                          <span className="inline-flex items-center gap-1 rounded bg-red-500/10 px-1.5 py-0.5 text-red-400">
                            <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
                            Failed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-gray-500/10 px-1.5 py-0.5 text-gray-400">
                            <span className="h-1.5 w-1.5 rounded-full bg-gray-400" />
                            {source.status}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      className="text-xs text-gray-400 hover:text-white"
                      onClick={() =>
                        onContextModeChange(source.id, cycleContext(mode))
                      }
                      title="Change context"
                    >
                      {indicator.emoji}
                    </button>

                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded">
                          <MoreVertical className="h-4 w-4" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="bg-gray-900 border-gray-800">
                        <DropdownMenuItem
                          onClick={() => onTransformSource(source)}
                          className="text-gray-300 hover:bg-gray-800"
                        >
                          Transform
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => onDeleteSource(source.id)}
                          className="text-red-400 hover:bg-gray-800"
                        >
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}



