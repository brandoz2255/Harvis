'use client'

import { useEffect, useState, useRef } from 'react'
import { useUser } from '@/lib/auth/UserProvider'
import { useVoiceStore, Voice, GenerationSettings } from '@/stores/voiceStore'
import VoiceLibrary from '@/components/voice/VoiceLibrary'
import {
  Mic,
  Volume2,
  Play,
  Pause,
  Loader2,
  Settings2,
  Sparkles,
  Wand2,
  Download,
  ChevronDown,
  AudioWaveform,
  Headphones,
  RefreshCw
} from 'lucide-react'

const DEMO_TEXTS = [
  "Welcome to Voice Studio! Here you can clone any voice and generate natural-sounding speech.",
  "The quick brown fox jumps over the lazy dog. This pangram contains every letter of the alphabet.",
  "In a world where technology and creativity intersect, we find new ways to express ourselves.",
  "Let me tell you a story about innovation, perseverance, and the power of imagination.",
  "Breaking news: Scientists have discovered a remarkable new species in the depths of the ocean."
]

export default function NotebookVoicesPage() {
  const { user, isLoading: authLoading } = useUser()
  const {
    voices,
    isLoading,
    isGenerating,
    error,
    fetchVoices,
    generateSpeech,
    clearError
  } = useVoiceStore()

  // State
  const [selectedVoice, setSelectedVoice] = useState<Voice | null>(null)
  const [testText, setTestText] = useState(DEMO_TEXTS[0])
  const [showSettings, setShowSettings] = useState(false)
  const [settings, setSettings] = useState<GenerationSettings>({
    cfg_scale: 1.3,
    inference_steps: 10,
    temperature: 0.7
  })
  const [generatedAudioUrl, setGeneratedAudioUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [audioDuration, setAudioDuration] = useState<number | null>(null)
  const [audioProgress, setAudioProgress] = useState(0)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const progressIntervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (!authLoading && user) {
      fetchVoices()
    }
  }, [authLoading, user, fetchVoices])

  // Clean up audio on unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current)
      }
    }
  }, [])

  // Generate speech
  const handleGenerateSpeech = async () => {
    if (!selectedVoice || !testText.trim()) return

    // Stop current audio
    if (audioRef.current) {
      audioRef.current.pause()
      setIsPlaying(false)
    }

    const result = await generateSpeech(testText, selectedVoice.voice_id, settings)

    if (result?.success && result.audio_url) {
      setGeneratedAudioUrl(result.audio_url)
      setAudioDuration(result.duration || null)
      setAudioProgress(0)
    }
  }

  // Play/pause generated audio
  const togglePlayback = async () => {
    if (!generatedAudioUrl) return

    if (isPlaying && audioRef.current) {
      audioRef.current.pause()
      setIsPlaying(false)
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current)
      }
      return
    }

    try {
      if (!audioRef.current || audioRef.current.src !== generatedAudioUrl) {
        audioRef.current = new Audio(`/api/tts${generatedAudioUrl}`)

        audioRef.current.onended = () => {
          setIsPlaying(false)
          setAudioProgress(0)
          if (progressIntervalRef.current) {
            clearInterval(progressIntervalRef.current)
          }
        }

        audioRef.current.onloadedmetadata = () => {
          if (audioRef.current) {
            setAudioDuration(audioRef.current.duration)
          }
        }
      }

      await audioRef.current.play()
      setIsPlaying(true)

      // Update progress
      progressIntervalRef.current = setInterval(() => {
        if (audioRef.current) {
          const progress = (audioRef.current.currentTime / audioRef.current.duration) * 100
          setAudioProgress(progress)
        }
      }, 100)
    } catch (err) {
      console.error('Failed to play audio:', err)
      setIsPlaying(false)
    }
  }

  // Download generated audio
  const handleDownload = () => {
    if (!generatedAudioUrl) return

    const link = document.createElement('a')
    link.href = `/api/tts${generatedAudioUrl}`
    link.download = `voice-studio-${Date.now()}.wav`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // Random demo text
  const randomizeText = () => {
    const currentIndex = DEMO_TEXTS.indexOf(testText)
    const newIndex = (currentIndex + 1) % DEMO_TEXTS.length
    setTestText(DEMO_TEXTS[newIndex])
  }

  if (authLoading) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-[#0a0a0a]">
        <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
      </div>
    )
  }

  const activatedVoices = voices.filter(v => v.voice_type === 'user' || v.activated)

  return (
    <div className="h-full w-full overflow-y-auto p-6 bg-[#0a0a0a]">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold text-white flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-gradient-to-br from-violet-600 to-fuchsia-600 shadow-lg shadow-violet-500/20">
                <Mic className="w-5 h-5 text-white" />
              </div>
              Voice Studio
            </h1>
            <p className="text-sm text-gray-400 mt-1">
              Clone voices & generate speech for your podcasts
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm text-gray-400">
            {activatedVoices.length} voice{activatedVoices.length !== 1 ? 's' : ''} available
          </div>
        </div>

        {/* Development Warning */}
        <div className="mb-6 bg-gradient-to-r from-blue-600/10 to-cyan-600/10 border border-blue-500/20 rounded-xl p-4 flex items-center gap-4">
          <div className="p-2 bg-blue-500/20 rounded-lg">
            <Sparkles className="w-5 h-5 text-blue-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-medium text-blue-400">Voice Studio Under Construction</h3>
            <p className="text-sm text-blue-300/70 mt-0.5">
              We are currently upgrading our voice cloning engine. Some features may be experimental or unavailable.
              Podcasts are currently restricted to the default Harvis voice.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Voice Library - Left Column */}
          <div className="lg:col-span-3">
            <div className="bg-gray-900/50 rounded-xl border border-gray-800 p-5">
              <h2 className="text-base font-medium text-white mb-5 flex items-center gap-2">
                <Headphones className="w-4 h-4 text-blue-400" />
                Voice Library
              </h2>

              <VoiceLibrary
                onSelect={setSelectedVoice}
                selectedVoiceId={selectedVoice?.voice_id}
                showCloneButton={true}
                showPresets={true}
              />
            </div>
          </div>

          {/* Text-to-Speech Panel - Right Column */}
          <div className="lg:col-span-2">
            <div className="sticky top-6 space-y-5">
              {/* Voice Preview Card */}
              <div className="bg-gray-900/50 rounded-xl border border-gray-800 p-5">
                <h2 className="text-base font-medium text-white mb-4 flex items-center gap-2">
                  <Wand2 className="w-4 h-4 text-fuchsia-400" />
                  Text-to-Speech
                </h2>

                {/* Selected Voice */}
                {selectedVoice ? (
                  <div className="mb-4 p-3 rounded-lg bg-violet-500/10 border border-violet-500/30">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-violet-500/20">
                        <Mic className="w-4 h-4 text-violet-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-white truncate text-sm">{selectedVoice.voice_name}</p>
                        <p className="text-xs text-gray-400 capitalize">{selectedVoice.category || 'Custom Voice'}</p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="mb-4 p-4 rounded-lg bg-gray-800/50 border border-dashed border-gray-700 text-center">
                    <p className="text-sm text-gray-500">Select a voice from the library to begin</p>
                  </div>
                )}

                {/* Text Input */}
                <div className="mb-4">
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm text-gray-400">Text to synthesize</label>
                    <button
                      onClick={randomizeText}
                      className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
                    >
                      <RefreshCw className="w-3 h-3" />
                      Random
                    </button>
                  </div>
                  <textarea
                    value={testText}
                    onChange={e => setTestText(e.target.value)}
                    placeholder="Enter text to generate speech..."
                    rows={4}
                    className="w-full px-3 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white placeholder-gray-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all resize-none text-sm"
                  />
                  <p className="text-xs text-gray-500 mt-1">{testText.length} characters</p>
                </div>

                {/* Generation Settings */}
                <div className="mb-4">
                  <button
                    onClick={() => setShowSettings(!showSettings)}
                    className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
                  >
                    <Settings2 className="w-4 h-4" />
                    Advanced Settings
                    <ChevronDown className={`w-4 h-4 transition-transform ${showSettings ? 'rotate-180' : ''}`} />
                  </button>

                  {showSettings && (
                    <div className="mt-3 p-4 rounded-lg bg-gray-800/50 space-y-4">
                      {/* CFG Scale */}
                      <div>
                        <div className="flex items-center justify-between mb-1.5">
                          <label className="text-xs text-gray-400">CFG Scale</label>
                          <span className="text-xs text-blue-400">{settings.cfg_scale.toFixed(1)}</span>
                        </div>
                        <input
                          type="range"
                          min="0.5"
                          max="3"
                          step="0.1"
                          value={settings.cfg_scale}
                          onChange={e => setSettings(s => ({ ...s, cfg_scale: parseFloat(e.target.value) }))}
                          className="w-full accent-blue-500"
                        />
                      </div>

                      {/* Temperature */}
                      <div>
                        <div className="flex items-center justify-between mb-1.5">
                          <label className="text-xs text-gray-400">Temperature</label>
                          <span className="text-xs text-blue-400">{settings.temperature.toFixed(1)}</span>
                        </div>
                        <input
                          type="range"
                          min="0.1"
                          max="1.5"
                          step="0.1"
                          value={settings.temperature}
                          onChange={e => setSettings(s => ({ ...s, temperature: parseFloat(e.target.value) }))}
                          className="w-full accent-blue-500"
                        />
                      </div>

                      {/* Inference Steps */}
                      <div>
                        <div className="flex items-center justify-between mb-1.5">
                          <label className="text-xs text-gray-400">Inference Steps</label>
                          <span className="text-xs text-blue-400">{settings.inference_steps}</span>
                        </div>
                        <input
                          type="range"
                          min="5"
                          max="50"
                          step="5"
                          value={settings.inference_steps}
                          onChange={e => setSettings(s => ({ ...s, inference_steps: parseInt(e.target.value) }))}
                          className="w-full accent-blue-500"
                        />
                      </div>
                    </div>
                  )}
                </div>

                {/* Generate Button */}
                <button
                  onClick={handleGenerateSpeech}
                  disabled={!selectedVoice || !testText.trim() || isGenerating}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-all text-sm"
                >
                  {isGenerating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" />
                      Generate Speech
                    </>
                  )}
                </button>
              </div>

              {/* Audio Player */}
              {generatedAudioUrl && (
                <div className="bg-gray-900/50 rounded-xl border border-gray-800 p-5">
                  <h3 className="text-sm font-medium text-gray-300 mb-4 flex items-center gap-2">
                    <AudioWaveform className="w-4 h-4 text-emerald-400" />
                    Generated Audio
                  </h3>

                  {/* Waveform visualization placeholder */}
                  <div className="relative mb-4 h-14 rounded-lg bg-gray-800/50 overflow-hidden">
                    <div className="absolute inset-0 flex items-center justify-center gap-1">
                      {Array.from({ length: 40 }).map((_, i) => (
                        <div
                          key={i}
                          className="w-1 bg-gradient-to-t from-blue-500 to-cyan-500 rounded-full transition-all"
                          style={{
                            height: `${Math.sin(i * 0.3) * 30 + 40}%`,
                            opacity: i / 40 < audioProgress / 100 ? 1 : 0.3
                          }}
                        />
                      ))}
                    </div>

                    {/* Progress overlay */}
                    <div
                      className="absolute inset-y-0 left-0 bg-gradient-to-r from-blue-500/20 to-transparent pointer-events-none"
                      style={{ width: `${audioProgress}%` }}
                    />
                  </div>

                  {/* Duration */}
                  {audioDuration && (
                    <div className="flex items-center justify-between text-xs text-gray-500 mb-4">
                      <span>{Math.floor(audioProgress / 100 * audioDuration)}s</span>
                      <span>{audioDuration.toFixed(1)}s</span>
                    </div>
                  )}

                  {/* Controls */}
                  <div className="flex items-center justify-center gap-3">
                    <button
                      onClick={togglePlayback}
                      className="flex items-center justify-center w-10 h-10 rounded-full bg-blue-600 hover:bg-blue-700 text-white transition-all"
                    >
                      {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
                    </button>

                    <button
                      onClick={handleDownload}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white transition-all text-sm"
                    >
                      <Download className="w-4 h-4" />
                      Download
                    </button>
                  </div>
                </div>
              )}

              {/* Tips Card */}
              <div className="bg-gradient-to-br from-blue-500/10 to-cyan-500/10 rounded-xl border border-blue-500/20 p-4">
                <h3 className="text-sm font-medium text-white mb-2 flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-amber-400" />
                  Pro Tips
                </h3>
                <ul className="space-y-1.5 text-xs text-gray-400">
                  <li className="flex items-start gap-2">
                    <span className="text-blue-400">•</span>
                    Use 10-60 second audio samples for best cloning quality
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-blue-400">•</span>
                    Clear recordings without background noise work best
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-blue-400">•</span>
                    Higher CFG scale = more adherence to the reference voice
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
