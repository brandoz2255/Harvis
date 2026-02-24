'use client'

import { useState } from 'react'
import { Zap, X, Loader2, ChevronRight, Cpu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useOpenClawStore } from '@/stores/openclawStore'
import { cn } from '@/lib/utils'

type WorkspaceModel = 'local' | 'kimi'

const MODEL_OPTIONS: { value: WorkspaceModel; label: string; description: string }[] = [
  { value: 'local', label: 'Local (Qwen)', description: 'Runs code & shell via OpenClaw' },
  { value: 'kimi',  label: 'Kimi K2.5',   description: 'Fast reasoning via Moonshot API' },
]

const TASK_TYPE_ICONS: Record<string, string> = {
  code: '⌨️',
  debug: '🐛',
  file: '📁',
  research: '🔍',
  document: '📄',
  shell: '💻',
  multi_step: '🔗',
}

interface WorkspaceSuggestionBannerProps {
  chatHistory: Array<{ role: string; content: string }>
}

export function WorkspaceSuggestionBanner({ chatHistory }: WorkspaceSuggestionBannerProps) {
  const {
    suggestion,
    setSuggestion,
    workspaceSessionId,
    setWorkspaceId,
    setWorkspaceSessionId,
    setWorkspaceModel,
    setWorkspaceActive,
    addLogEvent,
    clearLogEvents,
    setSseAbortController,
    setFinalSummary,
    setActiveTab,
  } = useOpenClawStore()

  const [launching, setLaunching] = useState(false)
  const [selectedModel, setSelectedModel] = useState<WorkspaceModel>('local')

  if (!suggestion?.should_suggest) return null

  const icon = TASK_TYPE_ICONS[suggestion.task_type ?? ''] ?? '⚡'

  const handleDismiss = () => setSuggestion(null)

  const handleLaunch = async () => {
    setLaunching(true)
    try {
      const token = localStorage.getItem('token')
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      // Launch the workspace — backend creates the OpenClaw session
      const res = await fetch('/api/workspace/launch', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          task_brief: suggestion.task_brief,
          chat_history: chatHistory,
          session_id: workspaceSessionId ?? undefined,
          model: selectedModel,
        }),
      })

      if (!res.ok) throw new Error(`Launch failed: ${res.status}`)

      const data = await res.json()
      const { workspace_id, session_id } = data

      setWorkspaceId(workspace_id)
      setWorkspaceSessionId(session_id)
      setWorkspaceModel(selectedModel)
      setSuggestion(null)
      clearLogEvents()
      setFinalSummary('')
      setActiveTab('progress')
      setWorkspaceActive(true)            // splits the layout

      // Connect to SSE stream
      const controller = new AbortController()
      setSseAbortController(controller)

      const streamRes = await fetch(`/api/workspace/stream/${workspace_id}`, {
        headers,
        signal: controller.signal,
      })

      if (!streamRes.body) throw new Error('No SSE body')

      const reader = streamRes.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      // Read SSE stream and push events into the store
      const readLoop = async () => {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const event = JSON.parse(line.slice(6))
              if (event.type === 'stream_end') break
              if (event.type === 'done') {
                setFinalSummary(event.summary ?? '')
              }
              addLogEvent(event)
            } catch {
              // ignore malformed SSE lines
            }
          }
        }
      }

      readLoop().catch(() => {
        // Stream closed (cancel or error) — addLogEvent handles the terminal event
      })

    } catch (err) {
      console.error('Workspace launch error:', err)
      setSuggestion(null)
    } finally {
      setLaunching(false)
    }
  }

  return (
    <div
      className={cn(
        'mx-4 mb-2 flex items-start gap-3 rounded-xl border border-violet-500/30',
        'bg-violet-950/30 px-4 py-3 backdrop-blur-sm',
        'animate-in slide-in-from-bottom-2 duration-200'
      )}
    >
      {/* Icon */}
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-500/20 text-base">
        {icon}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs font-semibold text-violet-300 uppercase tracking-wide">
            Launch Workspace?
          </span>
          <span className="rounded-full bg-violet-500/20 px-2 py-0.5 text-[10px] text-violet-400">
            {suggestion.task_type_label}
          </span>
        </div>
        <p className="text-sm text-foreground/90 leading-snug truncate">
          {suggestion.task_brief}
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {suggestion.reason}
        </p>
      </div>

      {/* Model selector */}
      <div className="flex items-center gap-1 shrink-0 self-center">
        <Cpu className="h-3 w-3 text-muted-foreground/60 shrink-0" />
        <div className="flex rounded-md border border-border overflow-hidden">
          {MODEL_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              title={opt.description}
              onClick={() => setSelectedModel(opt.value)}
              disabled={launching}
              className={cn(
                'px-2 py-1 text-[10px] font-medium transition-colors',
                selectedModel === opt.value
                  ? 'bg-violet-600 text-white'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 shrink-0 self-center">
        <Button
          variant="ghost"
          size="sm"
          onClick={handleDismiss}
          disabled={launching}
          className="h-7 px-2 text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          onClick={handleLaunch}
          disabled={launching}
          className="h-7 gap-1.5 bg-violet-600 hover:bg-violet-500 text-white text-xs"
        >
          {launching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Zap className="h-3.5 w-3.5" />
          )}
          {launching ? 'Launching…' : 'Launch'}
          {!launching && <ChevronRight className="h-3 w-3" />}
        </Button>
      </div>
    </div>
  )
}
