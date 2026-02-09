"use client"

import { NotebookNote } from "@/stores/notebookStore"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Bot, User, Plus, MoreVertical, Trash2 } from "lucide-react"
import { ContextMode } from "./types"

interface NotesColumnProps {
  notes: NotebookNote[]
  isLoading: boolean
  contextSelections: Record<string, ContextMode>
  onContextModeChange: (noteId: string, mode: ContextMode) => void
  onWriteNote: () => void
  onEditNote: (note: NotebookNote) => void
  onDeleteNote: (noteId: string) => void
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

const formatDate = (date: string) =>
  new Date(date).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  })

export default function NotesColumn({
  notes,
  isLoading,
  contextSelections,
  onContextModeChange,
  onWriteNote,
  onEditNote,
  onDeleteNote,
}: NotesColumnProps) {
  return (
    <div className="flex flex-col min-h-0 border border-gray-800 rounded-lg overflow-hidden bg-[#0a0a0a]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="text-sm font-semibold text-white">
          Notes ({notes.length})
        </div>
        <Button
          size="sm"
          onClick={onWriteNote}
          className="bg-blue-600 hover:bg-blue-700 text-white"
        >
          <Plus className="h-4 w-4 mr-2" />
          Write Note
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {isLoading ? (
          <div className="text-sm text-gray-400">Loading notes…</div>
        ) : notes.length === 0 ? (
          <div className="text-sm text-gray-500">No notes yet.</div>
        ) : (
          notes.map((note) => {
            const isAI = note.type !== "user_note"
            const mode = contextSelections[note.id] ?? "full"
            const indicator = contextIndicator(mode)

            return (
              <div
                key={note.id}
                className="border border-gray-800 rounded-lg p-3 bg-gray-900/40 hover:bg-gray-900 transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    {isAI ? (
                      <Bot className="h-4 w-4 text-blue-400" />
                    ) : (
                      <User className="h-4 w-4 text-gray-400" />
                    )}
                    <div>
                      <div className="text-sm text-white">
                        {note.title || "Untitled Note"}
                      </div>
                      <div className="text-xs text-gray-500">
                        {isAI ? "AI note" : "Manual note"} •{" "}
                        {formatDate(note.updated_at)}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      className="text-xs text-gray-400 hover:text-white"
                      onClick={() =>
                        onContextModeChange(note.id, cycleContext(mode))
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
                          onClick={() => onEditNote(note)}
                          className="text-gray-300 hover:bg-gray-800"
                        >
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => onDeleteNote(note.id)}
                          className="text-red-400 hover:bg-gray-800"
                        >
                          <Trash2 className="h-4 w-4 mr-2" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>

                {note.content && (
                  <p className="text-xs text-gray-400 mt-2 line-clamp-3">
                    {note.content}
                  </p>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}








