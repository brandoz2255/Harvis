"use client"

import type React from "react"

import { useState, useRef, useEffect } from "react"
import { Play, Pause } from "lucide-react"
import { Button } from "@/components/ui/button"

interface AudioWaveformProps {
  audioUrl: string
  duration?: number
}

export function AudioWaveform({ audioUrl, duration: propDuration }: AudioWaveformProps) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(propDuration || 0)
  const [waveformBars, setWaveformBars] = useState<number[]>([])
  const audioRef = useRef<HTMLAudioElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Update duration if prop changes
  useEffect(() => {
    if (propDuration) setDuration(propDuration)
  }, [propDuration])

  // Generate realistic waveform bars
  useEffect(() => {
    const bars = Array.from({ length: 40 }, () => {
      return Math.random() * 100
    })
    setWaveformBars(bars)
  }, [])

  const handlePlayPause = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause()
      } else {
        audioRef.current.play()
      }
      setIsPlaying(!isPlaying)
    }
  }

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime)
    }
  }

  const handleLoadedMetadata = () => {
    if (audioRef.current && !propDuration) {
      setDuration(audioRef.current.duration)
    }
  }

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!duration) return
    const rect = e.currentTarget.getBoundingClientRect()
    const percent = (e.clientX - rect.left) / rect.width
    const newTime = percent * duration

    if (audioRef.current) {
      audioRef.current.currentTime = newTime
      setCurrentTime(newTime)
    }
  }

  const handleEnded = () => {
    setIsPlaying(false)
    setCurrentTime(0)
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, "0")}`
  }

  const progress = (currentTime / duration) * 100

  return (
    <div className="mt-3 pt-3 border-t border-border/50">
      <audio 
        ref={audioRef} 
        src={audioUrl} 
        onTimeUpdate={handleTimeUpdate} 
        onEnded={handleEnded}
        onLoadedMetadata={handleLoadedMetadata}
      />

      {/* Play Controls */}
      <div className="flex items-center gap-3">
        <Button
          onClick={handlePlayPause}
          size="sm"
          className="bg-blue-500 hover:bg-blue-600 text-white p-1 h-auto w-auto"
        >
          {isPlaying ? <Pause size={16} /> : <Play size={16} />}
        </Button>

        {/* Waveform Visualization */}
        <div
          className="flex-1 flex items-center gap-px h-8 px-2 bg-black/20 rounded cursor-pointer group"
          onClick={handleSeek}
        >
          {waveformBars.map((bar, idx) => {
            const isActive = (idx / waveformBars.length) * 100 <= progress
            return (
              <div
                key={idx}
                className={`flex-1 rounded-full transition-all ${
                  isActive ? "bg-blue-400 group-hover:bg-blue-300" : "bg-blue-500/30 group-hover:bg-blue-400/50"
                }`}
                style={{
                  height: `${20 + (bar / 100) * 60}%`,
                }}
              />
            )
          })}
        </div>

        {/* Time Display */}
        <span className="text-xs font-mono text-muted-foreground whitespace-nowrap">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
      </div>
    </div>
  )
}
