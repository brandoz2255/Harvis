"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { motion } from "framer-motion"
import { Monitor, MonitorOff, Eye, EyeOff, MessageSquare, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

interface ScreenShareProps {
  onAnalysis?: (analysis: string) => void
  onAnalyzeAndRespond?: (response: string) => void
}

export default function CompactScreenShare({ onAnalysis, onAnalyzeAndRespond }: ScreenShareProps) {
  const [isSharing, setIsSharing] = useState(false)
  const [commentaryEnabled, setCommentaryEnabled] = useState(false)
  const [commentary, setCommentary] = useState("")
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [isAnalyzingAndResponding, setIsAnalyzingAndResponding] = useState(false)

  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const commentaryTimerRef = useRef<NodeJS.Timeout | null>(null)

  const startScreenShare = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      })

      if (videoRef.current) {
        videoRef.current.srcObject = stream
        streamRef.current = stream
        setIsSharing(true)

        stream.getVideoTracks()[0].addEventListener("ended", stopScreenShare)
      }
    } catch (error) {
      console.error("Error starting screen share:", error)
      alert("Failed to start screen sharing. Please check permissions.")
    }
  }

  const stopScreenShare = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null
    }

    setIsSharing(false)
    setCommentaryEnabled(false)
    setCommentary("")

    if (commentaryTimerRef.current) {
      clearInterval(commentaryTimerRef.current)
      commentaryTimerRef.current = null
    }
  }

  const analyzeScreen = useCallback(async () => {
    if (!videoRef.current || !streamRef.current || isAnalyzing) return

    setIsAnalyzing(true)

    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const canvas = document.createElement("canvas")
        canvas.width = videoRef.current.videoWidth
        canvas.height = videoRef.current.videoHeight

        const ctx = canvas.getContext("2d")
        if (ctx) {
          ctx.drawImage(videoRef.current, 0, 0)
          const imageData = canvas.toDataURL("image/jpeg", 0.8)

          const response = await fetch("/api/analyze-screen", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ image: imageData }),
          })

          if (!response.ok) throw new Error(await response.text())

          const data = await response.json()
          if (data.commentary) {
            setCommentary(data.commentary)
            onAnalysis?.(data.commentary)
          }
          setIsAnalyzing(false)
          return
        }
      } catch (error) {
        console.error(`Analyze attempt ${attempt + 1} failed:`, error)
        if (attempt === 2) {
          setCommentary("Sorry, can't analyze the screen.")
        }
        await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
      }
    }
    setIsAnalyzing(false)
  }, [isAnalyzing, onAnalysis])

  const analyzeAndRespond = useCallback(async () => {
    if (!videoRef.current || !streamRef.current || isAnalyzingAndResponding) return

    setIsAnalyzingAndResponding(true)

    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const canvas = document.createElement("canvas")
        canvas.width = videoRef.current.videoWidth
        canvas.height = videoRef.current.videoHeight

        const ctx = canvas.getContext("2d")
        if (ctx) {
          ctx.drawImage(videoRef.current, 0, 0)
          const imageData = canvas.toDataURL("image/jpeg", 0.8)

          const response = await fetch("/api/analyze-and-respond", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              image: imageData,
              system_prompt:
                "You are Harvis AI, an AI assistant analyzing what the user is seeing on their screen. Provide helpful insights, suggestions, or commentary about what you observe. Be conversational and helpful.",
              model: "mistral", // You can make this configurable
            }),
          })

          if (!response.ok) throw new Error(await response.text())

          const data = await response.json()
          if (data.response) {
            // Send the LLM response to the chat interface
            onAnalyzeAndRespond?.(data.response)

            // Also update local commentary for display
            setCommentary(`AI Response: ${data.response}`)
          }
          setIsAnalyzingAndResponding(false)
          return
        }
      } catch (error) {
        console.error(`Analyze and respond attempt ${attempt + 1} failed:`, error)
        if (attempt === 2) {
          setCommentary("Sorry, can't analyze and respond to the screen.")
          onAnalyzeAndRespond?.("Sorry, I'm having trouble analyzing your screen right now.")
        }
        await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
      }
    }
    setIsAnalyzingAndResponding(false)
  }, [isAnalyzingAndResponding, onAnalyzeAndRespond])

  const toggleCommentary = () => {
    const newState = !commentaryEnabled
    setCommentaryEnabled(newState)

    if (newState && isSharing) {
      analyzeScreen()
      commentaryTimerRef.current = setInterval(analyzeScreen, 30000)
    } else {
      if (commentaryTimerRef.current) {
        clearInterval(commentaryTimerRef.current)
        commentaryTimerRef.current = null
      }
      setCommentary("")
    }
  }

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "c" && isSharing) {
        e.preventDefault()
        analyzeScreen()
      }
      // Add new shortcut for analyze and respond (Ctrl/Cmd + Shift + C)
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "C" && isSharing) {
        e.preventDefault()
        analyzeAndRespond()
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [isSharing, analyzeScreen, analyzeAndRespond])

  useEffect(() => {
    return () => {
      if (commentaryTimerRef.current) {
        clearInterval(commentaryTimerRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
      }
    }
  }, [])

  return (
    <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30">
      <div className="p-3 border-b border-blue-500/30">
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-semibold text-blue-300">Screen Share</h3>
          <div className="flex space-x-1">
            <Button
              onClick={isSharing ? stopScreenShare : startScreenShare}
              size="sm"
              className={`${isSharing ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"} text-white`}
            >
              {isSharing ? <MonitorOff className="w-4 h-4" /> : <Monitor className="w-4 h-4" />}
            </Button>

            <Button
              onClick={toggleCommentary}
              disabled={!isSharing}
              size="sm"
              variant="outline"
              className={`${
                commentaryEnabled
                  ? "bg-green-600 hover:bg-green-700 text-white border-green-600"
                  : "bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
              }`}
            >
              {commentaryEnabled ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
            </Button>

            <Button
              onClick={analyzeAndRespond}
              disabled={!isSharing || isAnalyzingAndResponding}
              size="sm"
              variant="outline"
              className="bg-purple-600 hover:bg-purple-700 text-white border-purple-600 disabled:opacity-50"
              title="Analyze screen and get AI response (Ctrl/Cmd + Shift + C)"
            >
              {isAnalyzingAndResponding ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <MessageSquare className="w-4 h-4" />
              )}
            </Button>
          </div>
        </div>
      </div>

      <div className="p-3">
        <div className="relative">
          <video
            ref={videoRef}
            autoPlay
            muted
            className={`w-full rounded-lg border border-gray-600 ${isSharing ? "block" : "hidden"}`}
            style={{ maxHeight: "200px" }}
          />

          {!isSharing && (
            <div className="w-full h-32 bg-gray-800 rounded-lg border border-gray-600 flex items-center justify-center">
              <div className="text-center text-gray-400">
                <Monitor className="w-8 h-8 mx-auto mb-1 opacity-50" />
                <p className="text-xs">Click to start screen capture</p>
              </div>
            </div>
          )}
        </div>

        {/* Button descriptions */}
        {isSharing && (
          <div className="mt-2 text-xs text-gray-500 space-y-1">
            <div className="flex items-center space-x-2">
              <Eye className="w-3 h-3" />
              <span>Auto-analyze every 30s</span>
            </div>
            <div className="flex items-center space-x-2">
              <MessageSquare className="w-3 h-3" />
              <span>Analyze & get AI response</span>
            </div>
            <div>
              <span>Shortcuts: Ctrl+C (analyze), Ctrl+Shift+C (AI response)</span>
            </div>
          </div>
        )}

        {commentary && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-blue-900/30 border border-blue-500/50 rounded-lg p-2 mt-2"
          >
            <div className="flex items-start space-x-2">
              <Eye className="w-3 h-3 text-blue-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-xs text-blue-300 font-medium">Analysis</p>
                <p className="text-xs text-gray-300 mt-1">{commentary}</p>
                {(isAnalyzing || isAnalyzingAndResponding) && (
                  <div className="flex items-center space-x-1 mt-1">
                    <div className="w-1 h-1 bg-blue-400 rounded-full animate-pulse"></div>
                    <span className="text-xs text-blue-400">
                      {isAnalyzingAndResponding ? "Getting AI response..." : "Analyzing..."}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </div>
    </Card>
  )
}
