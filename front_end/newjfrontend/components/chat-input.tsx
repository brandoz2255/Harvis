"use client"

import React from "react"
import { useState, useRef, useEffect, useCallback } from "react"
import { cn } from "@/lib/utils"
import {
  Send,
  Paperclip,
  Mic,
  MicOff,
  ImageIcon,
  Sparkles,
  Loader2,
  Camera,
  CameraOff,
  X,
  FileText,
  Plug,
  Plus,
  File,
  AlertCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import type { MessageObject, Attachment, ImageAttachment, FileAttachment, MCPPlugin } from "@/types/message"
import { isVisionModel } from "@/types/message"

interface ChatInputProps {
  onSend: (message: string | MessageObject) => void
  isLoading?: boolean
  isResearchMode?: boolean
  selectedModel?: string
  sessionId?: string | null  // Current chat session ID for voice history
  className?: string
}

// Supported file types for file upload
const SUPPORTED_FILE_TYPES = {
  'application/pdf': '.pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
  'application/msword': '.doc',
  'text/plain': '.txt',
  'text/markdown': '.md',
  'text/csv': '.csv',
  'application/json': '.json',
  'text/javascript': '.js',
  'text/typescript': '.ts',
  'text/x-python': '.py',
  'text/html': '.html',
  'text/css': '.css',
  'application/xml': '.xml',
  'text/yaml': '.yaml',
}

const SUPPORTED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']

export function ChatInput({ onSend, isLoading, isResearchMode, selectedModel, sessionId, className }: ChatInputProps) {
  const [message, setMessage] = useState("")
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessingVoice, setIsProcessingVoice] = useState(false)
  const [isScreensharing, setIsScreensharing] = useState(false)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [showPaperclipMenu, setShowPaperclipMenu] = useState(false)
  const [showMCPModal, setShowMCPModal] = useState(false)
  const [mcpPlugins, setMcpPlugins] = useState<MCPPlugin[]>([])
  const [newMCPHost, setNewMCPHost] = useState("")
  const [newMCPPort, setNewMCPPort] = useState("")
  const [newMCPName, setNewMCPName] = useState("")
  const [vlModelError, setVlModelError] = useState<string | null>(null)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const transcribedTextRef = useRef<string>('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const screenStreamRef = useRef<MediaStream | null>(null)
  const screenshareIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  const isVL = isVisionModel(selectedModel || '')

  // Load MCP plugins from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('mcpPlugins')
    if (saved) {
      try {
        setMcpPlugins(JSON.parse(saved))
      } catch (e) {
        console.error('Failed to load MCP plugins:', e)
      }
    }
  }, [])

  // Save MCP plugins to localStorage
  useEffect(() => {
    localStorage.setItem('mcpPlugins', JSON.stringify(mcpPlugins))
  }, [mcpPlugins])

  // Clear VL error after a delay
  useEffect(() => {
    if (vlModelError) {
      const timer = setTimeout(() => setVlModelError(null), 5000)
      return () => clearTimeout(timer)
    }
  }, [vlModelError])

  const handleSend = () => {
    if ((message.trim() || attachments.length > 0) && !isLoading) {
      // If we have attachments, send as MessageObject
      if (attachments.length > 0) {
        const msgObj: MessageObject = {
          id: Date.now().toString(),
          role: 'user',
          content: message.trim() || 'Analyze this',
          timestamp: new Date(),
          inputType: attachments[0].type === 'image' ? 'image' : 'file',
          attachments: [...attachments],
          imageUrl: attachments.find(a => a.type === 'image')?.data
        }
        onSend(msgObj)
        setAttachments([])
      } else {
        onSend(message.trim())
      }
      setMessage("")
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // ============== PASTE HANDLING ==============
  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items
    const files = e.clipboardData.files

    // Check for image files in clipboard items (includes screenshots)
    const imageItems: DataTransferItem[] = []
    
    if (items) {
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image') !== -1) {
          imageItems.push(items[i])
        }
      }
    }

    // Also check files (for when copying from file manager)
    const imageFiles: File[] = []
    if (files) {
      for (let i = 0; i < files.length; i++) {
        if (files[i].type.indexOf('image') !== -1) {
          imageFiles.push(files[i])
        }
      }
    }

    // If we found images, process them
    if (imageItems.length > 0 || imageFiles.length > 0) {
      e.preventDefault() // Prevent pasting the image data into the textarea
      
      if (!requireVLModel('Image paste')) {
        return
      }

      // Process items (screenshots, copied from browser)
      imageItems.forEach((item) => {
        const blob = item.getAsFile()
        if (blob) {
          processImageBlob(blob, 'pasted-image')
        }
      })

      // Process files (copied from file manager)
      imageFiles.forEach((file) => {
        if (SUPPORTED_IMAGE_TYPES.includes(file.type)) {
          processImageBlob(file, file.name)
        }
      })
    }
    // Text paste will continue normally
  }

  const processImageBlob = (blob: File, name: string) => {
    const reader = new FileReader()
    reader.onload = (event) => {
      const base64 = event.target?.result as string
      const img = new Image()
      img.onload = () => {
        const attachment: ImageAttachment = {
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

  // Check if VL model is required and show error
  const requireVLModel = useCallback((action: string): boolean => {
    if (!isVL) {
      setVlModelError(`${action} requires a Vision Language model (like llava, moondream, qwen2-vl). Please select a VL model.`)
      return false
    }
    return true
  }, [isVL])

  // ============== IMAGE UPLOAD ==============
  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files?.length) return

    if (!requireVLModel('Image upload')) {
      e.target.value = ''
      return
    }

    for (const file of Array.from(files)) {
      if (!SUPPORTED_IMAGE_TYPES.includes(file.type)) {
        alert(`Unsupported image type: ${file.type}`)
        continue
      }

      const reader = new FileReader()
      reader.onload = (event) => {
        const base64 = event.target?.result as string
        const img = new Image()
        img.onload = () => {
          const attachment: ImageAttachment = {
            id: Date.now().toString() + Math.random().toString(36).slice(2),
            type: 'image',
            data: base64,
            mimeType: file.type,
            name: file.name,
            width: img.width,
            height: img.height
          }
          setAttachments(prev => [...prev, attachment])
        }
        img.src = base64
      }
      reader.readAsDataURL(file)
    }
    e.target.value = ''
  }

  // ============== FILE UPLOAD ==============
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files?.length) return

    for (const file of Array.from(files)) {
      const reader = new FileReader()
      reader.onload = (event) => {
        const base64 = event.target?.result as string
        const attachment: FileAttachment = {
          id: Date.now().toString() + Math.random().toString(36).slice(2),
          type: 'file',
          data: base64,
          mimeType: file.type || 'application/octet-stream',
          name: file.name,
          size: file.size
        }
        setAttachments(prev => [...prev, attachment])
      }
      reader.readAsDataURL(file)
    }
    e.target.value = ''
    setShowPaperclipMenu(false)
  }

  const removeAttachment = (id: string) => {
    setAttachments(prev => prev.filter(a => a.id !== id))
  }

  // ============== SCREENSHARE ==============
  const startScreenshare = async () => {
    if (!requireVLModel('Screenshare')) return

    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 5 },
        audio: false
      })

      screenStreamRef.current = stream

      // Create video and canvas elements for capturing frames
      const video = document.createElement('video')
      video.srcObject = stream
      video.muted = true
      // Important: Add playsinline for better compatibility
      video.playsInline = true
      videoRef.current = video

      const canvas = document.createElement('canvas')
      canvasRef.current = canvas

      // Wait for video to be ready and actually playing
      await new Promise<void>((resolve) => {
        video.onloadedmetadata = () => {
          canvas.width = video.videoWidth
          canvas.height = video.videoHeight
          // Explicitly play the video
          video.play().then(() => {
            console.log(`🎥 Screenshare started: ${video.videoWidth}x${video.videoHeight}`)
            resolve()
          }).catch(e => {
            console.error('Error playing video for screenshare:', e)
            resolve() // Try to continue anyway
          })
        }
      })

      setIsScreensharing(true)

      // Capture frame every 3 seconds (but only send on user prompt)
      screenshareIntervalRef.current = setInterval(() => {
        captureScreenFrame()
      }, 3000)

      // Handle stream end
      stream.getVideoTracks()[0].onended = () => {
        stopScreenshare()
      }

    } catch (error) {
      console.error('Error starting screenshare:', error)
      if (error instanceof DOMException && error.name === 'NotAllowedError') {
        alert('Screen sharing permission denied')
      }
    }
  }

  const captureScreenFrame = useCallback(() => {
    if (!videoRef.current || !canvasRef.current) return null

    const video = videoRef.current
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')

    if (!ctx) return null

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    // Use PNG format for better compatibility with Ollama VL models
    const dataUrl = canvas.toDataURL('image/png')

    // Update the latest screen capture as an attachment
    const screenAttachment: ImageAttachment = {
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

    return dataUrl
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

    // Remove screen capture attachment
    setAttachments(prev => prev.filter(a => a.id !== 'screen-capture'))
  }

  const handleCameraClick = () => {
    if (isScreensharing) {
      stopScreenshare()
    } else {
      startScreenshare()
    }
  }

  // ============== MCP PLUGIN ==============
  const addMCPPlugin = () => {
    if (!newMCPHost || !newMCPPort || !newMCPName) {
      alert('Please fill in all fields')
      return
    }

    const port = parseInt(newMCPPort)
    if (isNaN(port) || port < 1 || port > 65535) {
      alert('Invalid port number')
      return
    }

    const plugin: MCPPlugin = {
      id: Date.now().toString(),
      name: newMCPName,
      host: newMCPHost,
      port: port,
      enabled: true
    }

    setMcpPlugins(prev => [...prev, plugin])
    setNewMCPHost("")
    setNewMCPPort("")
    setNewMCPName("")
    setShowMCPModal(false)
  }

  const removeMCPPlugin = (id: string) => {
    setMcpPlugins(prev => prev.filter(p => p.id !== id))
  }

  const toggleMCPPlugin = (id: string) => {
    setMcpPlugins(prev => prev.map(p =>
      p.id === id ? { ...p, enabled: !p.enabled } : p
    ))
  }

  // ============== VOICE RECORDING ==============
  const startRecording = async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        alert('Voice recording is not supported in this browser')
        return
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      })

      streamRef.current = stream
      audioChunksRef.current = []

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/mp4')
          ? 'audio/mp4'
          : 'audio/webm'

      const mediaRecorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = mediaRecorder

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.onstop = async () => {
        setIsRecording(false)
        setIsProcessingVoice(true)

        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType })
        await sendAudioToBackend(audioBlob)

        if (streamRef.current) {
          streamRef.current.getTracks().forEach(track => track.stop())
          streamRef.current = null
        }

        setIsProcessingVoice(false)
      }

      mediaRecorder.start()
      setIsRecording(true)

    } catch (error) {
      console.error('Error starting recording:', error)
      if (error instanceof DOMException && error.name === 'NotAllowedError') {
        alert('Microphone access denied. Please enable microphone permissions.')
      } else {
        alert('Failed to start recording. Please try again.')
      }
      setIsRecording(false)
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }

  const handleMicClick = () => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }

  const sendAudioToBackend = async (audioBlob: Blob) => {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 600000)

    try {
      const token = localStorage.getItem('token')

      if (!token) {
        console.error('No auth token found')
        alert('Authentication required. Please log in.')
        clearTimeout(timeoutId)
        return
      }

      const formData = new FormData()
      formData.append('file', audioBlob, 'recording.webm')

      if (selectedModel) {
        formData.append('model', selectedModel)
      }

      // Pass current session for context & history saving
      if (sessionId) {
        formData.append('session_id', sessionId)
      }

      if (isResearchMode) {
        formData.append('research_mode', 'true')
      }

      // Include attachments if any (for vision + voice)
      if (attachments.length > 0 && isVL) {
        formData.append('attachments', JSON.stringify(attachments))
      }

      const response = await fetch('/api/mic-chat', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
        credentials: 'include',
        signal: controller.signal
      })

      clearTimeout(timeoutId)

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`Backend error: ${response.status} - ${errorText}`)
      }

      // Backend now returns JSON (not SSE)
      const data = await response.json()
      console.log('🎤 Voice response received:', data)

      // Store transcription if available
      if (data.transcription) {
        transcribedTextRef.current = data.transcription
        console.log('📝 Captured user transcription:', data.transcription)
      }

      // Handle the response
      handleVoiceResponse(data)

    } catch (error) {
      clearTimeout(timeoutId)
      console.error('Error sending audio to backend:', error)
      alert('Failed to process voice input. Please try again.')
    }
  }

  const handleVoiceResponse = (data: any) => {
    const userTranscription = transcribedTextRef.current ||
      data.history?.find((msg: any) => msg.role === 'user')?.content ||
      'Voice input'

    transcribedTextRef.current = ''

    console.log('🎤 Voice response - User said:', userTranscription)

    const userMessage: MessageObject = {
      id: Date.now().toString(),
      role: 'user',
      content: userTranscription,
      timestamp: new Date(),
      inputType: 'voice'
    }

    const assistantContent = data.final_answer ||
      (data.history && data.history.length > 0
        ? data.history[data.history.length - 1]?.content
        : '')

    const assistantMessage: MessageObject = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: assistantContent,
      audioUrl: data.audio_path,
      reasoning: data.reasoning,
      searchResults: data.search_results,
      timestamp: new Date(),
      inputType: 'voice'
    }

    if (onSend) {
      onSend(userMessage)
      setTimeout(() => onSend(assistantMessage), 100)
    }
  }

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`
    }
  }, [message])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopScreenshare()
    }
  }, [])

  return (
    <div className={cn("p-4 bg-background", className)}>
      <div className="mx-auto max-w-3xl">
        {/* VL Model Error */}
        {vlModelError && (
          <div className="mb-3 flex items-center gap-2 rounded-lg bg-amber-500/10 border border-amber-500/20 px-3 py-2 text-sm text-amber-400">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{vlModelError}</span>
            <button
              type="button"
              onClick={() => setVlModelError(null)}
              className="ml-auto hover:text-amber-300"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Attachments Preview */}
        {attachments.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {attachments.map((attachment) => (
              <div
                key={attachment.id}
                className="relative group rounded-lg border border-border bg-card overflow-hidden"
              >
                {attachment.type === 'image' ? (
                  <div className="w-20 h-20 relative">
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
                ) : (
                  <div className="w-20 h-20 flex flex-col items-center justify-center p-2">
                    <File className="h-6 w-6 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground truncate w-full text-center mt-1">
                      {attachment.name}
                    </span>
                  </div>
                )}
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
          <div className="mb-3 flex items-center gap-2 rounded-lg bg-green-500/10 border border-green-500/20 px-3 py-2 text-sm text-green-400">
            <Camera className="h-4 w-4 animate-pulse" />
            <span>Screen sharing active - capturing every 3 seconds</span>
            <button
              type="button"
              onClick={stopScreenshare}
              className="ml-auto text-red-400 hover:text-red-300"
            >
              Stop
            </button>
          </div>
        )}

        <div className="relative rounded-2xl border border-border bg-card shadow-lg">
          {/* Input Area */}
          <div className="flex items-end gap-2 p-3">
            <div className="flex gap-1 relative">
              {/* Paperclip Menu */}
              <div className="relative">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground"
                  onClick={() => setShowPaperclipMenu(!showPaperclipMenu)}
                >
                  <Paperclip className="h-5 w-5" />
                </Button>

                {showPaperclipMenu && (
                  <div className="absolute bottom-full left-0 mb-2 w-48 rounded-lg border border-border bg-card shadow-lg z-50">
                    <div className="p-1">
                      <button
                        type="button"
                        onClick={() => {
                          fileInputRef.current?.click()
                        }}
                        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
                      >
                        <FileText className="h-4 w-4" />
                        Upload Files
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setShowPaperclipMenu(false)
                          setShowMCPModal(true)
                        }}
                        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
                      >
                        <Plug className="h-4 w-4" />
                        Add MCP Plugin
                      </button>
                      {mcpPlugins.length > 0 && (
                        <>
                          <div className="my-1 border-t border-border" />
                          <div className="px-3 py-1 text-xs text-muted-foreground">
                            Active Plugins
                          </div>
                          {mcpPlugins.map(plugin => (
                            <div
                              key={plugin.id}
                              className="flex items-center gap-2 px-3 py-1 text-sm"
                            >
                              <input
                                type="checkbox"
                                checked={plugin.enabled}
                                onChange={() => toggleMCPPlugin(plugin.id)}
                                className="rounded"
                              />
                              <span className={cn(
                                "flex-1 truncate",
                                !plugin.enabled && "text-muted-foreground"
                              )}>
                                {plugin.name}
                              </span>
                              <button
                                type="button"
                                onClick={() => removeMCPPlugin(plugin.id)}
                                className="text-muted-foreground hover:text-destructive"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </div>
                          ))}
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Image Upload */}
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-9 w-9 shrink-0",
                  isVL
                    ? "text-muted-foreground hover:text-foreground"
                    : "text-muted-foreground/50 cursor-not-allowed"
                )}
                onClick={() => isVL ? imageInputRef.current?.click() : requireVLModel('Image upload')}
                title={isVL ? "Upload image" : "Requires VL model"}
              >
                <ImageIcon className="h-5 w-5" />
              </Button>

              {/* Camera/Screenshare */}
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-9 w-9 shrink-0",
                  isScreensharing && "bg-green-500 hover:bg-green-600 text-white",
                  !isVL && !isScreensharing && "text-muted-foreground/50 cursor-not-allowed"
                )}
                onClick={handleCameraClick}
                title={isScreensharing ? "Stop screenshare" : (isVL ? "Start screenshare" : "Requires VL model")}
              >
                {isScreensharing ? (
                  <CameraOff className="h-5 w-5" />
                ) : (
                  <Camera className="h-5 w-5" />
                )}
              </Button>
            </div>

            <Textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder={
                isScreensharing
                  ? "Ask about what's on your screen..."
                  : attachments.length > 0
                    ? "Describe what you want to know about this..."
                    : "Ask anything... (paste images to analyze)"
              }
              className="min-h-[44px] max-h-[200px] flex-1 resize-none border-0 bg-transparent p-2 text-foreground placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
              rows={1}
            />

            <div className="flex gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={handleMicClick}
                disabled={isProcessingVoice || isLoading}
                className={cn(
                  "h-9 w-9 shrink-0 relative",
                  isRecording && "bg-red-500 hover:bg-red-600 text-white animate-pulse"
                )}
                title={isRecording ? "Stop recording" : "Start voice input"}
              >
                {isProcessingVoice ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : isRecording ? (
                  <MicOff className="h-5 w-5" />
                ) : (
                  <Mic className="h-5 w-5" />
                )}
                {isRecording && (
                  <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-600 rounded-full animate-ping" />
                )}
              </Button>
              <Button
                onClick={handleSend}
                disabled={(!message.trim() && attachments.length === 0) || isLoading}
                className="h-9 w-9 shrink-0 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {isLoading ? (
                  <Sparkles className="h-5 w-5 animate-pulse" />
                ) : (
                  <Send className="h-5 w-5" />
                )}
              </Button>
            </div>
          </div>
        </div>

        {/* Hidden File Inputs */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={Object.values(SUPPORTED_FILE_TYPES).join(',')}
          onChange={handleFileUpload}
          className="hidden"
        />
        <input
          ref={imageInputRef}
          type="file"
          multiple
          accept={SUPPORTED_IMAGE_TYPES.join(',')}
          onChange={handleImageUpload}
          className="hidden"
        />

        {/* Footer */}
        <p className="text-xs text-muted-foreground text-center mt-2">
          {isVL ? (
            <span className="text-green-400">Vision model active</span>
          ) : (
            <span>Select a VL model (llava, moondream, etc.) for vision features</span>
          )}
          {' • '}Harvis can make mistakes. Consider checking important information.
        </p>
      </div>

      {/* MCP Plugin Modal */}
      {showMCPModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">Add MCP Plugin</h3>
              <button
                type="button"
                onClick={() => setShowMCPModal(false)}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="text-sm text-muted-foreground mb-4">
              Connect to an MCP (Model Context Protocol) server to extend Harvis with custom tools.
            </p>
            <div className="space-y-3">
              <div>
                <label className="text-sm font-medium">Plugin Name</label>
                <Input
                  placeholder="My Custom Tools"
                  value={newMCPName}
                  onChange={(e) => setNewMCPName(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Host</label>
                <Input
                  placeholder="localhost or 192.168.1.100"
                  value={newMCPHost}
                  onChange={(e) => setNewMCPHost(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Port</label>
                <Input
                  placeholder="8080"
                  type="number"
                  value={newMCPPort}
                  onChange={(e) => setNewMCPPort(e.target.value)}
                  className="mt-1"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <Button variant="outline" onClick={() => setShowMCPModal(false)}>
                Cancel
              </Button>
              <Button onClick={addMCPPlugin}>
                <Plus className="h-4 w-4 mr-2" />
                Add Plugin
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Click outside to close paperclip menu */}
      {showPaperclipMenu && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setShowPaperclipMenu(false)}
        />
      )}
    </div>
  )
}
