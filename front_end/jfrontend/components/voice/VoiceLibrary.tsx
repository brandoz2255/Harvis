'use client'

import { useState, useEffect, useRef } from 'react'
import {
  Mic,
  MicOff,
  Play,
  Pause,
  Trash2,
  Upload,
  Loader2,
  Volume2,
  User,
  Star,
  Sparkles,
  Globe,
  Book,
  BookOpen,
  Smile,
  Zap,
  Plus,
  X,
  Check,
  AlertCircle,
  ChevronDown
} from 'lucide-react'
import { useVoiceStore, Voice, VoicePreset } from '@/stores/voiceStore'

interface VoiceLibraryProps {
  onSelect?: (voice: Voice) => void
  selectedVoiceId?: string
  showCloneButton?: boolean
  showPresets?: boolean
  compact?: boolean
  filterCategory?: string
}

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  narrator: <Globe className="w-4 h-4" />,
  host: <User className="w-4 h-4" />,
  character: <Zap className="w-4 h-4" />,
  educator: <Book className="w-4 h-4" />,
  storyteller: <BookOpen className="w-4 h-4" />,
  user: <Mic className="w-4 h-4" />,
  general: <Smile className="w-4 h-4" />
}

export default function VoiceLibrary({
  onSelect,
  selectedVoiceId,
  showCloneButton = true,
  showPresets = true,
  compact = false,
  filterCategory
}: VoiceLibraryProps) {
  const {
    voices,
    presets,
    isLoading,
    isCloning,
    error,
    serviceAvailable,
    fetchVoices,
    fetchPresets,
    cloneVoice,
    deleteVoice,
    activatePreset,
    clearError
  } = useVoiceStore()

  const [showCloneDialog, setShowCloneDialog] = useState(false)
  const [showActivateDialog, setShowActivateDialog] = useState<string | null>(null)
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  // Clone form state
  const [cloneName, setCloneName] = useState('')
  const [cloneDescription, setCloneDescription] = useState('')
  const [cloneFile, setCloneFile] = useState<File | null>(null)
  const [activateFile, setActivateFile] = useState<File | null>(null)

  useEffect(() => {
    fetchVoices()
    if (showPresets) {
      fetchPresets()
    }
  }, [fetchVoices, fetchPresets, showPresets])

  // Filter voices
  const filteredVoices = filterCategory
    ? voices.filter(v => v.category === filterCategory || v.voice_type === 'user')
    : voices

  const userVoices = filteredVoices.filter(v => v.voice_type === 'user')
  const builtInVoices = filteredVoices.filter(v => v.voice_type === 'builtin')

  // Play voice sample
  const playVoiceSample = async (voiceId: string) => {
    if (playingVoiceId === voiceId) {
      audioRef.current?.pause()
      setPlayingVoiceId(null)
      return
    }

    try {
      if (audioRef.current) {
        audioRef.current.pause()
      }

      const audio = new Audio(`/api/tts/voices/${voiceId}/sample`)
      audioRef.current = audio
      
      audio.onended = () => setPlayingVoiceId(null)
      audio.onerror = () => setPlayingVoiceId(null)
      
      await audio.play()
      setPlayingVoiceId(voiceId)
    } catch (err) {
      console.error('Failed to play voice sample:', err)
      setPlayingVoiceId(null)
    }
  }

  // Handle voice cloning
  const handleClone = async () => {
    if (!cloneName.trim() || !cloneFile) return

    const voice = await cloneVoice(cloneName, cloneFile, cloneDescription)
    
    if (voice) {
      setShowCloneDialog(false)
      setCloneName('')
      setCloneDescription('')
      setCloneFile(null)
      if (onSelect) {
        onSelect(voice)
      }
    }
  }

  // Handle preset activation
  const handleActivatePreset = async (presetId: string) => {
    if (!activateFile) return

    const success = await activatePreset(presetId, activateFile)
    
    if (success) {
      setShowActivateDialog(null)
      setActivateFile(null)
    }
  }

  // Handle voice deletion
  const handleDelete = async (voiceId: string) => {
    if (confirm('Are you sure you want to delete this voice?')) {
      await deleteVoice(voiceId)
    }
  }

  // Voice card component
  const VoiceCard = ({ voice }: { voice: Voice }) => {
    const isSelected = selectedVoiceId === voice.voice_id
    const isPlaying = playingVoiceId === voice.voice_id
    const isActivated = voice.voice_type === 'user' || voice.activated
    const categoryIcon = CATEGORY_ICONS[voice.category || voice.voice_type] || CATEGORY_ICONS.general

    return (
      <div
        className={`group relative p-4 rounded-xl border transition-all cursor-pointer ${
          isSelected
            ? 'border-violet-500 bg-violet-500/10 ring-2 ring-violet-500/20'
            : 'border-white/10 bg-white/5 hover:border-violet-500/50 hover:bg-white/10'
        } ${!isActivated && voice.voice_type === 'builtin' ? 'opacity-60' : ''}`}
        onClick={() => isActivated && onSelect?.(voice)}
      >
        {/* Badge */}
        <div className="absolute top-2 right-2 flex items-center gap-1">
          {voice.voice_type === 'builtin' && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
              <Star className="w-3 h-3 inline mr-1" />
              Preset
            </span>
          )}
          {isSelected && (
            <span className="p-1 rounded-full bg-violet-500">
              <Check className="w-3 h-3 text-white" />
            </span>
          )}
        </div>

        {/* Icon & Name */}
        <div className="flex items-center gap-3 mb-2">
          <div className={`p-2 rounded-lg ${
            voice.voice_type === 'user' 
              ? 'bg-gradient-to-br from-violet-500/30 to-fuchsia-500/30'
              : 'bg-gradient-to-br from-amber-500/30 to-orange-500/30'
          }`}>
            {categoryIcon}
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="font-medium text-white truncate">{voice.voice_name}</h4>
            <p className="text-xs text-white/50 capitalize">{voice.category || 'Custom'}</p>
          </div>
        </div>

        {/* Description */}
        {voice.description && !compact && (
          <p className="text-sm text-white/60 mb-3 line-clamp-2">{voice.description}</p>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2 mt-3">
          {/* Play button */}
          {isActivated && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                playVoiceSample(voice.voice_id)
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-white/10 hover:bg-white/20 text-white/70 hover:text-white transition-all"
            >
              {isPlaying ? (
                <>
                  <Pause className="w-3 h-3" />
                  Stop
                </>
              ) : (
                <>
                  <Play className="w-3 h-3" />
                  Preview
                </>
              )}
            </button>
          )}

          {/* Activate button for presets */}
          {voice.voice_type === 'builtin' && !voice.activated && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                setShowActivateDialog(voice.voice_id)
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 transition-all"
            >
              <Upload className="w-3 h-3" />
              Activate
            </button>
          )}

          {/* Delete button for user voices */}
          {voice.voice_type === 'user' && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                handleDelete(voice.voice_id)
              }}
              className="ml-auto p-1.5 rounded-lg text-white/40 hover:text-red-400 hover:bg-red-500/20 transition-all opacity-0 group-hover:opacity-100"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}

          {/* Quality score */}
          {voice.quality_score !== undefined && (
            <div className="ml-auto flex items-center gap-1 text-xs text-white/40">
              <Volume2 className="w-3 h-3" />
              {Math.round(voice.quality_score * 100)}%
            </div>
          )}
        </div>
      </div>
    )
  }

  if (isLoading && voices.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-violet-400" />
        <span className="ml-3 text-white/60">Loading voices...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* TTS Service unavailable warning */}
      {!serviceAvailable && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30">
          <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-medium text-amber-400">TTS Service Not Running</p>
            <p className="text-xs text-amber-400/70 mt-1">
              Voice cloning and speech generation require the TTS service to be running.
              Start it with: <code className="bg-amber-500/20 px-1.5 py-0.5 rounded">docker compose up tts-service</code>
            </p>
          </div>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-red-500/10 border border-red-500/30">
          <AlertCircle className="w-5 h-5 text-red-400 shrink-0" />
          <p className="text-sm text-red-400 flex-1">{error}</p>
          <button
            onClick={clearError}
            className="p-1 hover:bg-red-500/20 rounded transition-colors"
          >
            <X className="w-4 h-4 text-red-400" />
          </button>
        </div>
      )}

      {/* Clone Voice Button */}
      {showCloneButton && (
        <button
          onClick={() => setShowCloneDialog(true)}
          className="w-full flex items-center justify-center gap-2 p-4 rounded-xl border-2 border-dashed border-violet-500/30 bg-violet-500/5 hover:bg-violet-500/10 hover:border-violet-500/50 transition-all group"
        >
          <Plus className="w-5 h-5 text-violet-400 group-hover:scale-110 transition-transform" />
          <span className="text-violet-400 font-medium">Clone New Voice</span>
        </button>
      )}

      {/* User Voices */}
      {userVoices.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-white/70 mb-3 flex items-center gap-2">
            <Mic className="w-4 h-4" />
            Your Voices ({userVoices.length})
          </h3>
          <div className={`grid gap-3 ${compact ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'}`}>
            {userVoices.map(voice => (
              <VoiceCard key={voice.voice_id} voice={voice} />
            ))}
          </div>
        </div>
      )}

      {/* Built-in Presets */}
      {showPresets && builtInVoices.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-white/70 mb-3 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-amber-400" />
            Voice Presets ({builtInVoices.length})
          </h3>
          <div className={`grid gap-3 ${compact ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'}`}>
            {builtInVoices.map(voice => (
              <VoiceCard key={voice.voice_id} voice={voice} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {voices.length === 0 && !isLoading && (
        <div className="text-center py-12">
          <MicOff className="w-12 h-12 mx-auto text-white/20 mb-4" />
          <h3 className="text-lg font-medium text-white/70 mb-2">No voices yet</h3>
          <p className="text-sm text-white/50 max-w-md mx-auto">
            Clone your first voice by uploading a 10-60 second audio sample. Higher quality samples produce better results.
          </p>
        </div>
      )}

      {/* Clone Voice Dialog */}
      {showCloneDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-gray-900 rounded-2xl border border-white/10 p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                <Mic className="w-5 h-5 text-violet-400" />
                Clone New Voice
              </h3>
              <button
                onClick={() => setShowCloneDialog(false)}
                className="p-1 hover:bg-white/10 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-white/60" />
              </button>
            </div>

            <div className="space-y-4">
              {/* Name input */}
              <div>
                <label className="block text-sm text-white/70 mb-1.5">Voice Name</label>
                <input
                  type="text"
                  value={cloneName}
                  onChange={e => setCloneName(e.target.value)}
                  placeholder="e.g., My Professional Voice"
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white placeholder-white/30 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none transition-all"
                />
              </div>

              {/* Description input */}
              <div>
                <label className="block text-sm text-white/70 mb-1.5">Description (optional)</label>
                <textarea
                  value={cloneDescription}
                  onChange={e => setCloneDescription(e.target.value)}
                  placeholder="Describe the voice characteristics..."
                  rows={2}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white placeholder-white/30 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none transition-all resize-none"
                />
              </div>

              {/* File upload */}
              <div>
                <label className="block text-sm text-white/70 mb-1.5">Audio Sample (10-60 seconds)</label>
                <div className="relative">
                  <input
                    type="file"
                    accept="audio/*"
                    onChange={e => setCloneFile(e.target.files?.[0] || null)}
                    className="absolute inset-0 opacity-0 cursor-pointer"
                  />
                  <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed transition-all ${
                    cloneFile ? 'border-violet-500 bg-violet-500/10' : 'border-white/20 bg-white/5 hover:border-white/40'
                  }`}>
                    {cloneFile ? (
                      <>
                        <Check className="w-5 h-5 text-violet-400" />
                        <span className="text-sm text-white truncate flex-1">{cloneFile.name}</span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setCloneFile(null)
                          }}
                          className="p-1 hover:bg-white/10 rounded"
                        >
                          <X className="w-4 h-4 text-white/60" />
                        </button>
                      </>
                    ) : (
                      <>
                        <Upload className="w-5 h-5 text-white/40" />
                        <span className="text-sm text-white/50">Click to upload or drag & drop</span>
                      </>
                    )}
                  </div>
                </div>
                <p className="text-xs text-white/40 mt-1.5">
                  Supported: WAV, MP3, M4A, OGG, FLAC. Higher quality = better results.
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-white/10">
              <button
                onClick={() => setShowCloneDialog(false)}
                className="px-4 py-2 text-sm text-white/60 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleClone}
                disabled={!cloneName.trim() || !cloneFile || isCloning}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white font-medium hover:from-violet-500 hover:to-fuchsia-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                {isCloning ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Cloning...
                  </>
                ) : (
                  <>
                    <Mic className="w-4 h-4" />
                    Clone Voice
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Activate Preset Dialog */}
      {showActivateDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-gray-900 rounded-2xl border border-white/10 p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-amber-400" />
                Activate Voice Preset
              </h3>
              <button
                onClick={() => {
                  setShowActivateDialog(null)
                  setActivateFile(null)
                }}
                className="p-1 hover:bg-white/10 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-white/60" />
              </button>
            </div>

            <p className="text-sm text-white/60 mb-4">
              To activate this preset, upload a 10-60 second audio sample that matches the voice style you want to recreate.
            </p>

            {/* File upload */}
            <div>
              <label className="block text-sm text-white/70 mb-1.5">Reference Audio</label>
              <div className="relative">
                <input
                  type="file"
                  accept="audio/*"
                  onChange={e => setActivateFile(e.target.files?.[0] || null)}
                  className="absolute inset-0 opacity-0 cursor-pointer"
                />
                <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed transition-all ${
                  activateFile ? 'border-amber-500 bg-amber-500/10' : 'border-white/20 bg-white/5 hover:border-white/40'
                }`}>
                  {activateFile ? (
                    <>
                      <Check className="w-5 h-5 text-amber-400" />
                      <span className="text-sm text-white truncate flex-1">{activateFile.name}</span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          setActivateFile(null)
                        }}
                        className="p-1 hover:bg-white/10 rounded"
                      >
                        <X className="w-4 h-4 text-white/60" />
                      </button>
                    </>
                  ) : (
                    <>
                      <Upload className="w-5 h-5 text-white/40" />
                      <span className="text-sm text-white/50">Upload reference audio</span>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-white/10">
              <button
                onClick={() => {
                  setShowActivateDialog(null)
                  setActivateFile(null)
                }}
                className="px-4 py-2 text-sm text-white/60 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleActivatePreset(showActivateDialog)}
                disabled={!activateFile || isCloning}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 text-white font-medium hover:from-amber-400 hover:to-orange-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                {isCloning ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Activating...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Activate Preset
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
