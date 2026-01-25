"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { cn } from "@/lib/utils"
import {
  Play,
  Pause,
  RotateCcw,
  RotateCw,
  Volume2,
  VolumeX,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"

interface VoicePlayerProps {
  text: string
  onClose?: () => void
  className?: string
}

export function VoicePlayer({ text, onClose, className }: VoicePlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(1)
  const [isMuted, setIsMuted] = useState(false)
  const [waveformData, setWaveformData] = useState<number[]>([])
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  const startTimeRef = useRef<number>(0)
  const pausedTimeRef = useRef<number>(0)

  // Generate waveform visualization data
  useEffect(() => {
    const bars = 60
    const data = Array.from({ length: bars }, () => Math.random() * 0.8 + 0.2)
    setWaveformData(data)
  }, [text])

  // Estimate duration based on text length and speech rate
  useEffect(() => {
    const wordsPerMinute = 150
    const words = text.split(/\s+/).length
    const estimatedDuration = (words / wordsPerMinute) * 60
    setDuration(Math.max(estimatedDuration, 5))
  }, [text])

  const speak = useCallback(() => {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel()

      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = 1
      utterance.pitch = 1
      utterance.volume = isMuted ? 0 : volume

      utterance.onstart = () => {
        startTimeRef.current = Date.now() - pausedTimeRef.current * 1000
        intervalRef.current = setInterval(() => {
          const elapsed = (Date.now() - startTimeRef.current) / 1000
          setCurrentTime(Math.min(elapsed, duration))
        }, 100)
      }

      utterance.onend = () => {
        setIsPlaying(false)
        setCurrentTime(0)
        pausedTimeRef.current = 0
        if (intervalRef.current) {
          clearInterval(intervalRef.current)
        }
      }

      utteranceRef.current = utterance
      window.speechSynthesis.speak(utterance)
      setIsPlaying(true)
    }
  }, [text, duration, volume, isMuted])

  const togglePlay = () => {
    if (isPlaying) {
      window.speechSynthesis.pause()
      setIsPlaying(false)
      pausedTimeRef.current = currentTime
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    } else {
      if (window.speechSynthesis.paused) {
        window.speechSynthesis.resume()
        startTimeRef.current = Date.now() - pausedTimeRef.current * 1000
        intervalRef.current = setInterval(() => {
          const elapsed = (Date.now() - startTimeRef.current) / 1000
          setCurrentTime(Math.min(elapsed, duration))
        }, 100)
        setIsPlaying(true)
      } else {
        speak()
      }
    }
  }

  const skipBackward = () => {
    const newTime = Math.max(0, currentTime - 5)
    setCurrentTime(newTime)
    pausedTimeRef.current = newTime
    if (isPlaying) {
      window.speechSynthesis.cancel()
      speak()
    }
  }

  const skipForward = () => {
    const newTime = Math.min(duration, currentTime + 5)
    setCurrentTime(newTime)
    pausedTimeRef.current = newTime
    if (isPlaying) {
      window.speechSynthesis.cancel()
      speak()
    }
  }

  const handleSeek = (value: number[]) => {
    const newTime = value[0]
    setCurrentTime(newTime)
    pausedTimeRef.current = newTime
    if (isPlaying) {
      window.speechSynthesis.cancel()
      speak()
    }
  }

  const toggleMute = () => {
    setIsMuted(!isMuted)
    if (utteranceRef.current) {
      utteranceRef.current.volume = isMuted ? volume : 0
    }
  }

  const handleVolumeChange = (value: number[]) => {
    const newVolume = value[0]
    setVolume(newVolume)
    setIsMuted(newVolume === 0)
    if (utteranceRef.current) {
      utteranceRef.current.volume = newVolume
    }
  }

  const formatTime = (time: number) => {
    const minutes = Math.floor(time / 60)
    const seconds = Math.floor(time % 60)
    return `${minutes}:${seconds.toString().padStart(2, "0")}`
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      window.speechSynthesis.cancel()
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [])

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0

  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card p-4 backdrop-blur-sm",
        className
      )}
    >
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/20">
            <Volume2 className="h-4 w-4 text-primary" />
          </div>
          <div>
            <p className="text-sm font-medium text-foreground">Voice Response</p>
            <p className="text-xs text-muted-foreground">
              {formatTime(currentTime)} / {formatTime(duration)}
            </p>
          </div>
        </div>
        {onClose && (
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Waveform Visualization */}
      <div className="mb-4 flex h-16 items-center justify-center gap-0.5 rounded-lg bg-background/50 px-4">
        {waveformData.map((height, index) => {
          const isActive = (index / waveformData.length) * 100 <= progress
          return (
            <div
              key={`bar-${index}`}
              className={cn(
                "w-1 rounded-full transition-all duration-150",
                isActive ? "bg-primary" : "bg-muted-foreground/30"
              )}
              style={{
                height: `${height * 100}%`,
                transform: isPlaying && isActive ? "scaleY(1.1)" : "scaleY(1)",
              }}
            />
          )
        })}
      </div>

      {/* Progress Slider */}
      <div className="mb-4">
        <Slider
          value={[currentTime]}
          max={duration}
          step={0.1}
          onValueChange={handleSeek}
          className="cursor-pointer"
        />
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleMute}
            className="h-9 w-9 text-muted-foreground hover:text-foreground"
          >
            {isMuted ? (
              <VolumeX className="h-4 w-4" />
            ) : (
              <Volume2 className="h-4 w-4" />
            )}
          </Button>
          <div className="w-20">
            <Slider
              value={[isMuted ? 0 : volume]}
              max={1}
              step={0.1}
              onValueChange={handleVolumeChange}
              className="cursor-pointer"
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={skipBackward}
            className="h-9 w-9 text-muted-foreground hover:text-foreground"
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
          <Button
            onClick={togglePlay}
            className="h-12 w-12 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {isPlaying ? (
              <Pause className="h-5 w-5" />
            ) : (
              <Play className="h-5 w-5 ml-0.5" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={skipForward}
            className="h-9 w-9 text-muted-foreground hover:text-foreground"
          >
            <RotateCw className="h-4 w-4" />
          </Button>
        </div>

        <div className="w-24 text-right">
          <span className="text-xs text-muted-foreground">
            {text.split(/\s+/).length} words
          </span>
        </div>
      </div>
    </div>
  )
}
