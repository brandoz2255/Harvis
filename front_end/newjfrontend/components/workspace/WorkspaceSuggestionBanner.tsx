'use client'

import { useState, useEffect, useRef } from 'react'
import { Zap, X, Loader2, ChevronRight, Cpu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useOpenClawStore } from '@/stores/openclawStore'
import { useChatHistoryStore } from '@/stores/chatHistoryStore'
import { cn } from '@/lib/utils'

const MODEL_OPTIONS = [
  { value: 'kimi' as const, label: 'Kimi K2.5', description: 'Moonshot (fast)' },
  { value: 'nvidia-kimi' as const, label: 'Kimi K2.5 NVIDIA', description: 'NVIDIA NIM (thinking mode)' },
  { value: 'qwen3' as const, label: 'Qwen3 235B', description: 'Cloud Ollama' },
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

const COUNTDOWN_SECONDS = 3

interface WorkspaceSuggestionBannerProps {
  chatHistory: Array<{ role: string; content: string }>
}

export function WorkspaceSuggestionBanner({ chatHistory }: WorkspaceSuggestionBannerProps) {
  const {
    suggestion,
    workspaceModel,
    setWorkspaceModel,
    setSuggestion,
    setWorkspaceId,
    setWorkspaceSessionId,
    setWorkspaceActive,
    addLogEvent,
    clearLogEvents,
    setSseAbortController,
    setFinalSummary,
    setActiveTab,
  } = useOpenClawStore()

  const { currentSession } = useChatHistoryStore()

  const [launching, setLaunching] = useState(false)
  const [launchError, setLaunchError] = useState<string | null>(null)
  const [countdown, setCountdown] = useState<number | null>(null)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const hasSetModelRef = useRef(false)

  // Pre-select model from LLM signal
  useEffect(() => {
    if (suggestion?.model && !hasSetModelRef.current) {
      setWorkspaceModel(suggestion.model)
      hasSetModelRef.current = true
    }
    if (!suggestion) hasSetModelRef.current = false
  }, [suggestion, setWorkspaceModel])

  const isAutoLaunch = suggestion?.auto_launch === true

  // 3-2-1 countdown auto-launch
  useEffect(() => {
    if (!isAutoLaunch || !suggestion?.should_suggest) return

    setCountdown(COUNTDOWN_SECONDS)
    countdownRef.current = setInterval(() => {
      setCountdown(prev => {
        if (prev === null || prev <= 1) {
          if (countdownRef.current) {
            clearInterval(countdownRef.current)
            countdownRef.current = null
          }
          return 0 // Will trigger launch via separate effect
        }
        return prev - 1
      })
    }, 1000)

    return () => {
      if (countdownRef.current) {
        clearInterval(countdownRef.current)
        countdownRef.current = null
      }
    }
  }, [isAutoLaunch, suggestion?.should_suggest])

  // Launch when countdown hits 0
  useEffect(() => {
    if (countdown === 0 && !launching) {
      doLaunch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countdown])

  if (!suggestion?.should_suggest) return null

  const icon = TASK_TYPE_ICONS[suggestion.task_type ?? ''] ?? '⚡'

  const handleDismiss = () => {
    if (countdownRef.current) {
      clearInterval(countdownRef.current)
      countdownRef.current = null
    }
    setCountdown(null)
    setSuggestion(null)
  }

  const doLaunch = async () => {
    if (countdownRef.current) {
      clearInterval(countdownRef.current)
      countdownRef.current = null
    }
    setCountdown(null)
    setLaunching(true)
    setLaunchError(null)
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        setLaunchError('Session expired — please log in again.')
        return
      }
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      }

      const res = await fetch('/api/workspace/launch', {
        method: 'POST',
        headers,
        credentials: 'include',
        body: JSON.stringify({
          task_brief: suggestion.task_brief,
          chat_history: chatHistory,
          // Pass the real chat session UUID so the workspace directory is
          // deterministic and tied to this conversation (not a random ws-* id).
          session_id: currentSession?.id ?? undefined,
          agent_id: workspaceModel === 'kimi' ? 'kimi'
                  : workspaceModel === 'qwen3' ? 'qwen3'
                  : workspaceModel === 'nvidia-kimi' ? 'nvidia-kimi'
                  : 'kimi',
        }),
      })

      if (res.status === 401) {
        setLaunchError('Session expired — please log in again.')
        return
      }
      if (!res.ok) throw new Error(`Launch failed: ${res.status}`)

      const data = await res.json()
      const { workspace_id, session_id } = data

      setWorkspaceId(workspace_id)
      setWorkspaceSessionId(session_id)
      setSuggestion(null)
      clearLogEvents()
      setFinalSummary('')
      setActiveTab('dashboard')
      setWorkspaceActive(true)

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
        // Stream closed
      })

    } catch (err) {
      console.error('Workspace launch error:', err)
      setLaunchError('Launch failed — check console for details.')
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
            {countdown !== null && countdown > 0
              ? `Launching in ${countdown}…`
              : countdown === 0
                ? 'Launching…'
                : 'Launch Workspace?'}
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
        {/* Model selector */}
        <div className="flex items-center gap-1 mt-1.5">
          <Cpu className="h-3 w-3 text-muted-foreground shrink-0" />
          {MODEL_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setWorkspaceModel(opt.value)}
              disabled={launching || countdown !== null}
              title={opt.description}
              className={cn(
                'rounded px-2 py-0.5 text-[10px] font-medium transition-colors',
                workspaceModel === opt.value
                  ? 'bg-violet-500/30 text-violet-200'
                  : 'text-muted-foreground hover:text-foreground hover:bg-white/5',
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Countdown progress bar */}
        {countdown !== null && (
          <div className="mt-2 h-1 w-full rounded-full bg-violet-950 overflow-hidden">
            <div
              className="h-full bg-violet-500 rounded-full transition-all duration-1000 ease-linear"
              style={{ width: `${(countdown / COUNTDOWN_SECONDS) * 100}%` }}
            />
          </div>
        )}

        {launchError && (
          <p className="text-[11px] text-red-400 mt-1">{launchError}</p>
        )}
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
          {countdown !== null ? 'Cancel' : <X className="h-3.5 w-3.5" />}
        </Button>
        {countdown === null && (
          <Button
            size="sm"
            onClick={doLaunch}
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
        )}
      </div>
    </div>
  )
}
