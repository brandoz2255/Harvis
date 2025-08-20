
"use client"

import { useState, useRef } from "react"
import { motion } from "framer-motion"
import { Mic, MicOff, Volume2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

interface VoiceControlsProps {
  selectedModel?: string
}

export default function VoiceControls({ selectedModel = "llama3.2:3b" }: VoiceControlsProps) {
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [lastTranscription, setLastTranscription] = useState("")

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const audioRef = useRef<HTMLAudioElement>(null)

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          sampleRate: { ideal: 16000 },  // Prefer 16kHz for Whisper
          channelCount: 1,    // Mono audio
          echoCancellation: true,
          noiseSuppression: false,  // Disable - can interfere with speech
          autoGainControl: false,   // Disable - can cause volume fluctuations
        }
      })
      
      // Log actual audio settings
      const audioTrack = stream.getAudioTracks()[0]
      const settings = audioTrack.getSettings()
      console.log('Actual audio settings:', settings)
      
      // Try to use WAV format if supported, fallback to webm
      let options: MediaRecorderOptions = {}
      if (MediaRecorder.isTypeSupported('audio/wav')) {
        options.mimeType = 'audio/wav'
      } else if (MediaRecorder.isTypeSupported('audio/webm;codecs=pcm')) {
        options.mimeType = 'audio/webm;codecs=pcm'
      } else if (MediaRecorder.isTypeSupported('audio/webm')) {
        options.mimeType = 'audio/webm'
      }
      
      const mediaRecorder = new MediaRecorder(stream, options)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      console.log('Recording with MIME type:', mediaRecorder.mimeType)

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.onstop = async () => {
        const mimeType = mediaRecorder.mimeType || 'audio/webm'
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType })
        console.log('Created audio blob:', audioBlob.size, 'bytes, type:', audioBlob.type)
        await sendAudioToBackend(audioBlob)

        // Stop all tracks to release microphone
        stream.getTracks().forEach((track) => track.stop())
      }

      mediaRecorder.start()
      setIsRecording(true)
    } catch (error) {
      console.error("Error accessing microphone:", error)
      alert("Unable to access microphone. Please check permissions.")
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
      setIsProcessing(true)
    }
  }

  const sendAudioToBackend = async (audioBlob: Blob) => {
    // Retry logic with 3 attempts
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        // Determine proper file extension based on MIME type
        let filename = "mic.wav"
        if (audioBlob.type.includes('webm')) {
          filename = "mic.webm"
        } else if (audioBlob.type.includes('wav')) {
          filename = "mic.wav"
        } else if (audioBlob.type.includes('ogg')) {
          filename = "mic.ogg"
        }
        
        console.log('Sending audio file:', filename, 'size:', audioBlob.size, 'type:', audioBlob.type)
        
        const formData = new FormData()
        formData.append("file", audioBlob, filename)
        formData.append("model", selectedModel)

        // Get auth token for API request
        const token = localStorage.getItem('token')
        console.log('🔥🔥🔥 VoiceControls: Token exists:', !!token, token ? `${token.substring(0, 20)}...` : 'null')
        alert('VoiceControls: AUTH CHECK - Token exists: ' + !!token)
        
        const headers: Record<string, string> = {}
        if (token) {
          headers['Authorization'] = `Bearer ${token}`
        } else {
          console.error('VoiceControls: No auth token found in localStorage')
        }

        const response = await fetch("/api/mic-chat", {
          method: "POST",
          headers,
          body: formData,
        })

        if (!response.ok) throw new Error("Network response was not ok")

        const data = await response.json()

        // Extract the user's transcribed message
        const userMessage = data.history.find((msg: any) => msg.role === "user")
        if (userMessage) {
          setLastTranscription(userMessage.content)
        }

        if (data.audio_path) {
          setAudioUrl(data.audio_path)
          // Auto-play response
          setTimeout(() => {
            if (audioRef.current) {
              audioRef.current.play().catch(console.warn)
            }
          }, 500)
        }

        setIsProcessing(false)
        return // Success, exit retry loop
      } catch (error) {
        console.error(`Audio processing attempt ${attempt + 1} failed:`, error)
        if (attempt === 2) {
          alert("Sorry, there was an error processing your audio.")
        }
        // Wait before retry (exponential backoff)
        await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
      }
    }
    setIsProcessing(false)
  }

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }

  const replayAudio = () => {
    if (audioRef.current) {
      audioRef.current.currentTime = 0
      audioRef.current.play()
    }
  }

  return (
    <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30">
      <div className="p-6">
        <h2 className="text-xl font-semibold text-blue-300 mb-4">Voice Controls</h2>

        <div className="flex flex-col items-center space-y-4">
          <motion.div whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}>
            <Button
              onClick={toggleRecording}
              disabled={isProcessing}
              className={`w-20 h-20 rounded-full ${
                isRecording ? "bg-red-600 hover:bg-red-700 animate-pulse" : "bg-blue-600 hover:bg-blue-700"
              } text-white shadow-lg`}
            >
              {isRecording ? <MicOff className="w-8 h-8" /> : <Mic className="w-8 h-8" />}
            </Button>
          </motion.div>

          <div className="text-center">
            {isRecording && (
              <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-red-400 font-medium">
                Recording... Click to stop
              </motion.p>
            )}

            {isProcessing && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center space-x-2 text-blue-400"
              >
                <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"></div>
                <div
                  className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"
                  style={{ animationDelay: "0.1s" }}
                ></div>
                <div
                  className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"
                  style={{ animationDelay: "0.2s" }}
                ></div>
                <span className="ml-2">Processing audio...</span>
              </motion.div>
            )}

            {!isRecording && !isProcessing && <p className="text-gray-400">Click to start voice recording</p>}
          </div>

          {lastTranscription && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-gray-800 rounded-lg p-3 max-w-md"
            >
              <p className="text-sm text-gray-300">
                <span className="text-blue-400 font-medium">You said:</span> &quot;{lastTranscription}&quot;
              </p>
            </motion.div>
          )}

          {audioUrl && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center space-x-3 bg-blue-900/30 rounded-lg p-3"
            >
              <Button
                onClick={replayAudio}
                variant="outline"
                size="sm"
                className="bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
              >
                <Volume2 className="w-4 h-4 mr-2" />
                Replay Response
              </Button>
              <audio ref={audioRef} src={audioUrl} className="hidden" />
            </motion.div>
          )}
        </div>
      </div>
    </Card>
  )
}
