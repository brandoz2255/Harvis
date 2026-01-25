"use client"

import React from "react"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"
import {
  Send,
  Paperclip,
  Mic,
  MicOff,
  ImageIcon as ImageIcon,
  Sparkles,

  Loader2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import type { MessageObject } from "@/types/message"

interface ChatInputProps {
  onSend: (message: string | MessageObject) => void
  isLoading?: boolean
  isResearchMode?: boolean
  selectedModel?: string
  className?: string
}

export function ChatInput({ onSend, isLoading, isResearchMode, selectedModel, className }: ChatInputProps) {
  const [message, setMessage] = useState("")
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessingVoice, setIsProcessingVoice] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)

  const handleSend = () => {
    if (message.trim() && !isLoading) {
      onSend(message.trim())
      setMessage("")
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Voice recording functions
  const startRecording = async () => {
    try {
      // Check browser support
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        alert('Voice recording is not supported in this browser')
        return
      }

      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1, // Mono
          sampleRate: 16000, // 16kHz for Whisper
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      })

      streamRef.current = stream
      audioChunksRef.current = []

      // Create MediaRecorder with appropriate MIME type
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

        // Create audio blob
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType })

        // Send to backend
        await sendAudioToBackend(audioBlob)

        // Cleanup
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
    // Create AbortController for long timeout (10 minutes for local hardware)
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 600000)

    try {
      // Get auth token from localStorage
      const token = localStorage.getItem('token')

      if (!token) {
        console.error('No auth token found')
        alert('Authentication required. Please log in.')
        clearTimeout(timeoutId) // Clear timeout if we return early
        return
      }

      // Create FormData
      const formData = new FormData()
      formData.append('file', audioBlob, 'recording.webm')

      // Add selected model (critical for using user's choice)
      if (selectedModel) {
        formData.append('model', selectedModel)
      }

      // Add research mode if active
      if (isResearchMode) {
        formData.append('research_mode', 'true')
      }

      // Call backend via nginx proxy with long timeout for local hardware
      // Voice requests can take a while: model loading + transcription + LLM + TTS
      const response = await fetch('/api/mic-chat', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
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

      const data = await response.json()

      // Handle response
      handleVoiceResponse(data)

    } catch (error) {
      clearTimeout(timeoutId)
      console.error('Error sending audio to backend:', error)
      alert('Failed to process voice input. Please try again.')
    }
  }

  const handleVoiceResponse = (data: any) => {
    // Extract user transcription from history
    const userTranscription = data.history?.find((msg: any) => msg.role === 'user')?.content || 'Voice input'

    // Add user message first
    const userMessage: MessageObject = {
      id: Date.now().toString(),
      role: 'user',
      content: userTranscription,
      timestamp: new Date(),
      inputType: 'voice'
    }

    // Add assistant response
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

    // Send both messages to parent
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

  return (
    <div className={cn("p-4", className)}>
      <div className="mx-auto max-w-3xl">
        <div className="relative rounded-2xl border border-border bg-card shadow-lg">
          {/* Input Area */}
          <div className="flex items-end gap-2 p-3">
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground"
              >
                <Paperclip className="h-5 w-5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground"
              >
                <ImageIcon className="h-5 w-5" />
              </Button>

            </div>

            <Textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything..."
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
                disabled={!message.trim() || isLoading}
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

        {/* Footer */}
        <p className="text-xs text-muted-foreground text-center mt-2">
          Harvis can make mistakes. Consider checking important information.
        </p>
      </div>
    </div>
  )
}
