"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"
import {
  Send,
  Loader2,
  Square,
  Paperclip,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

interface OpenClawChatInputProps {
  onSend: (text: string) => void
  onAbort: () => void
  isLoading: boolean
  isAborting: boolean
  value: string
  onChange: (value: string) => void
  className?: string
}

export function OpenClawChatInput({
  onSend,
  onAbort,
  isLoading,
  isAborting,
  value,
  onChange,
  className,
}: OpenClawChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return

    textarea.style.height = "auto"
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px"
  }, [value])

  const handleSubmit = () => {
    const trimmed = value.trim()
    if (!trimmed || isLoading) return
    onSend(trimmed)
    onChange("")
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className={cn("border-t bg-card p-3", className)}>
      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          <Textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message..."
            rows={1}
            disabled={isLoading || isAborting}
            className={cn(
              "resize-none border-muted/50 focus-visible:ring-muted-foreground/20 pr-10",
              "min-h-[40px] max-h-[200px]"
            )}
          />
        </div>
        {isLoading && !isAborting ? (
          <Button
            size="icon"
            variant="secondary"
            onClick={onAbort}
            className="h-10 w-10 shrink-0"
          >
            <Square className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            size="icon"
            onClick={handleSubmit}
            disabled={!value.trim() || isLoading}
            className="h-10 w-10 shrink-0"
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        )}
      </div>
    </div>
  )
}
