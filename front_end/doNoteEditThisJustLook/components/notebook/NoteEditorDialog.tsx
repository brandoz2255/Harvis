"use client"

import { useEffect, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

interface NoteEditorDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  initialTitle?: string
  initialContent?: string
  onSave: (title: string, content: string) => void
}

export default function NoteEditorDialog({
  open,
  onOpenChange,
  initialTitle = "",
  initialContent = "",
  onSave,
}: NoteEditorDialogProps) {
  const [title, setTitle] = useState(initialTitle)
  const [content, setContent] = useState(initialContent)

  useEffect(() => {
    if (open) {
      setTitle(initialTitle)
      setContent(initialContent)
    }
  }, [open, initialTitle, initialContent])

  const handleSave = () => {
    if (!content.trim()) return
    onSave(title.trim(), content.trim())
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-gray-900 border-gray-800 text-white">
        <DialogHeader>
          <DialogTitle>{initialContent ? "Edit Note" : "Write Note"}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Title</label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="My analysis"
              className="bg-gray-800 border-gray-700 text-white placeholder-gray-500"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Content</label>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Write your note..."
              className="min-h-[140px] bg-gray-800 border-gray-700 text-white placeholder-gray-500"
            />
          </div>
        </div>

        <DialogFooter className="pt-4">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            className="text-gray-300"
          >
            Cancel
          </Button>
          <Button onClick={handleSave} className="bg-blue-600 hover:bg-blue-700">
            Save Note
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}








