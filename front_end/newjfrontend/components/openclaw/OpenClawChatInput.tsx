"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { cn } from "@/lib/utils"
import {
  Send,
  Loader2,
  Square,
  Paperclip,
  ImageIcon,
  Camera,
  CameraOff,
  X,
  File,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

const SLASH_COMMANDS = [
  { command: "/new",        description: "Start a new session" },
  { command: "/compact",    description: "Compact the session context" },
  { command: "/clear",      description: "Clear session history" },
  { command: "/status",     description: "Show current status" },
  { command: "/agents",     description: "List thread-bound agents" },
  { command: "/approve",    description: "Approve or deny exec requests" },
  { command: "/activation", description: "Set group activation mode" },
  { command: "/think",      description: "Set thinking level (off/low/high/max)" },
  { command: "/verbose",    description: "Toggle verbose mode" },
  { command: "/model",      description: "Switch model" },
  { command: "/help",       description: "Show available commands" },
]

const SUPPORTED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']

interface Attachment {
  id: string
  type: 'image'
  data: string
  mimeType: string
  name: string
  width?: number
  height?: number
}

interface OpenClawChatInputProps {
  onSend: (text: string, attachments?: Attachment[]) => void
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
  const imageInputRef = useRef<HTMLInputElement>(null)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [isScreensharing, setIsScreensharing] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const screenshareIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const screenStreamRef = useRef<MediaStream | null>(null)
  const [showAttachmentMenu, setShowAttachmentMenu] = useState(false)
  const [slashCmdIndex, setSlashCmdIndex] = useState(0)

  // Filtered slash commands based on current input
  const slashMatches = value.startsWith("/") && !value.includes(" ")
    ? SLASH_COMMANDS.filter(c => c.command.startsWith(value.toLowerCase()))
    : []
  const showSlashMenu = slashMatches.length > 0

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return

    textarea.style.height = "auto"
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px"
  }, [value])

  // Cleanup screenshare on unmount
  useEffect(() => {
    return () => {
      if (screenshareIntervalRef.current) {
        clearInterval(screenshareIntervalRef.current)
      }
      if (screenStreamRef.current) {
        screenStreamRef.current.getTracks().forEach(track => track.stop())
      }
    }
  }, [])

  const handleSubmit = () => {
    const trimmed = value.trim()
    if (!trimmed || isLoading) return
    onSend(trimmed, attachments.length > 0 ? attachments : undefined)
    onChange("")
    setAttachments([])
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showSlashMenu) {
      if (e.key === "ArrowDown") {
        e.preventDefault()
        setSlashCmdIndex(i => (i + 1) % slashMatches.length)
        return
      }
      if (e.key === "ArrowUp") {
        e.preventDefault()
        setSlashCmdIndex(i => (i - 1 + slashMatches.length) % slashMatches.length)
        return
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault()
        onChange(slashMatches[slashCmdIndex].command + " ")
        setSlashCmdIndex(0)
        textareaRef.current?.focus()
        return
      }
      if (e.key === "Escape") {
        onChange("")
        return
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // Reset index when matches change
  useEffect(() => { setSlashCmdIndex(0) }, [value])

  // ============== PASTE HANDLING ==============
  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items
    const files = e.clipboardData.files
    const imageItems: DataTransferItem[] = []
    const imageFiles: File[] = []

    if (items) {
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image') !== -1) {
          imageItems.push(items[i])
        }
      }
    }

    if (files) {
      for (let i = 0; i < files.length; i++) {
        if (files[i].type.indexOf('image') !== -1) {
          imageFiles.push(files[i])
        }
      }
    }

    if (imageItems.length > 0 || imageFiles.length > 0) {
      e.preventDefault()
      
      imageItems.forEach((item) => {
        const blob = item.getAsFile()
        if (blob) {
          processImageBlob(blob, 'pasted-image')
        }
      })

      imageFiles.forEach((file) => {
        if (SUPPORTED_IMAGE_TYPES.includes(file.type)) {
          processImageBlob(file, file.name)
        }
      })
    }
  }

  const processImageBlob = (blob: File, name: string) => {
    const reader = new FileReader()
    reader.onload = (event) => {
      const base64 = event.target?.result as string
      const img = new Image()
      img.onload = () => {
        const attachment: Attachment = {
          id: Date.now().toString() + Math.random().toString(36).slice(2),
          type: 'image',
          data: base64,
          mimeType: blob.type,
          name: name,
          width: img.width,
          height: img.height
        }
        setAttachments(prev => [...prev, attachment])
      }
      img.src = base64
    }
    reader.readAsDataURL(blob)
  }

  // ============== IMAGE UPLOAD ==============
  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files?.length) return

    for (const file of Array.from(files)) {
      if (!SUPPORTED_IMAGE_TYPES.includes(file.type)) {
        continue
      }
      processImageBlob(file, file.name)
    }
    e.target.value = ''
  }

  const removeAttachment = (id: string) => {
    setAttachments(prev => prev.filter(a => a.id !== id))
  }

  // ============== SCREENSHARE ==============
  const startScreenshare = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 5 },
        audio: false
      })

      screenStreamRef.current = stream

      const video = document.createElement('video')
      video.srcObject = stream
      video.muted = true
      video.playsInline = true
      videoRef.current = video

      const canvas = document.createElement('canvas')
      canvasRef.current = canvas

      await new Promise<void>((resolve) => {
        video.onloadedmetadata = () => {
          canvas.width = video.videoWidth
          canvas.height = video.videoHeight
          video.play().then(resolve).catch(resolve)
        }
      })

      setIsScreensharing(true)

      screenshareIntervalRef.current = setInterval(() => {
        captureScreenFrame()
      }, 3000)

      stream.getVideoTracks()[0].onended = () => {
        stopScreenshare()
      }

    } catch (error) {
      console.error('Error starting screenshare:', error)
      if (error instanceof DOMException && error.name === 'NotAllowedError') {
        // User cancelled
      }
    }
  }

  const captureScreenFrame = useCallback(() => {
    if (!videoRef.current || !canvasRef.current) return

    const video = videoRef.current
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')

    if (!ctx) return

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    const dataUrl = canvas.toDataURL('image/png')

    const screenAttachment: Attachment = {
      id: 'screen-capture',
      type: 'image',
      data: dataUrl,
      mimeType: 'image/png',
      name: 'Screen Capture',
      width: canvas.width,
      height: canvas.height
    }

    setAttachments(prev => {
      const filtered = prev.filter(a => a.id !== 'screen-capture')
      return [...filtered, screenAttachment]
    })
  }, [])

  const stopScreenshare = () => {
    if (screenshareIntervalRef.current) {
      clearInterval(screenshareIntervalRef.current)
      screenshareIntervalRef.current = null
    }

    if (screenStreamRef.current) {
      screenStreamRef.current.getTracks().forEach(track => track.stop())
      screenStreamRef.current = null
    }

    videoRef.current = null
    canvasRef.current = null
    setIsScreensharing(false)
    setAttachments(prev => prev.filter(a => a.id !== 'screen-capture'))
  }

  const handleCameraClick = () => {
    if (isScreensharing) {
      stopScreenshare()
    } else {
      startScreenshare()
    }
  }

  return (
    <div className={cn("border-t bg-card p-3", className)}>
      {/* Attachments Preview */}
      {attachments.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {attachments.map((attachment) => (
            <div key={attachment.id} className="relative group rounded-lg border border-border overflow-hidden">
              <div className="w-16 h-16 relative">
                <img
                  src={attachment.data}
                  alt={attachment.name || 'Image'}
                  className="w-full h-full object-cover"
                />
                {attachment.id === 'screen-capture' && (
                  <div className="absolute bottom-0 left-0 right-0 bg-black/70 text-xs text-center py-0.5 text-green-400">
                    Live
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => removeAttachment(attachment.id)}
                className="absolute top-0.5 right-0.5 p-0.5 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Screensharing Indicator */}
      {isScreensharing && (
        <div className="mb-2 flex items-center gap-2 rounded-lg bg-green-500/10 border border-green-500/20 px-3 py-2 text-sm text-green-400">
          <Camera className="h-4 w-4 animate-pulse" />
          <span>Screen sharing active - capturing every 3 seconds</span>
          <button type="button" onClick={stopScreenshare} className="ml-auto text-red-400 hover:text-red-300">
            Stop
          </button>
        </div>
      )}

      <div className="flex justify-center">
        <div className="w-full max-w-xl">
          <div className="flex items-end gap-2">
            {/* Attachment Buttons */}
            <div className="flex gap-1 relative">
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground"
                onClick={() => setShowAttachmentMenu(!showAttachmentMenu)}
              >
                <Paperclip className="h-5 w-5" />
              </Button>

              {showAttachmentMenu && (
                <div className="absolute bottom-full left-0 mb-2 w-40 rounded-lg border border-border bg-card shadow-lg z-50 p-1">
                  <button
                    type="button"
                    onClick={() => {
                      imageInputRef.current?.click()
                      setShowAttachmentMenu(false)
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
                  >
                    <ImageIcon className="h-4 w-4" />
                    Upload Image
                  </button>
                  <button
                    type="button"
                    onClick={handleCameraClick}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent",
                      isScreensharing && "bg-green-500/10"
                    )}
                  >
                    {isScreensharing ? (
                      <CameraOff className="h-4 w-4" />
                    ) : (
                      <Camera className="h-4 w-4" />
                    )}
                    {isScreensharing ? 'Stop Screenshare' : 'Share Screen'}
                  </button>
                </div>
              )}

              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-9 w-9 shrink-0",
                  isScreensharing && "bg-green-500 hover:bg-green-600 text-white"
                )}
                onClick={handleCameraClick}
                title={isScreensharing ? "Stop screenshare" : "Start screenshare"}
              >
                {isScreensharing ? (
                  <CameraOff className="h-5 w-5" />
                ) : (
                  <Camera className="h-5 w-5" />
                )}
              </Button>
            </div>

            <div className="flex-1 relative">
              {/* Slash command picker */}
              {showSlashMenu && (
                <div className="absolute bottom-full left-0 mb-1 w-72 rounded-lg border border-border bg-card shadow-lg z-50 overflow-hidden">
                  <div className="px-3 py-1.5 text-xs text-muted-foreground border-b border-border">Commands</div>
                  {slashMatches.map((cmd, i) => (
                    <button
                      key={cmd.command}
                      type="button"
                      onMouseDown={(e) => {
                        e.preventDefault()
                        onChange(cmd.command + " ")
                        setSlashCmdIndex(0)
                        textareaRef.current?.focus()
                      }}
                      className={cn(
                        "flex w-full items-center gap-3 px-3 py-2 text-sm text-left",
                        i === slashCmdIndex ? "bg-accent text-accent-foreground" : "hover:bg-accent/50"
                      )}
                    >
                      <span className="font-mono text-primary">{cmd.command}</span>
                      <span className="text-muted-foreground truncate">{cmd.description}</span>
                    </button>
                  ))}
                </div>
              )}
              <Textarea
                ref={textareaRef}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                placeholder={
                  isScreensharing
                    ? "Ask about what's on your screen..."
                    : attachments.length > 0
                      ? "Describe what you want to know about this..."
                      : "Ask Harvis... (paste images to analyze)"
                }
                rows={1}
                disabled={isLoading || isAborting}
                className={cn(
                  "resize-none border-muted/50 focus-visible:ring-muted-foreground/20 pr-10",
                  "min-h-[32px] max-h-[120px]"
                )}
              />
            </div>
            {isLoading && !isAborting ? (
              <Button
                size="icon"
                variant="secondary"
                onClick={onAbort}
                className="h-8 w-8 shrink-0"
              >
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                size="icon"
                onClick={handleSubmit}
                disabled={(!value.trim() && attachments.length === 0) || isLoading}
                className="h-8 w-8 shrink-0"
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
      </div>

      {/* Hidden Image Input */}
      <input
        ref={imageInputRef}
        type="file"
        multiple
        accept={SUPPORTED_IMAGE_TYPES.join(',')}
        onChange={handleImageUpload}
        className="hidden"
      />

      {/* Click outside to close menu */}
      {showAttachmentMenu && (
        <div className="fixed inset-0 z-40" onClick={() => setShowAttachmentMenu(false)} />
      )}
    </div>
  )
}
