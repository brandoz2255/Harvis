'use client'

import { useState, useEffect } from 'react'
import { useNotebookStore, type NotebookSource, type NotebookNote } from '@/stores/notebookStore'
import { useNotebookPluginStore } from '@/stores/notebookPluginStore'
// Voice store available for future custom voice configuration
// import { useVoiceStore } from '@/stores/voiceStore'
import OpenNotebookAPI, { type Podcast, type PodcastConfig } from '@/lib/openNotebookApi'
import { AudioWaveform } from '@/components/ui/audio-waveform'
import {
  Mic, Loader2, Users, Clock,
  MessageSquare, BookOpen, GraduationCap, Coffee, Sword,
  Download, Trash2, Check, ChevronDown,
  FileText, StickyNote, AlertCircle, Headphones,
  Volume2, Edit3, X, Wand2
} from 'lucide-react'

const PODCAST_STYLES = [
  { id: 'conversational', name: 'Casual', icon: <Coffee className="w-3 h-3" /> },
  { id: 'interview', name: 'Interview', icon: <MessageSquare className="w-3 h-3" /> },
  { id: 'educational', name: 'Lecture', icon: <GraduationCap className="w-3 h-3" /> },
  { id: 'debate', name: 'Debate', icon: <Sword className="w-3 h-3" /> },
  { id: 'storytelling', name: 'Story', icon: <BookOpen className="w-3 h-3" /> },
]

const SPEAKER_COLORS = [
  'bg-violet-500/20 text-violet-300 border-violet-500/30',
  'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  'bg-amber-500/20 text-amber-300 border-amber-500/30',
  'bg-sky-500/20 text-sky-300 border-sky-500/30',
]
const DEFAULT_SPEAKER_NAMES = ['Host', 'Guest', 'Speaker 3', 'Speaker 4']

type GenerationStep = 'outline' | 'script' | 'audio' | null

interface SpeakerDraft {
  name: string; role?: string; personality?: string; rvc_voice_id?: string
  voice_model_name?: string; voice_model_url?: string
}

interface VoiceModelEntry {
  name: string
  page_url: string
  download_url: string
  run_url?: string
}

interface PodcastStudioProps {
  notebookId: string
  notebookTitle: string
  sources: NotebookSource[]
  notes: NotebookNote[]
  compact?: boolean
}

export default function PodcastStudio({
  notebookId, notebookTitle, sources, notes, compact = false,
}: PodcastStudioProps) {
  const { podcasts, isLoadingPodcasts, fetchPodcasts, deletePodcast } = useNotebookStore()


  const [title, setTitle] = useState(`${notebookTitle} Podcast`)
  const [style, setStyle] = useState('conversational')
  const [speakers, setSpeakers] = useState(2)
  const [duration, setDuration] = useState(10)
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set())
  const [selectedNotes, setSelectedNotes] = useState<Set<string>>(new Set())
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationStep, setGenerationStep] = useState<GenerationStep>(null)
  const [generationMessage, setGenerationMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [generateAudio, setGenerateAudio] = useState(true)
  const [expandedSection, setExpandedSection] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'generate' | 'library'>('generate')
  const [expandedPodcast, setExpandedPodcast] = useState<string | null>(null)

  const [speakerDrafts, setSpeakerDrafts] = useState<SpeakerDraft[]>([
    { name: 'Host', role: 'Host' }, { name: 'Guest', role: 'Guest' },
  ])

  const [showScriptEditor, setShowScriptEditor] = useState(false)
  const [draftPodcastId, setDraftPodcastId] = useState<string | null>(null)
  const [draftTranscript, setDraftTranscript] = useState<Array<{ speaker: string; dialogue: string }>>([])
  const [isGeneratingAudioFromDraft, setIsGeneratingAudioFromDraft] = useState(false)

  const [voiceModels, setVoiceModels] = useState<VoiceModelEntry[]>([])
  const [isLoadingVoiceModels, setIsLoadingVoiceModels] = useState(false)
  const [voiceModelsError, setVoiceModelsError] = useState<string | null>(null)
  const [voiceSearchQuery, setVoiceSearchQuery] = useState('')
  const [voicePickerSpeakerIdx, setVoicePickerSpeakerIdx] = useState<number | null>(null)

  const readySources = sources.filter(s => s.status === 'ready')
  const totalSelected = selectedSources.size + selectedNotes.size

  // Voice fetching removed - using Harvis default voice via Chatterbox
  useEffect(() => { if (notebookId) fetchPodcasts(notebookId) }, [notebookId])

  useEffect(() => {
    if (selectedSources.size === 0 && readySources.length > 0)
      setSelectedSources(new Set(readySources.map(s => s.id)))
  }, [readySources.length])

  useEffect(() => {
    if (selectedNotes.size === 0 && notes.length > 0)
      setSelectedNotes(new Set(notes.map(n => n.id)))
  }, [notes.length])

  useEffect(() => {
    setSpeakerDrafts(prev => {
      const next = [...prev]
      for (let i = prev.length; i < speakers; i++)
        next.push({ name: DEFAULT_SPEAKER_NAMES[i] || `Speaker ${i + 1}`, role: 'Speaker' })
      return next.slice(0, speakers)
    })
  }, [speakers])

  const fetchVoiceModels = async () => {
    if (voiceModels.length > 0) return
    setIsLoadingVoiceModels(true)
    setVoiceModelsError(null)
    try {
      const res = await fetch('/api/voice-models/browse')
      const data = await res.json()
      if (data.status === 'error') {
        setVoiceModelsError(data.error || 'Website unavailable')
        setVoiceModels([])
      } else {
        setVoiceModels(data.models || [])
        if (data.stale) setVoiceModelsError('Showing cached results (website may be down)')
      }
    } catch {
      setVoiceModelsError('Voice model website is currently unavailable. Using default Harvis voice.')
      setVoiceModels([])
    } finally {
      setIsLoadingVoiceModels(false)
    }
  }

  const handleSelectVoiceModel = (speakerIdx: number, model: VoiceModelEntry) => {
    setSpeakerDrafts(prev => {
      const next = [...prev]
      next[speakerIdx] = {
        ...next[speakerIdx],
        voice_model_name: model.name,
        voice_model_url: model.download_url,
      }
      return next
    })
    setVoicePickerSpeakerIdx(null)
    setVoiceSearchQuery('')
  }

  const handleClearVoiceModel = (speakerIdx: number) => {
    setSpeakerDrafts(prev => {
      const next = [...prev]
      next[speakerIdx] = {
        ...next[speakerIdx],
        voice_model_name: undefined,
        voice_model_url: undefined,
      }
      return next
    })
  }

  const filteredVoiceModels = voiceSearchQuery.trim()
    ? voiceModels.filter(m => m.name.toLowerCase().includes(voiceSearchQuery.toLowerCase()))
    : voiceModels

  const toggleSection = (section: string) =>
    setExpandedSection(prev => prev === section ? null : section)

  const toggleSource = (id: string) => {
    const s = new Set(selectedSources); s.has(id) ? s.delete(id) : s.add(id); setSelectedSources(s)
  }
  const toggleNote = (id: string) => {
    const s = new Set(selectedNotes); s.has(id) ? s.delete(id) : s.add(id); setSelectedNotes(s)
  }

  const handleGenerate = async () => {
    if (!title.trim() || totalSelected === 0) return
    setIsGenerating(true)
    setGenerationStep('outline')
    setGenerationMessage('Starting podcast generation...')
    setError(null)
    setShowScriptEditor(false)

    try {
      const customSpeakers = speakerDrafts.map((d, i) => ({
        name: (d.name || DEFAULT_SPEAKER_NAMES[i] || `Speaker ${i + 1}`).trim(),
        role: (d.role || 'Speaker').trim(),
        personality: (d.personality || '').trim() || undefined,
        rvc_voice_id: d.rvc_voice_id || undefined,
        voice_model_name: d.voice_model_name || undefined,
        voice_model_url: d.voice_model_url || undefined,
      }))

      const requestBody: PodcastConfig & { generate_audio?: boolean; custom_speakers?: any[] } = {
        notebook_id: notebookId,
        title: title.trim(),
        style, speakers,
        duration_minutes: duration,
        source_ids: selectedSources.size > 0 ? Array.from(selectedSources) : undefined,
        note_ids: selectedNotes.size > 0 ? Array.from(selectedNotes) : undefined,
        generate_audio: generateAudio,
        custom_speakers: customSpeakers,
      }

      const response = await OpenNotebookAPI.podcasts.generateStream(requestBody as any)
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      if (!reader) throw new Error('Failed to read stream')

      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEvent = '', currentData = ''
        for (const line of lines) {
          if (line.startsWith('event:')) currentEvent = line.slice(6).trim()
          else if (line.startsWith('data:')) currentData = line.slice(5).trim()
          else if (line === '' && currentData) {
            try {
              const eventData = JSON.parse(currentData)
              if (currentEvent === 'progress') {
                setGenerationStep(eventData.step as GenerationStep)
                setGenerationMessage(eventData.message || '')
              } else if (currentEvent === 'result') {
                fetchPodcasts(notebookId)
                setActiveTab('library')
                if (eventData?.status === 'script_only' && Array.isArray(eventData?.transcript)) {
                  setDraftPodcastId(eventData.id)
                  setDraftTranscript(eventData.transcript)
                  setShowScriptEditor(true)
                }
              } else if (currentEvent === 'error') {
                throw new Error(eventData.error || 'Generation failed')
              }
            } catch (parseError) {
              if (parseError instanceof Error && parseError.message !== 'Generation failed')
                console.error('SSE parse error:', parseError)
              else throw parseError
            }
            currentEvent = ''; currentData = ''
          }
        }
      }
    } catch (err: any) {
      setError(err.message || 'Failed to generate podcast')
    } finally {
      setIsGenerating(false)
      setGenerationStep(null)
      setGenerationMessage('')
    }
  }

  const handleGenerateAudioFromScript = async () => {
    if (!draftTranscript.length) return
    setIsGeneratingAudioFromDraft(true)
    setError(null)
    try {
      await OpenNotebookAPI.podcasts.generateAudioFromScript({
        podcast_id: draftPodcastId || undefined,
        notebook_id: notebookId,
        title: title.trim(),
        style, speakers, duration_minutes: duration,
        transcript: draftTranscript,
        custom_speakers: speakerDrafts,
      })
      fetchPodcasts(notebookId)
      setShowScriptEditor(false)
      setDraftPodcastId(null)
      setDraftTranscript([])
    } catch (e: any) {
      setError(e.message || 'Failed to generate audio')
    } finally {
      setIsGeneratingAudioFromDraft(false)
    }
  }

  const getAudioUrl = (podcast: Podcast): string | null => {
    if (!podcast.audio_path) return null
    return podcast.audio_path
  }

  const handleDelete = async (podcastId: string) => {
    if (!confirm('Delete this podcast?')) return
    await deletePodcast(podcastId)
  }

  const handleDownload = (podcast: Podcast) => {
    const url = getAudioUrl(podcast)
    if (!url) return
    const a = document.createElement('a')
    a.href = url
    a.download = `${podcast.title || 'podcast'}.wav`
    a.click()
  }

  const formatDuration = (s?: number) => {
    if (!s) return '--:--'
    const m = Math.floor(s / 60)
    return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
  }

  // ─── Script Editor View ─────────────────────────────────────────────
  if (showScriptEditor) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <Edit3 className="w-3.5 h-3.5 text-purple-400" />
            <span className="text-xs font-semibold text-foreground">Edit Script</span>
          </div>
          <button onClick={() => setShowScriptEditor(false)} className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
          {draftTranscript.map((line, i) => (
            <div key={i} className="space-y-0.5">
              <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border ${SPEAKER_COLORS[i % SPEAKER_COLORS.length]}`}>
                {line.speaker}
              </span>
              <textarea value={line.dialogue}
                onChange={e => { const v = e.target.value; setDraftTranscript(p => { const n = [...p]; n[i] = { ...n[i], dialogue: v }; return n }) }}
                rows={2}
                className="w-full px-2 py-1 text-[10px] bg-secondary/50 border border-border rounded text-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>
          ))}
        </div>
        <div className="p-2 border-t border-border shrink-0">
          <button onClick={handleGenerateAudioFromScript}
            disabled={isGeneratingAudioFromDraft || draftTranscript.length === 0}
            className="w-full py-1.5 rounded-lg text-[11px] font-medium bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white hover:from-violet-700 hover:to-fuchsia-700 disabled:opacity-50 flex items-center justify-center gap-2">
            {isGeneratingAudioFromDraft
              ? <><Loader2 className="w-3 h-3 animate-spin" /> Generating Audio...</>
              : <><Volume2 className="w-3 h-3" /> Generate Audio (Harvis Voice)</>}
          </button>
        </div>
      </div>
    )
  }

  // ─── Generate Tab ───────────────────────────────────────────────────
  const generateView = (
    <div className="flex-1 overflow-y-auto">
      <div className="p-3 space-y-3">
        {/* Title */}
        <input type="text" value={title} onChange={e => setTitle(e.target.value)}
          placeholder="Episode title..."
          className="w-full px-2.5 py-1.5 text-xs bg-secondary/50 border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary" />

        {/* Style selector - horizontal pills */}
        <div className="flex flex-wrap gap-1">
          {PODCAST_STYLES.map(s => (
            <button key={s.id} onClick={() => setStyle(s.id)}
              className={`flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium border transition-all ${
                style === s.id
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-border bg-secondary/30 text-muted-foreground hover:text-foreground hover:border-muted-foreground'
              }`}>
              {s.icon} {s.name}
            </button>
          ))}
        </div>

        {/* Speakers + Duration row */}
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="flex items-center gap-1 text-[9px] text-muted-foreground mb-0.5">
              <Users className="w-2.5 h-2.5" /> Speakers
            </label>
            <select value={speakers} onChange={e => setSpeakers(Number(e.target.value))}
              className="w-full px-2 py-1 text-[11px] bg-secondary/50 border border-border rounded text-foreground focus:outline-none focus:ring-1 focus:ring-primary">
              <option value={1}>1 - Mono</option>
              <option value={2}>2 - Dialogue</option>
              <option value={3}>3</option>
              <option value={4}>4</option>
            </select>
          </div>
          <div className="flex-1">
            <label className="flex items-center gap-1 text-[9px] text-muted-foreground mb-0.5">
              <Clock className="w-2.5 h-2.5" /> Length
            </label>
            <select value={duration} onChange={e => setDuration(Number(e.target.value))}
              className="w-full px-2 py-1 text-[11px] bg-secondary/50 border border-border rounded text-foreground focus:outline-none focus:ring-1 focus:ring-primary">
              <option value={5}>~5 min</option>
              <option value={10}>~10 min</option>
              <option value={15}>~15 min</option>
              <option value={20}>~20 min</option>
              <option value={30}>~30 min</option>
            </select>
          </div>
        </div>

        {/* Default voice indicator */}
        <div className="flex items-center gap-2 p-2 rounded-lg bg-gradient-to-r from-violet-500/10 to-fuchsia-500/10 border border-violet-500/20">
          <div className="w-6 h-6 rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center shrink-0">
            <Mic className="w-3 h-3 text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-semibold text-foreground">Harvis Voice</p>
            <p className="text-[9px] text-muted-foreground">Default TTS · Chatterbox engine</p>
          </div>
          <Check className="w-3 h-3 text-violet-400 shrink-0" />
        </div>

        {/* Audio toggle */}
        <label className="flex items-center gap-2 p-1.5 rounded-lg bg-secondary/30 border border-border cursor-pointer">
          <input type="checkbox" checked={generateAudio} onChange={e => setGenerateAudio(e.target.checked)}
            className="rounded border-border bg-secondary text-primary focus:ring-primary w-3.5 h-3.5" />
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-medium text-foreground">Generate audio</p>
            <p className="text-[9px] text-muted-foreground">Off = script only, edit before TTS</p>
          </div>
        </label>

        {/* Collapsible: Speaker Profiles */}
        <div className="border border-border rounded-lg overflow-hidden">
          <button onClick={() => { toggleSection('speakers'); fetchVoiceModels() }}
            className="flex items-center gap-1.5 w-full px-2.5 py-1.5 text-[10px] font-medium text-muted-foreground hover:text-foreground hover:bg-secondary/30">
            <Headphones className="w-3 h-3" />
            <span className="flex-1 text-left">Speaker Profiles</span>
            <ChevronDown className={`w-3 h-3 transition-transform ${expandedSection === 'speakers' ? 'rotate-180' : ''}`} />
          </button>
          {expandedSection === 'speakers' && (
            <div className="px-2.5 pb-2 space-y-2 border-t border-border pt-1.5">
              {speakerDrafts.map((d, i) => (
                <div key={i} className="space-y-1">
                  <div className={`inline-block px-1.5 py-0.5 rounded text-[9px] font-semibold border ${SPEAKER_COLORS[i]}`}>
                    {DEFAULT_SPEAKER_NAMES[i] || `Speaker ${i + 1}`}
                  </div>
                  <input type="text" value={d.name} placeholder="Name..."
                    onChange={e => { const v = e.target.value; setSpeakerDrafts(p => { const n = [...p]; n[i] = { ...n[i], name: v }; return n }) }}
                    className="w-full px-2 py-1 text-[10px] bg-secondary/50 border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none" />

                  {/* Voice model assignment */}
                  {d.voice_model_name ? (
                    <div className="flex items-center gap-1.5 px-2 py-1 bg-emerald-500/10 border border-emerald-500/30 rounded">
                      <Volume2 className="w-2.5 h-2.5 text-emerald-400 shrink-0" />
                      <span className="text-[9px] text-emerald-300 truncate flex-1">{d.voice_model_name}</span>
                      <button onClick={() => handleClearVoiceModel(i)}
                        className="p-0.5 rounded text-muted-foreground hover:text-destructive shrink-0">
                        <X className="w-2.5 h-2.5" />
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => { setVoicePickerSpeakerIdx(voicePickerSpeakerIdx === i ? null : i); fetchVoiceModels() }}
                      className="w-full flex items-center gap-1 px-2 py-1 text-[10px] text-primary bg-primary/10 border border-primary/30 rounded hover:bg-primary/20 transition-colors"
                    >
                      <Headphones className="w-2.5 h-2.5" />
                      {voicePickerSpeakerIdx === i ? 'Close voice picker' : 'Browse voice models'}
                    </button>
                  )}

                  {/* Inline voice model picker */}
                  {voicePickerSpeakerIdx === i && (
                    <div className="border border-border rounded-lg bg-secondary/30 overflow-hidden">
                      <div className="px-2 py-1 border-b border-border">
                        <input
                          type="text"
                          value={voiceSearchQuery}
                          onChange={e => setVoiceSearchQuery(e.target.value)}
                          placeholder="Search voice models..."
                          className="w-full px-1.5 py-0.5 text-[10px] bg-secondary/50 border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                        />
                      </div>

                      {isLoadingVoiceModels ? (
                        <div className="flex items-center justify-center gap-1.5 p-3">
                          <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />
                          <span className="text-[9px] text-muted-foreground">Loading voice models...</span>
                        </div>
                      ) : voiceModelsError && voiceModels.length === 0 ? (
                        <div className="p-2 space-y-1.5">
                          <div className="flex items-start gap-1.5 text-[9px] text-yellow-400">
                            <AlertCircle className="w-3 h-3 shrink-0 mt-0.5" />
                            <span>{voiceModelsError}</span>
                          </div>
                          <div className="flex items-center gap-1.5 px-2 py-1 bg-violet-500/10 border border-violet-500/20 rounded">
                            <Mic className="w-2.5 h-2.5 text-violet-400" />
                            <span className="text-[9px] text-violet-300">Default Harvis voice will be used</span>
                          </div>
                        </div>
                      ) : (
                        <div className="max-h-36 overflow-y-auto divide-y divide-border/50">
                          {voiceModelsError && (
                            <div className="px-2 py-1 text-[8px] text-yellow-400 bg-yellow-400/5">{voiceModelsError}</div>
                          )}
                          {filteredVoiceModels.length === 0 ? (
                            <div className="p-2 text-[9px] text-muted-foreground text-center">
                              No models matching &ldquo;{voiceSearchQuery}&rdquo;
                            </div>
                          ) : (
                            filteredVoiceModels.slice(0, 50).map((model, midx) => (
                              <button
                                key={midx}
                                onClick={() => handleSelectVoiceModel(i, model)}
                                className="w-full flex items-center gap-1.5 px-2 py-1 text-left hover:bg-primary/10 transition-colors"
                              >
                                <Volume2 className="w-2.5 h-2.5 text-muted-foreground shrink-0" />
                                <span className="text-[9px] text-foreground truncate flex-1">{model.name}</span>
                                <Download className="w-2.5 h-2.5 text-muted-foreground/50 shrink-0" />
                              </button>
                            ))
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Collapsible: Content Selection */}
        <div className="border border-border rounded-lg overflow-hidden">
          <button onClick={() => toggleSection('content')}
            className="flex items-center gap-1.5 w-full px-2.5 py-1.5 text-[10px] font-medium text-muted-foreground hover:text-foreground hover:bg-secondary/30">
            <FileText className="w-3 h-3" />
            <span className="flex-1 text-left">Content</span>
            <span className="text-[9px] px-1.5 py-0.5 bg-primary/15 text-primary rounded-full">{totalSelected}</span>
            <ChevronDown className={`w-3 h-3 ml-1 transition-transform ${expandedSection === 'content' ? 'rotate-180' : ''}`} />
          </button>
          {expandedSection === 'content' && (
            <div className="px-2.5 pb-2 space-y-1.5 border-t border-border pt-1.5">
              {readySources.length > 0 && (
                <div>
                  <div className="flex items-center justify-between text-[9px] mb-1">
                    <span className="text-muted-foreground font-medium">Sources ({selectedSources.size}/{readySources.length})</span>
                    <button onClick={() => setSelectedSources(selectedSources.size === readySources.length ? new Set() : new Set(readySources.map(s => s.id)))}
                      className="text-primary hover:underline">{selectedSources.size === readySources.length ? 'None' : 'All'}</button>
                  </div>
                  <div className="max-h-20 overflow-y-auto space-y-0.5">
                    {readySources.map(s => (
                      <label key={s.id} className="flex items-center gap-1.5 px-1.5 py-0.5 rounded hover:bg-secondary/30 cursor-pointer text-[10px]">
                        <input type="checkbox" checked={selectedSources.has(s.id)} onChange={() => toggleSource(s.id)}
                          className="rounded border-border bg-secondary text-primary focus:ring-primary w-3 h-3" />
                        <span className="text-foreground truncate">{s.title || s.original_filename || 'Untitled'}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
              {notes.length > 0 && (
                <div>
                  <div className="flex items-center justify-between text-[9px] mb-1">
                    <span className="text-muted-foreground font-medium">Notes ({selectedNotes.size}/{notes.length})</span>
                    <button onClick={() => setSelectedNotes(selectedNotes.size === notes.length ? new Set() : new Set(notes.map(n => n.id)))}
                      className="text-primary hover:underline">{selectedNotes.size === notes.length ? 'None' : 'All'}</button>
                  </div>
                  <div className="max-h-20 overflow-y-auto space-y-0.5">
                    {notes.map(n => (
                      <label key={n.id} className="flex items-center gap-1.5 px-1.5 py-0.5 rounded hover:bg-secondary/30 cursor-pointer text-[10px]">
                        <input type="checkbox" checked={selectedNotes.has(n.id)} onChange={() => toggleNote(n.id)}
                          className="rounded border-border bg-secondary text-primary focus:ring-primary w-3 h-3" />
                        <span className="text-foreground truncate">{n.title || 'Untitled'}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
              {readySources.length === 0 && notes.length === 0 && (
                <p className="text-[10px] text-yellow-400 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" /> Add sources or notes first
                </p>
              )}
            </div>
          )}
        </div>

        {/* Generation progress */}
        {isGenerating && generationStep && (
          <div className="p-2 rounded-lg bg-primary/5 border border-primary/20 space-y-1.5">
            <div className="flex items-center gap-2">
              {(['outline', 'script', 'audio'] as const).map((step, idx) => {
                const isActive = generationStep === step
                const stepOrder = { outline: 1, script: 2, audio: 3 }
                const currentOrder = stepOrder[generationStep] || 0
                const isCompleted = currentOrder > stepOrder[step]
                return (
                  <div key={step} className="flex items-center gap-1">
                    {idx > 0 && <div className={`w-4 h-px ${isCompleted ? 'bg-green-500' : 'bg-border'}`} />}
                    <div className={`w-4 h-4 rounded-full flex items-center justify-center text-[8px] font-bold ${
                      isActive ? 'bg-primary text-primary-foreground' : isCompleted ? 'bg-green-500 text-white' : 'bg-secondary text-muted-foreground'
                    }`}>
                      {isCompleted ? <Check className="w-2.5 h-2.5" /> : isActive ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : idx + 1}
                    </div>
                    <span className={`text-[9px] ${isActive ? 'text-primary font-medium' : isCompleted ? 'text-green-400' : 'text-muted-foreground'}`}>
                      {step.charAt(0).toUpperCase() + step.slice(1)}
                    </span>
                  </div>
                )
              })}
            </div>
            <p className="text-[9px] text-muted-foreground animate-pulse text-center">{generationMessage}</p>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="p-2 bg-destructive/10 border border-destructive/30 rounded-lg text-[10px] text-destructive flex items-start gap-1.5">
            <AlertCircle className="w-3 h-3 shrink-0 mt-0.5" />
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="shrink-0"><X className="w-3 h-3" /></button>
          </div>
        )}

        {/* Generate button */}
        <button onClick={handleGenerate}
          disabled={isGenerating || !title.trim() || totalSelected === 0}
          className="w-full py-2 rounded-lg text-[11px] font-semibold disabled:opacity-40 flex items-center justify-center gap-2 bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white hover:from-violet-700 hover:to-fuchsia-700 shadow-lg shadow-violet-500/20 transition-all">
          {isGenerating
            ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Generating...</>
            : <><Wand2 className="w-3.5 h-3.5" /> Generate Podcast</>}
        </button>
      </div>
    </div>
  )

  // ─── Library Tab ────────────────────────────────────────────────────
  const libraryView = (
    <div className="flex-1 overflow-y-auto">
      {isLoadingPodcasts ? (
        <div className="p-6 flex justify-center"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>
      ) : podcasts.length === 0 ? (
        <div className="p-6 text-center">
          <div className="w-10 h-10 rounded-full bg-secondary/50 flex items-center justify-center mx-auto mb-2">
            <Headphones className="w-5 h-5 text-muted-foreground/30" />
          </div>
          <p className="text-xs text-muted-foreground">No podcasts yet</p>
          <button onClick={() => setActiveTab('generate')} className="text-[10px] text-primary hover:underline mt-1">
            Create your first one
          </button>
        </div>
      ) : (
        <div className="divide-y divide-border">
          {podcasts.map(podcast => {
            const audioUrl = getAudioUrl(podcast)
            const isExpanded = expandedPodcast === podcast.id
            return (
              <div key={podcast.id} className="px-3 py-2 hover:bg-secondary/30 transition-colors group">
                <div className="flex items-center gap-2">
                  {/* Status icon */}
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                    podcast.status === 'completed' && audioUrl ? 'bg-gradient-to-br from-violet-500 to-fuchsia-500' :
                    podcast.status === 'generating' ? 'bg-yellow-500/20' :
                    podcast.status === 'error' ? 'bg-destructive/20' :
                    podcast.status === 'script_only' ? 'bg-purple-500/20' : 'bg-secondary'
                  }`}>
                    {podcast.status === 'completed' && audioUrl
                      ? <Headphones className="w-3 h-3 text-white" />
                      : podcast.status === 'generating' ? <Loader2 className="w-3 h-3 animate-spin text-yellow-400" />
                      : podcast.status === 'script_only' ? <Edit3 className="w-3 h-3 text-purple-400" />
                      : podcast.status === 'error' ? <AlertCircle className="w-3 h-3 text-destructive" />
                      : <Mic className="w-3 h-3 text-muted-foreground" />}
                  </div>

                  <button className="flex-1 min-w-0 text-left" onClick={() => setExpandedPodcast(isExpanded ? null : podcast.id)}>
                    <p className="text-[11px] font-medium text-foreground truncate">{podcast.title}</p>
                    <p className="text-[9px] text-muted-foreground">
                      {podcast.style} · {podcast.speakers} spk{podcast.speakers !== 1 ? 's' : ''}
                      {podcast.duration_seconds ? ` · ${formatDuration(podcast.duration_seconds)}` : ''}
                    </p>
                  </button>

                  <div className="flex items-center gap-0.5 shrink-0">
                    {podcast.status === 'completed' && audioUrl && (
                      <button onClick={() => handleDownload(podcast)} title="Download"
                        className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary opacity-0 group-hover:opacity-100 transition-opacity">
                        <Download className="w-3 h-3" />
                      </button>
                    )}
                    <button onClick={() => handleDelete(podcast.id)} title="Delete"
                      className="p-1 rounded text-muted-foreground/40 hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Trash2 className="w-3 h-3" />
                    </button>
                    <ChevronDown className={`w-3 h-3 text-muted-foreground transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                  </div>
                </div>

                {/* Audio player - shown when expanded or when completed with audio */}
                {audioUrl && (podcast.status === 'completed') && (
                  <AudioWaveform audioUrl={audioUrl} duration={podcast.duration_seconds} />
                )}

                {/* Transcript and details - shown when expanded */}
                {isExpanded && (
                  <div className="mt-1.5">
                    {podcast.transcript && podcast.transcript.length > 0 && (
                      <div className="p-2 bg-secondary/20 rounded-lg max-h-32 overflow-y-auto space-y-0.5">
                        {podcast.transcript.map((line, i) => (
                          <p key={i} className="text-[9px]">
                            <span className={`font-semibold px-1 py-0.5 rounded ${SPEAKER_COLORS[i % SPEAKER_COLORS.length]}`}>{line.speaker}</span>
                            <span className="text-foreground/80 ml-1">{line.dialogue}</span>
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {podcast.error_message && (
                  <p className="text-[9px] text-destructive mt-1">{podcast.error_message}</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )

  // ─── Main render ────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-center border-b border-border shrink-0">
        <button onClick={() => setActiveTab('generate')}
          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-[10px] font-medium border-b-2 transition-colors ${
            activeTab === 'generate'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}>
          <Wand2 className="w-3 h-3" /> Generate
        </button>
        <button onClick={() => setActiveTab('library')}
          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-[10px] font-medium border-b-2 transition-colors ${
            activeTab === 'library'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}>
          <Headphones className="w-3 h-3" /> Library
          {podcasts.length > 0 && (
            <span className="text-[8px] px-1 py-0.5 rounded-full bg-primary/15 text-primary">{podcasts.length}</span>
          )}
        </button>
      </div>

      {activeTab === 'generate' ? generateView : libraryView}
    </div>
  )
}
